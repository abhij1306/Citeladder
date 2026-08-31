"""Cohesive persisted Site Health Overview projection."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.domain.site_health.issue_snapshot import issue_impact
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    resolve_usable_crawl,
)
from app.models.site_health.snapshot import SiteHealthSnapshot


def _stored(value: object, fallback: object) -> object:
    return fallback if value is None else value


def _top_issues(value: object) -> list:
    """Backfill fields absent from older frozen top-issue rollups."""
    issues = []
    for issue in _stored_list(value)[:5]:
        if not isinstance(issue, dict):
            continue
        enriched = {**issue}
        rule_id = str(issue.get("rule_id", ""))
        rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
        enriched.setdefault("score_roles", sorted(rule.score_roles) if rule else [])
        impact_band, impact_label = issue_impact(
            rule_id,
            str(issue.get("finding_class", "")),
            str(issue.get("severity", "")),
        )
        enriched.setdefault("impact_band", impact_band)
        enriched.setdefault("impact_label", impact_label)
        issues.append(enriched)
    return issues


def _count(evidence: object, key: str) -> int:
    if not isinstance(evidence, dict):
        return 0
    value = evidence.get(key, 0)
    return int(value) if isinstance(value, int) else 0


def _stored_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _overview_limitations(snapshot: SiteHealthSnapshot) -> list[str]:
    limitations: list[str] = []
    if snapshot.aeo_measurement_state != "measured":
        limitations.append(
            "AEO Readiness has limited evidence; broader page-purpose "
            "coverage is needed."
        )
    if snapshot.coverage_state != "complete":
        limitations.append(
            f"AEO Readiness describes {snapshot.analyzed_url_count} audited pages, "
            "not the whole site."
        )
    return limitations


async def get_overview(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    crawl = await resolve_usable_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if crawl is None:
        raise SiteHealthNotFoundError("Site Health Overview is not available")
    snapshot = await session.scalar(
        select(SiteHealthSnapshot).where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
            SiteHealthSnapshot.crawl_id == crawl.id,
        )
    )
    if snapshot is None:
        raise SiteHealthNotFoundError("Site Health Overview is not available")
    coverage_evidence = _stored(snapshot.coverage_evidence, {})
    return {
        "project_id": project_id,
        "crawl_id": crawl.id,
        "snapshot_id": snapshot.id,
        "search_eligibility": snapshot.search_eligibility,
        "eligibility_totals": _stored(snapshot.eligibility_totals, {}),
        "eligibility_reasons": _stored(snapshot.eligibility_reasons, []),
        "web_fundamentals_score": snapshot.web_fundamentals_score,
        "web_fundamentals_coverage": snapshot.web_fundamentals_coverage,
        "web_fundamentals_state": snapshot.web_fundamentals_state,
        "aeo_readiness_score": snapshot.aeo_readiness_score,
        "aeo_measurement_coverage": snapshot.aeo_measurement_coverage,
        "aeo_measurement_state": snapshot.aeo_measurement_state,
        "classified_page_count": snapshot.classified_page_count,
        "other_page_count": snapshot.other_page_count,
        "classification_error_page_count": snapshot.classification_error_page_count,
        "classification_expected_page_count": (
            snapshot.classification_expected_page_count
        ),
        "classification_coverage": snapshot.classification_coverage,
        "classification_state": snapshot.classification_state,
        "classification_reason_groups": _stored(
            snapshot.classification_reason_groups, {}
        ),
        "classification_formula_version": snapshot.classification_formula_version,
        "classification_source_analysis_ids": _stored(
            snapshot.classification_source_analysis_ids, []
        ),
        "classification_source_artifact_ids": _stored(
            snapshot.classification_source_artifact_ids, []
        ),
        "classification_source_task_ids": _stored(
            snapshot.classification_source_task_ids, []
        ),
        "scored_page_kind_set": _stored(snapshot.scored_page_kind_set, []),
        "scored_page_count_by_kind": _stored(snapshot.scored_page_count_by_kind, {}),
        "crawl_coverage": {
            "state": snapshot.coverage_state,
            "evidence": coverage_evidence,
            "denominator_kind": "selected_intended_public_urls",
        },
        "audited_page_count": snapshot.analyzed_url_count,
        "selected_page_count": snapshot.selected_url_count,
        "status_counts": _stored(snapshot.status_counts, {}),
        "issue_count": snapshot.issue_count,
        "technical_defect_count": snapshot.technical_defect_count,
        "technical_defect_affected_page_count": (
            snapshot.technical_defect_affected_page_count
        ),
        "aeo_readiness_gap_count": snapshot.aeo_readiness_gap_count,
        "aeo_readiness_gap_affected_page_count": (
            snapshot.aeo_readiness_gap_affected_page_count
        ),
        "severity_counts": _stored(snapshot.severity_counts, {}),
        "category_counts": _stored(snapshot.category_counts, {}),
        "measured_check_count": _count(coverage_evidence, "measured_check_count"),
        "expected_check_count": _count(coverage_evidence, "expected_check_count"),
        "aeo_dimensions": _stored(snapshot.readiness_dimensions, []),
        "top_issues": _top_issues(snapshot.top_issues),
        "web_fundamentals": _stored(
            snapshot.web_fundamentals,
            {
                "state": "not_measured",
                "areas": [],
                "field_data": {
                    "state": "unavailable",
                    "reason": "provider_not_configured",
                    "lcp": None,
                    "inp": None,
                    "cls": None,
                },
                "source_analysis_ids": [],
                "source_artifact_ids": [],
                "source_evaluation_ids": [],
                "limitations": [],
            },
        ),
        "trend": _stored(
            snapshot.trend,
            {
                "state": "unavailable",
                "reason": "no_comparable_snapshot",
                "metric": "aeo_readiness_score",
                "series": [],
                "cohort_composition": {
                    "added_page_kinds": [],
                    "removed_page_kinds": [],
                    "previous_page_count_by_kind": {},
                    "current_page_count_by_kind": {},
                },
            },
        ),
        "change_summary": _stored(
            snapshot.change_summary,
            {
                "state": "unavailable",
                "reason": "no_comparable_snapshot",
                "metrics": [],
                "cohort_composition": {
                    "added_page_kinds": [],
                    "removed_page_kinds": [],
                    "previous_page_count_by_kind": {},
                    "current_page_count_by_kind": {},
                },
            },
        ),
        "limitations": _overview_limitations(snapshot),
    }


__all__ = ["get_overview"]
