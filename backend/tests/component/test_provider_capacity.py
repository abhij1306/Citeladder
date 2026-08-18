"""Provider capacity pools (T4): Postgres-authoritative acquire/release.

Two session factories over the same schema stand in for two worker processes
(the same SKIP LOCKED / FOR UPDATE posture as the queue tests): concurrency
ceilings must never overshoot under parallel acquires, lock order is
canonical, funded accounts share fairly, expired leases recover capacity, a
429 cooldown is visible to siblings, BYOK and funded pools stay separate,
parked decisions carry ``capacity_wait``/``available_at``, and funded pacing
fails CLOSED while route token rates are unconfigured.

Telemetry capture goes through the shared
``tests/component/log_capture.py`` helper (binds DIRECTLY to the emitting
logger, never caplog's root, with the level pinned for the capture window).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_QUEUE_SPEC,
    AUDIT_TRIGGER_MANUAL,
    CAPACITY_CODE_CONCURRENCY,
    CAPACITY_CODE_RATE_LIMITED,
    CAPACITY_CODE_UNCONFIGURED,
    CAPACITY_OUTCOME_RATE_LIMITED,
    CAPACITY_OUTCOME_SUCCEEDED,
    CREDENTIAL_KIND_BYOK,
    CREDENTIAL_KIND_FUNDED,
    POOL_KIND_CONNECTION,
    POOL_KIND_FUNDED_ACCOUNT,
    POOL_KIND_FUNDED_GLOBAL,
    POOL_KIND_TRANSPORT,
    TASK_STATUS_CAPACITY_WAIT,
    TELEMETRY_CAPACITY_RATE_LIMITED,
    TELEMETRY_CAPACITY_WAIT,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ENGINE_GEMINI,
    ROUTE_CAPACITY_POLICIES,
    TRANSPORT_GOOGLE,
    RouteCapacityPolicy,
)
from app.domain.audits.creation import create_audit
from app.models.audit import (
    AuditTask,
    ProviderCapacityBucket,
    ProviderCapacityLease,
)
from app.models.billing import BillingAccount
from app.models.provider import ProviderConnection
from app.models.user import User
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.orchestration.provider_capacity import (
    CapacityOutcome,
    CapacityRequest,
    _bucket_specs,
    acquire_provider_capacity,
    release_provider_capacity,
)
from tests.component.audit_helpers import seed_audit_fixtures
from tests.component.log_capture import capture_log_messages

_GEMINI_ROUTE = (ENGINE_GEMINI, TRANSPORT_GOOGLE)
_NOW = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


@dataclass
class CapacitySeed:
    task_ids: list[uuid.UUID]
    connection_id: uuid.UUID
    account_ids: tuple[uuid.UUID, uuid.UUID, uuid.UUID]


async def _seed(
    session_factory: async_sessionmaker[AsyncSession], *, prompts: int
) -> CapacitySeed:
    """Real AuditTask rows (lease FK target) + a BYOK connection + 3 accounts."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=prompts)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
        task_ids = list(
            (
                await session.scalars(
                    select(AuditTask.id).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        connection_id = await session.scalar(
            select(ProviderConnection.id).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert connection_id is not None
        account_ids: list[uuid.UUID] = []
        for _ in range(3):
            user = User(
                email=f"capacity-{uuid.uuid4().hex[:8]}@example.com",
                hashed_password="x",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            account = BillingAccount(owner_user_id=user.id)
            session.add(account)
            await session.flush()
            account_ids.append(account.id)
        await session.commit()
    assert len(task_ids) == prompts
    return CapacitySeed(
        task_ids=task_ids,
        connection_id=connection_id,
        account_ids=(account_ids[0], account_ids[1], account_ids[2]),
    )


def _byok(
    task_id: uuid.UUID, connection_id: uuid.UUID, *, attempt: int = 1
) -> CapacityRequest:
    return CapacityRequest(
        task_id=task_id,
        attempt_number=attempt,
        logical_engine=ENGINE_GEMINI,
        transport_provider=TRANSPORT_GOOGLE,
        credential_kind=CREDENTIAL_KIND_BYOK,
        connection_id=connection_id,
    )


def _funded(
    task_id: uuid.UUID, account_id: uuid.UUID, *, attempt: int = 1
) -> CapacityRequest:
    return CapacityRequest(
        task_id=task_id,
        attempt_number=attempt,
        logical_engine=ENGINE_GEMINI,
        transport_provider=TRANSPORT_GOOGLE,
        credential_kind=CREDENTIAL_KIND_FUNDED,
        billing_account_id=account_id,
    )


def _configure_route_pacing(
    monkeypatch: pytest.MonkeyPatch, *, capacity: float = 100.0, refill: float = 100.0
) -> None:
    """Give the Gemini route VERIFIED token rates for pacing-enabled tests."""
    monkeypatch.setitem(
        ROUTE_CAPACITY_POLICIES,
        _GEMINI_ROUTE,
        RouteCapacityPolicy(
            capacity=capacity,
            refill_tokens_per_second=refill,
            max_cooldown_seconds=60.0,
        ),
    )


@pytest_asyncio.fixture
async def second_session_factory(
    _schema_engine: AsyncEngine,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A second factory over the same schema: the other worker process.

    Mirrors the conftest ``session_factory`` kwargs exactly
    (``expire_on_commit=False``, ``autoflush=False``) so both workers run with
    production session semantics.
    """
    yield async_sessionmaker(
        _schema_engine,
        expire_on_commit=False,
        class_=AsyncSession,
        autoflush=False,
    )


async def _active_lease_count(
    session_factory: async_sessionmaker[AsyncSession], *, pool_kind: str
) -> int:
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(ProviderCapacityLease)
                .join(ProviderCapacityBucket)
                .where(
                    ProviderCapacityBucket.pool_kind == pool_kind,
                    ProviderCapacityLease.released_at.is_(None),
                    ProviderCapacityLease.expires_at > datetime.now(UTC),
                )
            )
        ).all()
        return len(rows)


def _parked_index(decisions: list, n: int) -> int:
    return [i for i, d in enumerate(decisions) if not d.acquired][n]


@pytest.mark.asyncio
async def test_concurrent_acquires_never_overshoot_transport_ceiling(
    session_factory: async_sessionmaker[AsyncSession],
    second_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two worker owners, six tasks, ceiling 2: never more than 2 holders."""
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 2)
    seed = await _seed(session_factory, prompts=6)
    factories = [session_factory, second_session_factory]

    async def _acquire(index: int):
        factory = factories[index % 2]  # interleave across the two workers
        return await acquire_provider_capacity(
            factory, request=_byok(seed.task_ids[index], seed.connection_id)
        )

    with capture_log_messages("app.orchestration.provider_capacity") as events:
        decisions = await asyncio.gather(*(_acquire(i) for i in range(6)))

    acquired = [d for d in decisions if d.acquired]
    parked = [d for d in decisions if not d.acquired]
    assert len(acquired) == 2
    assert len(parked) == 4
    assert all(d.code == CAPACITY_CODE_CONCURRENCY for d in parked)
    assert all(d.pool_kind == POOL_KIND_TRANSPORT for d in parked)
    assert all(d.task_status == TASK_STATUS_CAPACITY_WAIT for d in parked)
    assert all(d.available_at is not None for d in parked)
    # The ceiling held at every instant: exactly 2 active concurrency leases.
    assert (
        await _active_lease_count(session_factory, pool_kind=POOL_KIND_TRANSPORT) == 2
    )
    assert (
        await _active_lease_count(session_factory, pool_kind=POOL_KIND_CONNECTION) == 2
    )
    assert sum(1 for e in events if e.startswith(TELEMETRY_CAPACITY_WAIT)) == 4

    # Releasing one slot lets exactly one more task in — still never over 2.
    held = [i for i, d in enumerate(decisions) if d.acquired]
    await release_provider_capacity(
        session_factory,
        request=_byok(seed.task_ids[held[0]], seed.connection_id),
        outcome=CapacityOutcome(kind=CAPACITY_OUTCOME_SUCCEEDED),
    )
    extra = await acquire_provider_capacity(
        second_session_factory,
        request=_byok(seed.task_ids[_parked_index(decisions, 0)], seed.connection_id),
    )
    assert extra.acquired
    assert (
        await _active_lease_count(session_factory, pool_kind=POOL_KIND_TRANSPORT) == 2
    )


@pytest.mark.asyncio
async def test_lock_order_is_canonical_and_transport_bucket_shared(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every acquirer locks transport first; BYOK and funded share that row."""
    _configure_route_pacing(monkeypatch)
    seed = await _seed(session_factory, prompts=2)
    byok = _byok(seed.task_ids[0], seed.connection_id)
    funded = _funded(seed.task_ids[1], seed.account_ids[0])

    # THE deadlock-freedom contract: one fixed order for every request shape.
    assert [s.pool_kind for s in _bucket_specs(byok)] == [
        POOL_KIND_TRANSPORT,
        POOL_KIND_CONNECTION,
    ]
    assert [s.pool_kind for s in _bucket_specs(funded)] == [
        POOL_KIND_TRANSPORT,
        POOL_KIND_FUNDED_GLOBAL,
        POOL_KIND_FUNDED_ACCOUNT,
    ]

    byok_decision, funded_decision = await asyncio.gather(
        acquire_provider_capacity(session_factory, request=byok),
        acquire_provider_capacity(session_factory, request=funded),
    )
    assert byok_decision.acquired and funded_decision.acquired

    async with session_factory() as session:
        transport_buckets = (
            await session.scalars(
                select(ProviderCapacityBucket).where(
                    ProviderCapacityBucket.pool_kind == POOL_KIND_TRANSPORT
                )
            )
        ).all()
    # One shared transport row for both credential kinds (both hold leases on it).
    assert len(transport_buckets) == 1


@pytest.mark.asyncio
async def test_funded_account_fairness(
    session_factory: async_sessionmaker[AsyncSession],
    second_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """funded_pool_per_account bounds each account; siblings are not starved."""
    _configure_route_pacing(monkeypatch)
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 12)
    monkeypatch.setattr(audit_settings, "funded_pool_max_concurrency", 10)
    monkeypatch.setattr(audit_settings, "funded_pool_per_account", 2)
    seed = await _seed(session_factory, prompts=7)
    account_a, account_b, account_c = seed.account_ids

    async def _acquire(index: int, account_id: uuid.UUID):
        factory = [session_factory, second_session_factory][index % 2]
        return await acquire_provider_capacity(
            factory, request=_funded(seed.task_ids[index], account_id)
        )

    decisions = await asyncio.gather(
        *(_acquire(i, account_a) for i in range(3)),
        *(_acquire(3 + i, account_b) for i in range(3)),
    )
    acquired_a = sum(1 for d in decisions[:3] if d.acquired)
    acquired_b = sum(1 for d in decisions[3:] if d.acquired)
    # Each account takes exactly its per-account slice — no more, no less.
    assert acquired_a == 2
    assert acquired_b == 2
    parked = [d for d in decisions if not d.acquired]
    assert all(d.pool_kind == POOL_KIND_FUNDED_ACCOUNT for d in parked)
    assert all(d.code == CAPACITY_CODE_CONCURRENCY for d in parked)

    # A third account is not starved by A+B holding the funded pool: its own
    # per-account slice is still available (global ceiling not reached).
    sibling = await acquire_provider_capacity(
        second_session_factory, request=_funded(seed.task_ids[6], account_c)
    )
    assert sibling.acquired


@pytest.mark.asyncio
async def test_lease_expiry_recovers_capacity(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired (crashed worker) lease stops counting toward the ceiling."""
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 1)
    seed = await _seed(session_factory, prompts=3)
    first = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[0], seed.connection_id)
    )
    assert first.acquired

    # The live lease fills the only slot.
    blocked = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[1], seed.connection_id)
    )
    assert not blocked.acquired
    assert blocked.code == CAPACITY_CODE_CONCURRENCY

    # Crash the holder: force its leases (transport + connection) into the
    # past; capacity comes back on BOTH pools.
    async with session_factory() as session:
        leases = (
            await session.scalars(
                select(ProviderCapacityLease).where(
                    ProviderCapacityLease.task_id == seed.task_ids[0]
                )
            )
        ).all()
        assert len(leases) == 2
        for lease in leases:
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    recovered = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[2], seed.connection_id)
    )
    assert recovered.acquired
    assert (
        await _active_lease_count(session_factory, pool_kind=POOL_KIND_TRANSPORT) == 1
    )


