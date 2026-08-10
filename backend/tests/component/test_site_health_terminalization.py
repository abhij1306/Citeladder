"""Crawl terminalization: status reconciliation, cancel, snapshots, the finalize pass.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import (
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PENDING,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_RUNNING,
    ERROR_HTTP_4XX,
    EVENT_CRAWL_COMPLETED,
    EVENT_CRAWL_FAILED,
    FETCH_ATTEMPT_OUTCOME_ERROR,
    PHASE_DISCOVERY,
    PHASE_RUN_COMPLETED,
    PHASE_RUN_RUNNING,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    SELECTION_SOURCE_USER,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlEvent,
    SiteCrawlPhaseRun,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteFetchAttempt,
    SiteHealthSnapshot,
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
)
from app.workers.site_health.helpers import _is_crawl_finalize_rule
from app.workers.site_health.lifecycle import CrawlLifecycle
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    DEFAULT_SEED_MONITORED_URLS,
    _analyses_by_page_url,
    _configure_crawl,
    _html,
    _rich_html,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
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
async def test_advanced_controls_do_not_park_a_completed_sample_crawl(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The automatic sample remains a terminal crawl, not a manual phase batch."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        task = await session.get(SiteCrawlTask, seed.task_ids[0])
        assert crawl is not None and task is not None
        crawl.sample_mode = True
        crawl.discovery_status = DISCOVERY_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_PENDING
        crawl.discovered_url_count = 1
        crawl.configuration = {
            "advanced_controls_enabled": True,
            "count_disclosure": False,
        }
        phase_run = SiteCrawlPhaseRun(
            workspace_id=seed.workspace_id,
            crawl_id=seed.crawl_id,
            phase=PHASE_DISCOVERY,
            ordinal=1,
            status=PHASE_RUN_RUNNING,
            requested_count=1,
        )
        session.add(phase_run)
        await session.flush()
        task.phase_run_id = phase_run.id
        task.status = TASK_STATUS_SUCCEEDED
        task.completed_at = datetime.now(UTC)
        await session.commit()

    await CrawlLifecycle(session_factory).reconcile(seed.crawl_id)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        phase_run = await session.get(SiteCrawlPhaseRun, phase_run.id)
        assert crawl is not None and crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        assert phase_run is not None and phase_run.status == PHASE_RUN_COMPLETED


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
        # Discovery still terminalizes as completed (some inventory exists).
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.inventory_complete is True


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
    from app.core.config.site_health import (
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
        assert snapshot.overall_score is not None
        assert snapshot.overall_score > 0


@pytest.mark.asyncio
async def test_cancel_crawl_persists_partial_snapshot_from_completed_analyses(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancelling a run with completed analyses persists a partial snapshot.

    The dashboard requires a non-null ``score_summary``; cancellation must roll
    the already-completed analyses into the SAME canonical snapshot the worker
    writes on clean terminalization, so a partial cancel keeps its scores +
    inventory instead of hiding the dashboard behind a null summary.
    """
    from app.core.config.site_health import (
        CRAWL_STATUS_CANCELLED,
        FETCH_PURPOSE_ANALYZE,
        PAGE_ANALYSIS_STATUS_COMPLETED,
    )
    from app.domain.site_health.service import cancel_crawl

    seed, site_url_id, first_task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        # One analyze task already succeeded and produced a completed analysis;
        # a second URL is still queued (the not-yet-analyzed remainder).
        first_task = await session.get(SiteCrawlTask, first_task_id)
        assert first_task is not None
        first_task.status = TASK_STATUS_SUCCEEDED
        artifact = SiteFetchArtifact(
            task_id=first_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose=FETCH_PURPOSE_ANALYZE,
            requested_url=first_task.requested_url,
            final_url=first_task.requested_url,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            SitePageAnalysis(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                artifact_id=artifact.id,
                status=PAGE_ANALYSIS_STATUS_COMPLETED,
                technical_score=72.0,
                aeo_score=68.0,
                overall_score=70.0,
            )
        )
        # A still-queued analyze task for a second monitored URL — the run is
        # mid-flight when the user cancels.
        second_url = "https://example.com/pending"
        canonical, url_hash = canonical_identity(second_url)
        second_site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=canonical,
            url_hash=url_hash,
            display_url=canonical,
            host="example.com",
            depth=0,
        )
        session.add(second_site_url)
        await session.flush()
        session.add(
            MonitoredSiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                profile_id=seed.profile_id,
                site_url_id=second_site_url.id,
                active=True,
                selection_source="user",
            )
        )
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                site_url_id=second_site_url.id,
                task_kind=TASK_KIND_ANALYZE,
                requested_url=second_url,
                url_hash=url_hash,
                generation=0,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_ANALYZE}:{url_hash}:0",
                status=TASK_STATUS_QUEUED,
                priority=1,
                randomized_position=1,
            )
        )
        await session.commit()

    async with session_factory() as session:
        dto = await cancel_crawl(
            session, workspace_id=seed.workspace_id, crawl_id=seed.crawl_id
        )

    # The returned DTO carries the partial score_summary (dashboard-ready).
    summary = dto["score_summary"]
    assert summary is not None
    assert summary["overall_score"] is not None
    assert summary["overall_score"] > 0
    assert summary["analyzed_count"] == 1
    assert summary["selected_count"] == 2
    assert dto["status"] == CRAWL_STATUS_CANCELLED

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        # Only the one completed analysis is aggregated; the queued URL is never
        # fabricated as a zero.
        assert snapshot.analyzed_url_count == 1
        assert snapshot.selected_url_count == 2
        assert snapshot.overall_score is not None
        assert snapshot.overall_score > 0
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_CANCELLED
        # The still-queued analyze task was cancelled by terminalization.
        queued = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert queued == 0


