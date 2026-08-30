# Canonical crawl-aggregate snapshot/summary (single algorithm, no duplication).
#
# The ONE place the crawl-level ``SiteHealthSnapshot`` + the crawl's rolled-up
# ``score_summary`` are computed from persisted analyses. It aggregates only the
# LATEST completed analysis per ACTIVE monitored URL (missing/errored URLs are
# never fabricated as zero), rolls up the issue severity/category counts, and
# writes both the immutable snapshot row and the crawl projection field.
#
# Two callers share this exact algorithm:
#   - the worker's ``_reconcile_crawl_status`` on clean analysis terminalization;
#   - ``service.cancel_crawl`` when a cooperative cancel stops a run that has
#     already produced completed analyses — so a partial cancel still surfaces a
#     dashboard (partial scores + inventory) instead of a null ``score_summary``.
#
# Idempotent per crawl: the ``site_health_snapshots`` table is unique on
# ``crawl_id``, so this uses ``ON CONFLICT DO NOTHING`` for the immutable row and
# always (re)writes the crawl ``score_summary`` projection.
#
# The single fetched aggregate row set is authoritative — when it is empty the
# helper writes nothing and returns ``False`` (cancel), unless the caller passes
# ``persist_empty=True`` to force a canonical empty/null-score snapshot (the
# worker's clean terminalization). There is deliberately no separate precheck
# (that would be a TOCTOU race against membership/analysis changes).
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Row, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.score_aggregation import aggregate_by_page_kind
from app.analysis.site_health.scoring import (
    AnalysisMeasurementInput,
    aggregate_measurements,
)
from app.core.config.site_health_acquisition import ERROR_ROBOTS_DENIED
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PASS,
    SCORING_VERSION,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_link_metrics import COVERAGE_FORMULA_VERSION
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.domain.site_health.coverage import crawl_coverage
from app.models.site_health.acquisition import SiteFetchAttempt
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl

__all__ = ["persist_crawl_snapshot"]


def _latest_task_map(tasks: Sequence[SiteCrawlTask]) -> dict[uuid.UUID, SiteCrawlTask]:
    latest: dict[uuid.UUID, SiteCrawlTask] = {}
    for task in tasks:
        if task.site_url_id is None:
            continue
        current = latest.get(task.site_url_id)
        if current is None or task.generation >= current.generation:
            latest[task.site_url_id] = task
    return latest


def _latest_attempt_map(
    attempts: Sequence[SiteFetchAttempt],
) -> dict[uuid.UUID, SiteFetchAttempt]:
    latest: dict[uuid.UUID, SiteFetchAttempt] = {}
    for attempt in attempts:
        current = latest.get(attempt.task_id)
        current_order = (
            (-1, -1)
            if current is None
            else (current.attempt_number, current.request_ordinal)
        )
        if (attempt.attempt_number, attempt.request_ordinal) >= current_order:
            latest[attempt.task_id] = attempt
    return latest


def _representation(task: SiteCrawlTask | None) -> tuple[str, str]:
    if task is not None and task.result_artifact_id is not None:
        return "satisfied", "supported_public_representation"
    if (
        task is not None
        and task.status == TASK_STATUS_FAILED
        and task.error_code == ERROR_ROBOTS_DENIED
    ):
        return "missing", ERROR_ROBOTS_DENIED
    return "unknown", "acquisition_not_determinate"


def _eligibility_state(
    representation: str,
    indexing: str,
    task: SiteCrawlTask | None,
) -> tuple[str, str]:
    if representation == "missing" or indexing == RULE_OUTCOME_FAIL:
        return "blocked", "blocked"
    if representation == "satisfied" and indexing == RULE_OUTCOME_PASS:
        return "eligible", "audited"
    if task is not None and task.status == TASK_STATUS_FAILED:
        return "unknown", "error"
    return "unknown", "pending"


