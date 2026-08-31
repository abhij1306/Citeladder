"""The grouped issue catalog: groups, summary, detail, per-URL history.

Part of the read surface (with ``queries``), kept separate because grouping is
its own algorithm rather than another row projection: issues are aggregated by
``(crawl_id, rule_id)`` AFTER filtering, a group's identity is a deterministic UUID5
of that stable identity, and the summary counts DISTINCT RULE GROUPS rather
than occurrence rows so the tiles match what the list shows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    RULE_DIMENSIONS,
    SEVERITY_CRITICAL,
    SEVERITY_HIGH,
)
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_ADVISORY,
    FINDING_CLASS_DEFECT,
)
from app.domain.site_health.normalization import encode_keyset_cursor
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    _clamp_limit,
    _decode_url_keyset,
    _load_crawl,
)
from app.domain.site_health.service.issue_listing import (
    issue_items,
    issue_query_state,
    issue_summary_for_filters,
    page_issue_groups,
)
from app.domain.site_health.service.presentation import (
    _SEVERITY_ORDER,
    _SEVERITY_RANK,
    _iso,
    display_label_for,
)
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


# =========================================================================
# Grouped issues (mockup 710): group by (crawl_id, rule_id) after filters.
# =========================================================================
@dataclass
class _IssueGroup:
    rule_id: str
    dimension: str
    category: str
    severity: str
    finding_class: str
    group_id: uuid.UUID
    canonical_created_at: datetime
    affected_url_count: int
    description: str
    remediation: str
    analyzer_version: str
    rule_version: str


def issue_group_id(
    crawl_id: uuid.UUID,
    rule_id: str,
    finding_class: str = FINDING_CLASS_DEFECT,
) -> uuid.UUID:
    """Stable UUID for one ``(crawl, rule)`` issue group.

    An occurrence UUID cannot safely represent a group: issue timestamps can
    tie, and a later random UUID may sort before the previous representative.
    UUID5 gives filters, pagination, and later occurrences one immutable group
    identity without adding another table.
    """
    # Preserve the original defect identifier so shipped links remain stable.
    suffix = "" if finding_class == FINDING_CLASS_DEFECT else f":{finding_class}"
    return uuid.uuid5(crawl_id, f"site-issue-group:{rule_id}{suffix}")


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
    finding_class: str | None = FINDING_CLASS_DEFECT,
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
    if finding_class:
        clauses.append(SiteIssue.finding_class == finding_class)
    if query:
        clauses.append(SiteIssue.rule_id.ilike(f"%{query.strip()}%"))
    return clauses


async def _load_issue_groups(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    clauses: list,
    finding_class: str,
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
        # Persisted metadata is canonical within the selected finding class.
        canonical = await session.scalar(
            select(SiteIssue)
            .where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == rule_id,
                SiteIssue.finding_class == finding_class,
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
                finding_class=canonical.finding_class,
                group_id=issue_group_id(crawl_id, rule_id, finding_class),
                canonical_created_at=canonical.created_at,
                affected_url_count=int(row[4]),
                description=canonical.description or "",
                remediation=canonical.remediation or "",
                analyzer_version=canonical.analyzer_version,
                rule_version=canonical.rule_version,
            )
        )
    # Deterministic sort: (severity_rank, rule_id, group_id).
    groups.sort(
        key=lambda g: (
            _SEVERITY_RANK.get(g.severity, 99),
            g.rule_id,
            str(g.group_id),
        )
    )
    return groups


async def _issues_summary(
    session: AsyncSession, *, clauses: list, base_clauses: list
) -> dict:
    """Crawl-level canonical-group/severity/dimension + distinct affected counts.

    Counts are DISTINCT RULE GROUPS (the canonical issue cards the catalog
    renders), not per-page occurrence rows: 6 issue types across 10 pages is
    "6 issues", matching what the user sees in the list. Per-page multiplicity
    is carried by each group's ``affected_url_count`` instead.
    """
    class_rows = await session.execute(
        select(
            SiteIssue.finding_class,
            func.count(func.distinct(SiteIssue.rule_id)),
        )
        .where(*base_clauses)
        .group_by(SiteIssue.finding_class)
    )
    class_counts = {FINDING_CLASS_DEFECT: 0, FINDING_CLASS_ADVISORY: 0}
    for finding_class, count in class_rows.all():
        class_counts[finding_class] = int(count)
    defect_clauses = [*base_clauses, SiteIssue.finding_class == FINDING_CLASS_DEFECT]
    sev_rows = await session.execute(
        select(SiteIssue.severity, func.count(func.distinct(SiteIssue.rule_id)))
        .where(*defect_clauses)
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
    occurrences = (
        await session.scalar(select(func.count(SiteIssue.id)).where(*clauses)) or 0
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
        # Backward-compatible key with the corrected, explicit semantics.
        "issue_count": class_counts[FINDING_CLASS_DEFECT],
        "defect_issue_type_count": class_counts[FINDING_CLASS_DEFECT],
        "advisory_issue_type_count": class_counts[FINDING_CLASS_ADVISORY],
        "occurrence_count": int(occurrences),
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
    finding_class: str = FINDING_CLASS_DEFECT,
) -> dict:
    """Grouped issue catalog (``{items, next_cursor, summary}``) for mockup 710.

    Groups by ``(crawl_id, rule_id)`` after filters, keysets by
    ``(severity_rank, rule_id, group_id)`` and applies ``limit + 1`` so a
    rule group is never split across pages. ``id`` is the deterministic group
    UUID; ``title`` reads the CURRENT display label. The ``page_kind``
    filter (v2 P1) narrows to issues whose analysis classified as that type.
    """
    await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    limit = _clamp_limit(limit)
    filters, clauses = issue_query_state(
        crawl_id=crawl_id,
        query=query,
        severity=severity,
        category=category,
        dimension=dimension,
        rule=rule,
        site_url_id=site_url_id,
        page_kind=page_kind,
        finding_class=finding_class,
        filter_clause=_issue_filter_clause,
    )
    groups = await _load_issue_groups(
        session,
        crawl_id=crawl_id,
        clauses=clauses,
        finding_class=finding_class,
    )
    window, next_cursor = page_issue_groups(
        groups,
        limit=limit,
        cursor=cursor,
        filters=filters,
    )

    # Which PAGE TYPES each group actually affects. One aggregate for the
    # whole page of groups, not a query per row: the issue list is the screen
    # where "is this relevant to my product pages or my articles?" is the first
    # question, and a rule group can legitimately span several types.
    page_kinds_by_rule = await _page_kinds_for_rules(
        session,
        crawl_id=crawl_id,
        rule_ids=[g.rule_id for g in window],
        finding_class=finding_class,
    )
    items = issue_items(
        window,
        crawl_id=crawl_id,
        page_kinds_by_rule=page_kinds_by_rule,
    )
    # The summary powers the tiles + filter-chip counts, so it is computed
    # WITHOUT the severity/dimension chip filters (but WITH search/rule/url/
    # page-type narrowing): selecting the "High" chip must not zero out the
    # other chips' counts or shrink the headline tiles.
    summary = await issue_summary_for_filters(
        session,
        crawl_id=crawl_id,
        query=query,
        category=category,
        rule=rule,
        site_url_id=site_url_id,
        page_kind=page_kind,
        finding_class=finding_class,
        filter_clause=_issue_filter_clause,
        summary=_issues_summary,
    )
    return {"items": items, "next_cursor": next_cursor, "summary": summary}


async def _page_kinds_for_rules(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    rule_ids: list[str],
    finding_class: str,
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
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.rule_id.in_(rule_ids),
            SiteIssue.finding_class == finding_class,
        )
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
    group_id: uuid.UUID,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Return one stable issue group and its occurrence-backed evidence page."""
    await _load_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    resolved = await _resolve_issue_group(
        session,
        workspace_id=workspace_id,
        crawl_id=crawl_id,
        group_id=group_id,
    )
    if resolved is None:
        raise SiteHealthNotFoundError("Issue not found")
    rule_id, finding_class = resolved

    # Canonicalize to the stable representative row for the rule group (the
    # earliest issue by (created_at, id)) so a non-representative member id
    # resolves to the same group detail rather than a different projection.
    canonical = await session.scalar(
        select(SiteIssue)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.rule_id == rule_id,
            SiteIssue.finding_class == finding_class,
        )
        .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
        .limit(1)
    )
    if canonical is None:  # pragma: no cover - the rule lookup proves a row exists
        raise SiteHealthNotFoundError("Issue not found")

    limit = _clamp_limit(limit)
    scope = "issue_detail"
    filters = {
        "crawl_id": str(crawl_id),
        "group_id": str(group_id),
    }

    total = (
        await session.scalar(
            select(func.count(func.distinct(SiteIssue.site_url_id))).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == canonical.rule_id,
                SiteIssue.finding_class == finding_class,
            )
        )
        or 0
    )

    occurrence_count = (
        await session.scalar(
            select(func.count(SiteIssue.id)).where(
                SiteIssue.crawl_id == crawl_id,
                SiteIssue.rule_id == canonical.rule_id,
                SiteIssue.finding_class == finding_class,
            )
        )
        or 0
    )

    occurrence_rows, next_cursor = await _occurrence_page(
        session,
        crawl_id=crawl_id,
        rule_id=canonical.rule_id,
        finding_class=finding_class,
        limit=limit,
        cursor=cursor,
        scope=scope,
        filters=filters,
    )

    occurrences = [_occurrence_row(*row) for row in occurrence_rows]
    return {
        "group_id": group_id,
        "crawl_id": crawl_id,
        "rule_id": canonical.rule_id,
        "dimension": canonical.dimension,
        "category": canonical.category,
        "severity": canonical.severity,
        "finding_class": canonical.finding_class,
        "title": display_label_for(canonical.rule_id),
        "description": canonical.description or "",
        "remediation": canonical.remediation or "",
        "occurrences": occurrences,
        "occurrence_count": int(occurrence_count),
        "affected_url_count": int(total),
        "analyzer_version": canonical.analyzer_version,
        "rule_version": canonical.rule_version,
        "created_at": _iso(canonical.created_at),
        "next_cursor": next_cursor,
    }


