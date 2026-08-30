"""Shared persisted-evidence builder for live and terminal score summaries."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.site_health.score_aggregation import aggregate_by_page_kind
from app.analysis.site_health.scoring import (
    AggregateMeasurements,
    AnalysisMeasurementInput,
    RuleMeasurementInput,
    aggregate_measurements,
)
from app.core.config.site_health_contracts import PAGE_ANALYSIS_STATUS_COMPLETED
from app.core.config.site_health_measurement import PRESENTATION_VERSION
from app.domain.site_health.task_guards import crawl_is_active
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


@dataclass(frozen=True, slots=True)
class CrawlMeasurementProjection:
    """One workspace-scoped view of the crawl's latest persisted analyses."""

    rows: Sequence[Row]
    analysis_ids: list[uuid.UUID]
    artifact_ids: list[uuid.UUID]
    evaluation_rows: Sequence[Row]
    aggregate: AggregateMeasurements
    by_page_kind: dict[str, dict]


def _measurement_sources(
    rows: Sequence[Row],
) -> tuple[
    list[AnalysisMeasurementInput],
    list[uuid.UUID],
    list[uuid.UUID],
    dict[uuid.UUID, str],
]:
    inputs = [
        AnalysisMeasurementInput(
            analysis_id=str(row.id),
            page_kind=row.page_kind,
            page_traits=tuple(row.page_traits or ()),
        )
        for row in rows
    ]
    return (
        inputs,
        [row.id for row in rows],
        [row.artifact_id for row in rows],
        {row.id: row.page_kind for row in rows},
    )


async def _measurement_evaluations(
    session: AsyncSession, *, workspace_id: uuid.UUID, analysis_ids: list[uuid.UUID]
) -> Sequence[Row]:
    if not analysis_ids:
        return []
    return (
        await session.execute(
            select(
                SiteRuleEvaluation.id,
                SiteRuleEvaluation.analysis_id,
                SiteRuleEvaluation.rule_id,
                SiteRuleEvaluation.scope,
                SiteRuleEvaluation.outcome,
                SiteRuleEvaluation.expected_profile_membership,
                SiteRuleEvaluation.score_roles,
                SiteRuleEvaluation.weight,
                SiteRuleEvaluation.severity,
                SiteRuleEvaluation.checkpoint_family,
                SiteRuleEvaluation.readiness_dimension,
                SiteRuleEvaluation.readiness_weight,
                SiteRuleEvaluation.evidence,
            )
            .where(
                SiteRuleEvaluation.workspace_id == workspace_id,
                SiteRuleEvaluation.analysis_id.in_(analysis_ids),
            )
            .order_by(SiteRuleEvaluation.id)
        )
    ).all()


def _rule_measurements(
    rows: Sequence[Row], *, page_kind_by_analysis: dict[uuid.UUID, str]
) -> list[RuleMeasurementInput]:
    return [
        RuleMeasurementInput(
            analysis_id=str(row.analysis_id),
            page_kind=page_kind_by_analysis[row.analysis_id],
            rule_id=row.rule_id,
            scope=row.scope,
            outcome=row.outcome,
            expected=row.expected_profile_membership,
            score_roles=tuple(row.score_roles or ()),
            weight=row.weight,
            severity=row.severity,
            checkpoint_family=row.checkpoint_family,
            readiness_dimension=row.readiness_dimension,
            readiness_weight=row.readiness_weight,
            normalized_score=(row.evidence or {}).get("normalized_score"),
            normalized_coverage=(row.evidence or {}).get("normalized_coverage"),
        )
        for row in rows
    ]


