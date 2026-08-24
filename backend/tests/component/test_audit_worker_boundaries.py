"""Audit worker cancellation, deadline, lease-loss, and finalize boundaries.

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

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
    FinishReason,
)
from app.core.config.audits import (
    ATTEMPT_STATUS_SUCCEEDED,
    AUDIT_ANSWER_INSTRUCTION,
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_COMPLETED,
    MEASUREMENT_POLICY_KEY,
    audit_settings,
)
from app.core.config.provider_catalog import (
    route_policy,
)
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.reads import list_tasks
from app.models.analysis import ResponseAnalysis
from app.models.audit import (
    Audit,
    AuditTask,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.workers.audit import execution as audit_execution
from app.workers.audit import terminalization as audit_terminalization
from app.workers.audit_worker import AuditWorker
from tests.component.audit_worker_helpers import (
    _make_audit,
    _StubAdapter,
)
from tests.component.audit_worker_helpers import (
    _stub_adapter as _stub_adapter,
)


@pytest.mark.asyncio
async def test_worker_stops_at_boundary_when_cancelled(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    seed, audit = await _make_audit(session_factory, prompts=2, reps=1)  # 2

    # Kill the audit before the worker picks anything up.
    async with session_factory() as session:
        await cancel_audit(session, workspace_id=seed.workspace_id, audit_id=audit.id)

    worker = AuditWorker(session_factory=session_factory, owner="w-cancel")
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_CANCELLED
        # No provider was called -> no artifacts.
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        assert artifacts == 0
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"cancelled"}


@pytest.mark.asyncio
async def test_worker_cuts_off_at_run_deadline(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Deadline already elapsed the instant a task starts -> every task hits the
    # cutoff at its boundary before calling the (stub) provider.
    monkeypatch.setattr(audit_settings, "max_run_seconds", 0.0)
    seed, audit = await _make_audit(session_factory, prompts=2, reps=1)  # 2

    # Mark the audit started so the deadline math trips immediately.
    async with session_factory() as session:
        from datetime import UTC, datetime

        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        refreshed.started_at = datetime.now(UTC)
        await session.commit()

    worker = AuditWorker(session_factory=session_factory, owner="w-deadline")
    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"failed"}
        assert {t.error_code for t in tasks} == {"run_deadline_exceeded"}
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        assert artifacts == 0


@pytest.mark.asyncio
async def test_worker_reads_frozen_run_deadline_not_live_settings(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deadline is FROZEN at creation (invariant 9): shrinking the LIVE
    setting to zero mid-run must NOT terminalize an in-flight audit.
    """
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)  # 1
    monkeypatch.setattr(audit_settings, "max_run_seconds", 0.0)

    # Mark the audit started a minute ago: a LIVE read of the zeroed setting
    # would trip the cutoff immediately; the frozen default (1800s) must not.
    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        refreshed.started_at = datetime.now(UTC) - timedelta(seconds=60)
        await session.commit()

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen-dl")
    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"succeeded"}
        assert {t.error_code for t in tasks} == {""}


@pytest.mark.asyncio
async def test_worker_fails_task_with_missing_connection(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)  # 1

    # Deactivate the connection so key resolution fails terminally.
    async with session_factory() as session:
        from app.models.provider import ProviderConnection

        conns = (
            await session.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.workspace_id == seed.workspace_id
                )
            )
        ).all()
        for conn in conns:
            conn.active = False
        await session.commit()

    worker = AuditWorker(session_factory=session_factory, owner="w-noconn")
    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"failed"}
        assert {t.error_code for t in tasks} == {"provider_connection_missing"}


class _HookAdapter(_StubAdapter):
    """Runs an async callback mid-call, then returns a normal success.

    Simulates something happening on the row (cancel, lease loss) WHILE the
    provider call is in flight, so the persist-time owner/liveness guard can be
    exercised.
    """

    def __init__(self, hook) -> None:
        self._hook = hook

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        await self._hook()
        return await super().execute(request)


