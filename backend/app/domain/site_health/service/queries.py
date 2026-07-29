"""Site Health read paths: entitlement, crawls, inventory, pages, page detail.

The workspace-scoped projections behind the list/detail endpoints. Every query
here is bounded by the resolved workspace and (for crawl-scoped reads) by what
the crawl actually admitted, so a later downgraded crawl can never surface an
earlier, fuller catalog. Row shaping lives in ``presentation``; the grouped
issue catalog — the other half of the read surface — lives in ``issues``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, case, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health import TASK_KIND_ANALYZE, capability_profile
from app.domain.site_health.entitlements import resolve_entitlement
from app.domain.site_health.inventory_scope import (
    inherited_inventory_crawl_ids,
    inventory_site_url_subquery,
)
from app.domain.site_health.normalization import encode_keyset_cursor
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    _admitted_site_url_subquery,
    _clamp_limit,
    _decode_created_id_keyset,
    _decode_url_keyset,
    _load_crawl,
    _load_project,
)
from app.domain.site_health.service.presentation import (
    _MAX_EVALUATIONS,
    _MAX_LINK_REFERENCES,
    _SEVERITY_RANK,
    _UNRANKED_SEVERITY,
    _delivery_facts,
    _evaluation_row,
    _iso,
    _issue_row,
    _link_reference_row,
    _matches_page_status,
    _page_facts,
    _page_type_matches,
    presentation_status_for,
    project_crawl,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteHealthProfile,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
    WorkspaceSiteHealthEntitlement,
)


# =========================================================================
# Entitlement view
# =========================================================================
async def get_entitlement_view(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> dict:
    """Project the workspace entitlement into the strict entitlement contract.

    Derives ``access_mode`` (Starter selects a monitored set; Free gets a
    server sample) and ``can_view_discovered_total`` from the live capability
    profile. Seeds a Free row on first use (fail-closed).
    """
    row: WorkspaceSiteHealthEntitlement = await resolve_entitlement(
        session, workspace_id
    )
    profile = capability_profile(row.plan_key)
    access_mode = "selection" if profile.allows_user_selection else "sample"
    return {
        "workspace_id": row.workspace_id,
        "plan_key": profile.capability,
        "access_mode": access_mode,
        "sample_url_limit": int(row.sample_url_limit),
        "monitored_url_limit": int(row.monitored_url_limit),
        "can_view_discovered_total": bool(row.count_disclosure),
        "capability_revision": int(row.capability_revision),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


# =========================================================================
# Crawl summary / list
# =========================================================================
async def get_crawl_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> dict:
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    return project_crawl(crawl)


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
    """Latest ``SitePageAnalysis`` per site_url within a crawl (by created_at)."""
    if not site_url_ids:
        return {}
    rows = await session.execute(
        select(SitePageAnalysis)
        .where(
            SitePageAnalysis.crawl_id == crawl_id,
            SitePageAnalysis.site_url_id.in_(site_url_ids),
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
    page_type: str | None = None,
) -> dict:
    """Keyset inventory for a crawl's project, ordered ``(normalized_url, id)``.

    Filters by substring ``query`` (normalized/display url), a per-URL
    presentation ``status``, the ``monitored`` flag, and a ``page_type``
    exact match against the latest analysis's classified type (v2 P1 —
    semantics in ``_page_type_matches``). The cursor is bound to the
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
        "page_type": page_type or None,
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

    # A status/page_type filter is applied in Python from the derived
    # presentation status, so the SQL window is widened to keep pages full.
    over_fetch = status is not None or page_type is not None
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

    items: list[dict] = []
    last_scanned: SiteUrl | None = None
    for row in rows:
        last_scanned = row
        analysis = analyses.get(row.id)
        pres_status, _code = presentation_status_for(
            analysis=analysis,
            monitored=row.id in monitored_ids,
            latest_analyze_task=tasks.get(row.id),
        )
        # The SAME predicate the pages endpoint uses, so a compound value like
        # ``error_or_blocked`` filters identically on both surfaces (a plain
        # ``!=`` here silently matched nothing for it).
        if not _matches_page_status(pres_status, status):
            continue
        if not _page_type_matches(analysis, page_type):
            continue
        items.append(
            {
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
                "issue_count": (
                    issue_counts.get(row.id, 0) if analysis is not None else None
                ),
                "page_type": analysis.page_type if analysis is not None else None,
                "technical_score": (
                    analysis.technical_score if analysis is not None else None
                ),
                "aeo_score": (analysis.aeo_score if analysis is not None else None),
                "overall_score": (
                    analysis.overall_score if analysis is not None else None
                ),
                "last_audited": (
                    _iso(analysis.finalized_at) if analysis is not None else None
                ),
            }
        )
        if len(items) >= limit + 1:
            break

    next_cursor: str | None = None
    if len(items) > limit:
        items = items[:limit]
        last_kept = items[-1]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[
                last_kept["normalized_url"],
                str(last_kept["site_url_id"]),
            ],
        )
    elif (
        (status is not None or page_type is not None)
        and last_scanned is not None
        and len(rows) >= fetch_size
    ):
        # A sparse status/page_type filter can leave a partial (or even empty)
        # page while more matching rows exist beyond the scanned window. We
        # fetched a full window, so emit a cursor at the last SCANNED row (not
        # the last matched one) to guarantee forward progress even when a
        # window had no matches.
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last_scanned.normalized_url, str(last_scanned.id)],
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

    ``over_fetch`` widens the fetch when a status/page_type filter is applied
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
        "selection_version": selection_version,
        "monitored_urls": monitored_urls,
        "quota": {
            "used": int(used or 0),
            "limit": int(entitlement.monitored_url_limit),
        },
    }


