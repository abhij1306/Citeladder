"""Site Health crawl terminalization: the paths that bypass a task's finalize.

A crawl goes terminal ONLY inside ``_reconcile_crawl_status``, which normally
runs in the ``finally`` of ``_execute_task``. Anything that drains a crawl's
last non-terminal task WITHOUT running a worker's finalize therefore used to
strand the crawl in an active status forever — no snapshot, no ``crawl.completed``
event, and clients polling it indefinitely.

These tests pin the two guarantees that close that hole:
  - the sweeper reports the crawls whose tasks it terminalized, and the worker
    reconciles them (``release_expired_detailed`` -> ``run_once``);
  - a stalled crawl with no outstanding tasks is force-reconciled regardless of
    HOW it got that way (``_reconcile_stalled_crawls``).

Requires a real Postgres.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import (
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    EVENT_CRAWL_COMPLETED,
    PHASE_DISCOVERY,
    PHASE_RUN_COMPLETED,
    PHASE_RUN_RUNNING,
    SITE_CRAWL_QUEUE_SPEC,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED
from app.domain.site_health.service.lifecycle import load_events
from app.models.analytics import AnalyticsTask
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlEvent,
    SiteCrawlPhaseRun,
    SiteCrawlTask,
    SiteHealthSnapshot,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.site_health.lifecycle import CrawlLifecycle
from app.workers.site_health_worker import SiteHealthWorker
from tests.component.site_health_helpers import seed_site_crawl


def _worker(session_factory: async_sessionmaker[AsyncSession]) -> SiteHealthWorker:
    """A worker with no transport: these tests never let it reach a fetch."""
    return SiteHealthWorker(session_factory=session_factory, owner="lifecycle-test")


async def _expire_leases(
    session_factory: async_sessionmaker[AsyncSession], crawl_id: uuid.UUID
) -> None:
    async with session_factory() as session:
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == crawl_id)
            .values(lease_expires_at=datetime.now(UTC) - timedelta(minutes=5))
        )
        await session.commit()


async def _exhaust_attempts(
    session_factory: async_sessionmaker[AsyncSession], crawl_id: uuid.UUID
) -> None:
    """Put every task at its attempt ceiling so the sweeper FAILS it terminally."""
    async with session_factory() as session:
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == crawl_id)
            .values(attempt_count=SiteCrawlTask.max_attempts)
        )
        await session.commit()


async def _crawl(
    session_factory: async_sessionmaker[AsyncSession], crawl_id: uuid.UUID
) -> SiteCrawl:
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, crawl_id)
        assert crawl is not None
        return crawl


@pytest.mark.asyncio
async def test_sweeper_reports_crawls_whose_tasks_it_terminalized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``release_expired_detailed`` surfaces the owning crawl of a failed task.

    Without the parent ids nothing downstream can know a reconcile is owed —
    the sweeper's terminal write is invisible to every worker finalize.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=2)

    queue = PostgresTaskQueue(session_factory, SITE_CRAWL_QUEUE_SPEC)
    claimed = await queue.claim(owner="site-a", limit=2)
    assert len(claimed) == 2
    await _exhaust_attempts(session_factory, seed.crawl_id)
    await _expire_leases(session_factory, seed.crawl_id)

    sweep = await queue.release_expired_detailed()

    assert sweep.reclaimed == 2
    assert set(sweep.failed_task_ids) == set(seed.task_ids)
    # De-duplicated: two failed tasks of ONE crawl report that crawl once.
    assert sweep.failed_parent_ids == (seed.crawl_id,)


@pytest.mark.asyncio
async def test_sweeper_retry_reclaim_reports_no_parents(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A reclaim that returns a task to ``retry_wait`` owes no reconcile.

    The task is still outstanding, so the crawl is not drained and reporting it
    would make the worker reconcile on every sweep of a healthy busy crawl.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=2)

    queue = PostgresTaskQueue(session_factory, SITE_CRAWL_QUEUE_SPEC)
    await queue.claim(owner="site-a", limit=2)
    await _expire_leases(session_factory, seed.crawl_id)  # attempts NOT exhausted

    sweep = await queue.release_expired_detailed()

    assert sweep.reclaimed == 2
    assert sweep.failed_task_ids == ()
    assert sweep.failed_parent_ids == ()


@pytest.mark.asyncio
async def test_run_once_terminalizes_crawl_the_sweeper_drained(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """THE stuck-crawl regression.

    The sweeper fails the crawl's last outstanding tasks at max attempts. No
    worker ever runs ``_execute_task`` for them, so before the fix nothing
    called ``_reconcile_crawl_status`` and the crawl stayed 'running' forever.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=2)

    queue = PostgresTaskQueue(session_factory, SITE_CRAWL_QUEUE_SPEC)
    await queue.claim(owner="other-worker", limit=2)
    await _exhaust_attempts(session_factory, seed.crawl_id)
    await _expire_leases(session_factory, seed.crawl_id)

    # No claimable work remains, so this loop does nothing BUT sweep + reconcile.
    assert await _worker(session_factory).run_once() == 0

    async with session_factory() as session:
        statuses = set(
            (
                await session.scalars(
                    select(SiteCrawlTask.status).where(
                        SiteCrawlTask.crawl_id == seed.crawl_id
                    )
                )
            ).all()
        )
    assert statuses == {TASK_STATUS_FAILED}

    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status not in CRAWL_ACTIVE_STATUSES, (
        "crawl left active after the sweeper drained its last task"
    )
    assert crawl.completed_at is not None


