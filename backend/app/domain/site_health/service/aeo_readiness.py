"""Read-only AEO Readiness projection over current persisted evaluations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.aeo_readiness import (
    ReadinessEvaluationInput,
    project_aeo_readiness,
)
from app.core.config.site_health import (
    AEO_READINESS_MAX_EVALUATIONS,
    AEO_READINESS_RULE_DIMENSIONS,
    AEO_READINESS_TAXONOMY_VERSION,
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    PAGE_ANALYSIS_STATUS_COMPLETED,
)
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    _load_project,
)
from app.models.site_health import (
    SiteCrawl,
    SiteFetchArtifact,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
)

_USABLE_CRAWL_STATUSES = (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_CANCELLED,
)


async def _resolve_crawl(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None,
) -> SiteCrawl | None:
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    statement = select(SiteCrawl).where(
        SiteCrawl.workspace_id == workspace_id,
        SiteCrawl.project_id == project_id,
    )
    if crawl_id is not None:
        crawl = await session.scalar(statement.where(SiteCrawl.id == crawl_id))
        if crawl is None:
            raise SiteHealthNotFoundError("Crawl not found")
        return crawl if crawl.status in _USABLE_CRAWL_STATUSES else None
    return await session.scalar(
        statement.where(SiteCrawl.status.in_(_USABLE_CRAWL_STATUSES))
        .order_by(SiteCrawl.created_at.desc(), SiteCrawl.id.desc())
        .limit(1)
    )


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
        "rule_ids": list(item.rule_ids),
        "pass_count": item.pass_count,
        "fail_count": item.fail_count,
        "not_applicable_count": item.not_applicable_count,
        "error_count": item.error_count,
        "observed_evaluation_count": item.observed_evaluation_count,
        "expected_evaluation_count": item.expected_evaluation_count,
        "coverage": item.coverage,
        "evidence_links": [
            {
                "evaluation_id": row.evaluation_id,
                "analysis_id": row.analysis_id,
                "site_url_id": row.site_url_id,
                "normalized_url": row.normalized_url,
                "rule_id": row.rule_id,
                "outcome": row.outcome,
            }
            for row in item.evidence
        ],
    }


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
        "limitations": ["No usable persisted crawl is available for AEO Readiness."],
    }


async def get_aeo_readiness(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Project current persisted evaluations without crawling or repair."""
    crawl = await _resolve_crawl(
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
    result = project_aeo_readiness(
        [
            ReadinessEvaluationInput(
                evaluation_id=row.id,
                analysis_id=row.analysis_id,
                site_url_id=urls[row.analysis_id].id,
                normalized_url=urls[row.analysis_id].normalized_url,
                rule_id=row.rule_id,
                outcome=row.outcome,
            )
            for row in evaluation_rows
        ],
        analysis_count=len(analyses),
    )
    limitations = list(result.limitations)
    if truncated:
        limitations.append(
            f"Evaluation projection is bounded to {AEO_READINESS_MAX_EVALUATIONS} rows."
        )
    return {
        "state": "incomplete" if truncated else "available",
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
