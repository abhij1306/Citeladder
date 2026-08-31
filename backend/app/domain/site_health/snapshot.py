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
# ``crawl_id``. The transaction that inserts the immutable row also writes the
# crawl ``score_summary``; a replay changes neither projection.
#
# The single fetched aggregate row set is authoritative — when it is empty the
# helper writes nothing and returns ``False`` (cancel), unless the caller passes
# ``persist_empty=True`` to force a canonical empty/null-score snapshot (the
# worker's clean terminalization). There is deliberately no separate precheck
# (that would be a TOCTOU race against membership/analysis changes).
from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import Row, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_acquisition import (
    CORPUS_EXCLUSION_ERROR_CODES,
    ERROR_ROBOTS_DENIED,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_SATISFIED,
    SCORING_VERSION,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_link_metrics import COVERAGE_FORMULA_VERSION
from app.core.config.site_health_measurement import (
    CLASSIFICATION_FORMULA_VERSION,
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
    SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1,
)
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.domain.site_health.aeo_readiness_projection import (
    build_snapshot_aeo_readiness_descriptor,
)
from app.domain.site_health.coverage import crawl_coverage
from app.domain.site_health.issue_snapshot import build_issue_snapshot
from app.domain.site_health.overview_snapshot import (
    build_overview_history,
    measurement_check_counts,
)
from app.domain.site_health.score_summary import (
    latest_task_by_url,
    load_crawl_measurement_projection,
    score_summary_payload,
)
from app.domain.site_health.web_fundamentals_projection import (
    web_fundamentals_projection,
)
from app.models.site_health.acquisition import SiteFetchAttempt
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.snapshot import SiteHealthSnapshot

__all__ = ["persist_crawl_snapshot"]


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
    crawler_access: str,
    snippet_access: str,
    task: SiteCrawlTask | None,
) -> tuple[str, str]:
    outcomes = {
        "acquisition.public_representation": representation,
        "search.indexability": indexing,
        "search.crawler_access": crawler_access,
        "search.snippet_access": snippet_access,
    }
    critical = {
        checkpoint_id: outcomes.get(checkpoint_id, "unknown")
        for checkpoint_id in SEARCH_ELIGIBILITY_CRITICAL_CHECKPOINTS_1
    }
    if any(
        outcome in ("missing", RULE_OUTCOME_MISSING) for outcome in critical.values()
    ):
        return "blocked", "blocked"
    if all(
        outcome in ("satisfied", RULE_OUTCOME_SATISFIED)
        for outcome in critical.values()
    ):
        return "eligible", "audited"
    if (
        task is not None
        and task.status == TASK_STATUS_FAILED
        and task.error_code in CORPUS_EXCLUSION_ERROR_CODES
    ):
        return "excluded", "excluded"
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
    crawler_access: SiteRuleEvaluation | None,
    snippet_access: SiteRuleEvaluation | None,
    task: SiteCrawlTask | None,
    attempt: SiteFetchAttempt | None,
    evaluation: SiteRuleEvaluation | None,
) -> dict:
    representation_checkpoint = {
        "checkpoint_id": "acquisition.public_representation",
        "outcome": representation,
        "reason": representation_reason,
        "source_task_id": str(task.id) if task else None,
        "source_attempt_id": str(attempt.id) if attempt else None,
        "source_artifact_id": (
            str(task.result_artifact_id) if task and task.result_artifact_id else None
        ),
    }
    return {
        "site_url_id": str(site_url_id),
        "state": state,
        "checkpoints": [
            representation_checkpoint,
            _evaluation_checkpoint("search.crawler_access", crawler_access),
            _evaluation_checkpoint("search.snippet_access", snippet_access),
            _evaluation_checkpoint("search.indexability", evaluation, outcome=indexing),
        ],
    }


def _evaluation_checkpoint(
    checkpoint_id: str,
    evaluation: SiteRuleEvaluation | None,
    *,
    outcome: str | None = None,
) -> dict:
    if evaluation is None:
        return {
            "checkpoint_id": checkpoint_id,
            "outcome": outcome or "unknown",
            "reason": "analysis_missing",
            "source_analysis_id": None,
            "source_evaluation_id": None,
        }
    return {
        "checkpoint_id": checkpoint_id,
        "outcome": outcome or evaluation.outcome,
        "reason": evaluation.reason_code,
        "source_analysis_id": str(evaluation.analysis_id),
        "source_evaluation_id": str(evaluation.id),
    }