@pytest.mark.asyncio
async def test_stalled_crawl_with_no_tasks_is_reconciled(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The backstop: an active crawl with a fully-drained queue terminalizes.

    Models any route that terminalized the last task out of band (a killed
    process between the queue ack and the finalize, a manual status write).
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)

    # Task terminal, crawl still active, quiet for longer than the threshold.
    stale = datetime.now(UTC) - timedelta(seconds=3600)
    async with session_factory() as session:
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == seed.crawl_id)
            .values(status=TASK_STATUS_SUCCEEDED, completed_at=stale)
        )
        await session.execute(
            update(SiteCrawl)
            .where(SiteCrawl.id == seed.crawl_id)
            .values(status=CRAWL_STATUS_RUNNING, updated_at=stale)
        )
        await session.commit()

    # Through the real loop, not the helper directly: the backstop is only
    # worth anything if ``run_once`` actually reaches it.
    assert await _worker(session_factory).run_once() == 0

    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status not in CRAWL_ACTIVE_STATUSES


@pytest.mark.asyncio
async def test_stalled_backstop_ignores_recently_touched_crawls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A crawl merely BETWEEN tasks must never be force-terminalized.

    Its queue is momentarily empty (the enqueue of the next wave has not landed
    yet), but it was touched just now — inside the stall threshold.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == seed.crawl_id)
            .values(status=TASK_STATUS_SUCCEEDED)
        )
        await session.commit()

    reconciled = await CrawlLifecycle(session_factory).reconcile_stalled()

    assert reconciled == 0
    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status == CRAWL_STATUS_RUNNING


@pytest.mark.asyncio
async def test_stalled_backstop_ignores_crawls_with_outstanding_work(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An old crawl with a live queued task is progressing, not stalled."""
    stale = datetime.now(UTC) - timedelta(seconds=3600)
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        await session.execute(
            update(SiteCrawl)
            .where(SiteCrawl.id == seed.crawl_id)
            .values(status=CRAWL_STATUS_RUNNING, updated_at=stale)
        )
        await session.commit()  # task stays QUEUED

    reconciled = await CrawlLifecycle(session_factory).reconcile_stalled()

    assert reconciled == 0
    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status == CRAWL_STATUS_RUNNING


@pytest.mark.asyncio
async def test_stalled_backstop_ignores_paused_phase_control_crawls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    stale = datetime.now(UTC) - timedelta(seconds=3600)
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == seed.crawl_id)
            .values(status=TASK_STATUS_SUCCEEDED, completed_at=stale)
        )
        await session.execute(
            update(SiteCrawl)
            .where(SiteCrawl.id == seed.crawl_id)
            .values(status=CRAWL_STATUS_PAUSED, updated_at=stale)
        )
        await session.commit()

    assert await CrawlLifecycle(session_factory).reconcile_stalled() == 0
    assert (await _crawl(session_factory, seed.crawl_id)).status == CRAWL_STATUS_PAUSED


@pytest.mark.asyncio
async def test_advanced_manual_phase_parks_without_terminal_side_effects(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A drained manual phase pauses cleanly and repeated reconciliation is inert."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert crawl is not None and task is not None
        crawl.sample_mode = False
        crawl.configuration = {"advanced_controls_enabled": True}
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.discovered_url_count = 1
        phase_run = SiteCrawlPhaseRun(workspace_id=seed.workspace_id, crawl_id=seed.crawl_id, phase=PHASE_DISCOVERY, ordinal=1, status=PHASE_RUN_RUNNING, requested_count=1)
        session.add(phase_run)
        await session.flush()
        task.phase_run_id = phase_run.id
        task.status = TASK_STATUS_SUCCEEDED
        task.completed_at = datetime.now(UTC)
        phase_run_id = phase_run.id
        await session.commit()
    lifecycle = CrawlLifecycle(session_factory)
    await lifecycle.reconcile(seed.crawl_id)
    await lifecycle.reconcile(seed.crawl_id)
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        phase_run = await session.get(SiteCrawlPhaseRun, phase_run_id)
        assert crawl is not None and crawl.status == CRAWL_STATUS_PAUSED
        assert crawl.discovery_status == DISCOVERY_STATUS_STOPPED
        assert phase_run is not None and phase_run.status == PHASE_RUN_COMPLETED
        assert await session.scalar(select(SiteHealthSnapshot.id).where(SiteHealthSnapshot.crawl_id == seed.crawl_id)) is None
        assert await session.scalar(select(SiteCrawlEvent.id).where(SiteCrawlEvent.crawl_id == seed.crawl_id, SiteCrawlEvent.event_type == EVENT_CRAWL_COMPLETED)) is None
        assert await session.scalar(select(AnalyticsTask.id)) is None


@pytest.mark.asyncio
async def test_leased_heartbeats_across_the_whole_body(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_leased`` must keep beating for the PERSIST phase, not just the fetch.

    The persist phase takes the crawl row ``FOR UPDATE`` (contending with every
    sibling task's finalize) before it acknowledges the queue row. While it ran
    unheartbeated, a slow write outlived the lease, the sweeper reclaimed the
    task and — at max attempts — failed it terminally, stranding the crawl.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
    task_id = seed.task_ids[0]

    worker = _worker(session_factory)
    beats: list[uuid.UUID] = []

    async def _record(*, task_id: uuid.UUID, owner: str) -> bool:
        beats.append(task_id)
        return True

    monkeypatch.setattr(worker._queue, "heartbeat", _record)
    # The loop takes the configured interval down to a 50ms floor, so this
    # exercises real beats without spending real seconds of wall clock.
    monkeypatch.setattr(site_health_settings, "heartbeat_interval_seconds", 0.1)

    async with worker._leased(task_id):
        # Stand in for the fetch + the persist that follows it.
        await asyncio.sleep(0.35)

    assert beats, "no heartbeat fired inside the leased body"
    assert set(beats) == {task_id}

    # And it stops on exit: the lease must not be held past the body.
    settled = len(beats)
    await asyncio.sleep(0.35)
    assert len(beats) == settled, "heartbeat outlived the leased body"


@pytest.mark.asyncio
async def test_stalled_backstop_can_be_disabled(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A zero threshold turns the backstop off without touching the sweep path."""
    stale = datetime.now(UTC) - timedelta(seconds=3600)
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.crawl_id == seed.crawl_id)
            .values(status=TASK_STATUS_SUCCEEDED, completed_at=stale)
        )
        await session.execute(
            update(SiteCrawl)
            .where(SiteCrawl.id == seed.crawl_id)
            .values(status=CRAWL_STATUS_RUNNING, updated_at=stale)
        )
        await session.commit()

    monkeypatch.setattr(
        site_health_settings, "stalled_crawl_reconcile_seconds", 0.0, raising=False
    )
    assert await CrawlLifecycle(session_factory).reconcile_stalled() == 0

    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status == CRAWL_STATUS_RUNNING


