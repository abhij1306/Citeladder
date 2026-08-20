"""Adapter stubs and audit builders shared by the audit-worker test modules.

Extracted when the attempt-budget scenarios moved into their own file: the
stubs are the seam every worker test needs (no network, deterministic
provenance), and duplicating them per module is how two copies drift into
asserting different things about the same worker.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.workers.audit.execution as audit_execution
from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
    CitationResult,
    FinishReason,
    NormalizedUsage,
    SearchEventResult,
)
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.audits import AUDIT_TRIGGER_MANUAL, audit_settings
from app.core.config.provider_catalog import (
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    ERROR_CLIENT,
    ERROR_RATE_LIMIT,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
)
from app.domain.audits.creation import create_audit
from app.models.audit import ProviderCapacityBucket, ProviderCapacityLease
from app.models.billing import ConsumableLedger
from tests.component.audit_helpers import seed_audit_fixtures


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


def _pin_attempt_budget(monkeypatch: pytest.MonkeyPatch, attempts: int) -> None:
    """Pin the frozen attempt ceiling whichever mode the audit is planned in.

    The budget is per-mode policy (pulse retries fewer times than benchmark),
    so pinning only ``max_attempts`` pins the branch these pulse-mode audits
    do not take.
    """
    monkeypatch.setattr(audit_settings, "max_attempts", attempts)
    monkeypatch.setattr(audit_settings, "pulse_max_attempts", attempts)


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
    """Always fail with a non-retryable client error."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        raise ProviderError("bad request", error_code=ERROR_CLIENT, retryable=False)


async def _leased_pools(
    session: AsyncSession, task_id: uuid.UUID
) -> list[tuple[ProviderCapacityLease, ProviderCapacityBucket]]:
    """Return the capacity leases and buckets used by one task."""
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
    session: AsyncSession, task_id: uuid.UUID, kind: str | None = None
) -> list[ConsumableLedger]:
    """Return ledger entries for one task, optionally filtered by kind."""
    stmt = select(ConsumableLedger).where(ConsumableLedger.task_id == task_id)
    if kind is not None:
        stmt = stmt.where(ConsumableLedger.entry_kind == kind)
    return list((await session.scalars(stmt)).all())
