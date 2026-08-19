"""AuditWorker: claim -> call (mocked) -> persist -> finalize (invariants 3, 8, 9).

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

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
    CitationResult,
    FinishReason,
    NormalizedUsage,
    SearchEventResult,
)
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCEEDED,
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_FAILED,
    AUDIT_TRIGGER_MANUAL,
    CAPACITY_CODE_CONCURRENCY,
    CAPACITY_CODE_RATE_LIMITED,
    EVENT_TASK_CAPACITY_WAIT,
    EVENT_TASK_RETRY,
    EVENT_TASK_SUCCEEDED,
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_POLICY_KEY,
    POOL_KIND_CONNECTION,
    POOL_KIND_TRANSPORT,
    PULSE_ANSWER_INSTRUCTION,
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_CAPACITY_WAIT,
    TASK_STATUS_PENDING_RESERVATION,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RETRY_WAIT,
    audit_settings,
)
from app.core.config.costs import (
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_PARTIAL,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_FUNDED,
    KEY_PULSE_CREDITS,
    LEDGER_ENTRY_DEBIT,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    ERROR_AUTH,
    ERROR_CLIENT,
    ERROR_INVALID_SURFACE,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
    ROUTE_CAPACITY_POLICIES,
    TELEMETRY_BYOK_PAUSED,
    TELEMETRY_PLATFORM_AUTH_FAILED,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
    RouteCapacityPolicy,
    route_policy,
)
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.creation import create_audit
from app.domain.audits.reads import list_tasks
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.ledger import consumable_usage
from app.domain.entitlements.types import GrantSpec
from app.models.analysis import MetricSnapshot, ResponseAnalysis
from app.models.audit import (
    Audit,
    AuditEvent,
    AuditTask,
    ExecutionCostProjection,
    ProviderAttempt,
    ProviderCapacityBucket,
    ProviderCapacityLease,
    RawResponseArtifact,
)
from app.models.billing import ConsumableLedger
from app.models.provider import ProviderConnection
from app.workers.audit import execution as audit_execution
from app.workers.audit import terminalization as audit_terminalization
from app.workers.audit_worker import AuditWorker
from tests.component.audit_helpers import (
    _mark_connection_probed,
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.log_capture import capture_log_messages
from tests.component.occupancy_helpers import seed_occupancy_grants


class _StubAdapter:
    """In-memory stand-in for an answer-engine adapter (no network)."""

    logical_engine = ENGINE_GEMINI
    transport_provider = TRANSPORT_GOOGLE

    def __init__(self, **_: object) -> None:
        # No-op: stub holds no state; accepts and ignores adapter build kwargs.
        pass

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        return AnswerEngineResponse(
            logical_engine=self.logical_engine,
            transport_provider=self.transport_provider,
            transport_model=request.model,
            answer_text=f"Acme is a great option for {request.prompt}.",
            search_used=True,
            search_events=(SearchEventResult(sequence=0, query=request.prompt),),
            citations=(
                CitationResult(
                    ordinal=0,
                    url="https://acme.com/",
                    title="Acme",
                    domain="acme.com",
                    start_index=0,
                    end_index=4,
                    cited_text="Acme",
                ),
            ),
            provider_metadata={"query_text_available": True},
            # The typed usage contract (what all three live parsers emit).
            normalized_usage=NormalizedUsage(
                uncached_input_tokens=10,
                output_tokens=20,
                total_tokens=30,
                web_search_requests=1,
            ),
            finish_reason=FinishReason.STOP,
            raw_finish_reason="end_turn",
            latency_ms=5,
        )


@pytest.fixture
def _stub_adapter(monkeypatch: pytest.MonkeyPatch):
    def _build(**_: object) -> _StubAdapter:
        return _StubAdapter()

    monkeypatch.setattr(audit_execution, "build_adapter", _build)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)


async def _make_audit(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    prompts: int,
    reps: int,
    measurement_mode: str | None = None,
):
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
            repetitions=reps,
            random_seed="1",
            measurement_mode=measurement_mode,
        )
        return seed, audit


@pytest.mark.asyncio
async def test_worker_runs_all_tasks_and_finalizes(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    seed, audit = await _make_audit(session_factory, prompts=3, reps=2)  # 6
    worker = AuditWorker(session_factory=session_factory, owner="w-test")

    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"succeeded"}
        assert all(t.answer_text for t in tasks)
        assert all(t.result_artifact_id is not None for t in tasks)

        # One immutable artifact + one attempt per task (invariant 3).
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
        cost_projections = await session.scalar(
            select(func.count())
            .select_from(ExecutionCostProjection)
            .where(ExecutionCostProjection.audit_id == audit.id)
        )
        assert artifacts == 6
        assert attempts == 6
        assert cost_projections == 6

        cost_projection = await session.scalar(
            select(ExecutionCostProjection).where(
                ExecutionCostProjection.audit_id == audit.id
            )
        )
        assert cost_projection is not None
        # Legacy total keys map to uncached-input/output; cache/reasoning
        # splits and provider cost are unknown — null, never zero. The Gemini
        # Pulse token rates are verified, but its search-fee line is not, so
        # the complete projection remains partial.
        assert cost_projection.uncached_input_tokens == 10
        assert cost_projection.output_tokens == 20
        assert cost_projection.total_tokens == 30
        assert cost_projection.search_requests == 1
        assert cost_projection.cached_input_tokens is None
        assert cost_projection.reasoning_tokens is None
        assert cost_projection.uncached_input_cost_microusd == 3
        assert cost_projection.projected_total_cost_microusd is None
        assert cost_projection.provider_reported_cost_microusd is None
        assert cost_projection.projection_status == PROJECTION_STATUS_PARTIAL
        assert cost_projection.formula_version == EXECUTION_COST_FORMULA_VERSION
        assert cost_projection.pricing_version == PRICING_CATALOG_VERSION
        # Provenance: one actual persisted ProviderAttempt for this task, and
        # the projection points at its immutable source artifact.
        assert cost_projection.attempt_count == 1
        artifact = await session.get(
            RawResponseArtifact, cost_projection.raw_response_artifact_id
        )
        assert artifact is not None
        assert artifact.task_id == cost_projection.task_id

        # Each succeeded task was scored on persist (B6, invariant 4).
        assert all(t.score is not None for t in tasks)

        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        # Execution complete -> analysis stage runs -> audit COMPLETED (B6).
        assert refreshed.status == AUDIT_STATUS_COMPLETED
        assert refreshed.completed_count == 6
        assert refreshed.failed_count == 0
        assert refreshed.started_at is not None
        assert refreshed.completed_at is not None

        # One aggregated MetricSnapshot with a populated Visibility Score.
        snapshot = await session.scalar(
            select(MetricSnapshot).where(MetricSnapshot.audit_id == audit.id)
        )
        assert snapshot is not None
        assert snapshot.total_completed == 6
        assert snapshot.total_failed == 0
        # The stub always mentions "Acme" (the brand) -> 100% Visibility.
        assert snapshot.visibility_score == 100.0
        assert snapshot.analyzer_version

        # One ResponseAnalysis per succeeded execution (invariant 4).
        analyses = await session.scalar(
            select(func.count())
            .select_from(ResponseAnalysis)
            .where(ResponseAnalysis.audit_id == audit.id)
        )
        assert analyses == 6


class _OpenAIStubAdapter(_StubAdapter):
    """OpenAI direct stub: records the chatgpt/openai provenance triple."""

    logical_engine = ENGINE_CHATGPT
    transport_provider = TRANSPORT_OPENAI


class _ConcurrencyProbeAdapter(_StubAdapter):
    """Stub that records how many executes overlap in flight."""

    in_flight = 0
    max_in_flight = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        cls = _ConcurrencyProbeAdapter
        cls.in_flight += 1
        cls.max_in_flight = max(cls.max_in_flight, cls.in_flight)
        try:
            # Yield so concurrently-running tasks can enter before we return;
            # under serial execution max_in_flight would stay at 1.
            await asyncio.sleep(0.05)
            return await super().execute(request)
        finally:
            cls.in_flight -= 1


@pytest.mark.asyncio
async def test_worker_executes_claimed_batch_concurrently(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A claimed batch runs concurrently (asyncio.gather), so per-prompt provider
    # latency doesn't stack linearly across the run's wall-clock time.
    seed, audit = await _make_audit(session_factory, prompts=4, reps=1)  # 4 tasks

    _ConcurrencyProbeAdapter.in_flight = 0
    _ConcurrencyProbeAdapter.max_in_flight = 0
    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _ConcurrencyProbeAdapter()
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "worker_concurrency", 4)

    worker = AuditWorker(session_factory=session_factory, owner="w-conc")
    await worker.run_until_idle()

    assert _ConcurrencyProbeAdapter.max_in_flight > 1

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"succeeded"}
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED
        assert refreshed.completed_count == 4


class _BlockingFirstCallAdapter(_StubAdapter):
    """First call blocks until released; every later call returns immediately."""

    release: asyncio.Event
    started = 0
    finished = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        cls = _BlockingFirstCallAdapter
        cls.started += 1
        if cls.started == 1:
            await cls.release.wait()
        result = await super().execute(request)
        cls.finished += 1
        return result


@pytest.mark.asyncio
async def test_worker_refills_slots_while_a_slow_call_is_still_in_flight(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The convoy regression. The worker used to claim a batch of
    # ``worker_concurrency`` tasks, ``gather`` ALL of them, and only then claim
    # the next batch — so one slow call stalled every finished slot behind it.
    # Provider latency is very uneven in practice (a measured Claude run ranged
    # 3.4s to 46.3s, because latency tracks the answer's output-token count), so
    # a straggler in the batch is the normal case.
    #
    # Asserted behaviourally rather than by wall-clock, which would be both
    # flaky and a weak signal: uniform latency has no convoy effect at all, so a
    # timing threshold mostly measures fixture overhead. Here ONE call is pinned
    # open while the others run. Under lock-step batching the first batch can
    # never complete, so NO further task could even be claimed; pipelined, the
    # free slot keeps draining the queue past it.
    seed, audit = await _make_audit(session_factory, prompts=6, reps=1)

    _BlockingFirstCallAdapter.release = asyncio.Event()
    _BlockingFirstCallAdapter.started = 0
    _BlockingFirstCallAdapter.finished = 0
    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _BlockingFirstCallAdapter()
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "worker_concurrency", 2)

    worker = AuditWorker(session_factory=session_factory, owner="w-pipeline")
    run = asyncio.create_task(worker.run_until_idle())
    try:
        # The other slot must get through the remaining 5 tasks unaided. With a
        # concurrency of 2, batching could not finish even one.
        async with asyncio.timeout(30):
            while _BlockingFirstCallAdapter.finished < 5:
                await asyncio.sleep(0.01)
    finally:
        _BlockingFirstCallAdapter.release.set()
    await run

    assert _BlockingFirstCallAdapter.finished == 6
    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"succeeded"}
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED
        assert refreshed.completed_count == 6


@pytest.mark.asyncio
async def test_worker_persists_openai_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A ChatGPT audit executes over the direct ``openai`` transport and freezes
    # the configured ChatGPT/OpenAI provenance triple on the task + attempt.
    async with session_factory() as session:
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=[ENGINE_CHATGPT]
        )
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

    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _OpenAIStubAdapter()
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-openai")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        assert task.logical_engine == ENGINE_CHATGPT
        assert task.transport_provider == TRANSPORT_OPENAI
        assert task.transport_model == "gpt-5.4-nano-2026-03-17"
        assert task.result_artifact_id is not None


@pytest.mark.asyncio
async def test_worker_rejects_frozen_retired_task_without_network(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A task frozen before the transport retirement still points at a retired
    # transport. The worker must fail it terminally with ``invalid_surface``
    # BEFORE the connection-activity check, key decryption, or any network call
    # (invariant 6/10) — build_adapter must never be reached.
    seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    # Rewrite the frozen task + engine snapshot to the retired transport, as a
    # persisted pre-retirement task would look.
    async with session_factory() as session:
        from app.models.audit import AuditEngineSnapshot

        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        task.transport_provider = "retired"
        snapshot = await session.get(AuditEngineSnapshot, task.engine_snapshot_id)
        if snapshot is not None:
            snapshot.transport_provider = "retired"
        await session.commit()

    def _boom(**_: object):  # noqa: ANN202
        raise AssertionError("build_adapter must not be called for a retired transport")

    monkeypatch.setattr(audit_execution, "build_adapter", _boom)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen")
    await worker.run_until_idle()

    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"failed"}
        assert {t.error_code for t in tasks} == {ERROR_INVALID_SURFACE}
        # No external provider call was made (build_adapter would have raised)
        # → no raw artifact is persisted (invariant 6/10). The single terminal
        # bookkeeping attempt documents the rejection, not a network round-trip.
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        assert artifacts == 0
        attempts = (
            await session.scalars(
                select(ProviderAttempt).where(ProviderAttempt.audit_id == audit.id)
            )
        ).all()
        assert all(a.status == "failed" for a in attempts)
        assert all(a.error_code == ERROR_INVALID_SURFACE for a in attempts)
        assert all(a.artifact_id is None for a in attempts)


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


class _FlakyAdapter(_StubAdapter):
    """Fails with a retryable error ``fail_times`` times, then succeeds."""

    def __init__(self, *, fail_times: int, retry_after: float = 0.2) -> None:
        self._fail_times = fail_times
        # A 429 writes the shared pool cooldown (T4): keep the hint tiny by
        # default so the drain bridges it instead of waiting the full
        # configured max cooldown.
        self._retry_after = retry_after
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ProviderError(
                "temporary rate limit",
                error_code=ERROR_RATE_LIMIT,
                retryable=True,
                retry_after_seconds=self._retry_after,
            )
        return await super().execute(request)


@pytest.mark.asyncio
async def test_worker_records_one_attempt_per_provider_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two retryable failures then a success -> three append-only ProviderAttempt
    # rows (invariant 3: one row per attempt), not a single collapsed row.
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)

    adapter = _FlakyAdapter(fail_times=2)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    # Zero the delay knobs so the internal retry loop is fast + deterministic.
    monkeypatch.setattr(audit_settings, "retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "retry_jitter_seconds", 0.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-flaky")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        assert task.attempt_count == 3

        attempts = (
            await session.scalars(
                select(ProviderAttempt)
                .where(ProviderAttempt.audit_id == audit.id)
                .order_by(ProviderAttempt.attempt_number.asc())
            )
        ).all()
        assert len(attempts) == 3
        assert [a.status for a in attempts] == [
            ATTEMPT_STATUS_FAILED,
            ATTEMPT_STATUS_FAILED,
            ATTEMPT_STATUS_SUCCEEDED,
        ]
        assert [a.attempt_number for a in attempts] == [1, 2, 3]
        # The first two carry the retryable error; the last carries the artifact.
        assert attempts[0].error_code == ERROR_RATE_LIMIT
        assert attempts[1].error_code == ERROR_RATE_LIMIT
        assert attempts[-1].artifact_id is not None

        # Exactly one immutable artifact for the single successful call.
        artifacts = await session.scalar(
            select(func.count())
            .select_from(RawResponseArtifact)
            .where(RawResponseArtifact.audit_id == audit.id)
        )
        assert artifacts == 1


_FIXTURE_SURFACE = "google_shopping"


def _probe_row(measurement: AuditTask, *, surface: str) -> AuditTask:
    """A shopping-surface probe sharing the measurement slot (5th column)."""
    return AuditTask(
        audit_id=measurement.audit_id,
        workspace_id=measurement.workspace_id,
        prompt_snapshot_id=measurement.prompt_snapshot_id,
        engine_snapshot_id=measurement.engine_snapshot_id,
        prompt_index=measurement.prompt_index,
        repetition=measurement.repetition,
        randomized_position=measurement.randomized_position,
        logical_engine=measurement.logical_engine,
        transport_provider=measurement.transport_provider,
        transport_model=measurement.transport_model,
        shopping_surface=surface,
        prompt_text=measurement.prompt_text,
        provider_route_snapshot=measurement.provider_route_snapshot,
        idempotency_key=f"{measurement.idempotency_key}{surface}",
        max_attempts=measurement.max_attempts,
    )


@pytest.mark.asyncio
async def test_probe_rows_skip_brand_analysis_and_keep_denominators(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    """§7.1 isolation: probe rows never move brand metrics/counts.

    Seeds one TERMINAL probe (already succeeded — the worker must ignore it)
    and one LIVE probe (queued — the worker drains it but skips brand
    analysis). Progress denominators, the MetricSnapshot, and the
    ResponseAnalysis rows must be identical to the measurement-only baseline.
    """
    seed, audit = await _make_audit(session_factory, prompts=2, reps=1)  # 2

    async with session_factory() as session:
        measurement = await session.scalar(
            select(AuditTask)
            .where(AuditTask.audit_id == audit.id)
            .order_by(AuditTask.prompt_index)
            .limit(1)
        )
        assert measurement is not None
        assert measurement.shopping_surface == ""
        terminal_probe = _probe_row(measurement, surface=_FIXTURE_SURFACE)
        terminal_probe.status = "succeeded"
        terminal_probe.answer_text = "probe answer persisted earlier"
        terminal_probe.attempt_count = 1
        terminal_probe.completed_at = datetime.now(UTC)
        live_probe = _probe_row(measurement, surface="bing_shopping")
        session.add_all([terminal_probe, live_probe])
        await session.commit()
        terminal_probe_id = terminal_probe.id
        live_probe_id = live_probe.id

    worker = AuditWorker(session_factory=session_factory, owner="w-probes")
    await worker.run_until_idle()

    async with session_factory() as session:
        # The live probe drained through the worker: artifact + answer, but
        # NO brand score (brand analysis is measurement-only, §7.1).
        live = await session.get(AuditTask, live_probe_id)
        assert live is not None
        assert live.status == "succeeded"
        assert live.result_artifact_id is not None
        assert live.answer_text
        assert live.score is None

        # The terminal probe was never touched by the worker.
        terminal = await session.get(AuditTask, terminal_probe_id)
        assert terminal is not None
        assert terminal.status == "succeeded"
        assert terminal.result_artifact_id is None
        assert terminal.score is None

        # Brand denominators are measurement-only: identical to the baseline
        # (2 measurement tasks, both succeeded) as if no probe rows existed.
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED
        assert refreshed.completed_count == 2
        assert refreshed.failed_count == 0

        snapshot = await session.scalar(
            select(MetricSnapshot).where(MetricSnapshot.audit_id == audit.id)
        )
        assert snapshot is not None
        assert snapshot.total_completed == 2
        assert snapshot.total_failed == 0
        assert snapshot.visibility_score == 100.0

        # Brand analyses exist only for the two measurement tasks.
        analyses = (
            await session.scalars(
                select(ResponseAnalysis.task_id).where(
                    ResponseAnalysis.audit_id == audit.id
                )
            )
        ).all()
        assert len(analyses) == 2
        assert live_probe_id not in set(analyses)
        assert terminal_probe_id not in set(analyses)

        # Executions listing still defaults to the measurement surface.
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert len(tasks) == 2
        assert all(t.shopping_surface == "" for t in tasks)


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
    _seed, audit = await _make_audit(
        session_factory, prompts=1, reps=1, measurement_mode=MEASUREMENT_MODE_PULSE
    )
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
    assert snapshot["measurement_mode"] == MEASUREMENT_MODE_PULSE
    assert snapshot["stateless"] is True
    # Driven by the frozen block, NOT by whatever the live settings say now.
    assert snapshot["retrieval_enabled"] == frozen["retrieval_enabled"]
    assert snapshot["max_output_tokens"] == frozen["max_output_tokens"]
    assert snapshot["timeout_seconds"] == frozen["timeout_seconds"]
    assert snapshot["answer_instruction"] == frozen["answer_instruction"]
    assert snapshot["answer_instruction"] == PULSE_ANSWER_INSTRUCTION
    assert snapshot["reasoning_effort"] == (
        route_policy(task.logical_engine, MEASUREMENT_MODE_PULSE).reasoning_effort
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
    _seed, audit = await _make_audit(
        session_factory, prompts=1, reps=1, measurement_mode=MEASUREMENT_MODE_PULSE
    )
    planned_cap = audit_settings.pulse_max_output_tokens
    planned_timeout = audit_settings.pulse_timeout_seconds
    monkeypatch.setattr(audit_settings, "pulse_max_output_tokens", 1)
    monkeypatch.setattr(audit_settings, "pulse_timeout_seconds", 999.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
    assert task.request_snapshot["max_output_tokens"] == planned_cap
    assert task.request_snapshot["timeout_seconds"] == planned_timeout


# =========================================================================
# T4 stage B: one call per queue attempt, capacity integration, funded ledger
# =========================================================================


class _StallingAdapter(_StubAdapter):
    """Never returns inside the call; the frozen timeout must cut it off."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        await asyncio.sleep(3600)
        raise AssertionError("unreachable: the wait_for ceiling cancels first")


