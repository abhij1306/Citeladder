"""Durable abuse budgets, active-job caps, and tenant-fair audit claims."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.abuse import abuse_settings
from app.core.config.audits import AUDIT_QUEUE_SPEC, AUDIT_TRIGGER_MANUAL
from app.domain.abuse.service import UsageLimitExceededError, consume_usage
from app.domain.audits.creation import create_audit
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from tests.component.audit_helpers import seed_audit_fixtures


@pytest.mark.asyncio
async def test_usage_counter_is_atomic_across_api_sessions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def attempt() -> bool:
        async with session_factory() as session:
            try:
                await consume_usage(
                    session,
                    subject_kind="workspace",
                    subject="shared-workspace",
                    operation="expensive.operation",
                    limit=5,
                    window_seconds=3600,
                )
            except UsageLimitExceededError:
                await session.rollback()
                return False
            await session.commit()
            return True

    results = await asyncio.gather(*(attempt() for _ in range(12)))
    assert sum(results) == 5


@pytest.mark.asyncio
async def test_usage_counter_rejects_first_consumption_above_limit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(UsageLimitExceededError):
            await consume_usage(
                session,
                subject_kind="workspace",
                subject="oversized-first-consumption",
                operation="expensive.operation",
                limit=5,
                window_seconds=3600,
                amount=6,
            )
        await session.rollback()

        consumed = await consume_usage(
            session,
            subject_kind="workspace",
            subject="oversized-first-consumption",
            operation="expensive.operation",
            limit=5,
            window_seconds=3600,
            amount=5,
        )
        assert consumed == 5


@pytest.mark.asyncio
async def test_active_audit_limit_is_workspace_scoped_and_durable(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(abuse_settings, "active_audits_per_workspace", 1)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)

    async with session_factory() as session:
        await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
    async with session_factory() as session:
        with pytest.raises(UsageLimitExceededError) as exc_info:
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )
        assert exc_info.value.operation == "audit.active_jobs"


@pytest.mark.asyncio
async def test_concurrent_audit_enqueues_cannot_bypass_active_cap(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(abuse_settings, "active_audits_per_workspace", 1)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)

    async def attempt() -> bool:
        async with session_factory() as session:
            try:
                await create_audit(
                    session,
                    trigger=AUDIT_TRIGGER_MANUAL,
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    engines=seed.engines,
                    prompt_set_id=seed.prompt_set_id,
                    repetitions=1,
                )
            except UsageLimitExceededError:
                await session.rollback()
                return False
            return True

    assert sum(await asyncio.gather(attempt(), attempt())) == 1


@pytest.mark.asyncio
async def test_audit_claim_batch_round_robins_workspaces(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_ids = []
    for _ in range(2):
        async with session_factory() as session:
            seed = await seed_audit_fixtures(session, prompt_count=4)
            workspace_ids.append(seed.workspace_id)
        async with session_factory() as session:
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    claimed = await queue.claim(owner="fair-worker", limit=4)
    counts = {workspace_id: 0 for workspace_id in workspace_ids}
    for task in claimed:
        counts[task.workspace_id] += 1
    assert set(counts.values()) == {2}


@pytest.mark.asyncio
async def test_parallel_claims_are_disjoint_and_preserve_workspace_balance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_ids = []
    for _ in range(2):
        async with session_factory() as session:
            seed = await seed_audit_fixtures(session, prompt_count=4)
            workspace_ids.append(seed.workspace_id)
        async with session_factory() as session:
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    batches = await asyncio.gather(
        queue.claim(owner="fair-worker-a", limit=4),
        queue.claim(owner="fair-worker-b", limit=4),
    )
    claimed = [task for batch in batches for task in batch]

    assert len(claimed) == 8
    assert len({task.id for task in claimed}) == 8
    counts = {workspace_id: 0 for workspace_id in workspace_ids}
    for task in claimed:
        counts[task.workspace_id] += 1
    assert set(counts.values()) == {4}


@pytest.mark.asyncio
async def test_claim_rechecks_eligibility_on_the_locked_relation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The claim must filter eligibility on the row it LOCKS, not only in the
    ranked subquery.

    Under READ COMMITTED, a statement that meets a row another transaction
    updated and committed re-evaluates only the quals attached to the locked
    relation. With the predicate living solely inside
    ``fair_queue_candidates`` there is nothing left to re-check, and two
    workers whose claim statements overlap return the SAME tasks —
    ``SKIP LOCKED`` only covers the window while the first claim still holds
    its lock, not the window after it commits.

    ``test_parallel_claims_are_disjoint_and_preserve_workspace_balance``
    covers the same defect behaviourally, but only reproduces it when the two
    statements interleave just so, so it passes on an unloaded machine. This
    assertion is deterministic: it fails the moment the outer filter is
    dropped.
    """
    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    model = AUDIT_QUEUE_SPEC.model
    statement = queue._claim_statement(  # noqa: SLF001 - shape is the contract
        model=model,
        now=datetime.now(UTC),
        limit=1,
        kinds=None,
        queue_name="audit_tasks",
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))
    locked, _, tail = compiled.partition("FOR UPDATE")

    assert "FOR UPDATE OF audit_tasks SKIP LOCKED" in "FOR UPDATE" + tail
    # The predicate has to appear at BOTH levels: once to rank each
    # workspace's backlog, once on the locked relation for the re-check.
    assert locked.count("audit_tasks.status IN") == 2
    assert locked.count("audit_tasks.available_at <=") == 2


@pytest.mark.asyncio
async def test_new_workspace_is_not_starved_by_older_backlog(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await seed_audit_fixtures(session, prompt_count=4)
    async with session_factory() as session:
        await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=first.workspace_id,
            project_id=first.project_id,
            engines=first.engines,
            prompt_set_id=first.prompt_set_id,
            repetitions=1,
        )

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    first_claim = await queue.claim(owner="fair-worker", limit=1)
    assert first_claim[0].workspace_id == first.workspace_id

    async with session_factory() as session:
        newcomer = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=newcomer.workspace_id,
            project_id=newcomer.project_id,
            engines=newcomer.engines,
            prompt_set_id=newcomer.prompt_set_id,
            repetitions=1,
        )

    next_claim = await queue.claim(owner="fair-worker", limit=1)
    assert next_claim[0].workspace_id == newcomer.workspace_id
