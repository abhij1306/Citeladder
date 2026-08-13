"""Persisted Site Health page list and detail projections."""

from __future__ import annotations

import uuid

from sqlalchemy import case, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.site_health.inventory_scope import inherited_inventory_crawl_ids
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    _admitted_site_url_subquery,
    _clamp_limit,
    _load_crawl,
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
    _page_facts,
    presentation_status_for,
)
from app.domain.site_health.service.queries import (
    _issue_counts_by_site_url,
    _latest_analysis_by_site_url,
    _latest_analyze_task_by_site_url,
    _matching_page_summaries,
    _monitored_site_url_ids,
    _page_keyset_result,
    _pages_summary_row,
    _root_errors_for,
    _scan_window,
    _site_url_page_stmt,
)
from app.models.site_health import (
    SiteCrawl,
    SiteFetchArtifact,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
)


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
    page_kind: str | None = None,
) -> dict:
    """Analyzed-page summaries for a crawl, ordered ``(normalized_url, id)``.

    Accepts an exact presentation ``status`` or the combined ``error_or_blocked``
    filter, a ``monitored`` toggle, and a ``page_kind`` filter (v2 P1 —
    semantics in ``_page_kind_matches``). Filters are part of the cursor
    fingerprint. Rows are the crawl's project ``SiteUrl`` set, projected
    with the latest analysis and derived presentation status.
    """
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    limit = _clamp_limit(limit)
    project_id = crawl.project_id
    # B3 (SH-4): the root fetch's failed calls ride alongside the page rows so
    # a root failure is visible on the Errors & Blocked tab even though it
    # never created a page row of its own.
    root_errors = await _root_errors_for(session, crawl)
    scope = "pages"
    filters = {
        "crawl_id": str(crawl_id),
        "status": status or None,
        "monitored": (str(monitored) if monitored is not None else None),
        "page_kind": page_kind or None,
    }

    over_fetch = status is not None or page_kind is not None
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
        return {"items": [], "next_cursor": None, "root_errors": root_errors}
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

    def project_pages_row(
        row: SiteUrl,
        analysis: SitePageAnalysis | None,
        presentation_status: str,
        error_code: str | None,
    ) -> dict:
        return _pages_summary_row(
            row,
            analysis,
            presentation_status,
            error_code,
            crawl_id=crawl_id,
            current_observed_ids=current_observed_ids,
            inherited_crawl_by_url=inherited_crawl_by_url,
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
        project=project_pages_row,
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
    return {"items": items, "next_cursor": next_cursor, "root_errors": root_errors}


# =========================================================================
# Page detail (persisted facts/delivery/scores/issues/provenance; no network)
# =========================================================================
_DetailSections = tuple[
    dict | None, uuid.UUID | None, int | None, list[dict], list[dict], list[dict]
]


async def _detail_analysis_sections(
    session: AsyncSession, analysis: SitePageAnalysis | None
) -> _DetailSections:
    facts: dict | None = None
    artifact_id: uuid.UUID | None = None
    html_bytes: int | None = None
    issues: list[dict] = []
    evaluations: list[dict] = []
    link_references: list[dict] = []
    if analysis is None:
        return facts, artifact_id, html_bytes, issues, evaluations, link_references
    artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
    if artifact is not None:
        facts = artifact.normalized_facts
        artifact_id = artifact.id
        html_bytes = artifact.decoded_bytes
    issue_rows = await session.execute(
        select(SiteIssue)
        .where(SiteIssue.analysis_id == analysis.id)
        .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
    )
    issues = [_issue_row(issue, 1) for issue in issue_rows.scalars().all()]
    evaluation_rows = await session.execute(
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
        (_evaluation_row(row) for row in evaluation_rows.scalars().all()),
        key=lambda row: (
            _SEVERITY_RANK.get(row["severity"], _UNRANKED_SEVERITY),
            row["rule_id"],
        ),
    )
    link_rows = await session.execute(
        select(SiteLinkReference)
        .where(SiteLinkReference.source_analysis_id == analysis.id)
        .order_by(SiteLinkReference.target_url.asc(), SiteLinkReference.id.asc())
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
    return facts, artifact_id, html_bytes, issues, evaluations, link_references


def _detail_response(
    *,
    crawl: SiteCrawl,
    site_url: SiteUrl,
    analysis: SitePageAnalysis | None,
    presentation_status: str,
    error_code: str | None,
    facts: dict | None,
    artifact_id: uuid.UUID | None,
    html_bytes: int | None,
    issues: list[dict],
    evaluations: list[dict],
    link_references: list[dict],
) -> dict:
    return {
        "site_url_id": site_url.id,
        "crawl_id": crawl.id,
        "normalized_url": site_url.normalized_url,
        "display_url": site_url.display_url or site_url.normalized_url,
        "title": site_url.latest_title or None,
        "analysis_status": presentation_status,
        "error_code": error_code,
        "field_cwv_available": False,
        "page_kind": analysis.page_kind if analysis is not None else None,
        "page_kind_evidence": (
            analysis.page_kind_evidence if analysis is not None else None
        ),
        "technical_score": analysis.technical_score if analysis is not None else None,
        "aeo_score": analysis.aeo_score if analysis is not None else None,
        "overall_score": analysis.overall_score if analysis is not None else None,
        "issue_count": len(issues) if analysis is not None else None,
        "last_audited": _iso(analysis.finalized_at) if analysis is not None else None,
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

    (
        facts,
        artifact_id,
        html_bytes,
        issues,
        evaluations,
        link_references,
    ) = await _detail_analysis_sections(session, analysis)
    return _detail_response(
        crawl=crawl,
        site_url=site_url,
        analysis=analysis,
        presentation_status=pres_status,
        error_code=error_code,
        facts=facts,
        artifact_id=artifact_id,
        html_bytes=html_bytes,
        issues=issues,
        evaluations=evaluations,
        link_references=link_references,
    )