@pytest.mark.asyncio
async def test_cancel_crawl_without_completed_analyses_leaves_summary_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancelling before any analysis completes leaves score_summary null.

    With no completed analyses there is nothing to project — the summary stays
    null (never a fabricated zero) so the UI shows its terminal/selection state.
    """
    from app.core.config.site_health import CRAWL_STATUS_CANCELLED
    from app.domain.site_health.service import cancel_crawl

    seed, _site_url_id, _task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        dto = await cancel_crawl(
            session, workspace_id=seed.workspace_id, crawl_id=seed.crawl_id
        )

    assert dto["status"] == CRAWL_STATUS_CANCELLED
    assert dto["score_summary"] is None

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one_or_none()
        assert snapshot is None
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.score_summary is None


@pytest.mark.asyncio
async def test_cancel_crawl_with_only_deactivated_completed_analyses_skips_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A completed analysis whose monitored URL was deactivated is not aggregable.

    ``persist_crawl_snapshot`` aggregates only ACTIVE monitored URLs, so a cancel
    whose only completed analysis belongs to a since-deactivated URL must NOT
    write a snapshot or a non-null ``score_summary`` — otherwise the dashboard
    renders empty (zero aggregated rows). The precheck shares the persist
    helper's active-membership predicate to enforce this.
    """
    from app.core.config.site_health import (
        CRAWL_STATUS_CANCELLED,
        FETCH_PURPOSE_ANALYZE,
        PAGE_ANALYSIS_STATUS_COMPLETED,
    )
    from app.domain.site_health.service import cancel_crawl

    seed, site_url_id, first_task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        # One analysis completed, then its monitored URL was deactivated.
        first_task = await session.get(SiteCrawlTask, first_task_id)
        assert first_task is not None
        first_task.status = TASK_STATUS_SUCCEEDED
        artifact = SiteFetchArtifact(
            task_id=first_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose=FETCH_PURPOSE_ANALYZE,
            requested_url=first_task.requested_url,
            final_url=first_task.requested_url,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            SitePageAnalysis(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                artifact_id=artifact.id,
                status=PAGE_ANALYSIS_STATUS_COMPLETED,
                technical_score=72.0,
                aeo_score=68.0,
                overall_score=70.0,
            )
        )
        # Deactivate the monitored URL — no ACTIVE monitored row remains.
        monitored = (
            await session.execute(
                select(MonitoredSiteUrl).where(
                    MonitoredSiteUrl.site_url_id == site_url_id
                )
            )
        ).scalar_one()
        monitored.active = False
        await session.commit()

    async with session_factory() as session:
        dto = await cancel_crawl(
            session, workspace_id=seed.workspace_id, crawl_id=seed.crawl_id
        )

    assert dto["status"] == CRAWL_STATUS_CANCELLED
    assert dto["score_summary"] is None

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one_or_none()
        assert snapshot is None
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.score_summary is None


