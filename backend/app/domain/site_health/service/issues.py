"""The grouped issue catalog: groups, summary, detail, per-URL history.

Part of the read surface (with ``queries``), kept separate because grouping is
its own algorithm rather than another row projection: issues are aggregated by
``(crawl_id, rule_id)`` AFTER filtering, a group's id is a deterministic UUID5
of that stable identity, and the summary counts DISTINCT RULE GROUPS rather
than occurrence rows so the tiles match what the list shows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health import (
    RULE_DIMENSIONS,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
)
from app.core.config.site_health_page_profiles import ISSUE_HISTORY_TIMELINE_MAX_CRAWLS
from app.domain.site_health.normalization import (
    CursorScopeError,
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.domain.site_health.service.common import (
    InvalidCursorError,
    SiteHealthNotFoundError,
    _admitted_site_url_subquery,
    _clamp_limit,
    _decode_created_id_keyset,
    _decode_url_keyset,
    _load_crawl,
)
from app.domain.site_health.service.presentation import (
    _SEVERITY_ORDER,
    _SEVERITY_RANK,
    _iso,
    display_label_for,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
)


# =========================================================================
# Grouped issues (mockup 710): group by (crawl_id, rule_id) after filters.
# =========================================================================
@dataclass
class _IssueGroup:
    rule_id: str
    dimension: str
    category: str
    severity: str
    canonical_id: uuid.UUID
    canonical_created_at: datetime
    affected_url_count: int
    remediation: str
    analyzer_version: str
    rule_version: str


def issue_group_id(crawl_id: uuid.UUID, rule_id: str) -> uuid.UUID:
    """Stable UUID for one ``(crawl, rule)`` issue group.

    An occurrence UUID cannot safely represent a group: issue timestamps can
    tie, and a later random UUID may sort before the previous representative.
    UUID5 gives filters, pagination, and later occurrences one immutable group
    identity without adding another table.
    """
    return uuid.uuid5(crawl_id, f"site-issue-group:{rule_id}")


def _issue_filter_clause(
    *,
    crawl_id: uuid.UUID,
    query: str | None,
    severity: str | None,
    category: str | None,
    dimension: str | None,
    rule: str | None,
    site_url_id: uuid.UUID | None,
    page_kind: str | None = None,
):
    clauses = [SiteIssue.crawl_id == crawl_id]
    if severity:
        if severity == SEVERITY_HIGH:
            # The catalog UI exposes a three-tier vocabulary (high/medium/low);
            # ``critical`` folds into ``high`` so the High filter matches the
            # rows its chip count includes.
            clauses.append(SiteIssue.severity.in_([SEVERITY_HIGH, SEVERITY_CRITICAL]))
        else:
            clauses.append(SiteIssue.severity == severity)
    if category:
        clauses.append(SiteIssue.category == category)
    if dimension:
        clauses.append(SiteIssue.dimension == dimension)
    if rule:
        clauses.append(SiteIssue.rule_id == rule)
    if site_url_id is not None:
        clauses.append(SiteIssue.site_url_id == site_url_id)
    if page_kind:
        # v2 P1: narrow to issues whose analysis classified as this page
        # type (ignore-unknown: an unrecognized value simply matches nothing).
        clauses.append(
            SiteIssue.analysis_id.in_(
                select(SitePageAnalysis.id).where(
                    SitePageAnalysis.page_kind == page_kind
                )
            )
        )
    if query:
        clauses.append(SiteIssue.rule_id.ilike(f"%{query.strip()}%"))
    return clauses


async def _load_issue_groups(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    clauses: list,
) -> list[_IssueGroup]:
    """Aggregate issues into per-rule groups (canonical id, distinct affected).

    Group aggregation happens in the query BEFORE keyset/limit: for each
    ``rule_id`` we use its deterministic group UUID and count the DISTINCT
    affected ``site_url_id``. The earliest occurrence still supplies persisted
    metadata and the group's first-seen timestamp.
    """
    rows = await session.execute(
        select(
            SiteIssue.rule_id,
            func.min(SiteIssue.dimension),
            func.min(SiteIssue.category),
            func.min(SiteIssue.severity),
            func.count(func.distinct(SiteIssue.site_url_id)),
            func.min(SiteIssue.created_at),
            func.min(SiteIssue.remediation),
            func.min(SiteIssue.analyzer_version),
            func.min(SiteIssue.rule_version),
        )
        .where(*clauses)
        .group_by(SiteIssue.rule_id)
    )
    groups: list[_IssueGroup] = []
    for row in rows.all():
        rule_id = row[0]
        # Resolve the earliest occurrence UNFILTERED for persisted metadata.
        canonical = await session.scalar(
            select(SiteIssue)
            .where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == rule_id,
            )
            .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
            .limit(1)
        )
        if canonical is None:
            continue
        groups.append(
            _IssueGroup(
                rule_id=rule_id,
                dimension=canonical.dimension,
                category=canonical.category,
                severity=canonical.severity,
                canonical_id=issue_group_id(crawl_id, rule_id),
                canonical_created_at=canonical.created_at,
                affected_url_count=int(row[4]),
                remediation=canonical.remediation or "",
                analyzer_version=canonical.analyzer_version,
                rule_version=canonical.rule_version,
            )
        )
    # Deterministic sort: (severity_rank, rule_id, canonical_id).
    groups.sort(
        key=lambda g: (
            _SEVERITY_RANK.get(g.severity, 99),
            g.rule_id,
            str(g.canonical_id),
        )
    )
    return groups


async def _issues_summary(session: AsyncSession, *, clauses: list) -> dict:
    """Crawl-level canonical-group/severity/dimension + distinct affected counts.

    Counts are DISTINCT RULE GROUPS (the canonical issue cards the catalog
    renders), not per-page occurrence rows: 6 issue types across 10 pages is
    "6 issues", matching what the user sees in the list. Per-page multiplicity
    is carried by each group's ``affected_url_count`` instead.
    """
    total = (
        await session.scalar(
            select(func.count(func.distinct(SiteIssue.rule_id)))
            .select_from(SiteIssue)
            .where(*clauses)
        )
        or 0
    )
    sev_rows = await session.execute(
        select(SiteIssue.severity, func.count(func.distinct(SiteIssue.rule_id)))
        .where(*clauses)
        .group_by(SiteIssue.severity)
    )
    severity_counts = {name: 0 for name in _SEVERITY_ORDER}
    for name, count in sev_rows.all():
        # Three-tier UI vocabulary (high/medium/low): ``critical`` folds into
        # ``high`` so the High chip count matches the High filter's row set
        # (which already matches high OR critical). ``critical`` stays 0.
        key = SEVERITY_HIGH if name == SEVERITY_CRITICAL else name
        severity_counts[key] = severity_counts.get(key, 0) + int(count)
    dim_rows = await session.execute(
        select(SiteIssue.dimension, func.count(func.distinct(SiteIssue.rule_id)))
        .where(*clauses)
        .group_by(SiteIssue.dimension)
    )
    dimension_counts = {name: 0 for name in sorted(RULE_DIMENSIONS)}
    for name, count in dim_rows.all():
        dimension_counts[name] = int(count)
    affected = (
        await session.scalar(
            select(func.count(func.distinct(SiteIssue.site_url_id))).where(*clauses)
        )
        or 0
    )
    # Distinct affected URLs that are also active monitored members.
    monitored_affected = (
        await session.scalar(
            select(func.count(func.distinct(SiteIssue.site_url_id)))
            .select_from(SiteIssue)
            .join(
                MonitoredSiteUrl,
                and_(
                    MonitoredSiteUrl.site_url_id == SiteIssue.site_url_id,
                    MonitoredSiteUrl.active.is_(True),
                ),
            )
            .where(*clauses)
        )
        or 0
    )
    return {
        "issue_count": int(total),
        "severity_counts": severity_counts,
        "dimension_counts": dimension_counts,
        "affected_url_count": int(affected),
        "monitored_affected_url_count": int(monitored_affected),
    }


async def get_issues(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
    query: str | None = None,
    severity: str | None = None,
    category: str | None = None,
    dimension: str | None = None,
    rule: str | None = None,
    site_url_id: uuid.UUID | None = None,
    page_kind: str | None = None,
) -> dict:
    """Grouped issue catalog (``{items, next_cursor, summary}``) for mockup 710.

    Groups by ``(crawl_id, rule_id)`` after filters, keysets by
    ``(severity_rank, rule_id, canonical_id)`` and applies ``limit + 1`` so a
    rule group is never split across pages. ``id`` is the deterministic group
    UUID; ``title`` reads the CURRENT display label. The ``page_kind``
    filter (v2 P1) narrows to issues whose analysis classified as that type.
    """
    await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    limit = _clamp_limit(limit)
    scope = "issues"
    filters = {
        "crawl_id": str(crawl_id),
        "query": (query or "").strip() or None,
        "severity": severity or None,
        "category": category or None,
        "dimension": dimension or None,
        "rule": rule or None,
        "site_url_id": str(site_url_id) if site_url_id else None,
        "page_kind": page_kind or None,
    }
    clauses = _issue_filter_clause(
        crawl_id=crawl_id,
        query=query,
        severity=severity,
        category=category,
        dimension=dimension,
        rule=rule,
        site_url_id=site_url_id,
        page_kind=page_kind,
    )
    groups = await _load_issue_groups(session, crawl_id=crawl_id, clauses=clauses)

    start = 0
    if cursor:
        try:
            rank_raw, rule_raw, id_raw = decode_keyset_cursor(
                cursor, scope=scope, filters=filters
            )
            cursor_key = (int(rank_raw), rule_raw, id_raw)
        except CursorScopeError as exc:
            raise InvalidCursorError(str(exc)) from exc
        except ValueError as exc:
            raise InvalidCursorError(str(exc)) from exc
        for idx, g in enumerate(groups):
            gkey = (
                _SEVERITY_RANK.get(g.severity, 99),
                g.rule_id,
                str(g.canonical_id),
            )
            if gkey > cursor_key:
                start = idx
                break
        else:
            start = len(groups)

    window = groups[start : start + limit + 1]
    next_cursor: str | None = None
    if len(window) > limit:
        window = window[:limit]
        last = window[-1]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[
                _SEVERITY_RANK.get(last.severity, 99),
                last.rule_id,
                str(last.canonical_id),
            ],
        )

    # Which PAGE TYPES each group actually affects. One aggregate for the
    # whole page of groups, not a query per row: the issue list is the screen
    # where "is this relevant to my product pages or my articles?" is the first
    # question, and a rule group can legitimately span several types.
    page_kinds_by_rule = await _page_kinds_for_rules(
        session, crawl_id=crawl_id, rule_ids=[g.rule_id for g in window]
    )
    items = [
        {
            "id": g.canonical_id,
            "crawl_id": crawl_id,
            "rule_id": g.rule_id,
            "page_kinds": page_kinds_by_rule.get(g.rule_id, []),
            "dimension": g.dimension,
            "category": g.category,
            "severity": g.severity,
            "title": display_label_for(g.rule_id),
            "remediation": g.remediation,
            "affected_url_count": g.affected_url_count,
            "analyzer_version": g.analyzer_version,
            "rule_version": g.rule_version,
            "created_at": _iso(g.canonical_created_at),
        }
        for g in window
    ]
    # The summary powers the tiles + filter-chip counts, so it is computed
    # WITHOUT the severity/dimension chip filters (but WITH search/rule/url/
    # page-type narrowing): selecting the "High" chip must not zero out the
    # other chips' counts or shrink the headline tiles.
    summary_clauses = _issue_filter_clause(
        crawl_id=crawl_id,
        query=query,
        severity=None,
        category=category,
        dimension=None,
        rule=rule,
        site_url_id=site_url_id,
        page_kind=page_kind,
    )
    summary = await _issues_summary(session, clauses=summary_clauses)
    return {"items": items, "next_cursor": next_cursor, "summary": summary}


async def _page_kinds_for_rules(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    rule_ids: list[str],
) -> dict[str, list[str]]:
    """Distinct page types affected by each of ``rule_ids`` in this crawl.

    Scoped to the rule ids actually on the requested page so the cost tracks
    the window, not the whole catalog. Unclassified analyses contribute no
    type rather than an "unknown" bucket.
    """
    if not rule_ids:
        return {}
    rows = await session.execute(
        select(
            SiteIssue.rule_id,
            func.array_agg(func.distinct(SitePageAnalysis.page_kind)),
        )
        .join(SitePageAnalysis, SitePageAnalysis.id == SiteIssue.analysis_id)
        .where(SiteIssue.crawl_id == crawl_id, SiteIssue.rule_id.in_(rule_ids))
        .group_by(SiteIssue.rule_id)
    )
    return {
        rule_id: sorted(str(t) for t in (types or []) if t)
        for rule_id, types in rows.all()
    }


async def issue_group_page_kinds(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
) -> dict[str, list[str]]:
    """Map each grouped issue's ``rule_id`` to the sorted distinct page types
    of its affected analyses (v2 P1 export column).

    Read-only projection of persisted rows (invariant 7), workspace-scoped
    like every read here (invariant 5). Used by the issues export only — the
    grouped-issue JSON DTO deliberately stays unchanged (a group can span
    page types, so it has no single type badge).
    """
    await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    rows = await session.execute(
        select(
            SiteIssue.rule_id,
            func.array_agg(func.distinct(SitePageAnalysis.page_kind)),
        )
        .join(SitePageAnalysis, SitePageAnalysis.id == SiteIssue.analysis_id)
        .where(SiteIssue.crawl_id == crawl_id)
        .group_by(SiteIssue.rule_id)
    )
    return {
        rule_id: sorted(str(t) for t in (types or []) if t)
        for rule_id, types in rows.all()
    }


async def get_issue_detail(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    canonical_id: uuid.UUID,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Resolve a group/member UUID then return its rule group + affected URLs.

    Affected URLs are ordered ``(normalized_url, site_url_id)`` and keyset-
    limited for navigation. Title reads the current display label; remediation/
    evidence/versions come from the persisted canonical row.
    """
    await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    rule_id = await _resolve_issue_rule_id(
        session,
        workspace_id=workspace_id,
        crawl_id=crawl_id,
        canonical_id=canonical_id,
    )
    if rule_id is None:
        raise SiteHealthNotFoundError("Issue not found")

    # Canonicalize to the stable representative row for the rule group (the
    # earliest issue by (created_at, id)) so a non-representative member id
    # resolves to the same group detail rather than a different projection.
    canonical = await session.scalar(
        select(SiteIssue)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.rule_id == rule_id,
        )
        .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
        .limit(1)
    )
    if canonical is None:  # pragma: no cover - the rule lookup proves a row exists
        raise SiteHealthNotFoundError("Issue not found")

    group_id = issue_group_id(crawl_id, rule_id)

    limit = _clamp_limit(limit)
    scope = "issue_detail"
    # Fingerprint on the stable group id (not a requested occurrence id) so all
    # member links share the same page identity.
    filters = {
        "crawl_id": str(crawl_id),
        "canonical_id": str(group_id),
    }

    total = (
        await session.scalar(
            select(func.count(func.distinct(SiteIssue.site_url_id))).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == canonical.rule_id,
            )
        )
        or 0
    )

    aff_stmt = _affected_url_statement(crawl_id, canonical.rule_id)
    if cursor:
        cur_url, cur_id = _decode_url_keyset(cursor, scope=scope, filters=filters)
        aff_stmt = aff_stmt.where(
            tuple_(SiteUrl.normalized_url, SiteUrl.id) > (cur_url, cur_id)
        )
    aff_rows = list((await session.execute(aff_stmt.limit(limit + 1))).all())

    next_cursor: str | None = None
    if len(aff_rows) > limit:
        aff_rows = aff_rows[:limit]
        last = aff_rows[-1]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[last[1], str(last[0])],
        )

    page_kind_by_url = await _affected_page_kinds(
        session,
        crawl_id=crawl_id,
        rule_id=canonical.rule_id,
        affected_ids=[row[0] for row in aff_rows],
    )
    affected_urls = [
        {
            "site_url_id": row[0],
            "normalized_url": row[1],
            "display_url": row[2] or row[1],
            "title": row[3] or None,
            "page_kind": page_kind_by_url.get(row[0]),
        }
        for row in aff_rows
    ]
    return {
        "id": group_id,
        "crawl_id": crawl_id,
        "rule_id": canonical.rule_id,
        "dimension": canonical.dimension,
        "category": canonical.category,
        "severity": canonical.severity,
        "title": display_label_for(canonical.rule_id),
        "remediation": canonical.remediation or "",
        "evidence": canonical.evidence or {},
        "affected_urls": affected_urls,
        "affected_url_count": int(total),
        "analyzer_version": canonical.analyzer_version,
        "rule_version": canonical.rule_version,
        "created_at": _iso(canonical.created_at),
        "next_cursor": next_cursor,
    }