def _eligibility_rollup(
    selected_ids: list[uuid.UUID],
    *,
    tasks: dict[uuid.UUID, SiteCrawlTask],
    attempts: dict[uuid.UUID, SiteFetchAttempt],
    indexability: dict[uuid.UUID, SiteRuleEvaluation],
    crawler_access: SiteRuleEvaluation | None,
    snippet_access: dict[uuid.UUID, SiteRuleEvaluation],
) -> tuple[dict[str, int], list[dict], dict[str, int]]:
    totals = {"eligible": 0, "blocked": 0, "unknown": 0, "excluded": 0}
    reasons: list[dict] = []
    statuses = {
        "audited": 0,
        "blocked": 0,
        "excluded": 0,
        "error": 0,
        "pending": 0,
    }
    for site_url_id in selected_ids:
        task = tasks.get(site_url_id)
        attempt = attempts.get(task.id) if task else None
        evaluation = indexability.get(site_url_id)
        snippet_evaluation = snippet_access.get(site_url_id)
        representation, representation_reason = _representation(task)
        indexing = evaluation.outcome if evaluation else "unknown"
        crawler_outcome = crawler_access.outcome if crawler_access else "unknown"
        snippet_outcome = (
            snippet_evaluation.outcome if snippet_evaluation else "unknown"
        )
        state, status = _eligibility_state(
            representation, indexing, crawler_outcome, snippet_outcome, task
        )
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
                    crawler_access=crawler_access,
                    snippet_access=snippet_evaluation,
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
    latest_tasks = latest_task_by_url(tasks)
    task_ids = sorted((task.id for task in latest_tasks.values()), key=str)
    attempts = (
        list(
            await session.scalars(
                select(SiteFetchAttempt)
                .where(
                    SiteFetchAttempt.crawl_id == crawl.id,
                    SiteFetchAttempt.workspace_id == crawl.workspace_id,
                    SiteFetchAttempt.task_id.in_(task_ids),
                )
                .order_by(
                    SiteFetchAttempt.task_id,
                    SiteFetchAttempt.attempt_number,
                    SiteFetchAttempt.request_ordinal,
                    SiteFetchAttempt.id,
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
                    SiteRuleEvaluation.rule_id.in_(
                        (
                            "technical.indexable",
                            "search.crawler_access",
                            "search.snippet_access",
                        )
                    ),
                )
                .order_by(SitePageAnalysis.site_url_id, SiteRuleEvaluation.id)
            )
        ).all()
    indexability: dict[uuid.UUID, SiteRuleEvaluation] = {}
    snippet_access: dict[uuid.UUID, SiteRuleEvaluation] = {}
    crawler_access: SiteRuleEvaluation | None = None
    for site_url_id, evaluation in evaluation_rows:
        if evaluation.rule_id == "technical.indexable":
            indexability[site_url_id] = evaluation
        elif evaluation.rule_id == "search.snippet_access":
            snippet_access[site_url_id] = evaluation
        elif evaluation.rule_id == "search.crawler_access":
            crawler_access = evaluation
    totals, reasons, status_counts = _eligibility_rollup(
        selected_ids,
        tasks=latest_tasks,
        attempts=latest_attempts,
        indexability=indexability,
        crawler_access=crawler_access,
        snippet_access=snippet_access,
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
        persist when the frozen classification projection has expected pages,
        even if none completed analysis. Otherwise write neither projection and
        return ``False`` so a cancel with no measurement or classification
        evidence keeps the terminal/selection state instead of an empty
        dashboard.
      - ``persist_empty=True`` (used by the worker's clean terminalization):
        still write the explicit empty/null-score snapshot + projection, so an
        empty-plan crawl terminalizes with a canonical (zeroed) snapshot.

    Returns ``True`` only when this transaction inserted both projections;
    ``False`` for an empty aggregate or an immutable-snapshot replay.
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

    projection = await load_crawl_measurement_projection(session, crawl=crawl)
    rows = projection.rows

    # A cancellation with no completed analysis still has terminal measurement
    # evidence when supported HTML entered classification. Preserve that frozen
    # expected/error cohort and its task provenance instead of returning early.
    classification = projection.classification
    if not rows and not persist_empty and classification.expected_page_count <= 0:
        return False

    analysis_ids = projection.analysis_ids
    artifact_ids = projection.artifact_ids
    evaluation_rows = projection.evaluation_rows
    aggregate = projection.aggregate
    measured_check_count, expected_check_count = measurement_check_counts(
        evaluation_rows
    )
    # Issue severity/category rollups for this crawl.
    evaluation_ids = [row.id for row in evaluation_rows]
    issues = await build_issue_snapshot(session, crawl=crawl, analysis_ids=analysis_ids)

    selected_ids = projection.selected_ids
    selected_url_count = len(selected_ids)

    analyzer_version = crawl.analyzer_version or ANALYZER_VERSION
    scoring_version = crawl.scoring_version or SCORING_VERSION
    coverage = await crawl_coverage(session, crawl=crawl)
    coverage_evidence = dict(coverage.evidence)
    coverage_evidence.update(
        {
            "measured_check_count": measured_check_count,
            "expected_check_count": expected_check_count,
        }
    )
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
    web_fundamentals = await web_fundamentals_projection(
        session,
        workspace_id=crawl.workspace_id,
        analysis_ids=analysis_ids,
        artifact_ids=artifact_ids,
    )
    aeo_readiness_diagnostic = build_snapshot_aeo_readiness_descriptor(
        crawl=crawl,
        aggregate=aggregate,
        coverage_state=coverage.state,
        evaluations=evaluation_rows,
        analysis_rows=rows,
        scoring_version=scoring_version,
        analyzer_version=analyzer_version,
    )
    observed_at = datetime.now(UTC)
    trend, change_summary = await build_overview_history(
        session,
        crawl=crawl,
        analyzer_version=analyzer_version,
        scoring_version=scoring_version,
        current_metrics={
            "web_fundamentals_score": aggregate.web_fundamentals_score,
            "web_fundamentals_coverage": aggregate.web_fundamentals_coverage,
            "aeo_readiness_score": aggregate.aeo_readiness_score,
            "aeo_measurement_coverage": aggregate.aeo_measurement_coverage,
        },
        scored_page_count_by_kind=classification.scored_page_count_by_kind,
        observed_at=observed_at,
    )

    # One immutable snapshot per crawl. ``ON CONFLICT DO NOTHING`` makes this
    # safe if the worker and a cancel both reach terminalization. RETURNING
    # identifies the one transaction allowed to write the matching crawl
    # summary; a losing replay must not diverge the two projections.
    inserted_snapshot_id = await session.scalar(
        pg_insert(SiteHealthSnapshot)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            selected_url_count=selected_url_count,
            analyzed_url_count=aggregate.analyzed_url_count,
            web_fundamentals_score=aggregate.web_fundamentals_score,
            web_fundamentals_coverage=aggregate.web_fundamentals_coverage,
            web_fundamentals_state=aggregate.web_fundamentals_state,
            aeo_readiness_score=aggregate.aeo_readiness_score,
            aeo_measurement_coverage=aggregate.aeo_measurement_coverage,
            aeo_measurement_state=aggregate.aeo_measurement_state,
            classified_page_count=classification.classified_page_count,
            other_page_count=classification.other_page_count,
            classification_error_page_count=classification.error_page_count,
            classification_expected_page_count=classification.expected_page_count,
            classification_coverage=classification.coverage,
            classification_state=classification.state,
            classification_reason_groups=classification.reason_groups,
            classification_formula_version=CLASSIFICATION_FORMULA_VERSION,
            scored_page_kind_set=classification.scored_page_kind_set,
            scored_page_count_by_kind=classification.scored_page_count_by_kind,
            readiness_dimensions=list(aggregate.readiness_dimensions),
            aeo_readiness_diagnostic=aeo_readiness_diagnostic,
            search_eligibility=search_eligibility,
            eligibility_totals=eligibility_totals,
            eligibility_reasons=eligibility_reasons,
            status_counts=status_counts,
            top_issues=issues.top_issues,
            web_fundamentals=web_fundamentals,
            trend=trend,
            change_summary=change_summary,
            issue_count=issues.issue_count,
            severity_counts=issues.severity_counts,
            category_counts=issues.category_counts,
            technical_defect_count=issues.technical_defect_count,
            technical_defect_affected_page_count=(
                issues.technical_defect_affected_page_count
            ),
            aeo_readiness_gap_count=issues.aeo_readiness_gap_count,
            aeo_readiness_gap_affected_page_count=(
                issues.aeo_readiness_gap_affected_page_count
            ),
            coverage_state=coverage.state,
            coverage_evidence=coverage_evidence,
            coverage_formula_version=COVERAGE_FORMULA_VERSION,
            source_analysis_ids=analysis_ids,
            source_artifact_ids=artifact_ids,
            source_evaluation_ids=evaluation_ids,
            source_task_ids=source_task_ids,
            source_attempt_ids=source_attempt_ids,
            classification_source_analysis_ids=classification.source_analysis_ids,
            classification_source_artifact_ids=classification.source_artifact_ids,
            classification_source_task_ids=classification.source_task_ids,
            analyzer_version=analyzer_version,
            scoring_version=scoring_version,
            profile_version=PROFILE_VERSION,
            schema_contract_version=SCHEMA_CONTRACT_VERSION,
            presentation_version=PRESENTATION_VERSION,
            created_at=observed_at,
        )
        .on_conflict_do_nothing(
            constraint="uq_site_health_snapshot_crawl",
        )
        .returning(SiteHealthSnapshot.id)
    )
    if inserted_snapshot_id is None:
        return False
    crawl.score_summary = score_summary_payload(
        projection,
        selected_count=selected_url_count,
        issue_count=issues.issue_count,
    )
    crawl.score_summary["search_eligibility"] = search_eligibility
    return True