async def _occurrence_page(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    rule_id: str,
    finding_class: str,
    limit: int,
    cursor: str | None,
    scope: str,
    filters: dict,
) -> tuple[list, str | None]:
    statement = _occurrence_statement(crawl_id, rule_id, finding_class)
    if cursor:
        cur_url, cur_id = _decode_url_keyset(cursor, scope=scope, filters=filters)
        statement = statement.where(
            tuple_(SiteUrl.normalized_url, SiteIssue.id) > (cur_url, cur_id)
        )
    rows = list((await session.execute(statement.limit(limit + 1))).all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    last = rows[-1]
    return rows, encode_keyset_cursor(
        scope=scope,
        filters=filters,
        sort_values=[last[2], str(last[0].id)],
    )


async def _resolve_issue_group(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    group_id: uuid.UUID,
) -> tuple[str, str] | None:
    """Resolve a derived group id against the authorized crawl's rule set."""
    candidates = await session.execute(
        select(SiteIssue.rule_id, SiteIssue.finding_class)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.workspace_id == workspace_id,
        )
        .distinct()
    )
    return next(
        (
            (rule_id, finding_class)
            for rule_id, finding_class in candidates.all()
            if issue_group_id(crawl_id, rule_id, finding_class) == group_id
        ),
        None,
    )


