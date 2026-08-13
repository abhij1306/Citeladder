"""Site Health read paths: entitlement, crawls, inventory, pages, page detail.

The workspace-scoped projections behind the list/detail endpoints. Every query
here is bounded by the resolved workspace and (for crawl-scoped reads) by what
the crawl actually admitted, so a later downgraded crawl can never surface an
earlier, fuller catalog. Row shaping lives in ``presentation``; the grouped
issue catalog — the other half of the read surface — lives in ``issues``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.entitlements import KEY_MONITORED_URLS
from app.core.config.site_health import (
    CRAWL_STATUS_FAILED,
    TASK_KIND_ANALYZE,
    site_health_settings,
)
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_account,
    refresh_site_health_runtime_for_workspace,
    resolve_workspace_entitlement,
)
from app.domain.entitlements.types import STATUS_RESOLVED
from app.domain.site_health.entitlements import resolve_runtime
from app.domain.site_health.failure import load_root_errors, load_root_failure_summary
from app.domain.site_health.inventory_scope import (
    inventory_site_url_subquery,
)
from app.domain.site_health.normalization import encode_keyset_cursor
from app.domain.site_health.service.common import (
    _clamp_limit,
    _decode_created_id_keyset,
    _decode_url_keyset,
    _load_crawl,
    _load_project,
)
from app.domain.site_health.service.presentation import (
    _iso,
    _matches_page_status,
    _page_kind_matches,
    presentation_status_for,
    project_crawl,
)
from app.models.billing import WorkspaceBillingLink
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SiteHealthProfile,
    SiteIssue,
    SitePageAnalysis,
    SiteUrl,
)


# =========================================================================
# Entitlement view
# =========================================================================
async def get_entitlement_view(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> dict:
    """Project the workspace Site Health entitlement into the neutral contract.

    Thin wrapper kept at the frozen complexity budget; the projection lives in
    ``_site_health_entitlement_view``.
    """
    return await _site_health_entitlement_view(
        session, workspace_id=workspace_id, at=datetime.now(UTC)
    )


async def _site_health_entitlement_view(
    session: AsyncSession, *, workspace_id: uuid.UUID, at: datetime
) -> dict:
    """Resolve the account at an explicit ``at`` and project the neutral DTO.

    Sources ``resolver_status`` / ``contributing_grant_ids`` from the
    ``ResolvedEntitlement`` (never the runtime row) and lazily refreshes the
    runtime projection. ``unresolved`` yields a zero monitored limit, the
    neutral sample limit, no disclosure, and empty grant IDs. The read
    commits nothing.
    """
    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is None:
        entitlement = await resolve_workspace_entitlement(
            session, workspace_id=workspace_id, at=at
        )
        row = await refresh_site_health_runtime_for_workspace(
            session, workspace_id=workspace_id, at=at
        )
    else:
        entitlement = await refresh_site_health_runtime_for_account(
            session, account_id=account_id, at=at
        )
        row = await resolve_runtime(session, workspace_id)
    resolved = entitlement.status == STATUS_RESOLVED
    capability = entitlement.capability(KEY_MONITORED_URLS)
    if not resolved:
        access_mode = "unresolved"
    elif row.monitored_url_limit > 0:
        access_mode = "full"
    else:
        access_mode = "sample"
    return {
        "workspace_id": row.workspace_id,
        "access_mode": access_mode,
        "sample_url_limit": int(row.sample_url_limit),
        "monitored_url_limit": int(row.monitored_url_limit) if resolved else 0,
        "count_disclosure": bool(row.count_disclosure) if resolved else False,
        "resolver_status": entitlement.status,
        "registry_revision": entitlement.registry_revision,
        "entitlement_lifecycle_version": int(entitlement.entitlement_lifecycle_version),
        "valid_until": entitlement.valid_until,
        "contributing_grant_ids": (
            list(capability.contributing_grant_ids)
            if resolved and capability is not None
            else []
        ),
        "advanced_controls_enabled": site_health_settings.advanced_controls_enabled,
    }


# =========================================================================
# Crawl summary / list
# =========================================================================
async def _failure_summary_for(session: AsyncSession, crawl: SiteCrawl) -> dict | None:
    """B1 failure summary for the single-crawl read paths.

    Only a FAILED crawl can have one (a terminally failed root fetch is what
    makes a crawl fail), so healthy/partial crawls skip the evidence queries
    entirely. List projections stay ``None`` by not calling this (N+1
    avoidance).
    """
    if crawl.status != CRAWL_STATUS_FAILED:
        return None
    return await load_root_failure_summary(session, crawl=crawl)


async def _root_errors_for(session: AsyncSession, crawl: SiteCrawl) -> list[dict]:
    """B3 root-failure rows for the pages/dashboard responses (same guard)."""
    if crawl.status != CRAWL_STATUS_FAILED:
        return []
    return await load_root_errors(session, crawl=crawl)


async def get_crawl_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> dict:
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    return project_crawl(
        crawl, failure_summary=await _failure_summary_for(session, crawl)
    )


async def list_crawls(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    limit: int | None,
    cursor: str | None,
) -> dict:
    """List crawls ordered ``(created_at DESC, id DESC)`` with a keyset cursor."""
    limit = _clamp_limit(limit)
    scope = "crawls"
    filters = {"project_id": str(project_id) if project_id else None}

    stmt = select(SiteCrawl).where(SiteCrawl.workspace_id == workspace_id)
    if project_id is not None:
        # Authorize the project so a foreign id is a 404, not an empty page.
        await _load_project(session, workspace_id=workspace_id, project_id=project_id)
        stmt = stmt.where(SiteCrawl.project_id == project_id)

    if cursor:
        cur_created, cur_id = _decode_created_id_keyset(
            cursor, scope=scope, filters=filters
        )
        # (created_at, id) DESC keyset: rows strictly "older" than the cursor.
        stmt = stmt.where(
            or_(
                SiteCrawl.created_at < cur_created,
                and_(
                    SiteCrawl.created_at == cur_created,
                    SiteCrawl.id < cur_id,
                ),
            )
        )

    stmt = stmt.order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc()).limit(
        limit + 1
    )
    rows = list((await session.scalars(stmt)).all())

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last.created_at.isoformat(), str(last.id)],
        )
    return {
        "items": [project_crawl(row) for row in rows],
        "next_cursor": next_cursor,
    }


async def _monitored_site_url_ids(
    session: AsyncSession, *, project_id: uuid.UUID
) -> set[uuid.UUID]:
    """Set of ACTIVE monitored ``site_url_id`` for a project."""
    rows = await session.execute(
        select(MonitoredSiteUrl.site_url_id).where(
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    return {row[0] for row in rows.all()}


async def _latest_analysis_by_site_url(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    site_url_ids: list[uuid.UUID],
) -> dict[uuid.UUID, SitePageAnalysis]:
    """Current ``SitePageAnalysis`` per site_url within a crawl.

    ``SitePageAnalysis`` is append-only, so one artifact can hold several rows
    (one per analyzer/pack version pair). Only the ``is_current`` row is the
    live understanding; superseded rows stay queryable as history but must
    never surface as a page's present state.
    """
    if not site_url_ids:
        return {}
    rows = await session.execute(
        select(SitePageAnalysis)
        .where(
            SitePageAnalysis.crawl_id == crawl_id,
            SitePageAnalysis.site_url_id.in_(site_url_ids),
            SitePageAnalysis.is_current.is_(True),
        )
        .order_by(
            SitePageAnalysis.site_url_id,
            SitePageAnalysis.created_at.asc(),
            SitePageAnalysis.id.asc(),
        )
    )
    latest: dict[uuid.UUID, SitePageAnalysis] = {}
    for analysis in rows.scalars().all():
        latest[analysis.site_url_id] = analysis  # last wins = newest
    return latest


async def _latest_analyze_task_by_site_url(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    site_url_ids: list[uuid.UUID],
) -> dict[uuid.UUID, SiteCrawlTask]:
    """Latest ``analyze`` task per site_url within a crawl (by generation)."""
    if not site_url_ids:
        return {}
    rows = await session.execute(
        select(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            SiteCrawlTask.site_url_id.in_(site_url_ids),
        )
        .order_by(
            SiteCrawlTask.site_url_id,
            SiteCrawlTask.generation.asc(),
            SiteCrawlTask.created_at.asc(),
        )
    )
    latest: dict[uuid.UUID, SiteCrawlTask] = {}
    for task in rows.scalars().all():
        if task.site_url_id is not None:
            latest[task.site_url_id] = task  # last wins = newest generation
    return latest


async def _issue_counts_by_site_url(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    site_url_ids: list[uuid.UUID],
) -> dict[uuid.UUID, int]:
    """Count of persisted issues per site_url within a crawl."""
    if not site_url_ids:
        return {}
    rows = await session.execute(
        select(SiteIssue.site_url_id, func.count())
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.site_url_id.in_(site_url_ids),
        )
        .group_by(SiteIssue.site_url_id)
    )
    return {row[0]: int(row[1]) for row in rows.all()}


def _matching_page_summaries(
    rows: Sequence[SiteUrl],
    *,
    analyses: dict[uuid.UUID, SitePageAnalysis],
    tasks: dict[uuid.UUID, SiteCrawlTask],
    monitored_ids: set[uuid.UUID],
    status: str | None,
    page_kind: str | None,
    limit: int,
    project: Callable[[SiteUrl, SitePageAnalysis | None, str, str | None], dict],
) -> tuple[list[dict], SiteUrl | None]:
    """Project matching rows and retain the last scanned key for pagination.

    Status and page-kind are derived from persisted analysis/task state rather
    than SQL columns.  Keeping their filtering loop shared ensures inventory
    and pages have identical compound-status semantics and sparse-page cursor
    behavior.
    """
    items: list[dict] = []
    last_scanned: SiteUrl | None = None
    for row in rows:
        last_scanned = row
        analysis = analyses.get(row.id)
        presentation_status, error_code = presentation_status_for(
            analysis=analysis,
            monitored=row.id in monitored_ids,
            latest_analyze_task=tasks.get(row.id),
        )
        if not _matches_page_status(presentation_status, status):
            continue
        if not _page_kind_matches(analysis, page_kind):
            continue
        items.append(project(row, analysis, presentation_status, error_code))
        if len(items) >= limit + 1:
            break
    return items, last_scanned


def _page_keyset_result(
    items: list[dict],
    *,
    last_scanned: SiteUrl | None,
    scanned_row_count: int,
    fetch_size: int,
    limit: int,
    sparse_filter: bool,
    scope: str,
    filters: dict,
) -> tuple[list[dict], str | None]:
    """Trim a page and emit either a matched or sparse-scan cursor.

    A full widened scan that yields too few matches advances at the final
    scanned key.  That distinction prevents sparse derived filters from
    repeating an empty window forever.
    """
    if len(items) > limit:
        kept = items[:limit]
        last_kept = kept[-1]
        return kept, encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last_kept["normalized_url"], str(last_kept["site_url_id"])],
        )
    if sparse_filter and last_scanned is not None and scanned_row_count >= fetch_size:
        return items, encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last_scanned.normalized_url, str(last_scanned.id)],
        )
    return items, None


def _inventory_summary_row(
    row: SiteUrl,
    analysis: SitePageAnalysis | None,
    _presentation_status: str,
    _error_code: str | None,
    *,
    monitored_ids: set[uuid.UUID],
    issue_counts: dict[uuid.UUID, int],
) -> dict:
    """Render the bounded inventory projection for one persisted SiteUrl."""
    return {
        "site_url_id": row.id,
        "normalized_url": row.normalized_url,
        "display_url": row.display_url or row.normalized_url,
        "title": row.latest_title or None,
        "content_type": row.latest_content_type or None,
        "source": row.latest_source_kind or None,
        "depth": row.depth,
        "monitored": row.id in monitored_ids,
        "first_seen_at": _iso(row.first_seen_at),
        "last_seen_at": _iso(row.last_seen_at),
        "issue_count": issue_counts.get(row.id, 0) if analysis is not None else None,
        "page_kind": analysis.page_kind if analysis is not None else None,
        "technical_score": analysis.technical_score if analysis is not None else None,
        "aeo_score": analysis.aeo_score if analysis is not None else None,
        "overall_score": analysis.overall_score if analysis is not None else None,
        "last_audited": _iso(analysis.finalized_at) if analysis is not None else None,
    }


def _pages_summary_row(
    row: SiteUrl,
    analysis: SitePageAnalysis | None,
    presentation_status: str,
    error_code: str | None,
    *,
    crawl_id: uuid.UUID,
    current_observed_ids: set[uuid.UUID],
    inherited_crawl_by_url: dict[uuid.UUID, uuid.UUID],
    monitored_ids: set[uuid.UUID],
    issue_counts: dict[uuid.UUID, int],
) -> dict:
    """Render one persisted page projection, including inherited inventory."""
    return {
        "site_url_id": row.id,
        "crawl_id": (
            crawl_id
            if row.id in current_observed_ids
            else inherited_crawl_by_url.get(row.id, crawl_id)
        ),
        "normalized_url": row.normalized_url,
        "display_url": row.display_url or row.normalized_url,
        "title": row.latest_title or None,
        "monitored": row.id in monitored_ids,
        "analysis_status": presentation_status,
        "error_code": error_code,
        "issue_count": issue_counts.get(row.id, 0) if analysis is not None else None,
        "page_kind": analysis.page_kind if analysis is not None else None,
        "technical_score": analysis.technical_score if analysis is not None else None,
        "aeo_score": analysis.aeo_score if analysis is not None else None,
        "overall_score": analysis.overall_score if analysis is not None else None,
        "last_audited": _iso(analysis.finalized_at) if analysis is not None else None,
    }


# =========================================================================
# Inventory (keyset (normalized_url, id) over SiteUrl)
# =========================================================================
async def get_inventory(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
    query: str | None = None,
    status: str | None = None,
    monitored: bool | None = None,
    page_kind: str | None = None,
) -> dict:
    """Keyset inventory for a crawl's project, ordered ``(normalized_url, id)``.

    Filters by substring ``query`` (normalized/display url), a per-URL
    presentation ``status``, the ``monitored`` flag, and a ``page_kind``
    exact match against the latest analysis's classified type (v2 P1 —
    semantics in ``_page_kind_matches``). The cursor is bound to the
    endpoint + filter fingerprint so a filter change invalidates it.
    Nullable latest-analysis summaries are attached per row.
    """
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    limit = _clamp_limit(limit)
    project_id = crawl.project_id
    scope = "inventory"
    filters = {
        "crawl_id": str(crawl_id),
        "query": (query or "").strip().lower() or None,
        "status": status or None,
        "monitored": (str(monitored) if monitored is not None else None),
        "page_kind": page_kind or None,
    }

    search: list[Any] = []
    if query:
        pattern = f"%{query.strip().lower()}%"
        search.append(
            or_(
                func.lower(SiteUrl.normalized_url).like(pattern),
                func.lower(SiteUrl.display_url).like(pattern),
            )
        )

    # A status/page_kind filter is applied in Python from the derived
    # presentation status, so the SQL window is widened to keep pages full.
    over_fetch = status is not None or page_kind is not None
    fetch_size = _scan_window(limit, over_fetch=over_fetch)

    monitored_ids = await _monitored_site_url_ids(session, project_id=project_id)
    # A Starter recrawl reads its explicitly frozen earlier full inventories
    # while new observations stream in. Sample crawls ignore inherited ids, so
    # a Free/downgraded run cannot expose the earlier Starter catalog.
    stmt = _site_url_page_stmt(
        crawl,
        monitored=monitored,
        monitored_ids=monitored_ids,
        cursor=cursor,
        scope=scope,
        filters=filters,
        limit=limit,
        over_fetch=over_fetch,
        extra_where=search,
    )
    if stmt is None:
        return {"items": [], "next_cursor": None}
    rows = list((await session.scalars(stmt)).all())

    site_ids = [r.id for r in rows]
    analyses = await _latest_analysis_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )
    tasks = await _latest_analyze_task_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )
    issue_counts = await _issue_counts_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )

    def project_inventory_row(
        row: SiteUrl,
        analysis: SitePageAnalysis | None,
        presentation_status: str,
        error_code: str | None,
    ) -> dict:
        return _inventory_summary_row(
            row,
            analysis,
            presentation_status,
            error_code,
            monitored_ids=monitored_ids,
            issue_counts=issue_counts,
        )

    items, last_scanned = _matching_page_summaries(
        rows,
        analyses=analyses,
        tasks=tasks,
        monitored_ids=monitored_ids,
        status=status,
        page_kind=page_kind,
        limit=limit,
        project=project_inventory_row,
    )
    items, next_cursor = _page_keyset_result(
        items,
        last_scanned=last_scanned,
        scanned_row_count=len(rows),
        fetch_size=fetch_size,
        limit=limit,
        sparse_filter=over_fetch,
        scope=scope,
        filters=filters,
    )
    return {"items": items, "next_cursor": next_cursor}


def _scan_window(limit: int, *, over_fetch: bool) -> int:
    """Rows to scan for one page: the page itself, widened for sparse filters.

    Shared so the SELECT's LIMIT and the callers' "did we scan a full window?"
    cursor-advance check can never disagree — if they drift, a sparse filter
    either stops paginating early or loops on the same window forever.
    """
    fetch = limit + 1
    return fetch * 4 if over_fetch else fetch


def _site_url_page_stmt(
    crawl: SiteCrawl,
    *,
    monitored: bool | None,
    monitored_ids: set[uuid.UUID] | frozenset[uuid.UUID],
    cursor: str | None,
    scope: str,
    filters: dict,
    limit: int,
    over_fetch: bool,
    extra_where: Sequence[Any] = (),
):
    """The shared ``(normalized_url, id)`` keyset page over a crawl's SiteUrls.

    ``get_inventory`` and ``get_pages`` differ only in their row projection —
    the scope subquery, monitored filter, cursor predicate, ordering and
    over-fetch were an identical 37-line block in both (the audit's top
    duplication finding). Returns ``None`` when the filters select nothing, so
    callers short-circuit to an empty page.

    ``over_fetch`` widens the fetch when a status/page_kind filter is applied
    in Python from the derived presentation status, so a filtered page can
    still come back full. ``extra_where`` carries caller-specific predicates
    (the inventory's substring search) so they are applied with the rest of
    the filtering, before ordering and limiting.
    """
    stmt = select(SiteUrl).where(
        SiteUrl.project_id == crawl.project_id,
        SiteUrl.id.in_(inventory_site_url_subquery(crawl)),
    )
    for clause in extra_where:
        stmt = stmt.where(clause)
    if monitored is True:
        if not monitored_ids:
            return None
        stmt = stmt.where(SiteUrl.id.in_(list(monitored_ids)))
    elif monitored is False and monitored_ids:
        stmt = stmt.where(SiteUrl.id.notin_(list(monitored_ids)))

    if cursor:
        cur_url, cur_id = _decode_url_keyset(cursor, scope=scope, filters=filters)
        stmt = stmt.where(
            tuple_(SiteUrl.normalized_url, SiteUrl.id) > (cur_url, cur_id)
        )

    return stmt.order_by(SiteUrl.normalized_url.asc(), SiteUrl.id.asc()).limit(
        _scan_window(limit, over_fetch=over_fetch)
    )


# =========================================================================
# Monitored set
# =========================================================================
async def get_monitored_set(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """Project's persistent monitored set + selection version + workspace quota."""
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    profile = await session.scalar(
        select(SiteHealthProfile).where(SiteHealthProfile.project_id == project_id)
    )
    selection_version = int(profile.selection_version) if profile else 0

    rows = await session.execute(
        select(MonitoredSiteUrl, SiteUrl)
        .join(SiteUrl, SiteUrl.id == MonitoredSiteUrl.site_url_id)
        .where(MonitoredSiteUrl.project_id == project_id)
        .order_by(SiteUrl.normalized_url.asc(), SiteUrl.id.asc())
    )
    monitored_urls: list[dict] = []
    for membership, site_url in rows.all():
        monitored_urls.append(
            {
                "site_url_id": membership.site_url_id,
                "normalized_url": site_url.normalized_url,
                "display_url": site_url.display_url or site_url.normalized_url,
                "title": site_url.latest_title or None,
                "active": membership.active,
                "selection_source": membership.selection_source,
                "selected_at": _iso(membership.selected_at),
                "deselected_at": _iso(membership.deselected_at),
            }
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
    return {
        "project_id": project_id,
        "selection_version": selection_version,
        "monitored_urls": monitored_urls,
        "quota": {
            "used": int(used or 0),
            "limit": int(runtime.monitored_url_limit),
        },
    }


from app.domain.site_health.service.pages import (  # noqa: E402
    get_page_detail,
    get_pages,
)

__all__ = ["get_page_detail", "get_pages"]