def _eligibility_reason(
    site_url_id: uuid.UUID,
    *,
    state: str,
    representation: str,
    representation_reason: str,
    indexing: str,
    task: SiteCrawlTask | None,
    attempt: SiteFetchAttempt | None,
    evaluation: SiteRuleEvaluation | None,
) -> dict:
    return {
        "site_url_id": str(site_url_id),
        "state": state,
        "checkpoints": [
            {
                "checkpoint_id": "acquisition.public_representation",
                "outcome": representation,
                "reason": representation_reason,
                "source_task_id": str(task.id) if task else None,
                "source_attempt_id": str(attempt.id) if attempt else None,
                "source_artifact_id": (
                    str(task.result_artifact_id)
                    if task and task.result_artifact_id
                    else None
                ),
            },
            {
                "checkpoint_id": "search.indexability",
                "outcome": indexing,
                "reason": evaluation.reason_code if evaluation else "analysis_missing",
                "source_analysis_id": (
                    str(evaluation.analysis_id) if evaluation else None
                ),
                "source_evaluation_id": str(evaluation.id) if evaluation else None,
            },
        ],
    }


def _eligibility_rollup(
    selected_ids: list[uuid.UUID],
    *,
    tasks: dict[uuid.UUID, SiteCrawlTask],
    attempts: dict[uuid.UUID, SiteFetchAttempt],
    indexability: dict[uuid.UUID, SiteRuleEvaluation],
) -> tuple[dict[str, int], list[dict], dict[str, int]]:
    totals = {"eligible": 0, "blocked": 0, "unknown": 0, "excluded": 0}
    reasons: list[dict] = []
    statuses = {"audited": 0, "blocked": 0, "error": 0, "pending": 0}
    for site_url_id in selected_ids:
        task = tasks.get(site_url_id)
        attempt = attempts.get(task.id) if task else None
        evaluation = indexability.get(site_url_id)
        representation, representation_reason = _representation(task)
        indexing = evaluation.outcome if evaluation else "unknown"
        state, status = _eligibility_state(representation, indexing, task)
        totals[state] += 1
        statuses[status] += 1
        if state != "eligible":
            reasons.append(
                _eligibility_reason(
                    site_url_id,
                    state=state,
                    representation=representation,
                    representation_reason=representation_reason,
                    indexing=indexing,
                    task=task,
                    attempt=attempt,
                    evaluation=evaluation,
                )
            )
    return totals, reasons, statuses


def _eligibility_gate(totals: dict[str, int]) -> str:
    if totals["blocked"]:
        return "blocked"
    if totals["unknown"]:
        return "unknown"
    if totals["eligible"]:
        return "eligible"
    if totals["excluded"]:
        return "excluded"
    return "unknown"


async def _eligibility_projection(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    selected_ids: list[uuid.UUID],
    analysis_ids: list[uuid.UUID],
) -> tuple[
    str, dict[str, int], list[dict], list[uuid.UUID], list[uuid.UUID], dict[str, int]
]:
    """Freeze the PR2 two-checkpoint eligibility gate with exact sources."""
    tasks = (
        await session.scalars(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == crawl.id,
                SiteCrawlTask.workspace_id == crawl.workspace_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.site_url_id.in_(selected_ids),
            )
        )
    ).all()
    latest_tasks = _latest_task_map(tasks)
    task_ids = sorted((task.id for task in latest_tasks.values()), key=str)
    attempts = (
        list(
            await session.scalars(
                select(SiteFetchAttempt).where(
                    SiteFetchAttempt.crawl_id == crawl.id,
                    SiteFetchAttempt.workspace_id == crawl.workspace_id,
                    SiteFetchAttempt.task_id.in_(task_ids),
                )
            )
        )
        if task_ids
        else []
    )
    latest_attempts = _latest_attempt_map(attempts)
    evaluation_rows: Sequence[Row[tuple[uuid.UUID, SiteRuleEvaluation]]] = ()
    if analysis_ids:
        evaluation_rows = (
            await session.execute(
                select(SitePageAnalysis.site_url_id, SiteRuleEvaluation)
                .join(
                    SiteRuleEvaluation,
                    SiteRuleEvaluation.analysis_id == SitePageAnalysis.id,
                )
                .where(
                    SitePageAnalysis.id.in_(analysis_ids),
                    SiteRuleEvaluation.rule_id == "technical.indexable",
                )
            )
        ).all()
    indexability = {
        site_url_id: evaluation for site_url_id, evaluation in evaluation_rows
    }
    totals, reasons, status_counts = _eligibility_rollup(
        selected_ids,
        tasks=latest_tasks,
        attempts=latest_attempts,
        indexability=indexability,
    )
    gate = _eligibility_gate(totals)
    attempt_ids = sorted((attempt.id for attempt in latest_attempts.values()), key=str)
    return gate, totals, reasons, task_ids, attempt_ids, status_counts


