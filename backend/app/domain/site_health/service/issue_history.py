"""Per-URL and grouped issue history read projections."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_page_profiles import ISSUE_HISTORY_TIMELINE_MAX_CRAWLS
from app.domain.site_health.normalization import (
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.domain.site_health.service.common import (
    InvalidCursorError,
    SiteHealthNotFoundError,
    _admitted_site_url_subquery,
    _clamp_limit,
    _decode_created_id_keyset,
    _load_crawl,
)
from app.domain.site_health.service.presentation import _iso, display_label_for
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl


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
            "finding_class": i.finding_class,
            # Per-URL history rows are ONE occurrence each, so the variant
            # title applies (grouped/catalog rows above stay neutral — a group
            # can span both directions of the same rule).
            "title": display_label_for(i.rule_id, i.evidence),
            "description": i.description or "",
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
    finding_class: str
    outcome: str
    analyzer_version: str
    rule_version: str
    description: str
    remediation: str


def _group_issue_history(
    observations: list[_HistoryObservation],
) -> tuple[list[dict], dict[str, object]]:
    """Collapse persisted evaluation evidence into rule-grouped history.

    Only evaluations from the selected URL's latest analysis in each crawl are
    supplied.  A pass/not-applicable after a prior fail is therefore a real,
    persisted resolution — never an inferred repair.
    """
    by_rule = _observations_by_rule(observations)
    groups = [
        group
        for rule_id, rows in by_rule.items()
        if (group := _rule_history_group(rule_id, rows)) is not None
    ]
    transition_counts = {"new": 0, "continuing": 0, "resolved": 0}
    for group in groups:
        current_transition = str(group["current_transition"])
        if current_transition in transition_counts:
            transition_counts[current_transition] += 1
    groups.sort(
        key=lambda row: (str(row["last_seen_at"]), str(row["rule_id"])), reverse=True
    )
    summary: dict[str, object] = {
        "has_previous_crawl": len({row.crawl_id for row in observations}) > 1,
        **transition_counts,
    }
    return groups, summary


def _observations_by_rule(
    observations: list[_HistoryObservation],
) -> dict[str, list[_HistoryObservation]]:
    by_rule: dict[str, list[_HistoryObservation]] = {}
    for observation in observations:
        by_rule.setdefault(observation.rule_id, []).append(observation)
    return by_rule


def _history_timeline(rows: list[_HistoryObservation]) -> list[dict]:
    timeline: list[dict] = []
    previous_failed = False
    for row in rows:
        failed = row.outcome == "fail"
        transition = "continuing" if failed and previous_failed else "new"
        if not failed:
            transition = "resolved" if previous_failed else "unchanged"
        timeline.append(
            {
                "crawl_id": row.crawl_id,
                "observed_at": _iso(row.observed_at),
                "outcome": row.outcome,
                "transition": transition,
            }
        )
        previous_failed = failed
    return timeline


def _rule_history_group(rule_id: str, rows: list[_HistoryObservation]) -> dict | None:
    rows.sort(key=lambda row: (row.observed_at, str(row.crawl_id)))
    failures = [row for row in rows if row.outcome == "fail"]
    if not failures:
        return None
    timeline = _history_timeline(rows)
    latest = rows[-1]
    last_failure = failures[-1]
    return {
        "rule_id": rule_id,
        "dimension": last_failure.dimension,
        "category": last_failure.category,
        "severity": last_failure.severity,
        "finding_class": last_failure.finding_class,
        "title": display_label_for(rule_id),
        "description": last_failure.description,
        "remediation": last_failure.remediation,
        "current_state": "open" if latest.outcome == "fail" else "resolved",
        "current_transition": timeline[-1]["transition"],
        "occurrence_count": len(failures),
        "first_seen_at": _iso(failures[0].observed_at),
        "last_seen_at": _iso(last_failure.observed_at),
        "analyzer_version": last_failure.analyzer_version,
        "rule_version": last_failure.rule_version,
        "timeline": timeline[-ISSUE_HISTORY_TIMELINE_MAX_CRAWLS:],
    }


async def _history_observations(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    workspace_id: uuid.UUID,
    site_url_id: uuid.UUID,
) -> list[_HistoryObservation]:
    prior_or_same = or_(
        SiteCrawl.created_at < crawl.created_at,
        and_(SiteCrawl.created_at == crawl.created_at, SiteCrawl.id <= crawl.id),
    )
    crawl_ids = list(
        (
            await session.scalars(
                select(SiteCrawl.id)
                .where(
                    SiteCrawl.project_id == crawl.project_id,
                    SiteCrawl.workspace_id == workspace_id,
                    prior_or_same,
                )
                .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
                .limit(ISSUE_HISTORY_TIMELINE_MAX_CRAWLS)
            )
        ).all()
    )
    if not crawl_ids:
        return []
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
                    SiteCrawl.id.in_(crawl_ids),
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
    latest_analysis = {crawl_row.id: analysis.id for crawl_row, analysis, _ in rows}
    issue_rows = list(
        (
            await session.scalars(
                select(SiteIssue).where(
                    SiteIssue.project_id == crawl.project_id,
                    SiteIssue.site_url_id == site_url_id,
                    SiteIssue.crawl_id.in_(crawl_ids),
                    SiteIssue.crawl_id.in_(latest_analysis),
                )
            )
        ).all()
    )
    copy_by_evaluation = {
        issue.evaluation_id: (issue.description or "", issue.remediation or "")
        for issue in issue_rows
    }
    return [
        _HistoryObservation(
            crawl_id=crawl_row.id,
            observed_at=crawl_row.created_at,
            rule_id=evaluation.rule_id,
            dimension=evaluation.dimension,
            category=evaluation.category,
            severity=evaluation.severity,
            finding_class=evaluation.finding_class,
            outcome=evaluation.outcome,
            analyzer_version=evaluation.analyzer_version,
            rule_version=evaluation.rule_version,
            description=copy_by_evaluation.get(evaluation.id, ("", ""))[0],
            remediation=copy_by_evaluation.get(evaluation.id, ("", ""))[1],
        )
        for crawl_row, analysis, evaluation in rows
        if latest_analysis.get(crawl_row.id) == analysis.id
    ]


def _grouped_history_page(
    groups: list[dict],
    *,
    crawl: SiteCrawl,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    limit: int | None,
    cursor: str | None,
) -> dict:
    filters = {
        "site_url_id": str(site_url_id),
        "project_id": str(crawl.project_id),
        "crawl_id": str(crawl_id),
        "view": "grouped",
    }
    scope = "issue_history_grouped"
    if cursor:
        try:
            values = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        except ValueError as exc:
            raise InvalidCursorError("invalid grouped history cursor") from exc
        if len(values) != 1:
            raise InvalidCursorError("invalid grouped history cursor")
        start = next(
            (
                index + 1
                for index, item in enumerate(groups)
                if item["rule_id"] == values[0]
            ),
            len(groups),
        )
        groups = groups[start:]
    page_limit = _clamp_limit(limit)
    window = groups[: page_limit + 1]
    next_cursor = None
    if len(window) > page_limit:
        window = window[:page_limit]
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[window[-1]["rule_id"]],
        )
    return {"items": window, "next_cursor": next_cursor}


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

    observations = await _history_observations(
        session,
        crawl=crawl,
        workspace_id=workspace_id,
        site_url_id=site_url_id,
    )
    groups, since_previous_crawl = _group_issue_history(observations)
    return {
        **_grouped_history_page(
            groups,
            crawl=crawl,
            crawl_id=crawl_id,
            site_url_id=site_url_id,
            limit=limit,
            cursor=cursor,
        ),
        "since_previous_crawl": since_previous_crawl,
    }