@pytest.mark.asyncio
async def test_persist_crawl_snapshot_returns_false_and_writes_nothing_when_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Empty aggregate row set => skip persistence, return False (cancel path).

    ``persist_crawl_snapshot`` decides from its single fetched aggregate row set
    (no separate TOCTOU precheck): with zero aggregatable active completed
    analyses and the default ``persist_empty=False`` it writes NEITHER the
    snapshot NOR the ``score_summary`` projection and returns ``False``.
    """
    seed, _site_url_id, _task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        persisted = await persist_crawl_snapshot(session, crawl=crawl)
        await session.commit()

    assert persisted is False

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one_or_none()
        assert snapshot is None
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.score_summary is None


@pytest.mark.asyncio
async def test_persist_crawl_snapshot_persist_empty_writes_null_score_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``persist_empty=True`` forces a canonical empty/null-score snapshot.

    The worker's clean terminalization (including an empty analysis plan) must
    always write a snapshot. With no aggregatable rows and ``persist_empty=True``
    the helper writes the explicit zeroed/null-score snapshot + projection and
    returns ``True``.
    """
    seed, _site_url_id, _task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        persisted = await persist_crawl_snapshot(
            session, crawl=crawl, persist_empty=True
        )
        await session.commit()

    assert persisted is True

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 0
        assert snapshot.overall_score is None
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.score_summary is not None
        assert crawl.score_summary["overall_score"] is None


