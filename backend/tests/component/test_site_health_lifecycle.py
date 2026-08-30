"""Site Health crawl terminalization: the paths that bypass a task's finalize.

A crawl goes terminal ONLY inside ``_reconcile_crawl_status``, which normally
runs in the ``finally`` of ``_execute_task``. Intermediate successful analysis
may now pass a strict read-only gate, but every lifecycle boundary still takes
the authoritative reconciliation path. Anything that drains a crawl's last
non-terminal task WITHOUT running a worker's finalize therefore used to strand
the crawl in an active status forever — no snapshot, no ``crawl.completed``
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

import app.workers.site_health.lifecycle as lifecycle_module
from app.core.config.analytics import ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_RUNNING,
    EVENT_CRAWL_COMPLETED,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_runtime import (
    SITE_CRAWL_QUEUE_SPEC,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.service.lifecycle import load_events
from app.models.analytics import AnalyticsTask
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.events import SiteCrawlEvent
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.site_health.lifecycle import CrawlLifecycle
from app.workers.site_health_worker import SiteHealthWorker
from tests.component.site_health_helpers import SiteSeed, seed_site_crawl
from tests.component.site_health_worker_helpers import _seed_analyze_phase_crawl


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


async def _seed_completed_analyze_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    task_count: int,
) -> tuple[SiteSeed, uuid.UUID]:
    urls = tuple(f"https://example.com/page-{index}" for index in range(task_count))
    async with session_factory() as session:
        seed, task_ids = await _seed_analyze_phase_crawl(
            session,
            root=urls[0],
            urls=urls,
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        task = await session.get(SiteCrawlTask, task_ids[0][1])
        assert crawl is not None
        assert task is not None
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        task.status = TASK_STATUS_SUCCEEDED
        task.completed_at = datetime.now(UTC)
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose="analyze",
            requested_url=task.requested_url,
            final_url=task.requested_url,
            status_code=200,
            content_type="text/html",
        )
        session.add(artifact)
        await session.flush()
        task.result_artifact_id = artifact.id
        await session.commit()
        return seed, task.id


def _task_reference(
    seed: SiteSeed,
    task_id: uuid.UUID,
    *,
    workspace_id: uuid.UUID | None = None,
) -> SiteCrawlTask:
    return SiteCrawlTask(
        id=task_id,
        crawl_id=seed.crawl_id,
        workspace_id=workspace_id or seed.workspace_id,
    )


@pytest.mark.asyncio
async def test_intermediate_analyze_success_skips_full_reconciliation(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, task_id = await _seed_completed_analyze_task(session_factory, task_count=2)
    lifecycle = CrawlLifecycle(session_factory)
    refreshed: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def reject_full_reconcile(_crawl_id: uuid.UUID) -> None:
        raise AssertionError("intermediate analyze success took the aggregate path")

    async def record_live_refresh(
        _session_factory: async_sessionmaker[AsyncSession],
        *,
        crawl_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> None:
        refreshed.append((crawl_id, workspace_id))

    monkeypatch.setattr(lifecycle, "reconcile", reject_full_reconcile)
    monkeypatch.setattr(
        lifecycle_module,
        "refresh_live_score_summary_for_crawl",
        record_live_refresh,
    )

    await lifecycle.reconcile_after_task(_task_reference(seed, task_id))
    assert refreshed == [(seed.crawl_id, seed.workspace_id)]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsafe_state",
    ["missing_artifact", "failed", "pending", "discover"],
)
async def test_intermediate_analyze_uses_full_reconcile_for_unsafe_states(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    unsafe_state: str,
) -> None:
    seed, task_id = await _seed_completed_analyze_task(session_factory, task_count=2)
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        task = await session.get(SiteCrawlTask, task_id)
        assert crawl is not None
        assert task is not None
        if unsafe_state == "missing_artifact":
            task.result_artifact_id = None
        elif unsafe_state == "failed":
            task.status = TASK_STATUS_FAILED
        elif unsafe_state == "pending":
            crawl.analysis_status = ANALYSIS_STATUS_PENDING
        elif unsafe_state == "discover":
            task.task_kind = TASK_KIND_DISCOVER
        await session.commit()

    reconciled: list[uuid.UUID] = []
    lifecycle = CrawlLifecycle(session_factory)

    async def record_full_reconcile(crawl_id: uuid.UUID) -> None:
        reconciled.append(crawl_id)

    monkeypatch.setattr(lifecycle, "reconcile", record_full_reconcile)
    await lifecycle.reconcile_after_task(_task_reference(seed, task_id))

    assert reconciled == [seed.crawl_id]


@pytest.mark.asyncio
async def test_last_analyze_success_runs_authoritative_reconciliation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, task_id = await _seed_completed_analyze_task(session_factory, task_count=1)

    await CrawlLifecycle(session_factory).reconcile_after_task(
        _task_reference(seed, task_id)
    )

    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status == CRAWL_STATUS_COMPLETED
    assert crawl.completed_at is not None


@pytest.mark.asyncio
async def test_task_reconcile_does_not_cross_workspace_boundary(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, task_id = await _seed_completed_analyze_task(session_factory, task_count=2)
    lifecycle = CrawlLifecycle(session_factory)

    async def reject_full_reconcile(_crawl_id: uuid.UUID) -> None:
        raise AssertionError("workspace mismatch reached unscoped reconciliation")

    monkeypatch.setattr(lifecycle, "reconcile", reject_full_reconcile)
    await lifecycle.reconcile_after_task(
        _task_reference(seed, task_id, workspace_id=uuid.uuid4())
    )

    assert (await _crawl(session_factory, seed.crawl_id)).status == CRAWL_STATUS_RUNNING


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
async def test_stalled_backstop_ignores_retired_task_kinds(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A pre-upgrade link task must not strand an otherwise drained crawl."""
    stale = datetime.now(UTC) - timedelta(seconds=3600)
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                task_kind="link_check",
                requested_url="https://example.com/legacy-link",
                url_hash="legacy-link",
                generation=0,
                idempotency_key=f"{seed.crawl_id}:link_check:legacy-link:0",
                status=TASK_STATUS_QUEUED,
            )
        )
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.id == seed.task_ids[0])
            .values(status=TASK_STATUS_SUCCEEDED, completed_at=stale)
        )
        await session.execute(
            update(SiteCrawl)
            .where(SiteCrawl.id == seed.crawl_id)
            .values(status=CRAWL_STATUS_RUNNING, updated_at=stale)
        )
        await session.commit()

    assert await CrawlLifecycle(session_factory).reconcile_stalled() == 1
    crawl = await _crawl(session_factory, seed.crawl_id)
    assert crawl.status not in CRAWL_ACTIVE_STATUSES


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
async def test_standard_crawl_completes_when_advanced_controls_are_available(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The environment capability must never opt a standard crawl into pausing."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert crawl is not None
        assert task is not None
        crawl.configuration = {"advanced_controls_enabled": True}
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.discovered_url_count = 1
        task.status = TASK_STATUS_SUCCEEDED
        task.completed_at = datetime.now(UTC)
        await session.commit()

    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.completed_at is not None
        assert (
            await session.scalar(
                select(SiteHealthSnapshot.id).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
            is not None
        )
        assert (
            await session.scalar(
                select(SiteCrawlEvent.id).where(
                    SiteCrawlEvent.crawl_id == seed.crawl_id,
                    SiteCrawlEvent.event_type == EVENT_CRAWL_COMPLETED,
                )
            )
            is not None
        )
        # With no usable analysis evidence, no graph is invented. The crawl
        # provenance still refreshes Opportunities so stale signals are cleared.
        refresh = await session.scalar(
            select(AnalyticsTask).where(
                AnalyticsTask.project_id == seed.project_id,
                AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
            )
        )
        assert refresh is not None
        assert refresh.payload == {
            "trigger_kind": "site_crawl",
            "trigger_id": str(seed.crawl_id),
        }


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

    async with worker._phase_context.leased(task_id):
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
