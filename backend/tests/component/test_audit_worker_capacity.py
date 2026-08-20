"""Audit worker provider-capacity acquisition and release scenarios.

Provider calls are MOCKED (no network, no spend). Exercises the real
claim/lease loop against a Postgres schema:
  - a full audit runs every task to ``succeeded``, writes one immutable
    RawResponseArtifact + ProviderAttempt each, scores each on persist, and
    finalizes RUNNING -> ANALYZING -> REPORTING -> COMPLETED with an aggregated
    MetricSnapshot (B6);
  - a cooperatively-cancelled audit stops at the task boundary (no artifact);
  - the per-run wall-clock deadline terminalizes remaining tasks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCEEDED,
    CAPACITY_CODE_CONCURRENCY,
    CAPACITY_CODE_RATE_LIMITED,
    EVENT_TASK_CAPACITY_WAIT,
    POOL_KIND_CONNECTION,
    POOL_KIND_TRANSPORT,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ERROR_CLIENT,
)
from app.core.config.task_queue import (
    TASK_STATUS_CAPACITY_WAIT,
    TASK_STATUS_RETRY_WAIT,
)
from app.models.audit import (
    AuditEvent,
    AuditTask,
    ProviderAttempt,
    ProviderCapacityBucket,
    ProviderCapacityLease,
)
from app.workers.audit import execution as audit_execution
from app.workers.audit_worker import AuditWorker
from tests.component.audit_worker_helpers import (
    _ClientErrorAdapter,
    _FlakyAdapter,
    _leased_pools,
    _make_audit,
    _pin_attempt_budget,
    _StubAdapter,
)


@pytest.mark.asyncio
async def test_capacity_refusal_parks_task_without_calling_provider(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capacity refusal parks the task in ``capacity_wait`` — no call is made.

    The park spends NO attempt budget (``attempt_count`` stays 0, no
    ProviderAttempt row, no capacity lease) and records
    ``EVENT_TASK_CAPACITY_WAIT``; the bounded drain waits out one park horizon
    and then stops instead of re-parking forever. Once capacity is restored
    and the park is due, the same task becomes claimable and executes.
    """
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 0)
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    adapter = _FlakyAdapter(fail_times=0)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-park")
    claimed_at = datetime.now(UTC)
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_CAPACITY_WAIT
        assert task.available_at > claimed_at
        assert task.lease_owner is None
        # No provider call happened: no budget spent, no attempt row, no lease.
        assert task.attempt_count == 0
        assert adapter.calls == 0
        attempts = await session.scalar(
            select(func.count())
            .select_from(ProviderAttempt)
            .where(ProviderAttempt.task_id == task.id)
        )
        assert attempts == 0
        leases = await session.scalar(
            select(func.count())
            .select_from(ProviderCapacityLease)
            .where(ProviderCapacityLease.task_id == task.id)
        )
        assert leases == 0
        events = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.audit_id == audit.id,
                    AuditEvent.event_type == EVENT_TASK_CAPACITY_WAIT,
                )
            )
        ).all()
        # At least one park; the bounded drain may re-park once before its
        # patience budget runs out (the ceiling never frees up in this test).
        assert len(events) >= 1
        for event in events:
            assert event.payload["code"] == CAPACITY_CODE_CONCURRENCY
            assert event.payload["pool_kind"] == POOL_KIND_TRANSPORT
            assert event.payload["task_id"] == str(task.id)

    # Capacity restored and the park due: the task claims + executes.
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 4)
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        assert task.attempt_count == 1
        assert adapter.calls == 1


@pytest.mark.asyncio
async def test_claim_commits_before_capacity_and_provider_io(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant 8: the claim commits BEFORE any capacity I/O.

    Witnessed from a SEPARATE session at the moment capacity acquisition
    runs: the lease is already durable (visible to other transactions), so no
    DB transaction is ever held across capacity/provider I/O.

    The row is still ``leased`` at this point, not ``running``: a task is
    only marked running once capacity is actually held, so one waiting for a
    slot is never published as executing. The invariant is the DURABLE lease,
    which this asserts via ``lease_owner``.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    observed: dict[str, object] = {}
    real_acquire = audit_execution.acquire_provider_capacity

    async def _witness(factory, *, request, at=None):
        async with factory() as session:
            row = await session.get(AuditTask, request.task_id)
            observed["status"] = row.status if row is not None else None
            observed["lease_owner"] = row.lease_owner if row is not None else None
        return await real_acquire(factory, request=request, at=at)

    monkeypatch.setattr(audit_execution, "acquire_provider_capacity", _witness)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: _StubAdapter())
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-claim-order")
    await worker.run_until_idle()

    assert observed == {"status": "leased", "lease_owner": "w-claim-order"}
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"