@pytest.mark.asyncio
async def test_persist_crawl_snapshot_returns_true_when_active_rows_present(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A completed analysis for an ACTIVE URL persists and returns True.

    Regression for membership: the same call returns ``False`` once its only
    completed analysis's monitored URL is deactivated (no active rows), proving
    the decision derives from the single fetched aggregate row set rather than a
    precheck.
    """
    from app.core.config.site_health import (
        FETCH_PURPOSE_ANALYZE,
        PAGE_ANALYSIS_STATUS_COMPLETED,
    )

    seed, site_url_id, first_task_id = await _seed_analyze_ready(session_factory)

    async with session_factory() as session:
        first_task = await session.get(SiteCrawlTask, first_task_id)
        assert first_task is not None
        first_task.status = TASK_STATUS_SUCCEEDED
        artifact = SiteFetchArtifact(
            task_id=first_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose=FETCH_PURPOSE_ANALYZE,
            requested_url=first_task.requested_url,
            final_url=first_task.requested_url,
        )
        session.add(artifact)
        await session.flush()
        session.add(
            SitePageAnalysis(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                artifact_id=artifact.id,
                status=PAGE_ANALYSIS_STATUS_COMPLETED,
                technical_score=72.0,
                aeo_score=68.0,
                overall_score=70.0,
            )
        )
        await session.commit()

    # Active membership present -> persists + returns True.
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        persisted = await persist_crawl_snapshot(session, crawl=crawl)
        await session.commit()
    assert persisted is True

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1

    # Deactivate the monitored URL: the (idempotent) snapshot row survives, but a
    # fresh call now sees zero active rows and reports no persistence occurred.
    async with session_factory() as session:
        monitored = (
            await session.execute(
                select(MonitoredSiteUrl).where(
                    MonitoredSiteUrl.site_url_id == site_url_id
                )
            )
        ).scalar_one()
        monitored.active = False
        await session.commit()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        persisted = await persist_crawl_snapshot(session, crawl=crawl)
        await session.commit()
    assert persisted is False


@pytest.mark.asyncio
async def test_snapshot_uses_only_latest_completed_analysis_and_issues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Equal timestamps use UUID tie-break; stale scores/issues stay excluded."""
    from app.core.config.site_health import (
        FETCH_PURPOSE_ANALYZE,
        PAGE_ANALYSIS_STATUS_COMPLETED,
    )

    seed, site_url_id, first_task_id = await _seed_analyze_ready(session_factory)
    same_created_at = datetime.now(UTC)
    low_analysis_id = uuid.UUID(int=1)
    high_analysis_id = uuid.UUID(int=2)

    async with session_factory() as session:
        first_task = await session.get(SiteCrawlTask, first_task_id)
        assert first_task is not None
        first_task.status = TASK_STATUS_SUCCEEDED
        second_task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            site_url_id=site_url_id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url="https://example.com/rich",
            url_hash=first_task.url_hash,
            generation=1,
            idempotency_key=f"{seed.crawl_id}:analyze:latest:1",
            status=TASK_STATUS_SUCCEEDED,
            randomized_position=1,
        )
        session.add(second_task)
        await session.flush()

        artifacts = []
        for task in (first_task, second_task):
            artifact = SiteFetchArtifact(
                task_id=task.id,
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                fetch_purpose=FETCH_PURPOSE_ANALYZE,
                requested_url=task.requested_url,
                final_url=task.requested_url,
            )
            session.add(artifact)
            artifacts.append(artifact)
        await session.flush()

        analyses = []
        for analysis_id, artifact, score in (
            (low_analysis_id, artifacts[0], 10.0),
            (high_analysis_id, artifacts[1], 90.0),
        ):
            analysis = SitePageAnalysis(
                id=analysis_id,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                crawl_id=seed.crawl_id,
                site_url_id=site_url_id,
                artifact_id=artifact.id,
                status=PAGE_ANALYSIS_STATUS_COMPLETED,
                technical_score=score,
                aeo_score=score,
                overall_score=score,
                created_at=same_created_at,
            )
            session.add(analysis)
            analyses.append(analysis)
        await session.flush()

        for index, (analysis, artifact) in enumerate(
            zip(analyses, artifacts, strict=True)
        ):
            evaluation = SiteRuleEvaluation(
                workspace_id=seed.workspace_id,
                analysis_id=analysis.id,
                source_artifact_id=artifact.id,
                rule_id=f"rule-{index}",
                dimension="technical",
                category="stale" if index == 0 else "fresh",
                severity="high",
                weight=1.0,
                outcome=RULE_OUTCOME_FAIL,
            )
            session.add(evaluation)
            await session.flush()
            session.add(
                SiteIssue(
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    crawl_id=seed.crawl_id,
                    site_url_id=site_url_id,
                    analysis_id=analysis.id,
                    evaluation_id=evaluation.id,
                    source_artifact_id=artifact.id,
                    rule_id=evaluation.rule_id,
                    dimension="technical",
                    category=evaluation.category,
                    severity="high",
                )
            )
        # This block stands in for the finalize-pass writer, so it flushes the
        # way that writer does: the snapshot aggregates issues with a SELECT,
        # and sessions here (like production's) do not autoflush.
        await session.flush()

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        # The same call the worker's terminalization makes (its
        # ``_persist_snapshot`` is a thin ``persist_empty=True`` delegation).
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)
        latest_artifact_id = artifacts[1].id
        await session.commit()

    async with session_factory() as session:
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        assert snapshot.overall_score == 90.0
        assert snapshot.source_analysis_ids == [high_analysis_id]
        assert snapshot.source_artifact_ids == [latest_artifact_id]
        assert snapshot.issue_count == 1
        assert snapshot.category_counts == {"fresh": 1}


