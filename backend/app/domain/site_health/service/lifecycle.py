"""Crawl-facing service mutations + the project dashboard and event replay.

The write path (``cancel_crawl``) and the reads that are about a crawl's
lifecycle rather than its contents. Cancel is ONE atomic transaction: the crawl
row is locked ``FOR UPDATE``, the overall/discovery/analysis sub-states are
driven to cancelled where the guarded machine allows it, every non-terminal task
is cancelled, and the canonical snapshot writer runs so a partially-analyzed run
keeps its scores instead of dead-ending on a null summary.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health import (
    ANALYSIS_STATUS_CANCELLED,
    CRAWL_STATUS_CANCELLED,
    CRAWL_TERMINAL_STATUSES,
    DISCOVERY_STATUS_CANCELLED,
    EVENT_CRAWL_CANCELLED,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    PHASE_ANALYSIS,
    PHASE_DISCOVERY,
    POLICY_BLOCKING_ERROR_CODES,
    TASK_KIND_ANALYZE,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_workspace,
)
from app.domain.opportunities.service import enqueue_opportunity_refresh
from app.domain.site_health.service.common import (
    _CRAWL_NOT_FOUND,
    SiteHealthNotFoundError,
    _load_crawl,
    _load_project,
)
from app.domain.site_health.service.presentation import (
    _crawl_count_disclosure,
    _score_summary,
    project_crawl,
    project_phase_run,
)
from app.domain.site_health.service.queries import (
    _failure_summary_for,
    _root_errors_for,
)
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.state_events import (
    InvalidSiteCrawlTransition,
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlEvent,
    SiteCrawlPhaseRun,
    SiteCrawlTask,
    SitePageAnalysis,
)

logger = logging.getLogger("app.domain.site_health.service.lifecycle")


async def _crawl_counters(session: AsyncSession, crawl: SiteCrawl) -> dict:
    latest_tasks = (
        select(
            SiteCrawlTask.site_url_id,
            SiteCrawlTask.status,
            SiteCrawlTask.error_code,
        )
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            SiteCrawlTask.site_url_id.is_not(None),
        )
        .distinct(SiteCrawlTask.site_url_id)
        .order_by(SiteCrawlTask.site_url_id, SiteCrawlTask.generation.desc())
        .subquery()
    )
    queued_statuses = {TASK_STATUS_QUEUED, TASK_STATUS_RETRY_WAIT}
    running_statuses = {TASK_STATUS_LEASED, TASK_STATUS_RUNNING}
    task_counts = (
        await session.execute(
            select(
                func.count()
                .filter(latest_tasks.c.status.in_(queued_statuses))
                .label("queued"),
                func.count()
                .filter(latest_tasks.c.status.in_(running_statuses))
                .label("running"),
                func.count()
                .filter(latest_tasks.c.status == TASK_STATUS_SUCCEEDED)
                .label("analyzed"),
                func.count()
                .filter(latest_tasks.c.status == TASK_STATUS_FAILED)
                .label("failed"),
                func.count()
                .filter(
                    latest_tasks.c.status == TASK_STATUS_FAILED,
                    latest_tasks.c.error_code.in_(POLICY_BLOCKING_ERROR_CODES),
                )
                .label("blocked"),
            ).select_from(latest_tasks)
        )
    ).one()
    selected = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.project_id == crawl.project_id,
                MonitoredSiteUrl.active.is_(True),
            )
        )
        or 0
    )
    latest_analyses = (
        select(
            SitePageAnalysis.site_url_id,
            func.coalesce(SitePageAnalysis.page_kind, "other").label("page_kind"),
        )
        .where(
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
        )
        .distinct(SitePageAnalysis.site_url_id)
        .order_by(SitePageAnalysis.site_url_id, SitePageAnalysis.created_at.desc())
        .subquery()
    )
    page_kinds = {
        str(page_kind): int(count)
        for page_kind, count in (
            await session.execute(
                select(latest_analyses.c.page_kind, func.count())
                .select_from(latest_analyses)
                .group_by(latest_analyses.c.page_kind)
            )
        ).all()
    }
    blocked = int(task_counts.blocked)
    disclose = _crawl_count_disclosure(crawl)
    return {
        "discovered": int(crawl.admitted_url_count or 0) if disclose else None,
        "selected": selected,
        "queued": int(task_counts.queued),
        "running": int(task_counts.running),
        "analyzed": int(task_counts.analyzed),
        "errors": int(task_counts.failed) - blocked,
        "blocked": blocked,
        "by_page_kind": page_kinds,
    }


def _empty_phase_runs() -> dict[str, dict | None]:
    return {PHASE_DISCOVERY: None, PHASE_ANALYSIS: None}


async def _latest_phase_runs(
    session: AsyncSession, *, crawl_id: uuid.UUID
) -> dict[str, dict | None]:
    phase_runs = _empty_phase_runs()
    latest_runs = (
        await session.scalars(
            select(SiteCrawlPhaseRun)
            .where(
                SiteCrawlPhaseRun.crawl_id == crawl_id,
                SiteCrawlPhaseRun.phase.in_([PHASE_DISCOVERY, PHASE_ANALYSIS]),
            )
            .distinct(SiteCrawlPhaseRun.phase)
            .order_by(
                SiteCrawlPhaseRun.phase,
                SiteCrawlPhaseRun.ordinal.desc(),
            )
        )
    ).all()
    for latest_run in latest_runs:
        phase_runs[latest_run.phase] = project_phase_run(latest_run)
    return phase_runs


async def _dashboard_crawl_details(
    session: AsyncSession, crawl: SiteCrawl | None
) -> tuple[dict | None, list[dict], dict | None, dict[str, dict | None]]:
    if crawl is None:
        return None, [], None, _empty_phase_runs()
    return (
        await _failure_summary_for(session, crawl),
        await _root_errors_for(session, crawl),
        await _crawl_counters(session, crawl),
        await _latest_phase_runs(session, crawl_id=crawl.id),
    )


# =========================================================================
# Cancel (atomic)
# =========================================================================
async def cancel_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> dict:
    """Cancel a crawl atomically: transition states, cancel tasks, record event.

    Locks the crawl row ``FOR UPDATE``, drives the overall/discovery/analysis
    sub-states to ``cancelled`` where the guarded machine allows it, cancels
    every non-terminal ``SiteCrawlTask``, records a ``crawl.cancelled`` event
    (payload redacted for Free), and commits. Cancelling an already-terminal
    crawl is idempotent (no-op transition, still returns the current summary).
    """
    locked = await session.execute(
        select(SiteCrawl)
        .where(
            SiteCrawl.id == crawl_id,
            SiteCrawl.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    crawl = locked.scalar_one_or_none()
    if crawl is None:
        raise SiteHealthNotFoundError(_CRAWL_NOT_FOUND)

    if crawl.status in CRAWL_TERMINAL_STATUSES:
        # Idempotent cancel of an already-terminal crawl still answers with
        # the full single-crawl projection — including the B1 failure summary
        # when the terminal state is FAILED.
        return project_crawl(
            crawl, failure_summary=await _failure_summary_for(session, crawl)
        )

    apply_crawl_status(crawl, CRAWL_STATUS_CANCELLED)
    # Discovery / analysis sub-states are cancelled only from a non-terminal
    # state (the guarded machine keeps a completed sub-state as-is). ONLY the
    # state machine's rejection is ignored: a bare ``except Exception`` here
    # also swallowed session and programming errors, hiding real bugs behind a
    # silently-uncancelled sub-state.
    try:
        apply_discovery_status(crawl, DISCOVERY_STATUS_CANCELLED)
    except InvalidSiteCrawlTransition:
        pass
    try:
        apply_analysis_status(crawl, ANALYSIS_STATUS_CANCELLED)
    except InvalidSiteCrawlTransition:
        pass
    crawl.completed_at = func.now()

    # Cancel every non-terminal task for this crawl (queued/leased/running/
    # retry). Succeeded/failed/cancelled tasks keep their immutable evidence.
    await session.execute(
        update(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.status.notin_(
                [
                    TASK_STATUS_SUCCEEDED,
                    TASK_STATUS_FAILED,
                    TASK_STATUS_CANCELLED,
                ]
            ),
        )
        .values(
            status=TASK_STATUS_CANCELLED,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=func.now(),
            error_code="cancelled",
        )
    )

    # Cancellation-time snapshot: if the run already produced completed
    # analyses for ACTIVE monitored URLs, roll them up into the SAME canonical
    # crawl snapshot the worker writes on clean terminalization (one shared
    # algorithm, no duplication). This makes ``score_summary`` non-null so the
    # frontend keeps the dashboard (partial scores + inventory), labels the run
    # Cancelled, and offers Recrawl — instead of hiding results behind a null
    # summary. ``persist_crawl_snapshot`` decides from its single fetched
    # aggregate row set: when nothing aggregable exists (no active completed
    # analyses — including a completed analysis whose monitored URL was since
    # deactivated) it writes neither the snapshot nor the projection and returns
    # ``False``, so the summary stays null (never a fabricated zero) and the UI
    # shows its terminal / selection state. No separate precheck — that would be
    # a TOCTOU race against membership/analysis changes.
    snapshot_written = await persist_crawl_snapshot(session, crawl=crawl)

    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_CANCELLED,
        message="crawl cancelled",
        count_disclosure=_crawl_count_disclosure(crawl),
    )
    if snapshot_written:
        await enqueue_opportunity_refresh(
            session,
            workspace_id=workspace_id,
            project_id=crawl.project_id,
            trigger_kind="site_crawl",
            trigger_id=crawl.id,
        )
    await session.commit()

    refreshed = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    return project_crawl(
        refreshed, failure_summary=await _failure_summary_for(session, refreshed)
    )


# =========================================================================
# Dashboard (selected/latest crawl + score summary + quota)
# =========================================================================
async def get_dashboard(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Project dashboard: selected/latest crawl, score summary, monitored quota.

    With an explicit ``crawl_id`` uses that crawl (404 if foreign); otherwise
    the project's most recent crawl by ``created_at``. No severity/category
    rollups (Slice 7 does not need them). Quota is the workspace-wide active
    monitored count over the entitlement limit.
    """
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    crawl: SiteCrawl | None
    if crawl_id is not None:
        crawl = await session.scalar(
            select(SiteCrawl).where(
                SiteCrawl.id == crawl_id,
                SiteCrawl.workspace_id == workspace_id,
                SiteCrawl.project_id == project_id,
            )
        )
        if crawl is None:
            raise SiteHealthNotFoundError(_CRAWL_NOT_FOUND)
    else:
        crawl = await session.scalar(
            select(SiteCrawl)
            .where(
                SiteCrawl.workspace_id == workspace_id,
                SiteCrawl.project_id == project_id,
            )
            .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
            .limit(1)
        )

    runtime = await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=datetime.now(UTC)
    )
    used = await session.scalar(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    # B1/B3 and counters stay bundled with the selected crawl projection; an
    # empty dashboard returns the same neutral values without branching here.
    failure_summary, root_errors, counters, phase_runs = await _dashboard_crawl_details(
        session, crawl
    )
    return {
        "project_id": project_id,
        "crawl": (
            project_crawl(
                crawl,
                failure_summary=failure_summary,
                counters=counters,
            )
            if crawl is not None
            else None
        ),
        "score_summary": _score_summary(crawl) if crawl is not None else None,
        "quota": {
            "used": int(used or 0),
            "limit": int(runtime.monitored_url_limit),
        },
        "root_errors": root_errors,
        "phase_runs": phase_runs,
    }


# =========================================================================
# Events (JSON replay + SSE support)
# =========================================================================
async def load_events(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    after: uuid.UUID | None = None,
) -> list[SiteCrawlEvent]:
    """Ordered crawl events (``created_at``, then ``id``), optionally after an id.

    ``after`` is a resume anchor (the SSE loop's last delivered event, or a
    client ``Last-Event-ID``): the boundary is applied in SQL as a keyset over
    the SAME ``(created_at, id)`` ordering, so a long-lived stream never loads
    the crawl's whole history on every poll just to drop its head. An anchor
    that is not an event of THIS crawl (stale, or from another crawl) yields no
    events — replaying the full history to a resuming client would duplicate
    everything it already rendered.
    """
    stmt = (
        select(SiteCrawlEvent)
        .where(SiteCrawlEvent.crawl_id == crawl_id)
        .order_by(SiteCrawlEvent.created_at.asc(), SiteCrawlEvent.id.asc())
    )
    if after is not None:
        # The anchor's timestamp as a scalar subquery rather than a second
        # round trip. A stale/foreign anchor yields NULL, and both keyset
        # comparisons against NULL are NULL — so the page comes back empty on
        # its own, which is exactly the "do not replay the whole history to a
        # resuming client" rule the separate lookup used to enforce.
        anchor_created_at = (
            select(SiteCrawlEvent.created_at)
            .where(
                SiteCrawlEvent.id == after,
                SiteCrawlEvent.crawl_id == crawl_id,
            )
            .scalar_subquery()
        )
        stmt = stmt.where(
            or_(
                SiteCrawlEvent.created_at > anchor_created_at,
                and_(
                    SiteCrawlEvent.created_at == anchor_created_at,
                    SiteCrawlEvent.id > after,
                ),
            )
        )
    return list((await session.scalars(stmt)).all())


async def load_crawl_for_stream(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl:
    """Load a crawl for the SSE loop (workspace-scoped; None-safe caller)."""
    return await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