@pytest.mark.asyncio
async def test_worker_discards_success_when_cancelled_mid_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A user cancels the audit while the provider call is in flight. The
    # in-flight worker must NOT persist success evidence for a cancelled task.
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    async def _cancel_mid_call() -> None:
        async with session_factory() as session:
            await cancel_audit(
                session, workspace_id=seed.workspace_id, audit_id=audit.id
            )

    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _HookAdapter(_cancel_mid_call)
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-midcancel")
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_CANCELLED
        # The stale success was discarded: no artifact/attempt/analysis rows.
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        attempts = await session.scalar(
            select(func.count())
            .select_from(ProviderAttempt)
            .where(ProviderAttempt.audit_id == audit.id)
        )
        analyses = await session.scalar(
            select(func.count())
            .select_from(ResponseAnalysis)
            .where(ResponseAnalysis.audit_id == audit.id)
        )
        assert artifacts == 0
        assert attempts == 0
        assert analyses == 0
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"cancelled"}
        assert all(t.result_artifact_id is None for t in tasks)


@pytest.mark.asyncio
async def test_worker_discards_success_when_lease_lost_mid_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Worker A's lease expires mid-call and Worker B claims the task. When A
    # returns it must NOT write rows for a task it no longer owns (invariant 3/8).
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    async def _steal_lease() -> None:
        async with session_factory() as session:
            task = await session.scalar(
                select(AuditTask).where(AuditTask.audit_id == audit.id)
            )
            assert task is not None
            task.lease_owner = "worker-b"  # another worker holds it now
            await session.commit()

    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _HookAdapter(_steal_lease)
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="worker-a")
    await worker.run_until_idle()

    async with session_factory() as session:
        # Stale Worker A wrote nothing.
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        attempts = await session.scalar(
            select(func.count())
            .select_from(ProviderAttempt)
            .where(ProviderAttempt.audit_id == audit.id)
        )
        assert artifacts == 0
        assert attempts == 0
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        # The task still belongs to Worker B, not finalized by the stale worker.
        assert task.lease_owner == "worker-b"
        assert task.status == "running"
        assert task.result_artifact_id is None


# =========================================================================
# C4(a): the audit-finalize Opportunities refresh task
# =========================================================================
@pytest.mark.asyncio
async def test_completed_audit_enqueues_opportunities_refresh(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, audit = await _make_audit(session_factory, prompts=2, reps=1)
    calls: list[dict[str, object]] = []

    async def _record(session, *, workspace_id, project_id, audit_id):
        calls.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "audit_id": audit_id,
            }
        )

    monkeypatch.setattr(
        audit_terminalization, "enqueue_audit_opportunity_tasks", _record
    )
    worker = AuditWorker(session_factory=session_factory, owner="w-hook")
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED
    assert calls == [
        {
            "workspace_id": seed.workspace_id,
            "project_id": seed.project_id,
            "audit_id": audit.id,
        }
    ]