class _ClaudeStubAdapter(_StubAdapter):
    """Claude/anthropic provenance stub for funded-route executions."""

    logical_engine = ENGINE_CLAUDE
    transport_provider = TRANSPORT_ANTHROPIC

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        return await super().execute(request)


class _ClientErrorAdapter(_StubAdapter):
    """Always fails with a NON-retryable client error (terminal on one call)."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        raise ProviderError("bad request", error_code=ERROR_CLIENT, retryable=False)


async def _leased_pools(
    session: AsyncSession, task_id
) -> list[tuple[ProviderCapacityLease, ProviderCapacityBucket]]:
    """(lease, bucket) pairs one task drew, for release/cooldown assertions."""
    rows = (
        await session.execute(
            select(ProviderCapacityLease, ProviderCapacityBucket)
            .join(
                ProviderCapacityBucket,
                ProviderCapacityLease.bucket_id == ProviderCapacityBucket.id,
            )
            .where(ProviderCapacityLease.task_id == task_id)
        )
    ).all()
    return [(lease, bucket) for lease, bucket in rows]


async def _ledger_entries(
    session: AsyncSession, task_id, kind: str | None = None
) -> list[ConsumableLedger]:
    stmt = select(ConsumableLedger).where(ConsumableLedger.task_id == task_id)
    if kind is not None:
        stmt = stmt.where(ConsumableLedger.entry_kind == kind)
    return list((await session.scalars(stmt)).all())


@pytest.mark.asyncio
async def test_queue_retry_is_the_sole_retry_loop(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One external call per queue attempt; retries go through queue backoff.

    Two retryable failures then a success produce THREE queue attempts (each
    its own claim + ``task.retry`` event) — never a nested in-call retry loop:
    the queue's retry_wait/available_at is the only retry mechanism, and the
    ceiling is the frozen ``task.max_attempts``.
    """
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    adapter = _FlakyAdapter(fail_times=2)
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "retry_jitter_seconds", 0.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-retry")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "succeeded"
        assert task.attempt_count == 3
        # Three queue attempts -> exactly three external calls (no nesting).
        assert adapter.calls == 3
        attempts = (
            await session.scalars(
                select(ProviderAttempt)
                .where(ProviderAttempt.task_id == task.id)
                .order_by(ProviderAttempt.attempt_number.asc())
            )
        ).all()
        assert [a.attempt_number for a in attempts] == [1, 2, 3]
        assert [a.status for a in attempts] == [
            ATTEMPT_STATUS_FAILED,
            ATTEMPT_STATUS_FAILED,
            ATTEMPT_STATUS_SUCCEEDED,
        ]
        events = (
            await session.scalars(
                select(AuditEvent).where(AuditEvent.audit_id == audit.id)
            )
        ).all()
        retry_events = [e for e in events if e.event_type == EVENT_TASK_RETRY]
        succeeded_events = [e for e in events if e.event_type == EVENT_TASK_SUCCEEDED]
        # Two queue backoff cycles (retry_wait + available_at), then success.
        assert len(retry_events) == 2
        assert len(succeeded_events) == 1


