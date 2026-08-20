"""The attempt budget: one provider call per queue attempt, frozen ceilings.

Split out of ``test_audit_worker.py`` because these scenarios answer one
question the rest of that file does not: how many times may a task call a
provider, and where does that number come from. All three answers are frozen
at planning (invariant 9) — the per-mode attempt budget, the per-mode timeout,
and ``task.max_attempts`` itself — so a live settings change can never extend
or shorten a run already in flight.

Every audit here is planned in the default measurement mode (pulse), which
carries a SMALLER attempt budget than benchmark; ``_pin_attempt_budget`` pins
both knobs so a test that wants three attempts gets three regardless of which
branch the planner takes.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.workers.audit.execution as audit_execution
from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCEEDED,
    EVENT_TASK_RETRY,
    EVENT_TASK_SUCCEEDED,
    MEASUREMENT_MODE_PULSE,
    audit_settings,
)
from app.core.config.provider_catalog import ERROR_RATE_LIMIT, ERROR_TIMEOUT
from app.models.audit import (
    AuditEvent,
    AuditTask,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.workers.audit_worker import AuditWorker
from tests.component.audit_worker_helpers import (
    _FlakyAdapter,
    _make_audit,
    _pin_attempt_budget,
    _StallingAdapter,
)


@pytest.mark.asyncio
async def test_worker_records_one_attempt_per_provider_call(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two retryable failures then a success -> three append-only ProviderAttempt
    # rows (invariant 3: one row per attempt), not a single collapsed row.
    # Needs a budget of three; the default (pulse) mode allows two.
    _pin_attempt_budget(monkeypatch, 3)
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
    _pin_attempt_budget(monkeypatch, 3)
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
    _pin_attempt_budget(monkeypatch, 3)  # frozen at planning
    _seed, audit = await _make_audit(session_factory, prompts=1, reps=1)
    _pin_attempt_budget(monkeypatch, 50)  # live bump: no effect
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
    _pin_attempt_budget(monkeypatch, 1)
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