def _occurrence_statement(crawl_id: uuid.UUID, rule_id: str, finding_class: str):
    """Build the stable occurrence/evaluation query for one issue group."""
    return (
        select(
            SiteIssue,
            SiteUrl.id,
            SiteUrl.normalized_url,
            SiteUrl.display_url,
            SiteUrl.latest_title,
            SitePageAnalysis.page_kind,
            SiteRuleEvaluation.reason_code,
        )
        .join(SiteIssue, SiteIssue.site_url_id == SiteUrl.id)
        .join(SitePageAnalysis, SitePageAnalysis.id == SiteIssue.analysis_id)
        .join(SiteRuleEvaluation, SiteRuleEvaluation.id == SiteIssue.evaluation_id)
        .where(
            SiteIssue.crawl_id == crawl_id,
            SiteIssue.rule_id == rule_id,
            SiteIssue.finding_class == finding_class,
        )
        .order_by(SiteUrl.normalized_url.asc(), SiteIssue.id.asc())
    )


def _occurrence_row(
    issue: SiteIssue,
    site_url_id: uuid.UUID,
    normalized_url: str,
    display_url: str,
    page_title: str | None,
    page_kind: str | None,
    reason_code: str,
) -> dict:
    return {
        "occurrence_id": issue.id,
        "evaluation_id": issue.evaluation_id,
        "crawl_id": issue.crawl_id,
        "rule_id": issue.rule_id,
        "site_url_id": site_url_id,
        "normalized_url": normalized_url,
        "display_url": display_url or normalized_url,
        "title": page_title or None,
        "page_kind": page_kind,
        "dimension": issue.dimension,
        "category": issue.category,
        "severity": issue.severity,
        "finding_class": issue.finding_class,
        "issue_title": display_label_for(issue.rule_id, issue.evidence),
        "description": issue.description or "",
        "remediation": issue.remediation or "",
        "reason_code": reason_code,
        "evidence": issue.evidence or {},
        "analyzer_version": issue.analyzer_version,
        "rule_version": issue.rule_version,
        "created_at": _iso(issue.created_at),
    }


from app.domain.site_health.service.issue_history import (  # noqa: E402
    get_grouped_issue_history,
    get_issue_history,
)

__all__ = ["get_grouped_issue_history", "get_issue_history"]
