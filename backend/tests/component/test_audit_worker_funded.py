"""Audit worker funded-ledger and frozen-credential scenarios.

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
)
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.audits import (
    AUDIT_STATUS_FAILED,
    AUDIT_TRIGGER_MANUAL,
    EVENT_TASK_CAPACITY_WAIT,
    POOL_KIND_CONNECTION,
    POOL_KIND_TRANSPORT,
    TASK_STATUS_PENDING_RESERVATION,
    audit_settings,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_FUNDED,
    KEY_AUDIT_CREDITS,
    LEDGER_ENTRY_DEBIT,
)
from app.core.config.provider_catalog import (
    ENGINE_CLAUDE,
    ERROR_AUTH,
    ERROR_TIMEOUT,
    ROUTE_CAPACITY_POLICIES,
    TELEMETRY_BYOK_PAUSED,
    TELEMETRY_PLATFORM_AUTH_FAILED,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    RouteCapacityPolicy,
)
from app.core.config.task_queue import (
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_QUEUED,
)
from app.domain.audits.creation import create_audit
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.ledger import consumable_usage
from app.domain.entitlements.types import GrantSpec
from app.models.audit import (
    Audit,
    AuditEvent,
    AuditTask,
    ProviderAttempt,
)
from app.models.provider import ProviderConnection
from app.workers.audit import execution as audit_execution
from app.workers.audit_worker import AuditWorker
from tests.component.audit_helpers import (
    _mark_connection_probed,
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.audit_worker_helpers import (
    _ClaudeStubAdapter,
    _leased_pools,
    _ledger_entries,
    _make_audit,
    _StallingAdapter,
    _StubAdapter,
)
from tests.component.audit_worker_helpers import (
    _stub_adapter as _stub_adapter,
)
from tests.component.log_capture import capture_log_messages
from tests.component.occupancy_helpers import seed_occupancy_grants


@pytest.mark.asyncio
async def _make_funded_audit(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    credits: int = 100,
    freeze: dict[str, object] | None = None,
):
    """A FUNDED audit/claude audit whose task can execute under the worker.

    ``freeze`` knobs are monkeypatched BEFORE planning so they freeze onto
    the task. Funded capacity acquisition fails CLOSED while the route's
    token-bucket rates are UNSET (unverified by design), so test rates are
    configured. The tenant BYOK connection stays UNPROBED so BYOK precedence
    cannot claim the task; the planner freezes the seeded PLATFORM connection
    (T11) into the funded task, and the worker loads that frozen identity —
    these tests pin the capacity + LEDGER wiring on the platform credential.
    """
    for key, value in (freeze or {}).items():
        monkeypatch.setattr(audit_settings, key, value)
    monkeypatch.setitem(
        ROUTE_CAPACITY_POLICIES,
        (ENGINE_CLAUDE, TRANSPORT_ANTHROPIC),
        RouteCapacityPolicy(
            capacity=100.0,
            refill_tokens_per_second=100.0,
            max_cooldown_seconds=60.0,
        ),
    )
    clear_cache()
    async with session_factory() as session:
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=[ENGINE_CLAUDE], probed=False
        )
        system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        account = await seed_occupancy_grants(
            session,
            workspace_id=seed.workspace_id,
            grants=(GrantSpec(key=KEY_AUDIT_CREDITS, value=credits),),
        )
        await session.commit()
        audit = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            credential_mode=CREDENTIAL_MODE_FUNDED,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
        # T11: the funded task's frozen credential IS the platform connection
        # in the system workspace (planner-frozen, no shim).
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        platform_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == system.id
            )
        )
        assert platform_connection is not None
        snapshot = task.provider_route_snapshot or {}
        assert snapshot.get("credential_source") == "platform"
        assert snapshot.get("connection_id") == str(platform_connection.id)
        return seed, account, audit


@pytest.mark.asyncio
async def test_funded_task_bills_one_unit_per_actual_call_and_releases_unused(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Funded execution bills exactly one ledger unit per ACTUAL call.

    The debit's 1-based attempt number matches the persisted ProviderAttempt
    row, and terminalization releases the task's unused reservation exactly
    once (``reserved`` returns to zero while ``debited`` keeps the spent
    unit). A replay — re-draining plus re-applying the same deterministic
    ledger actions — never double-debits ((task_id, attempt) idempotency).
    """
    _seed, account, audit = await _make_funded_audit(session_factory, monkeypatch)
    adapter = _ClaudeStubAdapter()
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-funded")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        task_id = task.id
        assert task.status == "succeeded"
        assert task.attempt_count == 1
        assert adapter.calls == 1
        attempts = (
            await session.scalars(
                select(ProviderAttempt).where(ProviderAttempt.task_id == task_id)
            )
        ).all()
        assert [a.attempt_number for a in attempts] == [1]
        debits = await _ledger_entries(session, task_id, LEDGER_ENTRY_DEBIT)
        # Exactly one billable unit, keyed to the persisted attempt number.
        assert len(debits) == 1
        assert debits[0].attempt == 1
        assert debits[0].units == 1
        usage = await consumable_usage(
            session,
            account_id=account.id,
            capability_key=KEY_AUDIT_CREDITS,
            at=datetime.now(UTC),
        )
        assert usage.debited == 1
        # Reservation was max_attempts units: one converted, the rest
        # released at terminalization -> nothing stays reserved.
        assert usage.reserved == 0
        assert usage.available == usage.granted - 1

    # Replay through the public drain contract: a terminal task is a no-op and
    # cannot double-debit or recreate a reservation.
    await worker.run_until_idle()
    async with session_factory() as session:
        debits = await _ledger_entries(session, task_id, LEDGER_ENTRY_DEBIT)
        assert len(debits) == 1
        usage = await consumable_usage(
            session,
            account_id=account.id,
            capability_key=KEY_AUDIT_CREDITS,
            at=datetime.now(UTC),
        )
        assert usage.debited == 1
        assert usage.reserved == 0