async def load_crawl_measurement_projection(
    session: AsyncSession, *, crawl: SiteCrawl
) -> CrawlMeasurementProjection:
    """Normalize the latest completed analysis per active monitored URL."""
    ranked = (
        select(
            SitePageAnalysis.id.label("id"),
            SitePageAnalysis.site_url_id.label("site_url_id"),
            SitePageAnalysis.artifact_id.label("artifact_id"),
            SitePageAnalysis.page_kind.label("page_kind"),
            SitePageAnalysis.page_traits.label("page_traits"),
            SiteUrl.normalized_url.label("normalized_url"),
            func.row_number()
            .over(
                partition_by=SitePageAnalysis.site_url_id,
                order_by=(
                    SitePageAnalysis.created_at.desc(),
                    SitePageAnalysis.id.desc(),
                ),
            )
            .label("latest_rank"),
        )
        .join(
            MonitoredSiteUrl,
            (MonitoredSiteUrl.site_url_id == SitePageAnalysis.site_url_id)
            & (MonitoredSiteUrl.project_id == crawl.project_id)
            & (MonitoredSiteUrl.workspace_id == crawl.workspace_id),
        )
        .join(
            SiteUrl,
            (SiteUrl.id == SitePageAnalysis.site_url_id)
            & (SiteUrl.workspace_id == crawl.workspace_id)
            & (SiteUrl.project_id == crawl.project_id),
        )
        .where(
            SitePageAnalysis.workspace_id == crawl.workspace_id,
            SitePageAnalysis.project_id == crawl.project_id,
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            MonitoredSiteUrl.active.is_(True),
        )
        .subquery()
    )
    rows = (
        await session.execute(
            select(
                ranked.c.id,
                ranked.c.site_url_id,
                ranked.c.artifact_id,
                ranked.c.page_kind,
                ranked.c.page_traits,
                ranked.c.normalized_url,
            )
            .where(ranked.c.latest_rank == 1)
            .order_by(ranked.c.site_url_id)
        )
    ).all()
    inputs, analysis_ids, artifact_ids, page_kind_by_analysis = _measurement_sources(
        rows
    )
    evaluation_rows = await _measurement_evaluations(
        session, workspace_id=crawl.workspace_id, analysis_ids=analysis_ids
    )
    rules = _rule_measurements(
        evaluation_rows, page_kind_by_analysis=page_kind_by_analysis
    )
    return CrawlMeasurementProjection(
        rows=rows,
        analysis_ids=analysis_ids,
        artifact_ids=artifact_ids,
        evaluation_rows=evaluation_rows,
        aggregate=aggregate_measurements(inputs, rules),
        by_page_kind=aggregate_by_page_kind(inputs, rules),
    )


def score_summary_payload(
    projection: CrawlMeasurementProjection,
    *,
    selected_count: int,
    issue_count: int,
) -> dict:
    aggregate = projection.aggregate
    return {
        "web_fundamentals_score": aggregate.web_fundamentals_score,
        "web_fundamentals_coverage": aggregate.web_fundamentals_coverage,
        "web_fundamentals_state": aggregate.web_fundamentals_state,
        "aeo_readiness_score": aggregate.aeo_readiness_score,
        "aeo_measurement_coverage": aggregate.aeo_measurement_coverage,
        "aeo_measurement_state": aggregate.aeo_measurement_state,
        "search_eligibility": "unknown",
        "analyzed_count": aggregate.analyzed_url_count,
        "selected_count": selected_count,
        "issue_count": issue_count,
        "scoring_version": aggregate.scoring_version,
        "presentation_version": PRESENTATION_VERSION,
        "by_page_kind": projection.by_page_kind,
    }


async def refresh_live_score_summary(
    session: AsyncSession, *, crawl: SiteCrawl
) -> bool:
    """Persist the active crawl's current measurement projection in place."""
    await session.scalar(
        select(SiteHealthProfile.id)
        .where(
            SiteHealthProfile.id == crawl.profile_id,
            SiteHealthProfile.workspace_id == crawl.workspace_id,
            SiteHealthProfile.project_id == crawl.project_id,
        )
        .with_for_update()
    )
    projection = await load_crawl_measurement_projection(session, crawl=crawl)
    if not projection.rows:
        return False
    selected_count = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.workspace_id == crawl.workspace_id,
                MonitoredSiteUrl.project_id == crawl.project_id,
                MonitoredSiteUrl.active.is_(True),
            )
        )
        or 0
    )
    issue_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SiteIssue)
            .where(
                SiteIssue.workspace_id == crawl.workspace_id,
                SiteIssue.project_id == crawl.project_id,
                SiteIssue.crawl_id == crawl.id,
                SiteIssue.analysis_id.in_(projection.analysis_ids),
            )
        )
        or 0
    )
    crawl.score_summary = score_summary_payload(
        projection, selected_count=selected_count, issue_count=issue_count
    )
    return True


async def refresh_live_score_summary_for_crawl(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    crawl_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> None:
    """Lock and refresh one active crawl after an intermediate task commit."""
    async with session_factory() as session:
        crawl = await session.scalar(
            select(SiteCrawl)
            .where(
                SiteCrawl.id == crawl_id,
                SiteCrawl.workspace_id == workspace_id,
            )
            .with_for_update()
        )
        if crawl is None or not crawl_is_active(crawl):
            await session.rollback()
            return
        await refresh_live_score_summary(session, crawl=crawl)
        await session.commit()


__all__ = [
    "CrawlMeasurementProjection",
    "load_crawl_measurement_projection",
    "refresh_live_score_summary",
    "refresh_live_score_summary_for_crawl",
    "score_summary_payload",
]