async def _resolve_issue_rule_id(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    canonical_id: uuid.UUID,
) -> str | None:
    """Resolve either an occurrence id or the derived stable group id."""
    row = await session.scalar(
        select(SiteIssue).where(
            SiteIssue.id == canonical_id,
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.workspace_id == workspace_id,
        )
    )
    if row is not None:
        return row.rule_id
    # Group UUIDs are derived rather than stored. Resolve against the crawl's
    # bounded distinct rule set while retaining support for old occurrence links.
    rule_ids = await session.scalars(
        select(SiteIssue.rule_id)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.workspace_id == workspace_id,
        )
        .distinct()
    )
    return next(
        (
            candidate
            for candidate in rule_ids
            if issue_group_id(crawl_id, candidate) == canonical_id
        ),
        None,
    )


def _affected_url_statement(crawl_id: uuid.UUID, rule_id: str):
    """Build the stable, distinct affected-URL query for one issue group."""
    # Each affected URL's latest issue analysis supplies the optional page-kind
    # badge in ``_affected_page_kinds`` below.
    return (
        select(
            SiteUrl.id,
            SiteUrl.normalized_url,
            SiteUrl.display_url,
            SiteUrl.latest_title,
        )
        .join(SiteIssue, SiteIssue.site_url_id == SiteUrl.id)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.rule_id == rule_id,
        )
        .distinct()
        .order_by(SiteUrl.normalized_url.asc(), SiteUrl.id.asc())
    )


