"""Crawl-facing service mutations + the project dashboard and event replay.

The write path (``cancel_crawl``) and the reads that are about a crawl's
lifecycle rather than its contents. Cancel is ONE atomic transaction: the crawl
row is locked ``FOR UPDATE``, the overall/discovery/analysis sub-states are
driven to cancelled where the guarded machine allows it, every non-terminal task
is cancelled, and the canonical snapshot writer runs so a partially-analyzed run
keeps its scores instead of dead-ending on a null summary.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health import (
    ANALYSIS_STATUS_CANCELLED,
    CRAWL_STATUS_CANCELLED,
    CRAWL_TERMINAL_STATUSES,
    DISCOVERY_STATUS_CANCELLED,
    EVENT_CRAWL_CANCELLED,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.entitlements import resolve_entitlement
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
)
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlEvent,
    SiteCrawlTask,
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
        return project_crawl(crawl)

    apply_crawl_status(crawl, CRAWL_STATUS_CANCELLED)
    # Discovery / analysis sub-states are cancelled only from a non-terminal
    # state (the guarded machine keeps a completed sub-state as-is).
    try:
        apply_discovery_status(crawl, DISCOVERY_STATUS_CANCELLED)
    except Exception:
        pass
    try:
        apply_analysis_status(crawl, ANALYSIS_STATUS_CANCELLED)
    except Exception:
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
    await persist_crawl_snapshot(session, crawl=crawl)

    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_CRAWL_CANCELLED,
        message="crawl cancelled",
        count_disclosure=_crawl_count_disclosure(crawl),
    )
    await session.commit()
    refreshed = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    return project_crawl(refreshed)


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

    entitlement = await resolve_entitlement(session, workspace_id)
    used = await session.scalar(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    return {
        "project_id": project_id,
        "crawl": project_crawl(crawl) if crawl is not None else None,
        "score_summary": _score_summary(crawl) if crawl is not None else None,
        "quota": {
            "used": int(used or 0),
            "limit": int(entitlement.monitored_url_limit),
        },
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
    """Ordered crawl events (``created_at`` ASC), optionally after an id."""
    stmt = (
        select(SiteCrawlEvent)
        .where(SiteCrawlEvent.crawl_id == crawl_id)
        .order_by(SiteCrawlEvent.created_at.asc(), SiteCrawlEvent.id.asc())
    )
    events = list((await session.scalars(stmt)).all())
    if after is None:
        return events
    seen = False
    tail: list[SiteCrawlEvent] = []
    for event in events:
        if seen:
            tail.append(event)
        elif event.id == after:
            seen = True
    return tail if seen else events


async def load_crawl_for_stream(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl:
    """Load a crawl for the SSE loop (workspace-scoped; None-safe caller)."""
    return await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