@pytest.mark.asyncio
async def test_funded_timeout_call_is_billed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A TIMED-OUT funded call is billable — outcome is never a parameter.

    Both frozen attempts stall past the frozen 0.05s timeout (a live settings
    bump after planning has no effect — invariant 9), each producing one
    failed ProviderAttempt AND one debit with the matching 1-based attempt
    number. The reservation covered exactly ``max_attempts`` units, so
    terminalization leaves nothing reserved.
    """
    _seed, account, audit = await _make_funded_audit(
        session_factory,
        monkeypatch,
        freeze={"audit_timeout_seconds": 0.05, "max_attempts": 2},
    )
    monkeypatch.setattr(audit_settings, "audit_timeout_seconds", 3600.0)  # no effect
    adapter = _StallingAdapter()
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "retry_jitter_seconds", 0.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-funded-to")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        task_id = task.id
        assert task.status == "failed"
        assert task.error_code == ERROR_TIMEOUT
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
        assert all(a.error_code == ERROR_TIMEOUT for a in attempts)
        debits = await _ledger_entries(session, task_id, LEDGER_ENTRY_DEBIT)
        # Two actual (timed-out) calls -> two billable units, 1-based,
        # matching the ProviderAttempt rows exactly.
        assert sorted(d.attempt for d in debits) == [1, 2]
        usage = await consumable_usage(
            session,
            account_id=account.id,
            capability_key=KEY_AUDIT_CREDITS,
            at=datetime.now(UTC),
        )
        assert usage.debited == 2
        assert usage.reserved == 0
        assert usage.available == usage.granted - 2


@pytest.mark.asyncio
async def test_byok_task_never_touches_the_ledger(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    """A BYOK task has no frozen reservation: zero ledger writes, BYOK pools."""
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    worker = AuditWorker(session_factory=session_factory, owner="w-byok-ledger")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        # No reservation/debit/release rows exist for this task at all.
        assert await _ledger_entries(session, task.id) == []
        pairs = await _leased_pools(session, task.id)
        assert {bucket.pool_kind for _, bucket in pairs} == {
            POOL_KIND_TRANSPORT,
            POOL_KIND_CONNECTION,
        }


@pytest.mark.asyncio
async def test_funded_task_never_claimable_without_its_frozen_reservation(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planner invariant regression: no funded task is claimable unreserved.

    The task reaches the claimable ``queued`` state only after its
    reservation exists (same planner transaction), with the reservation id
    frozen into the task's funding block and mirrored in the audit
    configuration's task-reservation map; the pre-reservation state is never
    in the claimable vocabulary.
    """
    _seed, _account, audit = await _make_funded_audit(session_factory, monkeypatch)
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_QUEUED
        assert task.status != TASK_STATUS_PENDING_RESERVATION
        funding = (task.provider_route_snapshot or {}).get("funding") or {}
        assert funding["reservation_id"]
        assert funding["credential_mode"] == CREDENTIAL_MODE_FUNDED
        assert funding["reserved_units"] == task.max_attempts
        audit_row = await session.get(Audit, audit.id)
        assert audit_row is not None
        reservations = (audit_row.configuration or {}).get("task_reservations")
        assert reservations is not None
        assert reservations[str(task.id)] == funding["reservation_id"]
    assert TASK_STATUS_PENDING_RESERVATION not in TASK_CLAIMABLE_STATUSES


