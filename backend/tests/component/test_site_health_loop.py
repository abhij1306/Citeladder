"""The claim loop: bounded concurrent batches and failure propagation.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
)
from app.models.site_health import (
    SiteCrawlTask,
)
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    _worker,
)


@pytest.mark.asyncio
async def test_run_once_claims_and_executes_a_bounded_concurrent_batch(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Postgres claim batch executes concurrently instead of serially."""
    async with session_factory() as session:
        await seed_site_crawl(session, task_count=2)

    worker = _worker(session_factory, {}, owner="single-claim")
    executed: list[uuid.UUID] = []
    active = 0
    max_active = 0

    async def record_only(task: SiteCrawlTask) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        executed.append(task.id)
        await asyncio.sleep(0)
        active -= 1

    monkeypatch.setattr(site_health_settings, "worker_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "global_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "per_host_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    monkeypatch.setattr(worker, "_execute_task", record_only)
    assert await worker.run_once() == 2
    assert len(executed) == 2
    assert max_active == 2

    async with session_factory() as session:
        leased = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(SiteCrawlTask.status == TASK_STATUS_LEASED)
        )
        queued = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(SiteCrawlTask.status == TASK_STATUS_QUEUED)
        )
        assert leased == 2
        assert queued == 0


@pytest.mark.asyncio
async def test_run_once_waits_for_all_claimed_tasks_before_raising(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crashing child must not abandon a still-running sibling mid-lease.

    One claimed task raises immediately while the other blocks; ``run_once()``
    must stay pending until the blocked child completes, then re-raise.
    """
    async with session_factory() as session:
        await seed_site_crawl(session, task_count=2)

    worker = _worker(session_factory, {}, owner="gather-wait")
    release = asyncio.Event()
    blocked_started = asyncio.Event()
    blocked_finished = asyncio.Event()
    calls = 0

    async def crash_or_block(task: SiteCrawlTask) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        blocked_started.set()
        await release.wait()
        blocked_finished.set()

    monkeypatch.setattr(site_health_settings, "worker_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "global_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "per_host_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    monkeypatch.setattr(worker, "_execute_task", crash_or_block)

    run = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(blocked_started.wait(), timeout=5)
    # The crashed child has already raised; run_once must still be pending.
    await asyncio.sleep(0.05)
    assert not run.done()
    release.set()
    with pytest.raises(RuntimeError, match="boom"):
        await asyncio.wait_for(run, timeout=5)
    assert blocked_finished.is_set()
