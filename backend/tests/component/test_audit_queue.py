"""PostgresTaskQueue: SKIP LOCKED no-double-claim + lease sweeper (invariant 8).

Requires a real Postgres (the queue relies on ``FOR UPDATE SKIP LOCKED``, which
SQLite cannot emulate). Two workers claiming concurrently must partition the
tasks with no overlap; the sweeper must reclaim an expired lease.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_QUEUE_SPEC,
    AUDIT_TRIGGER_MANUAL,
    TASK_STATUS_CAPACITY_WAIT,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_RETRY_WAIT,
)
from app.domain.audits.creation import create_audit
from app.models.audit import AuditTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from tests.component.audit_helpers import seed_audit_fixtures


async def _make_queued_audit(
    session_factory: async_sessionmaker[AsyncSession], *, prompts: int, reps: int
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
        )
        return audit


@pytest.mark.asyncio
async def test_concurrent_claims_never_double_claim(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_queued_audit(session_factory, prompts=6, reps=2)  # 12
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    # Two workers claim the whole queue concurrently. SKIP LOCKED must partition
    # the rows so no task is handed to both.
    results = await asyncio.gather(
        queue.claim(owner="worker-a", limit=12),
        queue.claim(owner="worker-b", limit=12),
    )
    claimed_a = {t.id for t in results[0]}
    claimed_b = {t.id for t in results[1]}

    assert claimed_a.isdisjoint(claimed_b)
    assert len(claimed_a) + len(claimed_b) == 12
    assert all(t.status == TASK_STATUS_LEASED for r in results for t in r)
    assert all(t.lease_owner in ("worker-a", "worker-b") for r in results for t in r)


@pytest.mark.asyncio
async def test_sweeper_reclaims_expired_lease(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_queued_audit(session_factory, prompts=1, reps=1)  # 1
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    claimed = await queue.claim(owner="dead-worker", limit=1)
    assert len(claimed) == 1
    task_id = claimed[0].id

    # Force the lease into the past to simulate a crashed worker.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    reclaimed = await queue.release_expired()
    assert reclaimed == 1

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        # Attempts remain -> returned to retry_wait, available immediately.
        assert task.status == TASK_STATUS_RETRY_WAIT
        assert task.lease_owner is None

    # Now it is claimable again by a live worker.
    reclaimed_tasks = await queue.claim(owner="new-worker", limit=1)
    assert len(reclaimed_tasks) == 1
    assert reclaimed_tasks[0].id == task_id


@pytest.mark.asyncio
async def test_sweeper_fails_task_when_attempts_exhausted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _make_queued_audit(session_factory, prompts=1, reps=1)
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    claimed = await queue.claim(owner="dead-worker", limit=1)
    task_id = claimed[0].id

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.attempt_count = task.max_attempts  # budget spent
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    reclaimed = await queue.release_expired()
    assert reclaimed == 1

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.completed_at is not None


@pytest.mark.asyncio
async def test_succeed_and_retry_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    audit = await _make_queued_audit(session_factory, prompts=2, reps=1)  # 2
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    claimed = await queue.claim(owner="w1", limit=2)
    assert len(claimed) == 2
    first, second = claimed[0].id, claimed[1].id

    assert await queue.mark_running(task_id=first, owner="w1")
    assert await queue.succeed(task_id=first, owner="w1")
    # A retry reschedules into the future and releases the lease.
    assert await queue.retry(
        task_id=second,
        owner="w1",
        delay_seconds=60,
        error_code="rate_limit",
    )

    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditTask).where(AuditTask.audit_id == audit.id)
            )
        ).all()
        by_id = {r.id: r for r in rows}
        assert by_id[first].status == "succeeded"
        assert by_id[second].status == TASK_STATUS_RETRY_WAIT
        assert by_id[second].available_at > datetime.now(UTC)

    # A different owner cannot finalize a task it does not hold.
    assert not await queue.succeed(task_id=second, owner="someone-else")


_FIXTURE_SURFACE = "google_shopping"


@pytest.mark.asyncio
async def test_capacity_wait_rows_are_claimable_once_due(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``capacity_wait`` is in the claimable vocabulary, gated on available_at.

    A capacity-parked row reuses ``available_at`` (no duplicate queued-state
    column): it is skipped while its time is in the future and claimed exactly
    like a retry once due.
    """
    audit = await _make_queued_audit(session_factory, prompts=2, reps=1)  # 2
    async with session_factory() as session:
        rows = (
            await session.scalars(
                select(AuditTask).where(AuditTask.audit_id == audit.id)
            )
        ).all()
        parked, other = rows[0], rows[1]
        parked.status = TASK_STATUS_CAPACITY_WAIT
        parked.available_at = datetime.now(UTC) + timedelta(hours=1)
        await session.commit()
        parked_id, other_id = parked.id, other.id

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    claimed = await queue.claim(owner="w1", limit=10)
    # Parked in the future: not claimable; the queued sibling is.
    assert {t.id for t in claimed} == {other_id}

    async with session_factory() as session:
        task = await session.get(AuditTask, parked_id)
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    claimed = await queue.claim(owner="w1", limit=10)
    assert {t.id for t in claimed} == {parked_id}
    assert claimed[0].status == TASK_STATUS_LEASED