@pytest.mark.asyncio
async def test_shared_429_cooldown_blocks_siblings(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 writes blocked_until on the shared pools; siblings see it."""
    _configure_route_pacing(monkeypatch)
    seed = await _seed(session_factory, prompts=2)
    request = _byok(seed.task_ids[0], seed.connection_id)
    acquired = await acquire_provider_capacity(
        session_factory, request=request, at=_NOW
    )
    assert acquired.acquired

    with capture_log_messages("app.orchestration.provider_capacity") as events:
        await release_provider_capacity(
            session_factory,
            request=request,
            outcome=CapacityOutcome(
                kind=CAPACITY_OUTCOME_RATE_LIMITED, retry_after_seconds=30.0
            ),
            at=_NOW,
        )
    assert any(e.startswith(TELEMETRY_CAPACITY_RATE_LIMITED) for e in events)

    async with session_factory() as session:
        buckets = (await session.scalars(select(ProviderCapacityBucket))).all()
        by_kind = {b.pool_kind: b for b in buckets}
    # Every pool the request drew from carries the cooldown.
    expected_until = _NOW + timedelta(seconds=30)
    assert by_kind[POOL_KIND_TRANSPORT].blocked_until == expected_until
    assert by_kind[POOL_KIND_CONNECTION].blocked_until == expected_until

    # A sibling task on the same transport sees the shared cooldown.
    sibling = await acquire_provider_capacity(
        session_factory,
        request=_byok(seed.task_ids[1], seed.connection_id),
        at=_NOW + timedelta(seconds=5),
    )
    assert not sibling.acquired
    assert sibling.code == CAPACITY_CODE_RATE_LIMITED
    assert sibling.pool_kind == POOL_KIND_TRANSPORT
    assert sibling.available_at == expected_until
    assert sibling.retry_after_seconds == pytest.approx(25.0)

    # An untrusted Retry-After far beyond the route max is CLAMPED.
    await release_provider_capacity(
        session_factory,
        request=_byok(seed.task_ids[1], seed.connection_id),
        outcome=CapacityOutcome(
            kind=CAPACITY_OUTCOME_RATE_LIMITED, retry_after_seconds=10_000.0
        ),
        at=_NOW,
    )
    async with session_factory() as session:
        transport = await session.scalar(
            select(ProviderCapacityBucket).where(
                ProviderCapacityBucket.pool_kind == POOL_KIND_TRANSPORT
            )
        )
        assert transport is not None
        assert transport.blocked_until == _NOW + timedelta(seconds=60)


@pytest.mark.asyncio
async def test_byok_and_funded_pools_are_separate(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BYOK touches transport+connection only; funded never sees a connection."""
    _configure_route_pacing(monkeypatch)
    seed = await _seed(session_factory, prompts=2)
    byok = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[0], seed.connection_id)
    )
    funded = await acquire_provider_capacity(
        session_factory, request=_funded(seed.task_ids[1], seed.account_ids[0])
    )
    assert byok.acquired and funded.acquired

    async with session_factory() as session:
        buckets = (await session.scalars(select(ProviderCapacityBucket))).all()
        leases = (await session.scalars(select(ProviderCapacityLease))).all()
    kinds = {b.pool_kind for b in buckets}
    assert kinds == {
        POOL_KIND_TRANSPORT,
        POOL_KIND_CONNECTION,
        POOL_KIND_FUNDED_GLOBAL,
        POOL_KIND_FUNDED_ACCOUNT,
    }
    connection_bucket = next(b for b in buckets if b.pool_kind == POOL_KIND_CONNECTION)
    funded_account_bucket = next(
        b for b in buckets if b.pool_kind == POOL_KIND_FUNDED_ACCOUNT
    )
    assert connection_bucket.connection_id == seed.connection_id
    assert connection_bucket.billing_account_id is None
    assert funded_account_bucket.billing_account_id == seed.account_ids[0]
    assert funded_account_bucket.connection_id is None
    # Each task holds leases on exactly its own pool set.
    byok_buckets = {
        lease.bucket_id for lease in leases if lease.task_id == seed.task_ids[0]
    }
    funded_buckets = {
        lease.bucket_id for lease in leases if lease.task_id == seed.task_ids[1]
    }
    assert connection_bucket.id in byok_buckets
    assert connection_bucket.id not in funded_buckets
    assert funded_account_bucket.id in funded_buckets
    assert funded_account_bucket.id not in byok_buckets


