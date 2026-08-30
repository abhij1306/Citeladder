"""Crawl status reconciliation and terminal analytics refresh scenarios."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
    ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
)
from app.core.config.site_health_acquisition import (
    ERROR_HTTP_4XX,
    ERROR_ROBOTS_DENIED,
    ERROR_URL_ADMISSION_REJECTED,
    FETCH_ATTEMPT_OUTCOME_ERROR,
)
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_RUNNING,
    CRAWL_PARTIAL_REASON_DISCOVERY,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_RUNNING,
    EVENT_CRAWL_COMPLETED,
    EVENT_CRAWL_FAILED,
    TASK_KIND_ANALYZE,
    TASK_KIND_CHANGE_INTEL,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import SELECTION_SOURCE_USER
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.terminal_refresh import enqueue_terminal_analytics_refresh
from app.models.analytics import AnalyticsTask
from app.models.site_health.acquisition import SiteFetchAttempt
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.events import SiteCrawlEvent
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl
from app.models.traffic import TrafficSnapshot
from app.workers.site_health.lifecycle import CrawlLifecycle
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    DEFAULT_SEED_MONITORED_URLS,
    _configure_crawl,
    _html,
    _rich_html,
    _seed_root_only,
    _seed_runtime,
    _worker,
)


@pytest.mark.asyncio
async def test_fully_failed_root_terminalizes_crawl_as_failed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A root that 404s (no URL discovered) fails the crawl + discovery."""
    seed = await _seed_root_only(session_factory)
    # Empty page map -> the root "/" resolves to a 404 (non-retryable http_4xx).
    worker = _worker(session_factory, {}, owner="fail-root")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.discovered_url_count == 0
        assert crawl.failed_url_count >= 1
        assert crawl.status == CRAWL_STATUS_FAILED
        assert crawl.discovery_status == DISCOVERY_STATUS_FAILED
        # An empty inventory is not "complete".
        assert crawl.inventory_complete is False


@pytest.mark.asyncio
async def test_fully_failed_root_surfaces_humanized_failure_and_failed_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SH-2/SH-3/SH-5 (B1): a failed crawl explains itself, once, in code+prose.

    The terminalization must (a) map the empty analysis plan to FAILED (the
    plan was empty BECAUSE discovery produced nothing — not a legitimate
    0-of-0 completion), (b) write a humanized ``error_message`` naming the
    terminal status, and (c) record a ``crawl.failed`` event carrying the
    failure summary INSTEAD of the misleading ``crawl.completed``.
    """
    seed = await _seed_root_only(session_factory)
    # Empty page map -> the root "/" resolves to a 404 (non-retryable http_4xx).
    worker = _worker(session_factory, {}, owner="fail-root-surface")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_FAILED
        # SH-3: the analysis lifecycle failed WITH the crawl.
        assert crawl.analysis_status == ANALYSIS_STATUS_FAILED
        # SH-5: a human sentence naming the terminal status — never a bare
        # ``http_4xx`` code.
        assert crawl.error_message == "The site returned HTTP 404 for the start URL"

        # The evidence the read projections (failure_summary / root_errors)
        # rely on: one failed attempt row on the root task.
        root_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                SiteCrawlTask.depth == 0,
            )
        )
        assert root_task is not None
        assert root_task.status == TASK_STATUS_FAILED
        attempts = list(
            (
                await session.scalars(
                    select(SiteFetchAttempt).where(
                        SiteFetchAttempt.task_id == root_task.id
                    )
                )
            ).all()
        )
        assert len(attempts) == 1
        assert attempts[0].outcome == FETCH_ATTEMPT_OUTCOME_ERROR
        assert attempts[0].error_code == ERROR_HTTP_4XX
        assert attempts[0].status_code == 404

        # SH-2: crawl.failed INSTEAD of crawl.completed, with the summary.
        events = list(
            (
                await session.scalars(
                    select(SiteCrawlEvent).where(
                        SiteCrawlEvent.crawl_id == seed.crawl_id
                    )
                )
            ).all()
        )
        event_types = [e.event_type for e in events]
        assert EVENT_CRAWL_COMPLETED not in event_types
        failed_events = [e for e in events if e.event_type == EVENT_CRAWL_FAILED]
        assert len(failed_events) == 1
        assert failed_events[0].message == "crawl failed"
        payload = failed_events[0].payload
        assert payload["status"] == CRAWL_STATUS_FAILED
        failure = payload["failure"]
        assert failure["code"] == ERROR_HTTP_4XX
        assert failure["message"] == crawl.error_message
        assert failure["status_code"] == 404
        assert failure["target_url"] == "https://example.com/"


@pytest.mark.asyncio
async def test_legitimately_empty_plan_keeps_analysis_completed_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SH-3 guard: a HEALTHY crawl with an empty analysis plan is COMPLETED.

    The root fetches fine but admits no monitored selection (Starter with no
    monitored URLs -> zero analyze tasks): the empty plan is a legitimate
    0-of-0, so analysis terminalizes COMPLETED and the crawl records the
    usual ``crawl.completed`` — the fully-failed mapping must not leak here.
    """
    seed = await _seed_root_only(session_factory)
    # Root serves a linkless page: discovery succeeds, nothing else to do.
    worker = _worker(session_factory, {"/": _html([])}, owner="empty-plan")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        assert crawl.error_message in (None, "")

        event_types = list(
            (
                await session.scalars(
                    select(SiteCrawlEvent.event_type).where(
                        SiteCrawlEvent.crawl_id == seed.crawl_id
                    )
                )
            ).all()
        )
        assert EVENT_CRAWL_COMPLETED in event_types
        assert EVENT_CRAWL_FAILED not in event_types