@pytest.mark.asyncio
async def test_park_capacity_wait_releases_lease_until_due(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``park_capacity_wait`` parks an owned running row without spending budget.

    The lease is released and ``attempt_count`` untouched (no provider call
    happened); the row leaves the claimable set until ``available_at`` passes
    and only the lease owner may park it.
    """
    await _make_queued_audit(session_factory, prompts=1, reps=1)  # 1
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    claimed = await queue.claim(owner="w1", limit=1)
    assert len(claimed) == 1
    task_id = claimed[0].id
    assert await queue.mark_running(task_id=task_id, owner="w1")

    due = datetime.now(UTC) + timedelta(hours=1)
    assert await queue.park_capacity_wait(task_id=task_id, owner="w1", available_at=due)

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_CAPACITY_WAIT
        assert task.lease_owner is None
        assert task.lease_expires_at is None
        assert task.available_at == due
        # No attempt budget was spent: the provider call never started.
        assert task.attempt_count == 0

    # Parked in the future: not claimable by anyone.
    assert await queue.claim(owner="w2", limit=1) == []

    # Once due it is claimable again; a non-owner cannot park it.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.available_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    reclaimed = await queue.claim(owner="w2", limit=1)
    assert [t.id for t in reclaimed] == [task_id]
    assert await queue.mark_running(task_id=task_id, owner="w2")
    assert not await queue.park_capacity_wait(
        task_id=task_id, owner="w1", available_at=due
    )
    assert await queue.park_capacity_wait(task_id=task_id, owner="w2", available_at=due)
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_CAPACITY_WAIT
        assert task.attempt_count == 0


@pytest.mark.asyncio
async def test_claim_transition_sweeper_ignore_shopping_surface(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Fixture probe rows (non-measurement surface) stay fully queue-visible.

    The shopping-surface slot is a planner/API boundary only: claim, the
    succeed/retry transitions, and the lease sweeper must NOT predicate on
    ``shopping_surface`` — probe rows drain through the same worker pool.
    """
    audit = await _make_queued_audit(session_factory, prompts=1, reps=1)  # 1

    # Seed a probe task sharing the measurement slot except for the surface
    # segment (the fifth uq_audit_task_slot column + idempotency key suffix).
    async with session_factory() as session:
        measurement = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert measurement is not None
        assert measurement.shopping_surface == ""
        measurement_id = measurement.id
        probe = AuditTask(
            audit_id=audit.id,
            workspace_id=measurement.workspace_id,
            prompt_snapshot_id=measurement.prompt_snapshot_id,
            engine_snapshot_id=measurement.engine_snapshot_id,
            prompt_index=measurement.prompt_index,
            repetition=measurement.repetition,
            randomized_position=measurement.randomized_position,
            logical_engine=measurement.logical_engine,
            transport_provider=measurement.transport_provider,
            transport_model=measurement.transport_model,
            shopping_surface=_FIXTURE_SURFACE,
            prompt_text=measurement.prompt_text,
            provider_route_snapshot=measurement.provider_route_snapshot,
            idempotency_key=f"{measurement.idempotency_key}{_FIXTURE_SURFACE}",
            max_attempts=measurement.max_attempts,
        )
        session.add(probe)
        await session.commit()
        probe_id = probe.id

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)

    # Claim partitions BOTH rows with no surface predicate.
    claimed = await queue.claim(owner="w-probe", limit=10)
    assert {t.id for t in claimed} == {measurement_id, probe_id}

    # Expire only the probe's lease: the sweeper reclaims it (unfiltered).
    async with session_factory() as session:
        task = await session.get(AuditTask, probe_id)
        assert task is not None
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    assert await queue.release_expired() == 1
    async with session_factory() as session:
        task = await session.get(AuditTask, probe_id)
        assert task is not None
        assert task.status == TASK_STATUS_RETRY_WAIT
        assert task.lease_owner is None
        # The measurement lease was still valid: untouched by the sweep.
        other = await session.get(AuditTask, measurement_id)
        assert other is not None
        assert other.status == TASK_STATUS_LEASED

    # Transitions finalize the probe row exactly like a measurement row.
    assert await queue.claim(owner="w-probe", limit=10)
    assert await queue.mark_running(task_id=probe_id, owner="w-probe")
    assert await queue.succeed(task_id=probe_id, owner="w-probe")
    async with session_factory() as session:
        task = await session.get(AuditTask, probe_id)
        assert task is not None
        assert task.status == "succeeded"
        assert task.shopping_surface == _FIXTURE_SURFACE
