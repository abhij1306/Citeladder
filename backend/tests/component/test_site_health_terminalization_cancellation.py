"""Crawl cancellation and partial-snapshot persistence scenarios.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
    ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    TASK_KIND_ANALYZE,
    TASK_KIND_CHANGE_INTEL,
    TASK_KIND_LINK_METRICS,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.terminal_refresh import enqueue_terminal_analytics_refresh
from app.models.analytics import AnalyticsTask
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SitePageAnalysis,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    _seed_analyze_ready,
    _worker,
)


@pytest.mark.asyncio
async def test_claim_preparation_rejects_foreign_workspace(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        task_id, task_kind = task.id, task.task_kind
        await session.commit()

    worker = _worker(session_factory, {}, owner="foreign-workspace-boundary")
    prepared = await worker._prepare_claimed_task(
        task_id=task_id,
        crawl_id=seed.crawl_id,
        workspace_id=uuid.uuid4(),
        kind=task_kind,
    )
    assert prepared is False

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None and task.status == TASK_STATUS_CANCELLED


@pytest.mark.asyncio
async def test_running_crawl_preparation_does_not_wait_for_crawl_write_lock(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A sitemap persistence lock must not terminally fail a sibling page."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        task_id, task_kind = task.id, task.task_kind

    worker = _worker(session_factory, {}, owner="running-crawl-read-boundary")
    async with session_factory() as blocker:
        locked_crawl = await blocker.scalar(
            select(SiteCrawl).where(SiteCrawl.id == seed.crawl_id).with_for_update()
        )
        assert locked_crawl is not None

        prepared = await asyncio.wait_for(
            worker._prepare_claimed_task(
                task_id=task_id,
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                kind=task_kind,
            ),
            timeout=1.0,
        )

    assert prepared is True


@pytest.mark.asyncio
async def test_cancel_crawl_retries_a_transient_crawl_lock_timeout(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """An active evidence commit cannot turn a user cancellation into a 500."""
    from app.domain.site_health.service import cancel_crawl

    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=1)

    async with session_factory() as blocker:
        locked_crawl = await blocker.scalar(
            select(SiteCrawl).where(SiteCrawl.id == seed.crawl_id).with_for_update()
        )
        assert locked_crawl is not None

        async with session_factory() as cancel_session:
            await cancel_session.execute(text("SET LOCAL lock_timeout = '50ms'"))
            cancellation = asyncio.create_task(
                cancel_crawl(
                    cancel_session,
                    workspace_id=seed.workspace_id,
                    crawl_id=seed.crawl_id,
                )
            )
            await asyncio.sleep(0.15)
            await blocker.commit()
            result = await asyncio.wait_for(cancellation, timeout=5)

    assert result["status"] == CRAWL_STATUS_CANCELLED
    async with session_factory() as session:
        task_status = await session.scalar(
            select(SiteCrawlTask.status).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task_status == TASK_STATUS_CANCELLED


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
    from app.core.config.site_health_acquisition import (
        FETCH_PURPOSE_ANALYZE,
    )
    from app.core.config.site_health_contracts import (
        CRAWL_STATUS_CANCELLED,
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
                technical_integrity_score=72.0,
                technical_integrity_coverage=1.0,
                technical_integrity_state="measured",
                technical_earned_weight=0.72,
                technical_determinate_weight=1.0,
                technical_expected_weight=1.0,
                technical_critical_complete=True,
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
    assert summary["technical_integrity_score"] is not None
    assert summary["technical_integrity_score"] > 0
    assert summary["analyzed_count"] == 1
    assert summary["selected_count"] == 2
    assert dto["status"] == CRAWL_STATUS_CANCELLED

    # Idempotent readback of the already-terminal cancel cannot enqueue a
    # second downstream chain.
    async with session_factory() as session:
        repeated = await cancel_crawl(
            session, workspace_id=seed.workspace_id, crawl_id=seed.crawl_id
        )
    assert repeated["status"] == CRAWL_STATUS_CANCELLED

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
        assert snapshot.technical_integrity_score is not None
        assert snapshot.technical_integrity_score > 0
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_CANCELLED
        # The stale analyze task was cancelled; change intelligence is queued.
        queued = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert queued == 2
        change_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_CHANGE_INTEL,
            )
        )
        assert change_task is not None
        link_metric_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_METRICS,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert link_metric_task is not None
        verification = await session.scalar(
            select(AnalyticsTask).where(
                AnalyticsTask.project_id == seed.project_id,
                AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
            )
        )
        assert verification is None
        opportunity_tasks = list(
            (
                await session.scalars(
                    select(AnalyticsTask).where(
                        AnalyticsTask.project_id == seed.project_id,
                        AnalyticsTask.task_kind
                        == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
                    )
                )
            ).all()
        )
        assert opportunity_tasks == []

        change_snapshot_id = uuid.uuid4()
        await enqueue_terminal_analytics_refresh(
            session, crawl=crawl, change_snapshot_id=change_snapshot_id
        )
        await session.commit()
        verification = await session.scalar(
            select(AnalyticsTask).where(
                AnalyticsTask.project_id == seed.project_id,
                AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
            )
        )
        assert verification is not None
        opportunity = await session.scalar(
            select(AnalyticsTask).where(
                AnalyticsTask.project_id == seed.project_id,
                AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
            )
        )
        assert opportunity is not None
        assert opportunity.payload == {
            "trigger_kind": "site_change",
            "trigger_id": str(change_snapshot_id),
        }


@pytest.mark.asyncio
async def test_cancel_crawl_without_completed_analyses_leaves_summary_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancelling before any analysis completes leaves score_summary null.

    With no completed analyses there is nothing to project — the summary stays
    null (never a fabricated zero) so the UI shows its terminal/selection state.
    """
    from app.core.config.site_health_contracts import (
        CRAWL_STATUS_CANCELLED,
    )
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
    from app.core.config.site_health_acquisition import (
        FETCH_PURPOSE_ANALYZE,
    )
    from app.core.config.site_health_contracts import (
        CRAWL_STATUS_CANCELLED,
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
                technical_integrity_score=72.0,
                technical_integrity_coverage=1.0,
                technical_integrity_state="measured",
                technical_earned_weight=0.72,
                technical_determinate_weight=1.0,
                technical_expected_weight=1.0,
                technical_critical_complete=True,
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
        assert snapshot.technical_integrity_score is None
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.score_summary is not None
        assert crawl.score_summary["technical_integrity_score"] is None


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
    from app.core.config.site_health_acquisition import (
        FETCH_PURPOSE_ANALYZE,
    )
    from app.core.config.site_health_contracts import (
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
                technical_integrity_score=72.0,
                technical_integrity_coverage=1.0,
                technical_integrity_state="measured",
                technical_earned_weight=0.72,
                technical_determinate_weight=1.0,
                technical_expected_weight=1.0,
                technical_critical_complete=True,
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