@pytest.mark.asyncio
async def test_no_secret_bearing_logs_or_events(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invariant 6: no key material in capacity telemetry, logs, or events.

    Drives a run that parks on capacity (firing ``audit.capacity.wait``
    telemetry), then decrypts the BYOK key and executes; the seeded key must
    appear in NO captured log line, AuditEvent row, or request snapshot.
    """
    monkeypatch.setattr(audit_settings, "per_transport_concurrency", 0)
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: _StubAdapter())
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-secrets")
    with capture_log_messages(
        "app.workers.audit_worker", "app.orchestration.provider_capacity"
    ) as messages:
        await worker.run_pipelined(drain=True)  # parks; capacity telemetry fires
        monkeypatch.setattr(audit_settings, "per_transport_concurrency", 4)
        async with session_factory() as session:
            task = await session.scalar(
                select(AuditTask).where(AuditTask.audit_id == audit.id)
            )
            assert task is not None
            task.available_at = datetime.now(UTC) - timedelta(seconds=1)
            await session.commit()
        await worker.run_until_idle()  # decrypts the key, calls, succeeds

    log_blob = "\n".join(messages)
    assert "audit.capacity.wait" in log_blob  # the park telemetry fired
    assert "secret-test-key" not in log_blob

    async with session_factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.audit_id == audit.id)
            )
        ).all()
        event_blob = "\n".join(
            f"{event.event_type} {event.message} {event.payload}" for event in events
        )
        assert "secret-test-key" not in event_blob
        assert any(e.event_type == EVENT_TASK_CAPACITY_WAIT for e in events)
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        assert "secret-test-key" not in str(task.request_snapshot)


# ---------------------------------------------------------------------------
# T11: the worker LOADS the frozen credential identity — never re-resolves
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_funded_task_executes_with_frozen_platform_connection_key(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The funded task runs against the frozen PLATFORM connection.

    A healthy probed tenant BYOK connection appearing AFTER admission does
    not matter: the worker loads the planner-frozen identity (it never
    re-resolves), so the adapter is built with the platform key, not the
    tenant key.
    """
    seed, _account, audit = await _make_funded_audit(session_factory, monkeypatch)
    # Post-admission, the tenant BYOK connection becomes fully healthy — a
    # re-resolving worker would now prefer it (BYOK precedence).
    async with session_factory() as session:
        tenant_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert tenant_connection is not None
        _mark_connection_probed(
            session, connection=tenant_connection, engine=ENGINE_CLAUDE
        )
        await session.commit()

    captured: dict[str, object] = {}

    def _build(**kwargs: object) -> _ClaudeStubAdapter:
        captured.update(kwargs)
        return _ClaudeStubAdapter()

    monkeypatch.setattr(audit_execution, "build_adapter", _build)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen-platform")
    await worker.run_until_idle()

    assert captured["api_key"] == "platform-secret-test-key"
    assert captured["api_key"] != "secret-test-key"
    assert captured["transport_provider"] == TRANSPORT_ANTHROPIC
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"


@pytest.mark.asyncio
async def test_byok_task_executes_with_frozen_tenant_connection_key(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The BYOK task runs against the frozen TENANT connection.

    A pause marker written AFTER admission does not revoke the frozen
    identity: the worker loads the exact frozen connection (pause affects
    future resolution, not in-flight tasks).
    """
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    async with session_factory() as session:
        tenant_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert tenant_connection is not None
        tenant_connection.paused_at = datetime.now(UTC)
        tenant_connection.pause_reason = ERROR_AUTH
        await session.commit()

    captured: dict[str, object] = {}

    def _build(**kwargs: object) -> _StubAdapter:
        captured.update(kwargs)
        return _StubAdapter()

    monkeypatch.setattr(audit_execution, "build_adapter", _build)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen-byok")
    await worker.run_until_idle()

    assert captured["api_key"] == "secret-test-key"
    assert captured["transport_provider"] == TRANSPORT_GOOGLE
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"


# ---------------------------------------------------------------------------
# T11 stage D: ERROR_AUTH pauses the frozen credential (BYOK + platform)
# ---------------------------------------------------------------------------


class _AuthFailureAdapter(_StubAdapter):
    """Always fails with a NON-retryable auth error (terminal on one call)."""

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        raise ProviderError(
            "provider rejected the credential",
            error_code=ERROR_AUTH,
            retryable=False,
        )


class _ClaudeAuthFailureAdapter(_AuthFailureAdapter):
    """Claude/anthropic auth-failure stub for funded-route executions."""

    logical_engine = ENGINE_CLAUDE
    transport_provider = TRANSPORT_ANTHROPIC


@pytest.mark.asyncio
async def test_byok_auth_failure_pauses_connection_and_fails_task(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BYOK ERROR_AUTH pauses the frozen tenant connection (7-day grace).

    The task fails through CURRENT finalization (auth is non-retryable, so
    one call, then ``failed``; the zero-success audit lands ``failed``), the
    ``provider.byok.paused`` telemetry carries only opaque ids + pause timing,
    and NO platform fallback is attempted — the frozen credential identity
    stands (exactly one adapter build, with the tenant key).
    """
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    builds: list[dict[str, object]] = []

    def _build(**kwargs: object) -> _AuthFailureAdapter:
        builds.append(kwargs)
        return _AuthFailureAdapter()

    monkeypatch.setattr(audit_execution, "build_adapter", _build)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-auth-byok")
    with capture_log_messages("app.providers") as events:
        await worker.run_until_idle()

    # One provider call total: auth is non-retryable and the worker never
    # re-resolves or falls back to another credential.
    assert len(builds) == 1
    assert builds[0]["api_key"] == "secret-test-key"
    assert builds[0]["transport_provider"] == TRANSPORT_GOOGLE

    async with session_factory() as session:
        connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert connection is not None
        assert connection.paused_at is not None
        assert connection.pause_reason == ERROR_AUTH
        assert connection.pause_until is not None
        # The configured seven-day grace window (pause_until = at + 7 days).
        assert connection.pause_until - connection.paused_at == timedelta(days=7)
        # Pause is separate from operator enablement.
        assert connection.active is True

        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "failed"
        assert task.error_code == ERROR_AUTH

        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        # Current finalization: no successful executions -> audit failed.
        assert refreshed.status == AUDIT_STATUS_FAILED
        assert refreshed.failed_count == 1

        # The tenant-facing task-failure event payload is the safe shape
        # only (opaque task id + classification token).
        task_events = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.audit_id == audit.id)
                )
            )
            .scalars()
            .all()
        )
        failure_payloads = [
            e.payload for e in task_events if (e.payload or {}).get("error_code")
        ]
        assert failure_payloads
        for payload in failure_payloads:
            assert set(payload) == {"task_id", "error_code"}
            assert payload["error_code"] == ERROR_AUTH

    rendered = "\n".join(events)
    assert any(TELEMETRY_BYOK_PAUSED in message for message in events)
    assert not any(TELEMETRY_PLATFORM_AUTH_FAILED in message for message in events)
    assert "secret-test-key" not in rendered
    assert str(connection.id) in rendered