@pytest.mark.asyncio
async def test_failed_audit_never_enqueues_opportunities_refresh(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    # Deactivate the connection so every task fails terminally (0 successes
    # -> RUNNING -> FAILED, never ANALYZING).
    async with session_factory() as session:
        from app.models.provider import ProviderConnection

        conns = (
            await session.scalars(
                select(ProviderConnection).where(
                    ProviderConnection.workspace_id == seed.workspace_id
                )
            )
        ).all()
        for conn in conns:
            conn.active = False
        await session.commit()

    calls: list[dict[str, object]] = []

    async def _record(session, *, workspace_id, project_id, audit_id):
        calls.append({"audit_id": audit_id})

    monkeypatch.setattr(
        audit_terminalization, "enqueue_audit_opportunity_tasks", _record
    )
    worker = AuditWorker(session_factory=session_factory, owner="w-hook-fail")
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == "failed"
    assert calls == []


@pytest.mark.asyncio
async def test_opportunities_enqueue_failure_never_blocks_terminalization(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    async def _boom(session, *, workspace_id, project_id, audit_id):
        raise RuntimeError("enqueue exploded")

    monkeypatch.setattr(audit_terminalization, "enqueue_audit_opportunity_tasks", _boom)
    worker = AuditWorker(session_factory=session_factory, owner="w-hook-boom")
    # Best-effort: the raise is logged + swallowed; the audit still
    # terminalizes.
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_comparison_projection_failure_never_blocks_terminalization(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    async def _boom(session, *, audit):
        raise RuntimeError("comparison exploded")

    monkeypatch.setattr(audit_terminalization, "persist_comparison_snapshot", _boom)
    worker = AuditWorker(session_factory=session_factory, owner="w-comparison-boom")
    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_worker_persists_canonical_and_raw_finish_reasons(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    """The canonical finish reason lands on BOTH the task and the artifact.

    Gates read only the canonical enum value; the provider's own spelling is
    kept alongside it for debugging and stays nullable so an absent value is
    never invented.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    worker = AuditWorker(session_factory=session_factory, owner="w-finish")

    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == ATTEMPT_STATUS_SUCCEEDED
        assert task.finish_reason == FinishReason.STOP
        assert task.raw_finish_reason == "end_turn"

        artifact = await session.get(RawResponseArtifact, task.result_artifact_id)
        assert artifact is not None
        assert artifact.finish_reason == FinishReason.STOP
        assert artifact.raw_finish_reason == "end_turn"
        # The artifact persists the TYPED usage contract (unknown counters stay
        # absent/null, never a fabricated zero).
        assert artifact.usage["uncached_input_tokens"] == 10
        assert artifact.usage["output_tokens"] == 20
        assert artifact.usage["total_tokens"] == 30
        assert artifact.usage["cached_input_tokens"] is None
        assert artifact.usage["reasoning_tokens"] is None
        assert artifact.usage["provider_cost_microusd"] is None


@pytest.mark.asyncio
async def test_request_snapshot_records_the_frozen_policy_and_no_secret(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    """The snapshot reproduces the call from the FROZEN policy (invariants 6, 9).

    Every field the adapter was driven by is recorded, and the BYOK key (and the
    brand/competitor list) never reaches a snapshot.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    worker = AuditWorker(session_factory=session_factory, owner="w-snapshot")

    await worker.run_until_idle()

    async with session_factory() as session:
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        frozen = refreshed.configuration[MEASUREMENT_POLICY_KEY]
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None

    snapshot = task.request_snapshot
    assert snapshot["stateless"] is True
    # Driven by the frozen block, NOT by whatever the live settings say now.
    assert snapshot["retrieval_enabled"] == frozen["retrieval_enabled"]
    assert snapshot["max_output_tokens"] == frozen["max_output_tokens"]
    assert snapshot["timeout_seconds"] == frozen["timeout_seconds"]
    assert snapshot["answer_instruction"] == frozen["answer_instruction"]
    assert snapshot["answer_instruction"] == AUDIT_ANSWER_INSTRUCTION
    assert snapshot["reasoning_effort"] == (
        route_policy(task.logical_engine).reasoning_effort
    )
    # Invariant 6: no credential, in any field, at any depth.
    assert "api_key" not in snapshot
    assert "secret-test-key" not in str(snapshot)


@pytest.mark.asyncio
async def test_frozen_policy_survives_a_live_settings_change(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A settings change after planning never leaks into a running audit.

    Invariant 9: the worker executes the policy frozen at plan time, so the
    snapshot keeps the planned cap/timeout even though the live values moved.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    planned_cap = audit_settings.audit_max_output_tokens
    planned_timeout = audit_settings.audit_timeout_seconds
    monkeypatch.setattr(audit_settings, "audit_max_output_tokens", 1)
    monkeypatch.setattr(audit_settings, "audit_timeout_seconds", 999.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
    assert task.request_snapshot["max_output_tokens"] == planned_cap
    assert task.request_snapshot["timeout_seconds"] == planned_timeout