@pytest.mark.asyncio
async def test_finalize_pass_broken_link_and_hreflang_conflict_end_to_end(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The finalize pass reads link_check probe evidence + counterpart page
    facts: the root's unreachable internal link fails ``broken_internal_link``
    and its hreflang alternate (analyzed, but not linking back) fails
    ``hreflang_conflict`` — while the counterpart page's own rows are N/A."""
    root = "https://example.com/rich"
    second = "https://example.com/fr"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, second)
        )

    root_html = (
        b"<html><head><title>Root page about widgets and gadgets</title>"
        b'<link rel="alternate" hreflang="fr" href="https://example.com/fr">'
        b"</head><body><h1>Root</h1>"
        b"<p>Root body text with enough words to matter for the checks.</p>"
        b'<a href="https://example.com/fr">fr</a>'
        b'<a href="https://example.com/broken">broken</a>'
        b"</body></html>"
    )
    fr_html = b"<html><head><title>FR</title></head><body><p>bonjour</p></body></html>"
    pages = {"/rich": root_html, "/fr": fr_html}  # /broken -> 404
    worker = _worker(session_factory, pages, owner="p2-hreflang")
    await worker.run_until_idle()

    async with session_factory() as session:
        by_url = await _analyses_by_page_url(session, seed)
        assert len(by_url) == 2
        root_analysis = by_url["https://example.com/rich"]
        fr_analysis = by_url["https://example.com/fr"]

        async def _evals(analysis_id):
            rows = (
                (
                    await session.execute(
                        select(SiteRuleEvaluation).where(
                            SiteRuleEvaluation.analysis_id == analysis_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            return {row.rule_id: row for row in rows}

        root_evals = await _evals(root_analysis.id)
        broken = root_evals["technical.broken_internal_link"]
        assert broken.outcome == RULE_OUTCOME_FAIL
        assert broken.evidence["checked_count"] == 2
        assert broken.evidence["broken_count"] == 1
        assert broken.evidence["broken_urls"] == ["https://example.com/broken"]

        hreflang = root_evals["technical.hreflang_conflict"]
        assert hreflang.outcome == RULE_OUTCOME_FAIL
        assert hreflang.evidence["alternate_count"] == 1
        assert hreflang.evidence["checked_count"] == 1
        assert hreflang.evidence["missing_return_tags"] == ["https://example.com/fr"]

        # The counterpart page's own finalize rows are clean N/As.
        fr_evals = await _evals(fr_analysis.id)
        assert fr_evals["technical.broken_internal_link"].outcome == (
            RULE_OUTCOME_NOT_APPLICABLE
        )
        fr_hreflang = fr_evals["technical.hreflang_conflict"]
        assert fr_hreflang.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert fr_hreflang.evidence["reason"] == "no_hreflang"

        # Both failures surfaced as issues and in the snapshot rollup count.
        issues = (
            (
                await session.execute(
                    select(SiteIssue.rule_id).where(SiteIssue.crawl_id == seed.crawl_id)
                )
            )
            .scalars()
            .all()
        )
        assert "technical.broken_internal_link" in issues
        assert "technical.hreflang_conflict" in issues

        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 2
        # The crawl_finalize pass runs BEFORE the snapshot precisely so its
        # issues land in the rollup. It writes them with ``session.add`` and
        # production sessions do not autoflush, so without an explicit flush
        # the snapshot's SELECT could not see them and this count came back
        # short by exactly the finalize findings.
        assert snapshot.issue_count == len(issues)
        assert "technical.broken_internal_link" in issues
        assert sum(1 for rule_id in issues if _is_crawl_finalize_rule(rule_id)) > 0, (
            "the finalize issues must be part of what issue_count counted"
        )