@pytest.mark.asyncio
async def test_capacity_acquired_and_released_on_success(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success releases every drawn concurrency lease; BYOK draws BYOK pools.

    Pool separation: a BYOK task draws transport + connection only — never
    the funded-global/funded-account pools.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: _StubAdapter())
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-rel-ok")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        pairs = await _leased_pools(session, task.id)
        assert {bucket.pool_kind for _, bucket in pairs} == {
            POOL_KIND_TRANSPORT,
            POOL_KIND_CONNECTION,
        }
        assert all(lease.released_at is not None for lease, _ in pairs)
        assert all(bucket.blocked_until is None for _, bucket in pairs)


@pytest.mark.asyncio
async def test_capacity_released_with_failed_outcome_on_terminal_error(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-retryable failure releases capacity as ``failed``: leases
    returned, no shared cooldown written."""
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    adapter = _ClientErrorAdapter()
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-rel-fail")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "failed"
        assert task.error_code == ERROR_CLIENT
        assert adapter.calls == 1
        pairs = await _leased_pools(session, task.id)
        assert len(pairs) == 2
        assert all(lease.released_at is not None for lease, _ in pairs)
        assert all(bucket.blocked_until is None for _, bucket in pairs)


@pytest.mark.asyncio
async def test_429_release_writes_shared_cooldown_and_parks_reclaim(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A provider 429 releases as ``rate_limited`` with the Retry-After hint.

    Phase 1: the failed call writes the clamped ``blocked_until`` cooldown on
    EVERY drawn pool and the task goes to queue backoff (``retry_wait``).
    Phase 2: once the backoff is due the capacity layer refuses the re-claim
    (the pools are still cooling down) and parks the task in
    ``capacity_wait`` WITHOUT a second external call. Phase 3: after the
    cooldown passes the task executes — one more queue attempt, one call.
    """
    _pin_attempt_budget(monkeypatch, 3)  # frozen budget
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    adapter = _FlakyAdapter(fail_times=1, retry_after=30.0)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "retry_jitter_seconds", 0.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-429")
    # Phase 1: one claim, one call, one 429.
    await worker.run_pipelined(drain=True)

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        task_id = task.id
        assert task.status == TASK_STATUS_RETRY_WAIT
        assert task.available_at > datetime.now(UTC) + timedelta(seconds=20)
        assert task.attempt_count == 1
        assert adapter.calls == 1
        pairs = await _leased_pools(session, task_id)
        assert len(pairs) == 2
        assert all(lease.released_at is not None for lease, _ in pairs)
        # The shared cooldown: every drawn pool observes the clamped hint.
        assert all(
            bucket.blocked_until is not None
            and bucket.blocked_until > datetime.now(UTC) + timedelta(seconds=20)
            for _, bucket in pairs
        )

    # Phase 2: backoff due, but the pools still cool down -> parked, no call.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    await worker.run_pipelined(drain=True)

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_CAPACITY_WAIT
        assert task.available_at > datetime.now(UTC) + timedelta(seconds=20)
        assert task.attempt_count == 1  # unchanged: no second call happened
        assert adapter.calls == 1
        events = (
            await session.scalars(
                select(AuditEvent).where(
                    AuditEvent.audit_id == audit.id,
                    AuditEvent.event_type == EVENT_TASK_CAPACITY_WAIT,
                )
            )
        ).all()
        assert len(events) == 1
        assert events[0].payload["code"] == CAPACITY_CODE_RATE_LIMITED

    # Phase 3: cooldown passed -> the task executes on its next queue attempt.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        buckets = (await session.scalars(select(ProviderCapacityBucket))).all()
        for bucket in buckets:
            bucket.blocked_until = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == "succeeded"
        assert task.attempt_count == 2
        assert adapter.calls == 2
        attempts = (
            await session.scalars(
                select(ProviderAttempt)
                .where(ProviderAttempt.task_id == task_id)
                .order_by(ProviderAttempt.attempt_number.asc())
            )
        ).all()
        assert [a.attempt_number for a in attempts] == [1, 2]
        assert [a.status for a in attempts] == [
            ATTEMPT_STATUS_FAILED,
            ATTEMPT_STATUS_SUCCEEDED,
        ]
