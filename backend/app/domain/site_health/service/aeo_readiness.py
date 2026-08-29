"""Read-only AEO Readiness projection over current persisted evaluations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.aeo_readiness import (
    ReadinessEvaluationInput,
    project_aeo_readiness,
)
from app.analysis.site_health.rules import rule_for
from app.core.config.site_health_contracts import (
    AEO_READINESS_MAX_EVALUATIONS,
    AEO_READINESS_RULE_DIMENSIONS,
    AEO_READINESS_TAXONOMY_VERSION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
)
from app.domain.site_health.service.common import resolve_usable_crawl
from app.domain.site_health.service.presentation import display_label_for
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl


async def _current_analysis_rows(
    session: AsyncSession, *, crawl: SiteCrawl
) -> list[tuple[SitePageAnalysis, SiteUrl]]:
    return [
        tuple(row)
        for row in (
            await session.execute(
                select(SitePageAnalysis, SiteUrl)
                .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
                .join(
                    SiteFetchArtifact,
                    SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
                )
                .where(
                    SitePageAnalysis.workspace_id == crawl.workspace_id,
                    SitePageAnalysis.project_id == crawl.project_id,
                    SitePageAnalysis.crawl_id == crawl.id,
                    SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                    SitePageAnalysis.is_current.is_(True),
                    SitePageAnalysis.analyzer_version == crawl.analyzer_version,
                    SiteFetchArtifact.extractor_version == crawl.extractor_version,
                    SiteFetchArtifact.content_type.ilike("%html%"),
                )
                .order_by(SitePageAnalysis.site_url_id, SitePageAnalysis.id)
            )
        ).all()
    ]


def _dimension(item) -> dict:
    return {
        "key": item.key,
        "label": item.label,
        "description": item.description,
        "rule_ids": list(item.rule_ids),
        "pass_count": item.pass_count,
        "fail_count": item.fail_count,
        "not_applicable_count": item.not_applicable_count,
        "error_count": item.error_count,
        "observed_evaluation_count": item.observed_evaluation_count,
        "expected_evaluation_count": item.expected_evaluation_count,
        "coverage": item.coverage,
        "checked_page_count": item.checked_page_count,
        "failing_page_count": item.failing_page_count,
        "checks": [
            {
                "rule_id": check.rule_id,
                "title": check.title,
                "remediation": check.remediation,
                "pass_count": check.pass_count,
                "fail_count": check.fail_count,
                "not_applicable_count": check.not_applicable_count,
                "error_count": check.error_count,
                "failing_page_count": check.failing_page_count,
            }
            for check in item.checks
        ],
        "evidence_pages": [
            {
                "site_url_id": page.site_url_id,
                "normalized_url": page.normalized_url,
                "failed_checks": [
                    {"rule_id": check.rule_id, "title": check.title}
                    for check in page.failed_checks
                ],
            }
            for page in item.evidence_pages
        ],
        "evidence_truncated": item.evidence_truncated,
    }


def _rule_copy(rule_id: str) -> tuple[str, str]:
    """Current catalog title + remediation for a mapped rule.

    Resolved here rather than in the pure projection so the analysis module
    never reaches into the rule catalog, and so the surface can never fall back
    to showing a reader a raw rule id.
    """
    rule = rule_for(rule_id)
    return display_label_for(rule_id), (rule.remediation if rule is not None else "")


def _unavailable() -> dict:
    return {
        "state": "unavailable",
        "crawl_id": None,
        "taxonomy_version": AEO_READINESS_TAXONOMY_VERSION,
        "analyzer_version": "",
        "source_analysis_ids": [],
        "analysis_count": 0,
        "observed_evaluation_count": 0,
        "expected_evaluation_count": 0,
        "coverage": None,
        "dimensions": [],
        "limitations": [
            "AEO Readiness appears once a crawl has finished analyzing pages."
        ],
    }


async def get_aeo_readiness(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Project current persisted evaluations without crawling or repair."""
    crawl = await resolve_usable_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if crawl is None:
        return _unavailable()
    analyses = await _current_analysis_rows(session, crawl=crawl)
    if not analyses:
        return {**_unavailable(), "crawl_id": crawl.id}
    urls = {analysis.id: site_url for analysis, site_url in analyses}
    evaluation_rows = list(
        (
            await session.scalars(
                select(SiteRuleEvaluation)
                .where(
                    SiteRuleEvaluation.workspace_id == workspace_id,
                    SiteRuleEvaluation.analysis_id.in_(urls),
                    SiteRuleEvaluation.rule_id.in_(AEO_READINESS_RULE_DIMENSIONS),
                    SiteRuleEvaluation.analyzer_version == crawl.analyzer_version,
                    SiteRuleEvaluation.extractor_version == crawl.extractor_version,
                )
                .order_by(
                    SiteRuleEvaluation.analysis_id,
                    SiteRuleEvaluation.rule_id,
                    SiteRuleEvaluation.id,
                )
                .limit(AEO_READINESS_MAX_EVALUATIONS + 1)
            )
        ).all()
    )
    truncated = len(evaluation_rows) > AEO_READINESS_MAX_EVALUATIONS
    evaluation_rows = evaluation_rows[:AEO_READINESS_MAX_EVALUATIONS]
    rule_copy = {
        rule_id: _rule_copy(rule_id) for rule_id in AEO_READINESS_RULE_DIMENSIONS
    }
    result = project_aeo_readiness(
        [
            ReadinessEvaluationInput(
                evaluation_id=row.id,
                analysis_id=row.analysis_id,
                site_url_id=urls[row.analysis_id].id,
                normalized_url=urls[row.analysis_id].normalized_url,
                rule_id=row.rule_id,
                outcome=row.outcome,
                title=rule_copy[row.rule_id][0],
                remediation=rule_copy[row.rule_id][1],
                reason=str((row.evidence or {}).get("reason") or ""),
            )
            for row in evaluation_rows
        ],
        analysis_count=len(analyses),
        rule_copy=rule_copy,
    )
    limitations = list(result.limitations)
    if truncated:
        limitations.append(
            "This crawl produced more check results than one view can hold, so "
            "the counts below are a bounded sample of them."
        )
    return {
        "state": "incomplete" if truncated or limitations else "available",
        "crawl_id": crawl.id,
        "taxonomy_version": AEO_READINESS_TAXONOMY_VERSION,
        "analyzer_version": crawl.analyzer_version,
        "source_analysis_ids": sorted(urls, key=str),
        "analysis_count": len(analyses),
        "observed_evaluation_count": result.observed_evaluation_count,
        "expected_evaluation_count": result.expected_evaluation_count,
        "coverage": result.coverage,
        "dimensions": [_dimension(item) for item in result.dimensions],
        "limitations": limitations,
    }


__all__ = ["get_aeo_readiness"]