@pytest.mark.asyncio
async def test_max_attempts_ceiling_comes_from_the_frozen_task_config(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The queue retry loop stops at the FROZEN ``task.max_attempts``.

    The planner freezes the budget onto the task row; a live settings bump
    after planning must never extend an in-flight run (invariant 9).
    """
    monkeypatch.setattr(audit_settings, "max_attempts", 3)  # frozen at planning
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    monkeypatch.setattr(audit_settings, "max_attempts", 50)  # live bump: no effect
    adapter = _FlakyAdapter(fail_times=100)  # always fails retryably
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    monkeypatch.setattr(audit_settings, "retry_base_delay_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "retry_jitter_seconds", 0.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-ceiling")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "failed"
        # The frozen 3-attempt ceiling held, not the live 50.
        assert task.attempt_count == 3
        assert adapter.calls == 3
        attempts = await session.scalar(
            select(func.count())
            .select_from(ProviderAttempt)
            .where(ProviderAttempt.task_id == task.id)
        )
        assert attempts == 3


@pytest.mark.asyncio
async def test_frozen_mode_timeout_drives_the_call_ceiling(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-call ceiling is the FROZEN per-mode timeout, never live config.

    The stalled adapter would hang this test for an hour if the worker read
    the live settings bumped after planning (invariant 9); the frozen 0.05s
    pulse timeout cuts the call off instead.
    """
    monkeypatch.setattr(audit_settings, "pulse_timeout_seconds", 0.05)
    monkeypatch.setattr(audit_settings, "max_attempts", 1)
    _seed, audit = await _make_audit(
        session_factory, prompts=1, reps=1, measurement_mode=MEASUREMENT_MODE_PULSE
    )
    monkeypatch.setattr(audit_settings, "pulse_timeout_seconds", 3600.0)  # no effect
    adapter = _StallingAdapter()
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: adapter)
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    worker = AuditWorker(session_factory=session_factory, owner="w-frozen-to")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == "failed"
        assert task.error_code == ERROR_TIMEOUT
        assert task.attempt_count == 1
        assert task.request_snapshot["timeout_seconds"] == 0.05
        attempt = await session.scalar(
            select(ProviderAttempt).where(ProviderAttempt.task_id == task.id)
        )
        assert attempt is not None
        assert attempt.attempt_number == 1
        assert attempt.error_code == ERROR_TIMEOUT
        assert adapter.calls == 1


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
    monkeypatch.setattr(audit_settings, "max_attempts", 3)  # frozen budget
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