@pytest.mark.asyncio
async def test_partial_failure_terminalizes_crawl_as_partially_completed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Root succeeds but a child 404s -> partially_completed / completed."""
    seed = await _seed_root_only(session_factory)
    # Root serves one in-scope child link; the child path is absent (-> 404).
    pages = {"/": _html(["https://example.com/missing"])}
    worker = _worker(session_factory, pages, owner="partial-root")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.discovered_url_count >= 1  # root succeeded
        assert crawl.failed_url_count >= 1  # child 404
        assert crawl.status == CRAWL_STATUS_PARTIALLY_COMPLETED
        # The shortfall was a URL that could not be FETCHED. Analysis itself
        # completed, so the crawl must not claim pages could not be analyzed —
        # a dead link is routine on a real site, and blaming analysis for it
        # made effectively every crawl report a failure it did not have.
        assert crawl.partial_reason == CRAWL_PARTIAL_REASON_DISCOVERY
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        # Discovery still terminalizes as completed (some inventory exists).
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.inventory_complete is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "excluded_error_code", [ERROR_URL_ADMISSION_REJECTED, ERROR_ROBOTS_DENIED]
)
async def test_discovery_policy_exclusion_does_not_make_the_crawl_partial(
    session_factory: async_sessionmaker[AsyncSession],
    excluded_error_code: str,
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        crawl.discovered_url_count = 1
        now = datetime.now(UTC)
        session.add_all(
            [
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url="https://example.com/",
                    url_hash=canonical_identity("https://example.com/")[1],
                    idempotency_key=f"{seed.crawl_id}:discover:root:0",
                    status=TASK_STATUS_SUCCEEDED,
                    completed_at=now,
                ),
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url="https://example.com/account-redirect",
                    url_hash=canonical_identity("https://example.com/account-redirect")[
                        1
                    ],
                    idempotency_key=f"{seed.crawl_id}:discover:excluded:0",
                    status=TASK_STATUS_FAILED,
                    error_code=excluded_error_code,
                    completed_at=now,
                ),
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url="https://example.com/",
                    url_hash=canonical_identity("https://example.com/")[1],
                    idempotency_key=f"{seed.crawl_id}:analyze:root:0",
                    status=TASK_STATUS_SUCCEEDED,
                    completed_at=now,
                ),
            ]
        )
        await session.commit()

    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.partial_reason in (None, "")


@pytest.mark.asyncio
async def test_recrawl_root_failure_keeps_successful_monitored_analysis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A blocked root must not discard successful recrawl evidence."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        now = datetime.now(UTC)
        root_url = "https://example.com/"
        monitored_url = "https://example.com/monitored"
        session.add_all(
            [
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url=root_url,
                    url_hash=canonical_identity(root_url)[1],
                    generation=0,
                    idempotency_key=f"{seed.crawl_id}:discover:blocked-root:0",
                    status=TASK_STATUS_FAILED,
                    randomized_position=0,
                    completed_at=now,
                ),
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url=monitored_url,
                    url_hash=canonical_identity(monitored_url)[1],
                    generation=0,
                    idempotency_key=f"{seed.crawl_id}:analyze:monitored:0",
                    status=TASK_STATUS_SUCCEEDED,
                    randomized_position=1,
                    completed_at=now,
                ),
            ]
        )
        await session.commit()

    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_PARTIALLY_COMPLETED
        assert crawl.discovery_status == DISCOVERY_STATUS_FAILED
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        assert crawl.inventory_complete is False
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SiteHealthSnapshot)
                .where(SiteHealthSnapshot.crawl_id == seed.crawl_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(
                    SiteCrawlTask.crawl_id == seed.crawl_id,
                    SiteCrawlTask.task_kind == TASK_KIND_CHANGE_INTEL,
                    SiteCrawlTask.status == TASK_STATUS_QUEUED,
                )
            )
            == 1
        )


@pytest.mark.asyncio
async def test_completed_crawl_refreshes_demand_when_traffic_exists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        session.add(
            TrafficSnapshot(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                window_start=datetime(2025, 1, 1, tzinfo=UTC).date(),
                window_end=datetime(2025, 1, 28, tzinfo=UTC).date(),
                granularity="day",
                metrics={},
                source_metric_row_ids=[],
                source_artifact_ids=[],
            )
        )
        await session.flush()

        change_snapshot_id = uuid.uuid4()
        await enqueue_terminal_analytics_refresh(
            session, crawl=crawl, change_snapshot_id=change_snapshot_id
        )
        await enqueue_terminal_analytics_refresh(
            session, crawl=crawl, change_snapshot_id=change_snapshot_id
        )
        await session.commit()

    async with session_factory() as session:
        tasks = list(
            (
                await session.scalars(
                    select(AnalyticsTask).where(
                        AnalyticsTask.project_id == seed.project_id
                    )
                )
            ).all()
        )
        assert {task.task_kind for task in tasks} == {
            ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
            ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
        }
        demand_task = next(
            task
            for task in tasks
            if task.task_kind == ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH
        )
        assert demand_task.payload["downstream_trigger_kind"] == "site_change"
        assert demand_task.payload["downstream_trigger_id"] == str(change_snapshot_id)


@pytest.mark.asyncio
async def test_stolen_lease_does_not_terminalize_crawl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A task whose lease is stolen must not let the crawl complete early."""
    root = "https://example.com/"
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0, root_url=root)
        await _seed_runtime(
            session, seed.workspace_id, monitored_urls=DEFAULT_SEED_MONITORED_URLS
        )
        await session.commit()
        await _configure_crawl(
            session,
            crawl_id=seed.crawl_id,
            sample_mode=False,
            count_disclosure=True,
        )
        _canonical, root_hash = canonical_identity(root)
        task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            task_kind=TASK_KIND_DISCOVER,
            requested_url=root,
            url_hash=root_hash,
            generation=0,
            idempotency_key=f"{seed.crawl_id}:{TASK_KIND_DISCOVER}:root:0",
            status=TASK_STATUS_QUEUED,
            randomized_position=0,
        )
        session.add(task)
        await session.commit()
        task_id = task.id

    # Simulate the sweeper handing this task's lease to ANOTHER owner while it
    # is still non-terminal (LEASED to "other-owner").
    async with session_factory() as session:
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.id == task_id)
            .values(
                status=TASK_STATUS_LEASED,
                lease_owner="other-owner",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()

    # This worker directly reconciles: the non-terminal task must keep the
    # crawl active (remaining discover work > 0).
    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_RUNNING
        assert crawl.inventory_complete is False


@pytest.mark.asyncio
async def test_crawl_not_completed_while_analyze_queued(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A drained discover task must NOT complete the crawl while an analyze
    task is still queued."""
    root = "https://example.com/rich"
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0, root_url=root)
        await _seed_runtime(
            session, seed.workspace_id, monitored_urls=DEFAULT_SEED_MONITORED_URLS
        )
        await session.commit()
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.configuration = {
            "root_registrable_domain": "example.com",
            "include_globs": None,
            "exclude_globs": None,
            "count_disclosure": True,
        }
        canonical, url_hash = canonical_identity(root)
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=canonical,
            url_hash=url_hash,
            display_url=canonical,
            host="example.com",
            depth=0,
        )
        session.add(site_url)
        await session.flush()
        session.add(
            MonitoredSiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                profile_id=seed.profile_id,
                site_url_id=site_url.id,
                active=True,
            )
        )
        # One root discover task + one QUEUED analyze task the worker won't run.
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=root,
                url_hash=url_hash,
                generation=0,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_DISCOVER}:root:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=0,
            )
        )
        # Analyze task is LEASED to another owner (non-terminal, unclaimable).
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                site_url_id=site_url.id,
                task_kind=TASK_KIND_ANALYZE,
                requested_url=root,
                url_hash=url_hash,
                generation=0,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_ANALYZE}:{url_hash}:0",
                status=TASK_STATUS_LEASED,
                lease_owner="other-owner",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                priority=1,
                randomized_position=0,
            )
        )
        await session.commit()

    pages = {"/rich": _rich_html()}
    # Only claim discover so the analyze row stays non-terminal.
    worker = _worker(session_factory, pages, owner="disc-only")
    tasks = await worker._queue.claim(
        owner=worker.owner, limit=8, kinds=[TASK_KIND_DISCOVER]
    )
    for t in tasks:
        await worker._execute_task(t)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        # Discovery drained but the queued analyze keeps the crawl RUNNING.
        assert crawl.status == CRAWL_STATUS_RUNNING


@pytest.mark.asyncio
async def test_partial_analysis_failure_partially_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """One analyze succeeds, one 404s -> partially_completed, no zero score."""
    from app.core.config.site_health_contracts import (
        ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    )

    async with session_factory() as session:
        seed = await seed_site_crawl(
            session, task_count=0, root_url="https://example.com/rich"
        )
        await _seed_runtime(
            session, seed.workspace_id, monitored_urls=DEFAULT_SEED_MONITORED_URLS
        )
        await session.commit()
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.discovery_status = DISCOVERY_STATUS_COMPLETED
        crawl.discovered_url_count = 2
        crawl.inventory_complete = True
        crawl.configuration = {
            "root_registrable_domain": "example.com",
            "include_globs": None,
            "exclude_globs": None,
            "count_disclosure": True,
        }
        for path in ("rich", "missing"):
            url = f"https://example.com/{path}"
            canonical, url_hash = canonical_identity(url)
            site_url = SiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                normalized_url=canonical,
                url_hash=url_hash,
                display_url=canonical,
                host="example.com",
                depth=0,
            )
            session.add(site_url)
            await session.flush()
            session.add(
                MonitoredSiteUrl(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    profile_id=seed.profile_id,
                    site_url_id=site_url.id,
                    active=True,
                    selection_source=SELECTION_SOURCE_USER,
                )
            )
            session.add(
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    site_url_id=site_url.id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url=url,
                    url_hash=url_hash,
                    generation=0,
                    idempotency_key=(
                        f"{seed.crawl_id}:{TASK_KIND_ANALYZE}:{url_hash}:0"
                    ),
                    status=TASK_STATUS_QUEUED,
                    priority=1,
                    randomized_position=0,
                )
            )
        await session.commit()

    # Only /rich is served; /missing 404s (non-retryable).
    pages = {"/rich": _rich_html()}
    worker = _worker(session_factory, pages, owner="partial-analyze")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_PARTIALLY_COMPLETED
        assert crawl.analysis_status == ANALYSIS_STATUS_PARTIALLY_COMPLETED
        # Exactly one analysis succeeded; the snapshot aggregates only it and
        # never fabricates a zero for the missing URL.
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        assert snapshot.web_fundamentals_score is not None
        assert snapshot.web_fundamentals_score > 0


@pytest.mark.asyncio
async def test_no_evidence_partial_crawl_refreshes_without_inventing_graph(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A drained failed analysis clears stale Opportunities via crawl provenance."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.discovery_status = DISCOVERY_STATUS_COMPLETED
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        crawl.inventory_complete = True
        crawl.discovered_url_count = 1
        crawl.analysis_requested_count = 1
        session.add_all(
            [
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_DISCOVER,
                    requested_url="https://example.com/",
                    url_hash=canonical_identity("https://example.com/")[1],
                    generation=0,
                    idempotency_key=f"{seed.crawl_id}:discover:no-evidence:0",
                    status=TASK_STATUS_SUCCEEDED,
                    completed_at=datetime.now(UTC),
                ),
                SiteCrawlTask(
                    crawl_id=seed.crawl_id,
                    workspace_id=seed.workspace_id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url="https://example.com/failed",
                    url_hash=canonical_identity("https://example.com/failed")[1],
                    generation=0,
                    idempotency_key=f"{seed.crawl_id}:analyze:no-evidence:0",
                    status=TASK_STATUS_FAILED,
                    error_code="http_404",
                    completed_at=datetime.now(UTC),
                ),
            ]
        )
        await session.commit()

    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_PARTIALLY_COMPLETED
        change_tasks = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_CHANGE_INTEL,
            )
        )
        assert change_tasks == 0
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