async def persist_crawl_snapshot(
    session: AsyncSession, *, crawl: SiteCrawl, persist_empty: bool = False
) -> bool:
    """Compute + persist the crawl aggregate snapshot (unique per crawl).

    Aggregates only the LATEST completed analyses for ACTIVE monitored URLs
    (ignoring missing/errored URLs — never a fabricated zero), rolls up the
    issue severity/category counts, and writes both the immutable
    ``SiteHealthSnapshot`` (``ON CONFLICT DO NOTHING`` — one per crawl) and the
    crawl's rolled-up ``score_summary`` projection.

    The single fetched aggregate row set is authoritative — there is no separate
    precheck (which would be a TOCTOU race against membership/analysis changes).
    When that row set is empty (zero aggregatable active completed analyses) the
    behaviour depends on ``persist_empty``:

      - ``persist_empty=False`` (default; used by ``service.cancel_crawl``):
        write NEITHER the snapshot NOR the ``score_summary`` projection and
        return ``False``. A partial cancel with nothing aggregable (e.g. its
        only completed analysis belongs to a since-deactivated URL) keeps
        ``score_summary`` null so the UI shows its terminal/selection state
        instead of an empty dashboard from zero aggregated rows.
      - ``persist_empty=True`` (used by the worker's clean terminalization):
        still write the explicit empty/null-score snapshot + projection, so an
        empty-plan crawl terminalizes with a canonical (zeroed) snapshot.

    Returns ``True`` when a snapshot/projection was (re)written, ``False`` when
    persistence was skipped because the aggregate was empty.
    """
    # The caller holds the crawl row lock, which closes discovery/task writes.
    # Selection mutations are serialized by the profile row, so take that same
    # lock before the first membership-backed read. The aggregate, selected
    # count, and coverage evidence then describe one frozen terminal state.
    await session.scalar(
        select(SiteHealthProfile.id)
        .where(
            SiteHealthProfile.id == crawl.profile_id,
            SiteHealthProfile.workspace_id == crawl.workspace_id,
            SiteHealthProfile.project_id == crawl.project_id,
        )
        .with_for_update()
    )

    # Exactly one latest completed analysis per ACTIVE monitored URL in this
    # crawl. Rank by the full timestamp, then UUID for a deterministic tie-break
    # (never truncate timestamps to whole seconds).
    ranked = (
        select(
            SitePageAnalysis.id.label("id"),
            SitePageAnalysis.site_url_id.label("site_url_id"),
            SitePageAnalysis.artifact_id.label("artifact_id"),
            SitePageAnalysis.technical_integrity_score.label(
                "technical_integrity_score"
            ),
            SitePageAnalysis.technical_integrity_coverage.label(
                "technical_integrity_coverage"
            ),
            SitePageAnalysis.technical_integrity_state.label(
                "technical_integrity_state"
            ),
            SitePageAnalysis.technical_earned_weight.label("technical_earned_weight"),
            SitePageAnalysis.technical_determinate_weight.label(
                "technical_determinate_weight"
            ),
            SitePageAnalysis.technical_expected_weight.label(
                "technical_expected_weight"
            ),
            SitePageAnalysis.technical_critical_complete.label(
                "technical_critical_complete"
            ),
            SitePageAnalysis.aeo_readiness_score.label("aeo_readiness_score"),
            SitePageAnalysis.aeo_measurement_coverage.label("aeo_measurement_coverage"),
            SitePageAnalysis.aeo_measurement_state.label("aeo_measurement_state"),
            SitePageAnalysis.readiness_dimensions.label("readiness_dimensions"),
            SitePageAnalysis.page_kind.label("page_kind"),
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
        .where(
            SitePageAnalysis.workspace_id == crawl.workspace_id,
            SitePageAnalysis.project_id == crawl.project_id,
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            MonitoredSiteUrl.workspace_id == crawl.workspace_id,
            MonitoredSiteUrl.project_id == crawl.project_id,
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
                ranked.c.technical_integrity_score,
                ranked.c.technical_integrity_coverage,
                ranked.c.technical_integrity_state,
                ranked.c.technical_earned_weight,
                ranked.c.technical_determinate_weight,
                ranked.c.technical_expected_weight,
                ranked.c.technical_critical_complete,
                ranked.c.aeo_readiness_score,
                ranked.c.aeo_measurement_coverage,
                ranked.c.aeo_measurement_state,
                ranked.c.readiness_dimensions,
                ranked.c.page_kind,
            )
            .where(ranked.c.latest_rank == 1)
            .order_by(ranked.c.site_url_id)
        )
    ).all()

    # The single fetched aggregate row set decides persistence — no separate
    # precheck (which would race membership/analysis changes). Zero aggregatable
    # active completed analyses => write nothing unless the caller explicitly
    # wants an empty/null-score snapshot (the worker's empty-plan terminalize).
    if not rows and not persist_empty:
        return False

    inputs: list[AnalysisMeasurementInput] = []
    analysis_ids: list[uuid.UUID] = []
    artifact_ids: list[uuid.UUID] = []
    for row in rows:
        analysis_ids.append(row.id)
        artifact_ids.append(row.artifact_id)
        inputs.append(
            AnalysisMeasurementInput(
                page_kind=row.page_kind,
                technical_integrity_score=row.technical_integrity_score,
                technical_integrity_coverage=row.technical_integrity_coverage,
                technical_integrity_state=row.technical_integrity_state,
                technical_earned_weight=row.technical_earned_weight,
                technical_determinate_weight=row.technical_determinate_weight,
                technical_expected_weight=row.technical_expected_weight,
                technical_critical_complete=row.technical_critical_complete,
                aeo_readiness_score=row.aeo_readiness_score,
                aeo_measurement_coverage=row.aeo_measurement_coverage,
                aeo_measurement_state=row.aeo_measurement_state,
                readiness_dimensions=tuple(row.readiness_dimensions or ()),
            )
        )
    aggregate = aggregate_measurements(inputs)
    by_page_kind = aggregate_by_page_kind(inputs)

    # Issue severity/category rollups for this crawl.
    severity_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    issue_total = 0
    evaluation_ids = (
        list(
            await session.scalars(
                select(SiteRuleEvaluation.id)
                .where(
                    SiteRuleEvaluation.workspace_id == crawl.workspace_id,
                    SiteRuleEvaluation.analysis_id.in_(analysis_ids),
                )
                .order_by(SiteRuleEvaluation.id)
            )
        )
        if analysis_ids
        else []
    )
    issue_rows: Sequence[Row] = []
    if analysis_ids:
        issue_rows = (
            await session.execute(
                select(
                    SiteIssue.severity,
                    SiteIssue.category,
                    SiteIssue.rule_id,
                    SiteIssue.finding_class,
                    SiteIssue.site_url_id,
                    SiteIssue.description,
                    SiteIssue.remediation,
                ).where(
                    SiteIssue.workspace_id == crawl.workspace_id,
                    SiteIssue.project_id == crawl.project_id,
                    SiteIssue.crawl_id == crawl.id,
                    SiteIssue.analysis_id.in_(analysis_ids),
                )
            )
        ).all()
    issue_groups: dict[tuple[str, str], dict] = {}
    for (
        severity,
        category,
        rule_id,
        finding_class,
        site_url_id,
        description,
        remediation,
    ) in issue_rows:
        issue_total += 1
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        key = (rule_id, finding_class)
        group = issue_groups.setdefault(
            key,
            {
                "rule_id": rule_id,
                "finding_class": finding_class,
                "severity": severity,
                "category": category,
                "description": description,
                "remediation": remediation,
                "affected_site_url_ids": set(),
            },
        )
        group["affected_site_url_ids"].add(site_url_id)
    impact_order = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
    top_issues = []
    for group in issue_groups.values():
        group["affected_pages"] = len(group.pop("affected_site_url_ids"))
        group["eligibility_blocker"] = group["rule_id"] == "technical.indexable"
        group["impact_band"] = impact_order.get(group["severity"], 0)
        top_issues.append(group)
    top_issues.sort(
        key=lambda item: (
            -int(item["eligibility_blocker"]),
            -int(item["impact_band"]),
            0 if item["finding_class"] == "defect" else 1,
            -int(item["affected_pages"]),
            str(item["rule_id"]),
        )
    )
    top_issues = top_issues[:10]

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
    selected_url_count = len(selected_ids)

    analyzer_version = crawl.analyzer_version or ANALYZER_VERSION
    scoring_version = crawl.scoring_version or SCORING_VERSION
    coverage = await crawl_coverage(session, crawl=crawl)
    (
        search_eligibility,
        eligibility_totals,
        eligibility_reasons,
        source_task_ids,
        source_attempt_ids,
        status_counts,
    ) = await _eligibility_projection(
        session,
        crawl=crawl,
        selected_ids=selected_ids,
        analysis_ids=analysis_ids,
    )

    # One immutable snapshot per crawl. ``ON CONFLICT DO NOTHING`` makes this
    # safe if the worker and a cancel both reach terminalization (the earliest
    # writer wins; the crawl ``score_summary`` projection below is still
    # (re)written so the DTO reflects the same aggregate).
    await session.execute(
        pg_insert(SiteHealthSnapshot)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            selected_url_count=selected_url_count,
            analyzed_url_count=aggregate.analyzed_url_count,
            technical_integrity_score=aggregate.technical_integrity_score,
            technical_integrity_coverage=aggregate.technical_integrity_coverage,
            technical_integrity_state=aggregate.technical_integrity_state,
            aeo_readiness_score=aggregate.aeo_readiness_score,
            aeo_measurement_coverage=aggregate.aeo_measurement_coverage,
            aeo_measurement_state=aggregate.aeo_measurement_state,
            readiness_dimensions=list(aggregate.readiness_dimensions),
            search_eligibility=search_eligibility,
            eligibility_totals=eligibility_totals,
            eligibility_reasons=eligibility_reasons,
            status_counts=status_counts,
            top_issues=top_issues,
            web_fundamentals={"state": "not_measured", "field_data_available": False},
            trend={"state": "unavailable", "reason": "no_comparable_snapshot"},
            change_summary={"state": "unavailable", "reason": "no_comparable_snapshot"},
            issue_count=issue_total,
            severity_counts=severity_counts,
            category_counts=category_counts,
            coverage_state=coverage.state,
            coverage_evidence=coverage.evidence,
            coverage_formula_version=COVERAGE_FORMULA_VERSION,
            source_analysis_ids=analysis_ids,
            source_artifact_ids=artifact_ids,
            source_evaluation_ids=evaluation_ids,
            source_task_ids=source_task_ids,
            source_attempt_ids=source_attempt_ids,
            analyzer_version=analyzer_version,
            scoring_version=scoring_version,
            profile_version=PROFILE_VERSION,
            schema_contract_version=SCHEMA_CONTRACT_VERSION,
            presentation_version=PRESENTATION_VERSION,
        )
        .on_conflict_do_nothing(
            constraint="uq_site_health_snapshot_crawl",
        )
    )
    crawl.score_summary = {
        "technical_integrity_score": aggregate.technical_integrity_score,
        "technical_integrity_coverage": aggregate.technical_integrity_coverage,
        "technical_integrity_state": aggregate.technical_integrity_state,
        "aeo_readiness_score": aggregate.aeo_readiness_score,
        "aeo_measurement_coverage": aggregate.aeo_measurement_coverage,
        "aeo_measurement_state": aggregate.aeo_measurement_state,
        "search_eligibility": search_eligibility,
        "analyzed_count": aggregate.analyzed_url_count,
        "selected_count": selected_url_count,
        "issue_count": issue_total,
        "scoring_version": aggregate.scoring_version,
        "presentation_version": PRESENTATION_VERSION,
        # Persisted per-page-kind measurement rollups. Missing/errored URLs
        # never appear here.
        "by_page_kind": by_page_kind,
    }
    return True