# =========================================================================
# Pages (CursorPage<PageSummary> ordered (normalized_url, site_url_id))
# =========================================================================
async def get_pages(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
    status: str | None = None,
    monitored: bool | None = None,
    page_type: str | None = None,
) -> dict:
    """Analyzed-page summaries for a crawl, ordered ``(normalized_url, id)``.

    Accepts an exact presentation ``status`` or the combined ``error_or_blocked``
    filter, a ``monitored`` toggle, and a ``page_type`` filter (v2 P1 —
    semantics in ``_page_type_matches``). Filters are part of the cursor
    fingerprint. Rows are the crawl's project ``SiteUrl`` set, projected
    with the latest analysis and derived presentation status.
    """
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    limit = _clamp_limit(limit)
    project_id = crawl.project_id
    scope = "pages"
    filters = {
        "crawl_id": str(crawl_id),
        "status": status or None,
        "monitored": (str(monitored) if monitored is not None else None),
        "page_type": page_type or None,
    }

    over_fetch = status is not None or page_type is not None
    fetch_size = _scan_window(limit, over_fetch=over_fetch)

    monitored_ids = await _monitored_site_url_ids(session, project_id=project_id)
    # Same durable Starter inventory scope as get_inventory. Analysis, tasks,
    # issues, and scores below remain current-crawl-only, so inherited rows
    # show as not selected rather than borrowing old evidence.
    stmt = _site_url_page_stmt(
        crawl,
        monitored=monitored,
        monitored_ids=monitored_ids,
        cursor=cursor,
        scope=scope,
        filters=filters,
        limit=limit,
        over_fetch=over_fetch,
    )
    if stmt is None:
        return {"items": [], "next_cursor": None}
    rows = list((await session.scalars(stmt)).all())

    site_ids = [r.id for r in rows]
    current_observed_ids = set(
        (
            await session.scalars(
                select(SiteUrlObservation.site_url_id).where(
                    SiteUrlObservation.crawl_id == crawl_id,
                    SiteUrlObservation.site_url_id.in_(site_ids),
                )
            )
        ).all()
    )
    inherited_ids = inherited_inventory_crawl_ids(crawl)
    inherited_crawl_by_url: dict[uuid.UUID, uuid.UUID] = {}
    if inherited_ids and site_ids:
        source_rows = (
            await session.execute(
                select(
                    SiteUrlObservation.site_url_id,
                    SiteUrlObservation.crawl_id,
                ).where(
                    SiteUrlObservation.crawl_id.in_(inherited_ids),
                    SiteUrlObservation.site_url_id.in_(site_ids),
                )
            )
        ).all()
        source_rank = {value: rank for rank, value in enumerate(inherited_ids)}
        for source_site_url_id, source_crawl_id in sorted(
            source_rows, key=lambda row: source_rank.get(row[1], len(source_rank))
        ):
            inherited_crawl_by_url.setdefault(source_site_url_id, source_crawl_id)
    analyses = await _latest_analysis_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )
    tasks = await _latest_analyze_task_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )
    issue_counts = await _issue_counts_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=site_ids
    )

    items: list[dict] = []
    last_scanned: SiteUrl | None = None
    for row in rows:
        analysis = analyses.get(row.id)
        pres_status, error_code = presentation_status_for(
            analysis=analysis,
            monitored=row.id in monitored_ids,
            latest_analyze_task=tasks.get(row.id),
        )
        last_scanned = row
        if not _matches_page_status(pres_status, status):
            continue
        if not _page_type_matches(analysis, page_type):
            continue
        items.append(
            {
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
                "analysis_status": pres_status,
                "error_code": error_code,
                "issue_count": (
                    issue_counts.get(row.id, 0) if analysis is not None else None
                ),
                "page_type": analysis.page_type if analysis is not None else None,
                "technical_score": (
                    analysis.technical_score if analysis is not None else None
                ),
                "aeo_score": (analysis.aeo_score if analysis is not None else None),
                "overall_score": (
                    analysis.overall_score if analysis is not None else None
                ),
                "last_audited": (
                    _iso(analysis.finalized_at) if analysis is not None else None
                ),
            }
        )
        if len(items) >= limit + 1:
            break

    next_cursor: str | None = None
    if len(items) > limit:
        items = items[:limit]
        last_kept = items[-1]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[
                last_kept["normalized_url"],
                str(last_kept["site_url_id"]),
            ],
        )
    elif (
        (status is not None or page_type is not None)
        and last_scanned is not None
        and len(rows) >= fetch_size
    ):
        # Sparse status/page_type filter: a full window yielded a partial/empty
        # page while more matching rows may exist. Advance the cursor to the
        # last SCANNED row so traversal keeps making progress across empty
        # windows.
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last_scanned.normalized_url, str(last_scanned.id)],
        )
    return {"items": items, "next_cursor": next_cursor}