@pytest.mark.asyncio
async def test_capacity_wait_parks_task_until_available_at(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A parked decision maps onto the queue row: not claimable until due."""
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 1)
    seed = await _seed(session_factory, prompts=2)
    first = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[0], seed.connection_id)
    )
    assert first.acquired

    decision = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[1], seed.connection_id)
    )
    assert not decision.acquired
    assert decision.task_status == TASK_STATUS_CAPACITY_WAIT
    assert decision.code == CAPACITY_CODE_CONCURRENCY
    assert decision.available_at is not None
    assert decision.retry_after_seconds == pytest.approx(
        audit_settings.capacity_concurrency_retry_seconds
    )

    # Apply the decision to the queue row exactly as the worker will: status
    # capacity_wait, reusing available_at (no duplicate queued-state column).
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    async with session_factory() as session:
        task = await session.get(AuditTask, seed.task_ids[1])
        assert task is not None
        task.status = TASK_STATUS_CAPACITY_WAIT
        task.available_at = datetime.now(UTC) + timedelta(hours=1)
        await session.commit()

    claimed = await queue.claim(owner="w1", limit=10)
    # The parked task is NOT claimable while its available_at is in the future.
    assert seed.task_ids[1] not in {t.id for t in claimed}

    async with session_factory() as session:
        task = await session.get(AuditTask, seed.task_ids[1])
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    claimed = await queue.claim(owner="w1", limit=10)
    # Once due, a capacity_wait row IS claimable (config claimable vocabulary).
    assert seed.task_ids[1] in {t.id for t in claimed}


@pytest.mark.asyncio
async def test_funded_fails_closed_when_route_rates_unset(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unverified (None) route rates: funded parks; BYOK is concurrency-only."""
    seed = await _seed(session_factory, prompts=2)

    with capture_log_messages("app.orchestration.provider_capacity") as events:
        funded = await acquire_provider_capacity(
            session_factory, request=_funded(seed.task_ids[0], seed.account_ids[0])
        )
    assert not funded.acquired
    assert funded.code == CAPACITY_CODE_UNCONFIGURED
    assert funded.pool_kind == POOL_KIND_TRANSPORT
    assert funded.task_status == TASK_STATUS_CAPACITY_WAIT
    assert funded.retry_after_seconds == pytest.approx(60.0)  # route max cooldown
    rate_limited_events = [
        e for e in events if e.startswith(TELEMETRY_CAPACITY_RATE_LIMITED)
    ]
    assert len(rate_limited_events) == 1
    message = rate_limited_events[0]
    assert f"task_id={seed.task_ids[0]}" in message
    assert f"account_id={seed.account_ids[0]}" in message
    # Never credentials, prompts, or provider bodies (invariant 6).
    for forbidden in ("secret", "api_key", "prompt", "key"):
        assert forbidden not in message.lower()

    # BYOK on the same unconfigured route acquires with concurrency only and
    # leaves the token state untouched (tokens stay 0, refill stays 0).
    byok = await acquire_provider_capacity(
        session_factory, request=_byok(seed.task_ids[1], seed.connection_id)
    )
    assert byok.acquired
    async with session_factory() as session:
        transport = await session.scalar(
            select(ProviderCapacityBucket).where(
                ProviderCapacityBucket.pool_kind == POOL_KIND_TRANSPORT
            )
        )
        assert transport is not None
        assert float(transport.tokens) == 0.0
        assert float(transport.refill_tokens_per_second) == 0.0


@pytest.mark.asyncio
async def test_release_returns_concurrency_but_tokens_stay_consumed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Release frees the lease; the consumed token start is never credited."""
    _configure_route_pacing(monkeypatch, capacity=4.0, refill=0.0)
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 1)
    seed = await _seed(session_factory, prompts=2)
    request = _byok(seed.task_ids[0], seed.connection_id)
    acquired = await acquire_provider_capacity(
        session_factory, request=request, at=_NOW
    )
    assert acquired.acquired

    async with session_factory() as session:
        transport = await session.scalar(
            select(ProviderCapacityBucket).where(
                ProviderCapacityBucket.pool_kind == POOL_KIND_TRANSPORT
            )
        )
        assert transport is not None
        assert float(transport.tokens) == pytest.approx(3.0)  # 4 - 1 start

    await release_provider_capacity(
        session_factory,
        request=request,
        outcome=CapacityOutcome(kind=CAPACITY_OUTCOME_SUCCEEDED),
        at=_NOW,
    )
    # Concurrency freed: a sibling fits under the ceiling of 1 again...
    sibling = await acquire_provider_capacity(
        session_factory,
        request=_byok(seed.task_ids[1], seed.connection_id),
        at=_NOW,
    )
    assert sibling.acquired
    # ...but the token budget kept both starts (4 - 2), refill 0: no credit.
    async with session_factory() as session:
        transport = await session.scalar(
            select(ProviderCapacityBucket).where(
                ProviderCapacityBucket.pool_kind == POOL_KIND_TRANSPORT
            )
        )
        assert transport is not None
        assert float(transport.tokens) == pytest.approx(2.0)
        leases = (
            await session.scalars(
                select(ProviderCapacityLease).where(
                    ProviderCapacityLease.task_id == seed.task_ids[0]
                )
            )
        ).all()
        assert all(lease.released_at is not None for lease in leases)
