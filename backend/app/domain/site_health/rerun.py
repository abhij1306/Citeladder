# Explicit per-page rerun of one monitored URL.
#
# Reuses the monitored-selection locking primitives so a rerun serializes
# against a concurrent selection change and against full-crawl creation. The
# global lock order stays ``project -> runtime -> profile``.
from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    TASK_KIND_ANALYZE,
)
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_workspace,
)
from app.domain.site_health.entitlements import (
    lock_runtime,
    runtime_allows_monitored_analysis,
)
from app.domain.site_health.selection import (
    MonitoringNotAllowedError,
    SelectionError,
    SelectionValidationError,
    active_crawl,
    enqueue_analyze_task,
    lock_profile,
    next_generations,
    utcnow,
)
from app.models.project import Project
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


class RerunNotAllowedError(SelectionError):
    """A rerun was requested for a URL not (still) monitored / no active crawl."""

    code = "rerun_not_allowed"


@dataclass(frozen=True)
class RerunResult:
    """Identity/status of a freshly-enqueued page rerun (frontend polls this).

    - ``crawl_id`` — the crawl the rerun's analyze task lives in. This is a
      NEW crawl when the project's latest crawl was terminal, or the current
      active crawl when one exists. The frontend must poll the page detail on
      THIS crawl (not the terminal source crawl).
    - ``site_url_id`` — the target URL (unchanged from the request).
    - ``task_id`` — the enqueued ``analyze`` task id (for provenance/debugging).
    - ``created_new_crawl`` — ``True`` iff a fresh crawl was minted, so the
      caller can decide whether to redirect the client to a new crawl route.
    - ``analysis_status`` — the crawl's analysis sub-state at enqueue time
      (always ``pending`` for a brand-new crawl; the current value otherwise),
      so the frontend starts polling from a known non-terminal baseline.
    """

    crawl_id: uuid.UUID
    site_url_id: uuid.UUID
    task_id: uuid.UUID
    created_new_crawl: bool
    analysis_status: str


async def _lock_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project | None:
    """Load + lock the project row ``FOR UPDATE``.

    This is the SAME lock ``create_crawl`` takes first (before the runtime
    and profile). Taking it here serializes a terminal-page rerun against a
    concurrent full-crawl creation for the same project, so the active-crawl
    check below cannot race past ``create_crawl``'s and mint a second active
    crawl. The global lock order is ``project -> runtime -> profile``.
    """
    result = await session.execute(
        select(Project)
        .where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def rerun_page(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    site_url_id: uuid.UUID,
) -> RerunResult:
    """Enqueue a fresh ``analyze`` task for one monitored URL under lock.

    Requires an active monitored membership for the URL (``rerun_not_allowed``
    otherwise — never silently no-ops). Locks the project row, then the
    runtime row, then the project profile — the SAME order ``create_crawl``
    uses — so a concurrent selection change, another rerun of the same URL, or
    a concurrent full-crawl creation is serialized. The active-crawl check
    below runs while holding the project lock, so a terminal-page rerun and a
    full crawl can never both observe "no active crawl" and each mint one.

    Crawl identity is chosen so the rerun's task can actually run:

    - If the project has an ACTIVE crawl, the analyze task is enqueued into it
      at the NEXT ``generation`` (so it never collides with a prior run's slot
      or a cancelled task).
    - Otherwise (the latest crawl is terminal — the common "Re-audit from a
      completed crawl" case), a fresh single-page rerun crawl is minted via
      the planner and the task is seeded there. Enqueuing into a terminal
      crawl would be cooperatively cancelled by the worker and never run, so
      this path is required for the visible action to work.

    Returns a ``RerunResult`` carrying the (possibly new) crawl id, the task
    id, the ``created_new_crawl`` flag, and the crawl's analysis sub-state, so
    the API can hand the frontend enough identity to poll the fresh rerun.
    """
    # Lock the project row FIRST — the same lock ``create_crawl`` takes before
    # its active-crawl check — so a concurrent full crawl and this terminal-page
    # rerun serialize and cannot both mint an active crawl. Global lock order:
    # project -> runtime -> profile.
    project = await _lock_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if project is None:
        raise SelectionValidationError("Project not found")

    await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=utcnow()
    )
    runtime = await lock_runtime(session, workspace_id)
    profile = await lock_profile(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if profile is None:
        raise SelectionValidationError("Site Health profile not found")

    membership = await session.scalar(
        select(MonitoredSiteUrl).where(
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.site_url_id == site_url_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    if membership is None:
        raise RerunNotAllowedError(
            "The URL is not part of the active monitored selection"
        )
    if not runtime_allows_monitored_analysis(
        runtime, selection_source=membership.selection_source
    ):
        raise MonitoringNotAllowedError(
            "The current monitored-URL allowance does not allow analysis of this URL"
        )

    site_url = await session.get(SiteUrl, site_url_id)
    if site_url is None or site_url.project_id != project_id:
        raise SelectionValidationError("Site URL not found in this project")

    crawl = await active_crawl(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if crawl is not None:
        generations = await next_generations(
            session,
            crawl_id=crawl.id,
            task_kind=TASK_KIND_ANALYZE,
            url_hashes=[site_url.url_hash],
        )
        task = await enqueue_analyze_task(
            session,
            crawl=crawl,
            site_url=site_url,
            generation=generations[site_url.url_hash],
            position=0,
        )
        await session.flush()
        return RerunResult(
            crawl_id=crawl.id,
            site_url_id=site_url_id,
            task_id=task.id,
            created_new_crawl=False,
            analysis_status=crawl.analysis_status,
        )

    # No active crawl: mint a fresh single-page rerun crawl so the analyze
    # task can actually run. Imported lazily so this module does not pull the
    # crawl planner (and its own seeding dependencies) in at import time.
    from app.domain.site_health.planner import create_page_rerun_crawl

    new_crawl = await create_page_rerun_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        profile=profile,
        site_url=site_url,
        runtime=runtime,
    )
    existing_task = await session.scalar(
        select(SiteCrawlTask).where(
            SiteCrawlTask.crawl_id == new_crawl.id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            SiteCrawlTask.site_url_id == site_url_id,
        )
    )
    await session.flush()
    return RerunResult(
        crawl_id=new_crawl.id,
        site_url_id=site_url_id,
        task_id=existing_task.id if existing_task is not None else new_crawl.id,
        created_new_crawl=True,
        analysis_status=new_crawl.analysis_status,
    )