async def _affected_page_kinds(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    rule_id: str,
    affected_ids: list[uuid.UUID],
) -> dict[uuid.UUID, str]:
    """Return the newest classification for each affected URL."""
    page_kind_by_url: dict[uuid.UUID, str] = {}
    if affected_ids:
        type_rows = await session.execute(
            select(SiteIssue.site_url_id, SitePageAnalysis.page_kind)
            .join(SitePageAnalysis, SitePageAnalysis.id == SiteIssue.analysis_id)
            .where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == rule_id,
                SiteIssue.site_url_id.in_(affected_ids),
            )
            .order_by(SiteIssue.created_at.desc(), SiteIssue.id.desc())
        )
        for site_url_id_value, page_kind_value in type_rows.all():
            page_kind_by_url.setdefault(site_url_id_value, page_kind_value)

    return page_kind_by_url


async def get_issue_history(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
) -> dict:
    """Per-URL issue history ordered ``(created_at DESC, id DESC)``.

    Uses the ``ix_site_issues_url_created`` index, bounded to the URL's project
    AND to crawls at or before the selected crawl in the project chronology, so
    an older crawl's detail never shows issues from a later crawl.
    """
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    # The URL must be admitted to the selected crawl (404 otherwise), matching
    # the page-detail scope; history then spans that crawl and prior ones.
    site_url = await session.scalar(
        select(SiteUrl).where(
            SiteUrl.id == site_url_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.id.in_(_admitted_site_url_subquery(crawl_id)),
        )
    )
    if site_url is None:
        raise SiteHealthNotFoundError("Site URL not found")

    limit = _clamp_limit(limit)
    scope = "issue_history"
    filters = {
        "site_url_id": str(site_url_id),
        "project_id": str(crawl.project_id),
        "crawl_id": str(crawl_id),
    }

    # Bound history to crawls at or before the SELECTED crawl in the project's
    # chronology (by (created_at, id)) so viewing an older crawl never shows
    # issues from a later one. Issue rows are immutable, so the crawl's
    # position is stable.
    prior_or_same_crawls = (
        select(SiteCrawl.id)
        .where(
            SiteCrawl.project_id == crawl.project_id,
            or_(
                SiteCrawl.created_at < crawl.created_at,
                and_(
                    SiteCrawl.created_at == crawl.created_at,
                    SiteCrawl.id <= crawl.id,
                ),
            ),
        )
        .scalar_subquery()
    )
    stmt = select(SiteIssue).where(
        SiteIssue.site_url_id == site_url_id,
        SiteIssue.project_id == crawl.project_id,
        SiteIssue.crawl_id.in_(prior_or_same_crawls),
    )
    if cursor:
        cur_created, cur_id = _decode_created_id_keyset(
            cursor, scope=scope, filters=filters
        )
        stmt = stmt.where(
            or_(
                SiteIssue.created_at < cur_created,
                and_(
                    SiteIssue.created_at == cur_created,
                    SiteIssue.id < cur_id,
                ),
            )
        )
    stmt = stmt.order_by(SiteIssue.created_at.desc(), SiteIssue.id.desc()).limit(
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
    items = [
        {
            "id": i.id,
            "crawl_id": i.crawl_id,
            "rule_id": i.rule_id,
            "dimension": i.dimension,
            "category": i.category,
            "severity": i.severity,
            # Per-URL history rows are ONE occurrence each, so the variant
            # title applies (grouped/catalog rows above stay neutral — a group
            # can span both directions of the same rule).
            "title": display_label_for(i.rule_id, i.evidence),
            "remediation": i.remediation or "",
            "analyzer_version": i.analyzer_version,
            "rule_version": i.rule_version,
            "created_at": _iso(i.created_at),
        }
        for i in rows
    ]
    return {"items": items, "next_cursor": next_cursor}


@dataclass(frozen=True)
class _HistoryObservation:
    crawl_id: uuid.UUID
    observed_at: datetime
    rule_id: str
    dimension: str
    category: str
    severity: str
    outcome: str
    analyzer_version: str
    rule_version: str
    remediation: str


def _group_issue_history(
    observations: list[_HistoryObservation],
) -> tuple[list[dict], dict[str, object]]:
    """Collapse persisted evaluation evidence into rule-grouped history.

    Only evaluations from the selected URL's latest analysis in each crawl are
    supplied.  A pass/not-applicable after a prior fail is therefore a real,
    persisted resolution — never an inferred repair.
    """
    by_rule: dict[str, list[_HistoryObservation]] = {}
    for observation in observations:
        by_rule.setdefault(observation.rule_id, []).append(observation)

    groups: list[dict] = []
    transition_counts = {"new": 0, "continuing": 0, "resolved": 0}
    for rule_id, rows in by_rule.items():
        rows.sort(key=lambda row: (row.observed_at, str(row.crawl_id)))
        failures = [row for row in rows if row.outcome == "fail"]
        if not failures:
            continue
        timeline: list[dict] = []
        previous_failed = False
        for row in rows:
            failed = row.outcome == "fail"
            if failed:
                transition = "continuing" if previous_failed else "new"
            elif previous_failed:
                transition = "resolved"
            else:
                transition = "unchanged"
            timeline.append(
                {
                    "crawl_id": row.crawl_id,
                    "observed_at": _iso(row.observed_at),
                    "outcome": row.outcome,
                    "transition": transition,
                }
            )
            previous_failed = failed
        latest = rows[-1]
        current_transition = timeline[-1]["transition"]
        if current_transition in transition_counts:
            transition_counts[current_transition] += 1
        last_failure = failures[-1]
        groups.append(
            {
                "rule_id": rule_id,
                "dimension": last_failure.dimension,
                "category": last_failure.category,
                "severity": last_failure.severity,
                "title": display_label_for(rule_id),
                "remediation": last_failure.remediation,
                "current_state": "open" if latest.outcome == "fail" else "resolved",
                "current_transition": current_transition,
                "occurrence_count": len(failures),
                "first_seen_at": _iso(failures[0].observed_at),
                "last_seen_at": _iso(last_failure.observed_at),
                "analyzer_version": last_failure.analyzer_version,
                "rule_version": last_failure.rule_version,
                "timeline": timeline[-ISSUE_HISTORY_TIMELINE_MAX_CRAWLS:],
            }
        )
    groups.sort(
        key=lambda row: (str(row["last_seen_at"]), str(row["rule_id"])), reverse=True
    )
    summary: dict[str, object] = {
        "has_previous_crawl": len({row.crawl_id for row in observations}) > 1,
        **transition_counts,
    }
    return groups, summary


async def get_grouped_issue_history(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
) -> dict:
    """Rule-grouped issue history derived solely from persisted evaluations.

    This is opt-in while the existing frontend's strict legacy occurrence DTO
    remains deployed.  The endpoint's data is nevertheless the replacement
    projection: one row per rule with state transitions and a collapsed crawl
    timeline, not repeated issue rows.
    """
    crawl = await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    site_url = await session.scalar(
        select(SiteUrl).where(
            SiteUrl.id == site_url_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.id.in_(_admitted_site_url_subquery(crawl_id)),
        )
    )
    if site_url is None:
        raise SiteHealthNotFoundError("Site URL not found")

    prior_or_same = or_(
        SiteCrawl.created_at < crawl.created_at,
        and_(SiteCrawl.created_at == crawl.created_at, SiteCrawl.id <= crawl.id),
    )
    rows = list(
        (
            await session.execute(
                select(SiteCrawl, SitePageAnalysis, SiteRuleEvaluation)
                .join(SitePageAnalysis, SitePageAnalysis.crawl_id == SiteCrawl.id)
                .join(
                    SiteRuleEvaluation,
                    SiteRuleEvaluation.analysis_id == SitePageAnalysis.id,
                )
                .where(
                    SiteCrawl.project_id == crawl.project_id,
                    SiteCrawl.workspace_id == workspace_id,
                    prior_or_same,
                    SitePageAnalysis.site_url_id == site_url_id,
                )
                .order_by(
                    SiteCrawl.created_at.asc(),
                    SiteCrawl.id.asc(),
                    SitePageAnalysis.created_at.asc(),
                    SitePageAnalysis.id.asc(),
                )
            )
        ).all()
    )
    # A rerun can create more than one analysis for a URL/crawl.  Only the
    # latest complete evaluation set represents that crawl in the timeline.
    latest_analysis: dict[uuid.UUID, uuid.UUID] = {}
    for crawl_row, analysis, _evaluation in rows:
        latest_analysis[crawl_row.id] = analysis.id
    issue_rows = list(
        (
            await session.scalars(
                select(SiteIssue).where(
                    SiteIssue.project_id == crawl.project_id,
                    SiteIssue.site_url_id == site_url_id,
                    SiteIssue.crawl_id.in_(latest_analysis),
                )
            )
        ).all()
    )
    remediation_by_evaluation = {
        issue.evaluation_id: issue.remediation or "" for issue in issue_rows
    }
    observations = [
        _HistoryObservation(
            crawl_id=crawl_row.id,
            observed_at=crawl_row.created_at,
            rule_id=evaluation.rule_id,
            dimension=evaluation.dimension,
            category=evaluation.category,
            severity=evaluation.severity,
            outcome=evaluation.outcome,
            analyzer_version=evaluation.analyzer_version,
            rule_version=evaluation.rule_version,
            remediation=remediation_by_evaluation.get(evaluation.id, ""),
        )
        for crawl_row, analysis, evaluation in rows
        if latest_analysis.get(crawl_row.id) == analysis.id
    ]
    groups, since_previous_crawl = _group_issue_history(observations)
    filters = {
        "site_url_id": str(site_url_id),
        "project_id": str(crawl.project_id),
        "crawl_id": str(crawl_id),
        "view": "grouped",
    }
    scope = "issue_history_grouped"
    after_rule_id = ""
    if cursor:
        try:
            values = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        except ValueError as exc:
            raise InvalidCursorError("invalid grouped history cursor") from exc
        if len(values) != 1:
            raise InvalidCursorError("invalid grouped history cursor")
        after_rule_id = values[0]
    # Sort newest-first, but retain a stable rule-id cursor only within the
    # materialized bounded group projection.  It prevents duplicate pages
    # without pretending a grouped value has an immutable row id.
    if after_rule_id:
        start = next(
            (
                index + 1
                for index, item in enumerate(groups)
                if item["rule_id"] == after_rule_id
            ),
            len(groups),
        )
        groups = groups[start:]
    limit = _clamp_limit(limit)
    window = groups[: limit + 1]
    next_cursor = None
    if len(window) > limit:
        window = window[:limit]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[window[-1]["rule_id"]],
        )
    return {
        "items": window,
        "next_cursor": next_cursor,
        "since_previous_crawl": since_previous_crawl,
    }