# =========================================================================
# Page detail (persisted facts/delivery/scores/issues/provenance; no network)
# =========================================================================
async def get_page_detail(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
) -> dict:
    """Full per-URL detail from persisted rows only (never a network call)."""
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    # Only a URL admitted to THIS crawl has a detail here (404 otherwise), so a
    # detail request can never surface a URL the crawl did not observe.
    site_url = await session.scalar(
        select(SiteUrl).where(
            SiteUrl.id == site_url_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.id.in_(_admitted_site_url_subquery(crawl_id)),
        )
    )
    if site_url is None:
        raise SiteHealthNotFoundError("Site URL not found")

    monitored_ids = await _monitored_site_url_ids(session, project_id=crawl.project_id)
    analyses = await _latest_analysis_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=[site_url_id]
    )
    analysis = analyses.get(site_url_id)
    tasks = await _latest_analyze_task_by_site_url(
        session, crawl_id=crawl_id, site_url_ids=[site_url_id]
    )
    pres_status, error_code = presentation_status_for(
        analysis=analysis,
        monitored=site_url_id in monitored_ids,
        latest_analyze_task=tasks.get(site_url_id),
    )

    facts: dict | None = None
    artifact_id: uuid.UUID | None = None
    html_bytes: int | None = None
    if analysis is not None:
        artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
        if artifact is not None:
            facts = artifact.normalized_facts
            artifact_id = artifact.id
            html_bytes = artifact.decoded_bytes

    issues: list[dict] = []
    evaluations: list[dict] = []
    link_references: list[dict] = []
    if analysis is not None:
        issue_rows = await session.execute(
            select(SiteIssue)
            .where(SiteIssue.analysis_id == analysis.id)
            .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
        )
        issues = [_issue_row(i, 1) for i in issue_rows.scalars().all()]

        # ALL persisted rule evaluations for this analysis, worst severity
        # first (then rule_id) so the current/failing rules lead the list. The
        # ordering is in SQL as well as in Python below: with an unordered
        # SELECT the _MAX_EVALUATIONS cap kept an arbitrary slice, so a capped
        # analysis could drop its critical rows and then "sort" what remained.
        eval_rows = await session.execute(
            select(SiteRuleEvaluation)
            .where(SiteRuleEvaluation.analysis_id == analysis.id)
            .order_by(
                case(
                    _SEVERITY_RANK,
                    value=SiteRuleEvaluation.severity,
                    else_=_UNRANKED_SEVERITY,
                ),
                SiteRuleEvaluation.rule_id.asc(),
            )
            .limit(_MAX_EVALUATIONS)
        )
        evaluations = sorted(
            (_evaluation_row(e) for e in eval_rows.scalars().all()),
            key=lambda r: (
                _SEVERITY_RANK.get(r["severity"], _UNRANKED_SEVERITY),
                r["rule_id"],
            ),
        )

        # Deduplicated link references for this analysis. Rows are already
        # deduped at write time by (artifact, kind, target_hash, fingerprint);
        # collapse defensively by (kind, target_hash) and order by target url.
        link_rows = await session.execute(
            select(SiteLinkReference)
            .where(SiteLinkReference.source_analysis_id == analysis.id)
            .order_by(
                SiteLinkReference.target_url.asc(),
                SiteLinkReference.id.asc(),
            )
        )
        seen_links: set[tuple[str, str]] = set()
        for link in link_rows.scalars().all():
            key = (link.kind, link.target_hash)
            if key in seen_links:
                continue
            seen_links.add(key)
            link_references.append(_link_reference_row(link))
            if len(link_references) >= _MAX_LINK_REFERENCES:
                break

    return {
        "site_url_id": site_url.id,
        "crawl_id": crawl_id,
        "normalized_url": site_url.normalized_url,
        "display_url": site_url.display_url or site_url.normalized_url,
        "title": site_url.latest_title or None,
        "analysis_status": pres_status,
        "error_code": error_code,
        "field_cwv_available": False,
        "page_type": analysis.page_type if analysis is not None else None,
        # Per-URL detail ONLY: the bounded classifier evidence powering the
        # "why this type?" disclosure (never projected onto list rows).
        "page_type_evidence": (
            analysis.page_type_evidence if analysis is not None else None
        ),
        "technical_score": (analysis.technical_score if analysis is not None else None),
        "aeo_score": analysis.aeo_score if analysis is not None else None,
        "overall_score": (analysis.overall_score if analysis is not None else None),
        "issue_count": len(issues) if analysis is not None else None,
        "last_audited": (_iso(analysis.finalized_at) if analysis is not None else None),
        "facts": _page_facts(facts),
        "delivery": _delivery_facts(facts, html_bytes=html_bytes),
        "issues": issues,
        "evaluations": evaluations,
        "link_references": link_references,
        "artifact_id": artifact_id,
        "extractor_version": crawl.extractor_version,
        "analyzer_version": crawl.analyzer_version,
        "rule_version": crawl.rule_catalog_version,
        "scoring_version": crawl.scoring_version,
    }
