"""Frozen issue rollups and card counts for one Site Health snapshot."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import AEO_READINESS_DIMENSION_LABELS
from app.core.config.site_health_measurement import READINESS_DIMENSION_WEIGHTS
from app.core.config.site_health_rule_types import (
    FINDING_CLASS_ADVISORY,
    FINDING_CLASS_DEFECT,
    SCORE_ROLE_AEO,
    SCORE_ROLE_TECHNICAL,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.models.site_health.analysis import SiteIssue, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl

_DEFECT_IMPACT_BANDS = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
    "info": 0,
}


@dataclass(frozen=True, slots=True)
class IssueSnapshot:
    issue_count: int
    severity_counts: dict[str, int]
    category_counts: dict[str, int]
    top_issues: list[dict]
    technical_defect_count: int
    technical_defect_affected_page_count: int
    aeo_readiness_gap_count: int
    aeo_readiness_gap_affected_page_count: int


def _impact(rule_id: str, finding_class: str, severity: str) -> tuple[int, str]:
    if finding_class == FINDING_CLASS_DEFECT:
        return _DEFECT_IMPACT_BANDS.get(severity, 0), severity.replace("_", " ").title()
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    if (
        finding_class == FINDING_CLASS_ADVISORY
        and rule is not None
        and rule.readiness_dimension in READINESS_DIMENSION_WEIGHTS
        and SCORE_ROLE_AEO in rule.score_roles
    ):
        weighted_impact = (
            READINESS_DIMENSION_WEIGHTS[rule.readiness_dimension]
            * rule.readiness_weight
        )
        label = AEO_READINESS_DIMENSION_LABELS[rule.readiness_dimension]
        return max(1, round(weighted_impact * 10)), f"{label} · {weighted_impact:.0%}"
    return 0, "Advisory"


def _rollup(rows: Sequence[Row]) -> IssueSnapshot:
    severity_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    groups: dict[tuple[str, str], dict] = {}
    technical_pages: set[uuid.UUID] = set()
    readiness_pages: set[uuid.UUID] = set()
    technical_count = 0
    readiness_count = 0
    for row in rows:
        severity_counts[row.severity] = severity_counts.get(row.severity, 0) + 1
        category_counts[row.category] = category_counts.get(row.category, 0) + 1
        roles = set(row.score_roles or ())
        if row.finding_class == FINDING_CLASS_DEFECT and SCORE_ROLE_TECHNICAL in roles:
            technical_count += 1
            technical_pages.add(row.site_url_id)
        if SCORE_ROLE_AEO in roles:
            readiness_count += 1
            if row.scope == "page":
                readiness_pages.add(row.site_url_id)
        group = groups.setdefault(
            (row.rule_id, row.finding_class),
            {
                "rule_id": row.rule_id,
                "finding_class": row.finding_class,
                "severity": row.severity,
                "category": row.category,
                "description": row.description,
                "remediation": row.remediation,
                "score_roles": set(),
                "affected_site_url_ids": set(),
            },
        )
        group["score_roles"].update(roles)
        group["affected_site_url_ids"].add(row.site_url_id)
    top_issues: list[dict] = []
    for group in groups.values():
        group["affected_pages"] = len(group.pop("affected_site_url_ids"))
        group["score_roles"] = sorted(group["score_roles"])
        group["eligibility_blocker"] = group["rule_id"] == "technical.indexable"
        group["impact_band"], group["impact_label"] = _impact(
            group["rule_id"], group["finding_class"], group["severity"]
        )
        top_issues.append(group)
    top_issues.sort(
        key=lambda item: (
            -int(item["eligibility_blocker"]),
            -int(item["impact_band"]),
            0 if item["finding_class"] == FINDING_CLASS_DEFECT else 1,
            -int(item["affected_pages"]),
            str(item["rule_id"]),
        )
    )
    return IssueSnapshot(
        issue_count=len(rows),
        severity_counts=severity_counts,
        category_counts=category_counts,
        top_issues=top_issues[:10],
        technical_defect_count=technical_count,
        technical_defect_affected_page_count=len(technical_pages),
        aeo_readiness_gap_count=readiness_count,
        aeo_readiness_gap_affected_page_count=len(readiness_pages),
    )


async def build_issue_snapshot(
    session: AsyncSession, *, crawl: SiteCrawl, analysis_ids: list[uuid.UUID]
) -> IssueSnapshot:
    rows: Sequence[Row] = []
    if analysis_ids:
        rows = (
            await session.execute(
                select(
                    SiteIssue.severity,
                    SiteIssue.category,
                    SiteIssue.rule_id,
                    SiteIssue.finding_class,
                    SiteIssue.site_url_id,
                    SiteIssue.description,
                    SiteIssue.remediation,
                    SiteRuleEvaluation.score_roles,
                    SiteRuleEvaluation.scope,
                )
                .join(
                    SiteRuleEvaluation,
                    (SiteRuleEvaluation.id == SiteIssue.evaluation_id)
                    & (SiteRuleEvaluation.workspace_id == crawl.workspace_id)
                    & (SiteRuleEvaluation.analysis_id == SiteIssue.analysis_id)
                    & (SiteRuleEvaluation.rule_id == SiteIssue.rule_id),
                )
                .where(
                    SiteIssue.workspace_id == crawl.workspace_id,
                    SiteIssue.project_id == crawl.project_id,
                    SiteIssue.crawl_id == crawl.id,
                    SiteIssue.analysis_id.in_(analysis_ids),
                )
            )
        ).all()
    return _rollup(rows)


__all__ = ["IssueSnapshot", "build_issue_snapshot"]