@pytest.mark.asyncio
async def test_platform_auth_failure_pauses_platform_row_without_tenant_exposure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Platform ERROR_AUTH pauses the platform row; tenants see no system details.

    The funded task's frozen PLATFORM connection gets the same 7-day pause
    writer treatment (the row's own ``credential_source`` keys the
    ``provider.platform.auth_failed`` telemetry), while every tenant-facing
    audit event payload stays free of system-workspace/platform identity.
    """
    seed, _account, audit = await _make_funded_audit(session_factory, monkeypatch)

    def _build(**kwargs: object) -> _ClaudeAuthFailureAdapter:
        return _ClaudeAuthFailureAdapter()

    monkeypatch.setattr(audit_execution, "build_adapter", _build)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-auth-platform")
    with capture_log_messages("app.providers") as events:
        await worker.run_until_idle()

    async with session_factory() as session:
        platform_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.credential_source == "platform"
            )
        )
        assert platform_connection is not None
        assert platform_connection.paused_at is not None
        assert platform_connection.pause_reason == ERROR_AUTH
        assert platform_connection.pause_until is not None
        assert platform_connection.pause_until - platform_connection.paused_at == (
            timedelta(days=7)
        )

        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "failed"
        assert task.error_code == ERROR_AUTH

        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_FAILED

        # Tenant-facing DTO/event surface: NO system-workspace or platform
        # identity anywhere in the audit's event payloads.
        task_events = (
            (
                await session.execute(
                    select(AuditEvent).where(AuditEvent.audit_id == audit.id)
                )
            )
            .scalars()
            .all()
        )
        assert task_events
        for event in task_events:
            rendered_payload = str(event.payload)
            assert str(platform_connection.id) not in rendered_payload
            assert str(platform_connection.workspace_id) not in rendered_payload
            assert "platform" not in rendered_payload
            assert "system" not in rendered_payload

    rendered = "\n".join(events)
    assert any(TELEMETRY_PLATFORM_AUTH_FAILED in message for message in events)
    assert not any(TELEMETRY_BYOK_PAUSED in message for message in events)
    assert "platform-secret-test-key" not in rendered