# --- Funded ledger call sites (stage B; real Postgres) ---------------------


async def _make_funded_audit(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    credits: int = 100,
    freeze: dict[str, object] | None = None,
):
    """A FUNDED pulse/claude audit whose task can execute under the worker.

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
            grants=(GrantSpec(key=KEY_PULSE_CREDITS, value=credits),),
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
            measurement_mode=MEASUREMENT_MODE_PULSE,
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
            capability_key=KEY_PULSE_CREDITS,
            at=datetime.now(UTC),
        )
        assert usage.debited == 1
        # Reservation was max_attempts units: one converted, the rest
        # released at terminalization -> nothing stays reserved.
        assert usage.reserved == 0
        assert usage.available == usage.granted - 1

    # Replay: a duplicate drain is a no-op (the task is terminal), and
    # re-applying the same deterministic ledger actions cannot double-debit.
    await worker.run_until_idle()
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        await worker._apply_funded_ledger(
            session, task=task, billable=True, terminal=True
        )
        await session.commit()
    async with session_factory() as session:
        debits = await _ledger_entries(session, task_id, LEDGER_ENTRY_DEBIT)
        assert len(debits) == 1
        usage = await consumable_usage(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
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
        freeze={"pulse_timeout_seconds": 0.05, "max_attempts": 2},
    )
    monkeypatch.setattr(audit_settings, "pulse_timeout_seconds", 3600.0)  # no effect
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
            capability_key=KEY_PULSE_CREDITS,
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
