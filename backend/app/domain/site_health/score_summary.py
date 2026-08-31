"""Shared persisted-evidence builder for live and terminal score summaries."""

from __future__ import annotations

import uuid
from collections import Counter
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
from app.core.config.site_health_contracts import (
    PAGE_ANALYSIS_STATUS_COMPLETED,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_measurement import (
    CLASSIFICATION_FORMULA_VERSION,
    CLASSIFICATION_STATE_COMPLETE,
    CLASSIFICATION_STATE_NOT_MEASURED,
    CLASSIFICATION_STATE_PARTIAL,
    PRESENTATION_VERSION,
)
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER
from app.core.config.task_queue import TASK_TERMINAL_STATUSES
from app.domain.site_health.task_guards import crawl_is_active
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


@dataclass(frozen=True, slots=True)
class ClassificationProjection:
    classified_page_count: int
    other_page_count: int
    error_page_count: int
    expected_page_count: int
    coverage: float | None
    state: str
    reason_groups: dict[str, int]
    scored_page_kind_set: list[str]
    scored_page_count_by_kind: dict[str, int]
    source_analysis_ids: list[uuid.UUID]
    source_artifact_ids: list[uuid.UUID]
    source_task_ids: list[uuid.UUID]

    def to_payload(self) -> dict:
        return {
            "classified_page_count": self.classified_page_count,
            "other_page_count": self.other_page_count,
            "classification_error_page_count": self.error_page_count,
            "classification_expected_page_count": self.expected_page_count,
            "classification_coverage": self.coverage,
            "classification_state": self.state,
            "classification_reason_groups": self.reason_groups,
            "classification_formula_version": CLASSIFICATION_FORMULA_VERSION,
            "classification_source_analysis_ids": [
                str(value) for value in self.source_analysis_ids
            ],
            "classification_source_artifact_ids": [
                str(value) for value in self.source_artifact_ids
            ],
            "classification_source_task_ids": [
                str(value) for value in self.source_task_ids
            ],
            "scored_page_kind_set": self.scored_page_kind_set,
            "scored_page_count_by_kind": self.scored_page_count_by_kind,
        }


def latest_task_by_url(
    tasks: Sequence[SiteCrawlTask],
) -> dict[uuid.UUID, SiteCrawlTask]:
    latest: dict[uuid.UUID, SiteCrawlTask] = {}
    for task in tasks:
        if task.site_url_id is None:
            continue
        current = latest.get(task.site_url_id)
        if current is None or task.generation >= current.generation:
            latest[task.site_url_id] = task
    return latest


@dataclass(slots=True)
class _ClassifiedEvidence:
    kind_counts: Counter[str]
    reasons: Counter[str]
    analysis_ids: list[uuid.UUID]
    artifact_ids: set[uuid.UUID]
    completed_site_url_ids: set[uuid.UUID]
    classified_count: int = 0
    other_count: int = 0


def _classified_evidence(
    rows: Sequence[Row], expected_tasks: dict[uuid.UUID, SiteCrawlTask]
) -> _ClassifiedEvidence:
    evidence = _ClassifiedEvidence(Counter(), Counter(), [], set(), set())
    for row in rows:
        task = expected_tasks.get(row.site_url_id)
        if task is None or task.result_artifact_id != row.artifact_id:
            continue
        evidence.completed_site_url_ids.add(row.site_url_id)
        evidence.analysis_ids.append(row.id)
        evidence.artifact_ids.add(row.artifact_id)
        if row.page_kind == PAGE_KIND_OTHER:
            evidence.other_count += 1
            kind_evidence = row.page_kind_evidence or {}
            reason = str(kind_evidence.get("other_reason") or "page_purpose_unresolved")
            evidence.reasons[reason] += 1
            continue
        evidence.classified_count += 1
        evidence.kind_counts[row.page_kind] += 1
    return evidence


def _classification_errors(
    expected_tasks: dict[uuid.UUID, SiteCrawlTask],
    completed_ids: set[uuid.UUID],
) -> tuple[int, Counter[str], set[uuid.UUID]]:
    error_ids = {
        site_url_id
        for site_url_id, task in expected_tasks.items()
        if site_url_id not in completed_ids and task.status in TASK_TERMINAL_STATUSES
    }
    reasons: Counter[str] = Counter()
    artifact_ids: set[uuid.UUID] = set()
    for site_url_id in error_ids:
        task = expected_tasks[site_url_id]
        reasons[task.error_code or "classification_failed"] += 1
        if task.result_artifact_id is not None:
            artifact_ids.add(task.result_artifact_id)
    return len(error_ids), reasons, artifact_ids


def _classification_state(classified_count: int, expected_count: int) -> str:
    if not expected_count:
        return CLASSIFICATION_STATE_NOT_MEASURED
    if classified_count == expected_count:
        return CLASSIFICATION_STATE_COMPLETE
    return CLASSIFICATION_STATE_PARTIAL


async def load_classification_projection(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    selected_ids: list[uuid.UUID],
    rows: Sequence[Row],
) -> ClassificationProjection:
    tasks = (
        await session.scalars(
            select(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == crawl.id,
                SiteCrawlTask.workspace_id == crawl.workspace_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.site_url_id.in_(selected_ids),
            )
            .order_by(
                SiteCrawlTask.site_url_id,
                SiteCrawlTask.generation,
                SiteCrawlTask.id,
            )
        )
    ).all()
    expected_tasks = {
        site_url_id: task
        for site_url_id, task in latest_task_by_url(tasks).items()
        if task.classification_expected
    }
    evidence = _classified_evidence(rows, expected_tasks)
    error_count, error_reasons, error_artifacts = _classification_errors(
        expected_tasks, evidence.completed_site_url_ids
    )
    evidence.reasons.update(error_reasons)
    evidence.artifact_ids.update(error_artifacts)
    expected_count = len(expected_tasks)
    coverage = (
        round(evidence.classified_count / expected_count, 4) if expected_count else None
    )
    return ClassificationProjection(
        classified_page_count=evidence.classified_count,
        other_page_count=evidence.other_count,
        error_page_count=error_count,
        expected_page_count=expected_count,
        coverage=coverage,
        state=_classification_state(evidence.classified_count, expected_count),
        reason_groups=dict(sorted(evidence.reasons.items())),
        scored_page_kind_set=sorted(evidence.kind_counts),
        scored_page_count_by_kind=dict(sorted(evidence.kind_counts.items())),
        source_analysis_ids=sorted(evidence.analysis_ids, key=str),
        source_artifact_ids=sorted(evidence.artifact_ids, key=str),
        source_task_ids=sorted((task.id for task in expected_tasks.values()), key=str),
    )


@dataclass(frozen=True, slots=True)
class CrawlMeasurementProjection:
    """One workspace-scoped view of the crawl's latest persisted analyses."""

    selected_ids: list[uuid.UUID]
    rows: Sequence[Row]
    analysis_ids: list[uuid.UUID]
    artifact_ids: list[uuid.UUID]
    evaluation_rows: Sequence[Row]
    aggregate: AggregateMeasurements
    by_page_kind: dict[str, dict]
    classification: ClassificationProjection


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
            expected_family_profile=tuple(row.expected_checkpoint_profile or ()),
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
            SitePageAnalysis.page_kind_evidence.label("page_kind_evidence"),
            SitePageAnalysis.expected_checkpoint_profile.label(
                "expected_checkpoint_profile"
            ),
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
                ranked.c.page_kind_evidence,
                ranked.c.page_traits,
                ranked.c.expected_checkpoint_profile,
                ranked.c.normalized_url,
            )
            .where(ranked.c.latest_rank == 1)
            .order_by(ranked.c.site_url_id)
        )
    ).all()
    selected_ids = list(
        await session.scalars(
            select(MonitoredSiteUrl.site_url_id)
            .where(
                MonitoredSiteUrl.workspace_id == crawl.workspace_id,
                MonitoredSiteUrl.project_id == crawl.project_id,
                MonitoredSiteUrl.active.is_(True),
            )
            .order_by(MonitoredSiteUrl.site_url_id)
        )
    )
    classification = await load_classification_projection(
        session,
        crawl=crawl,
        selected_ids=selected_ids,
        rows=rows,
    )
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
        selected_ids=selected_ids,
        rows=rows,
        analysis_ids=analysis_ids,
        artifact_ids=artifact_ids,
        evaluation_rows=evaluation_rows,
        classification=classification,
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
        **projection.classification.to_payload(),
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
    selected_count = len(projection.selected_ids)
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
