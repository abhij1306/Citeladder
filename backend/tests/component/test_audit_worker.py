"""Audit worker happy paths, concurrency, and provider provenance."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
)
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    audit_settings,
)
from app.core.config.costs import (
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ERROR_INVALID_SURFACE,
    TRANSPORT_OPENAI,
)
from app.domain.audits.creation import create_audit
from app.domain.audits.reads import list_tasks
from app.models.analysis import MetricSnapshot, ResponseAnalysis
from app.models.audit import (
    Audit,
    AuditTask,
    ExecutionCostProjection,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.workers.audit import execution as audit_execution
from app.workers.audit_worker import AuditWorker
from tests.component.audit_helpers import (
    seed_audit_fixtures,
)
from tests.component.audit_worker_helpers import (
    _make_audit,
    _StubAdapter,
)
from tests.component.audit_worker_helpers import (
    _stub_adapter as _stub_adapter,
)


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
        # splits and provider cost are unknown — null, never zero. The exact
        # Gemini audit route has verified token and search rates.
        assert cost_projection.uncached_input_tokens == 10
        assert cost_projection.output_tokens == 20
        assert cost_projection.total_tokens == 30
        assert cost_projection.search_requests == 1
        assert cost_projection.cached_input_tokens is None
        assert cost_projection.reasoning_tokens is None
        assert cost_projection.uncached_input_cost_microusd == 15
        assert cost_projection.output_cost_microusd == 150
        assert cost_projection.search_cost_microusd == 14_000
        assert cost_projection.projected_total_cost_microusd == 14_165
        assert cost_projection.provider_reported_cost_microusd is None
        assert cost_projection.projection_status == PROJECTION_STATUS_COMPLETE
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
        assert task.transport_model == "gpt-5.6-sol"
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