# =========================================================================
# Event replay keyset (the SSE resume anchor)
# =========================================================================
async def _add_event(
    session: AsyncSession, *, crawl_id: uuid.UUID, event_type: str
) -> SiteCrawlEvent:
    event = SiteCrawlEvent(crawl_id=crawl_id, event_type=event_type, message="")
    session.add(event)
    await session.flush()
    return event


@pytest.mark.asyncio
async def test_load_events_resumes_after_the_anchor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``after`` returns strictly the events past the anchor, in order."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        first = await _add_event(session, crawl_id=seed.crawl_id, event_type="a")
        second = await _add_event(session, crawl_id=seed.crawl_id, event_type="b")
        third = await _add_event(session, crawl_id=seed.crawl_id, event_type="c")
        await session.commit()
        ordered = sorted(
            (first, second, third), key=lambda row: (row.created_at, row.id)
        )
        anchor_id = ordered[0].id
        last_id = ordered[-1].id
        expected_ids = [row.id for row in ordered[1:]]

    async with session_factory() as session:
        rows = await load_events(session, crawl_id=seed.crawl_id, after=anchor_id)
        assert [row.id for row in rows] == expected_ids

        # No anchor replays everything.
        assert len(await load_events(session, crawl_id=seed.crawl_id)) == 3

        # The LAST event as anchor leaves nothing to send.
        assert await load_events(session, crawl_id=seed.crawl_id, after=last_id) == []


@pytest.mark.asyncio
async def test_load_events_stale_or_foreign_anchor_replays_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An anchor this crawl does not own must NOT replay the whole history.

    The keyset compares against a scalar subquery, so an unknown anchor makes
    both comparisons NULL and the page comes back empty. Replaying instead
    would duplicate every event a resuming client already rendered.
    """
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        other = await seed_site_crawl(session)
        await _add_event(session, crawl_id=seed.crawl_id, event_type="a")
        foreign = await _add_event(session, crawl_id=other.crawl_id, event_type="a")
        await session.commit()
        foreign_id = foreign.id

    async with session_factory() as session:
        # An id that exists, but on another crawl.
        assert (
            await load_events(session, crawl_id=seed.crawl_id, after=foreign_id) == []
        )
        # An id that does not exist at all.
        assert (
            await load_events(session, crawl_id=seed.crawl_id, after=uuid.uuid4()) == []
        )
