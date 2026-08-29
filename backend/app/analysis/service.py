# Analysis + finalize wiring (B6, invariants 4/7/9).
#
# Adapts the reference ``ai_visibility`` per-execution ``_analyze`` +
# ``_finalize_run`` aggregation to CiteLadder's queue model:
#   - ``analyze_task`` deterministically scores ONE completed execution from its
#     persisted answer + citations (no provider call — invariant 9) and persists
#     the derived rows (``ResponseAnalysis`` + ``BrandMention`` /
#     ``CompetitorMention`` / ``Citation``), each stamped with the raw-artifact
#     provenance + ``analyzer_version`` (invariant 4). Idempotent per task.
#   - ``finalize_audit_analysis`` aggregates a single ``MetricSnapshot`` from the
#     persisted analyses (never re-reading providers — invariant 7), writes the
#     audit ``summary`` + ``analyzer_version``, and drives ANALYZING -> REPORTING
#     -> COMPLETED / PARTIALLY_COMPLETED via the state machine.
#
# Sentiment + average position are NOT computed (decision B-2): they are exposed
# as null on the derived rows + in the aggregate.
from __future__ import annotations

import uuid
from collections.abc import Collection, Sequence
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.entity_assessment import assess_entities
from app.analysis.observed_competitors import (
    persist_observed_competitors as _persist_observed_competitors,
)
from app.analysis.scoring import (
    ScoringConfig,
    aggregate_run,
    classify_citation,
    score_execution,
)
from app.analysis.trend_metrics import _prompt_trend_values
from app.core.config.analysis import (
    ANALYZER_VERSION,
    PROMPT_DECLINE_HISTORY_CANDIDATE_LIMIT,
    PROMPT_DECLINE_MIN_ENGINES,
    PROMPT_DECLINE_WINDOW_MOVEMENTS,
    SCORING_RULE_VERSION,
)
from app.core.config.audits import (
    AUDIT_STATUS_ANALYZING,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
    AUDIT_STATUS_REPORTING,
    EVENT_AUDIT_COMPLETED,
)
from app.core.config.prompts import ORGANIC_PROMPT_COHORTS
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.prompts.normalization import prompt_text_hash
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    MetricSnapshot,
    PromptMetricSnapshot,
    ResponseAnalysis,
)
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask, RawResponseArtifact

# Deterministic classification labels for a source citation (invariant 4).
CITATION_OWNED = "owned"
CITATION_UNINTENDED = "unintended"
CITATION_COMPETITOR = "competitor"
CITATION_THIRD_PARTY = "third_party"


def build_scoring_config(configuration: dict | None) -> ScoringConfig:
    """Build the deterministic scorer config from the audit's frozen identity.

    The audit froze the brand/competitor/domain identity into ``configuration``
    at creation (via ``project_scoring_identity``); scoring reads that frozen
    copy, never live config (determinism, invariant 9).
    """
    return ScoringConfig.from_project(configuration or {})


def _classification(classified: dict) -> str:
    if classified.get("is_owned"):
        return CITATION_OWNED
    if classified.get("is_unintended"):
        return CITATION_UNINTENDED
    if classified.get("matched_competitor"):
        return CITATION_COMPETITOR
    return CITATION_THIRD_PARTY


def _response_analysis(
    *, task: AuditTask, score: dict, cohort: str, entity_assessments: list[dict]
) -> ResponseAnalysis:
    return ResponseAnalysis(
        workspace_id=task.workspace_id,
        audit_id=task.audit_id,
        task_id=task.id,
        artifact_id=task.result_artifact_id,
        analyzer_version=ANALYZER_VERSION,
        scoring_rule_version=SCORING_RULE_VERSION,
        logical_engine=task.logical_engine,
        transport_provider=task.transport_provider,
        transport_model=task.transport_model,
        prompt_index=task.prompt_index,
        repetition=task.repetition,
        prompt_class=str(score.get("prompt_class", "")),
        cohort=cohort,
        brand_mentioned=bool(score.get("brand_mentioned")),
        brand_first_offset=score.get("brand_first_offset"),
        owned_domain_cited=bool(score.get("owned_domain_cited")),
        owned_citation_count=int(score.get("owned_citation_count") or 0),
        unintended_domain_cited=bool(score.get("unintended_domain_cited")),
        citation_count=int(score.get("citation_count") or 0),
        search_used=bool(score.get("search_used")),
        search_query_count=int(score.get("search_query_count") or 0),
        sentiment=None,
        avg_position=None,
        score=score,
        entity_assessments=entity_assessments,
    )


def _persist_analysis_rows(
    session: AsyncSession,
    *,
    task: AuditTask,
    analysis: ResponseAnalysis,
    score: dict,
    citations: list[dict],
    config: ScoringConfig,
) -> None:
    if score.get("brand_mentioned"):
        session.add(
            BrandMention(
                workspace_id=task.workspace_id,
                audit_id=task.audit_id,
                analysis_id=analysis.id,
                artifact_id=task.result_artifact_id,
                analyzer_version=ANALYZER_VERSION,
                brand_name=config.brand_name,
                first_offset=score.get("brand_first_offset"),
            )
        )
    for name in score.get("competitors_mentioned") or []:
        session.add(
            CompetitorMention(
                workspace_id=task.workspace_id,
                audit_id=task.audit_id,
                analysis_id=analysis.id,
                artifact_id=task.result_artifact_id,
                analyzer_version=ANALYZER_VERSION,
                competitor_name=name,
            )
        )
    for ordinal, citation in enumerate(citations):
        classified = classify_citation(citation, config)
        session.add(
            Citation(
                workspace_id=task.workspace_id,
                audit_id=task.audit_id,
                analysis_id=analysis.id,
                artifact_id=task.result_artifact_id,
                analyzer_version=ANALYZER_VERSION,
                ordinal=int(citation.get("ordinal", ordinal)),
                url=str(citation.get("url") or ""),
                title=str(citation.get("title") or ""),
                domain=str(classified.get("domain") or ""),
                classification=_classification(classified),
                is_owned=bool(classified.get("is_owned")),
                is_unintended=bool(classified.get("is_unintended")),
                matched_competitor=classified.get("matched_competitor"),
            )
        )


async def analyze_task(
    session: AsyncSession,
    *,
    task: AuditTask,
    config: ScoringConfig,
) -> ResponseAnalysis | None:
    """Score one completed execution and persist its derived rows.

    Deterministic + idempotent: if an analysis already exists for this task it is
    returned unchanged. Caller owns the commit.
    """
    existing = await session.scalar(
        select(ResponseAnalysis).where(ResponseAnalysis.task_id == task.id)
    )
    if existing is not None:
        return existing

    citations = list(task.citations or [])
    search_events = list(task.search_events or [])
    provider_metadata = task.provider_metadata or {}
    query_text_available = bool(provider_metadata.get("query_text_available", True))
    score = score_execution(
        answer_text=task.answer_text or "",
        search_events=search_events,
        citations=citations,
        search_used=bool(task.search_used),
        config=config,
        prompt_text=task.prompt_text or "",
        query_text_available=query_text_available,
    )
    prompt_snapshot = await session.get(AuditPromptSnapshot, task.prompt_snapshot_id)
    cohort = prompt_snapshot.cohort if prompt_snapshot is not None else "core"
    score["cohort"] = cohort

    analysis = _response_analysis(
        task=task,
        score=score,
        cohort=cohort,
        entity_assessments=assess_entities(task.answer_text or "", config),
    )
    session.add(analysis)
    await session.flush()  # assign analysis.id for child rows
    _persist_analysis_rows(
        session,
        task=task,
        analysis=analysis,
        score=score,
        citations=citations,
        config=config,
    )
    return analysis


async def _execution_dicts(
    session: AsyncSession, *, audit_id: uuid.UUID
) -> tuple[list[dict], dict[str, list[dict]], list[ResponseAnalysis]]:
    """Build the aggregate input from persisted analyses (invariant 7).

    Reads only persisted ``ResponseAnalysis`` + ``Citation`` + ``AuditTask``
    rows — never a provider. Re-attaches each execution's immutable artifact
    usage and task metadata so token/cost aggregation is not lost. Returns
    ``(all_execution_dicts, per_engine_execution_dicts, analyses)``.
    """
    analyses = list(
        (
            await session.scalars(
                select(ResponseAnalysis).where(ResponseAnalysis.audit_id == audit_id)
            )
        ).all()
    )
    # prompt_index -> (text, theme) from the frozen prompt snapshots.
    snapshots = list(
        (
            await session.scalars(
                select(AuditPromptSnapshot).where(
                    AuditPromptSnapshot.audit_id == audit_id
                )
            )
        ).all()
    )
    prompt_meta = {
        snap.prompt_index: (snap.text, snap.theme, snap.cohort) for snap in snapshots
    }
    # analysis_id -> classified citation dicts (reconstructed from persisted rows).
    citation_rows = list(
        (
            await session.scalars(select(Citation).where(Citation.audit_id == audit_id))
        ).all()
    )
    citations_by_analysis: dict[uuid.UUID, list[dict]] = {}
    for row in citation_rows:
        citations_by_analysis.setdefault(row.analysis_id, []).append(
            {
                "url": row.url,
                "domain": row.domain,
                "is_owned": row.is_owned,
                "is_unintended": row.is_unintended,
                "matched_competitor": row.matched_competitor,
            }
        )
    # Task metadata carries evidence flags; immutable artifacts own usage.
    provider_metadata_by_task: dict[uuid.UUID, dict] = {}
    for task_id, provider_metadata in (
        await session.execute(
            select(AuditTask.id, AuditTask.provider_metadata).where(
                AuditTask.audit_id == audit_id
            )
        )
    ).all():
        provider_metadata_by_task[task_id] = provider_metadata or {}
    usage_by_task = await _artifact_usage_by_task(
        session,
        audit_id=audit_id,
        analyses=analyses,
    )

    all_dicts: list[dict] = []
    per_engine: dict[str, list[dict]] = {}
    for analysis in analyses:
        text, theme, cohort = prompt_meta.get(analysis.prompt_index, ("", "", "core"))
        execution = {
            "status": "completed",
            "prompt_index": analysis.prompt_index,
            "prompt_text_snapshot": text,
            "prompt_theme_snapshot": theme,
            "cohort": cohort,
            "logical_engine": analysis.logical_engine,
            "citations": citations_by_analysis.get(analysis.id, []),
            "score": analysis.score or {},
            "provider_metadata": provider_metadata_by_task.get(analysis.task_id, {}),
            "usage": usage_by_task.get(analysis.task_id, {}),
        }
        all_dicts.append(execution)
        per_engine.setdefault(analysis.logical_engine, []).append(execution)
    return all_dicts, per_engine, analyses


def _prompt_metric_rows(metrics: dict) -> list[dict]:
    rows = list(metrics.get("per_prompt") or [])
    rows.extend((metrics.get("brand_diagnostic") or {}).get("per_prompt") or [])
    rows.extend((metrics.get("comparison") or {}).get("per_prompt") or [])
    return rows


async def _previous_prompt_metrics(
    session: AsyncSession,
    *,
    audit: Audit,
    identities: dict[tuple[str, str], set[str]],
) -> dict[tuple[str, str], list[PromptMetricSnapshot]]:
    if not identities:
        return {}
    candidates = list(
        (
            await session.scalars(
                select(PromptMetricSnapshot)
                .join(Audit, Audit.id == PromptMetricSnapshot.audit_id)
                .where(
                    PromptMetricSnapshot.project_id == audit.project_id,
                    PromptMetricSnapshot.audit_id != audit.id,
                    PromptMetricSnapshot.analyzer_version == ANALYZER_VERSION,
                    PromptMetricSnapshot.scoring_rule_version == SCORING_RULE_VERSION,
                    Audit.benchmark_mode == audit.benchmark_mode,
                    Audit.audit_scope == audit.audit_scope,
                    Audit.completed_at.is_not(None),
                    or_(
                        *(
                            and_(
                                PromptMetricSnapshot.prompt_identity == identity,
                                PromptMetricSnapshot.cohort == cohort,
                            )
                            for identity, cohort in identities.keys()
                        )
                    ),
                )
                .order_by(
                    Audit.completed_at.desc(),
                    Audit.id.desc(),
                )
                .limit(PROMPT_DECLINE_HISTORY_CANDIDATE_LIMIT * len(identities))
            )
        ).all()
    )
    grouped: dict[tuple[str, str], list[PromptMetricSnapshot]] = {
        key: [] for key in identities
    }
    for item in candidates:
        key = (item.prompt_identity, item.cohort)
        current_engines = identities.get(key, set())
        if (
            key in grouped
            and len(current_engines.intersection(item.per_engine_scores))
            >= PROMPT_DECLINE_MIN_ENGINES
            and len(grouped[key]) < PROMPT_DECLINE_WINDOW_MOVEMENTS
        ):
            grouped[key].append(item)
    return grouped


async def _persist_prompt_metric_snapshots(
    session: AsyncSession,
    *,
    audit: Audit,
    metrics: dict,
    analyses: list[ResponseAnalysis],
    prompt_snapshots: list[AuditPromptSnapshot],
    engine_count: int,
) -> None:
    snapshots_by_index = {row.prompt_index: row for row in prompt_snapshots}
    analyses_by_index: dict[int, list[ResponseAnalysis]] = {}
    for analysis in analyses:
        analyses_by_index.setdefault(analysis.prompt_index, []).append(analysis)
    prepared: list[tuple[dict, AuditPromptSnapshot, str, set[str]]] = []
    for row in _prompt_metric_rows(metrics):
        prompt_index = int(row.get("prompt_index") or 0)
        prompt = snapshots_by_index.get(prompt_index)
        if prompt is None:
            continue
        identity = prompt_text_hash(prompt.text)
        engines = set((row.get("per_engine_scores") or {}).keys())
        prepared.append((row, prompt, identity, engines))
    histories = await _previous_prompt_metrics(
        session,
        audit=audit,
        identities={
            (identity, prompt.cohort): engines
            for _, prompt, identity, engines in prepared
        },
    )
    for row, prompt, identity, _engines in prepared:
        session.add(
            _build_prompt_metric_snapshot(
                audit=audit,
                row=row,
                prompt=prompt,
                identity=identity,
                previous=histories.get((identity, prompt.cohort), []),
                prompt_analyses=analyses_by_index.get(prompt.prompt_index, []),
                engine_count=engine_count,
            )
        )


def _build_prompt_metric_snapshot(
    *,
    audit,
    row,
    prompt,
    identity,
    previous,
    prompt_analyses,
    engine_count,
):
    trend = _prompt_trend_values(
        previous=previous,
        row=row,
        repetitions=audit.repetitions,
        engine_count=engine_count,
    )
    return PromptMetricSnapshot(
        workspace_id=audit.workspace_id,
        project_id=audit.project_id,
        audit_id=audit.id,
        prompt_id=prompt.prompt_id,
        prompt_identity=identity,
        prompt_index=prompt.prompt_index,
        prompt_text=prompt.text,
        cohort=prompt.cohort,
        analyzer_version=ANALYZER_VERSION,
        scoring_rule_version=SCORING_RULE_VERSION,
        components=dict(row.get("score_components") or {}),
        source_analysis_ids=[str(item.id) for item in prompt_analyses],
        source_artifact_ids=[
            str(item.artifact_id)
            for item in prompt_analyses
            if item.artifact_id is not None
        ],
        **trend,
    )


async def _artifact_usage_by_task(
    session: AsyncSession, *, audit_id: uuid.UUID, analyses: list[ResponseAnalysis]
) -> dict[uuid.UUID, dict]:
    task_ids = [analysis.task_id for analysis in analyses]
    rows = await session.execute(
        select(RawResponseArtifact.task_id, RawResponseArtifact.usage).where(
            RawResponseArtifact.audit_id == audit_id,
            RawResponseArtifact.task_id.in_(task_ids),
        )
    )
    return _unique_artifact_usage(rows.tuples().all())


def _unique_artifact_usage(
    rows: Sequence[tuple[uuid.UUID, dict | None]],
) -> dict[uuid.UUID, dict]:
    usage_by_task: dict[uuid.UUID, dict] = {}
    for task_id, usage in rows:
        if task_id in usage_by_task:
            raise RuntimeError(f"multiple raw artifacts found for task {task_id}")
        usage_by_task[task_id] = usage or {}
    return usage_by_task


def _cohort_metrics(rows, config, cohort, requested):
    metrics = aggregate_run(rows, config)
    metrics["cohort"] = cohort
    metrics["coverage"] = {
        "completed": len(rows),
        "requested": requested,
        "rate": round(len(rows) / requested, 4) if requested else 0.0,
    }
    return metrics


def _cohort_projection(
    rows: list[dict], config: ScoringConfig, cohort: str, requested: int
) -> dict:
    return _cohort_metrics(
        [row for row in rows if row.get("cohort") == cohort],
        config,
        cohort,
        requested,
    )


def _per_engine_cohort_metrics(
    per_engine: dict[str, list[dict]],
    config: ScoringConfig,
    cohorts: Collection[str],
) -> dict[str, dict]:
    return {
        engine: aggregate_run(
            [row for row in rows if row.get("cohort") in cohorts], config
        )
        for engine, rows in sorted(per_engine.items())
    }


def _finalized_metrics(
    all_rows, per_engine, prompt_cohorts, engine_count, repetitions, config
):
    slot_count = engine_count * repetitions
    organic = [row for row in all_rows if row.get("cohort") in ORGANIC_PROMPT_COHORTS]
    metrics = _cohort_metrics(
        organic,
        config,
        "market_visibility",
        sum(cohort in ORGANIC_PROMPT_COHORTS for cohort in prompt_cohorts) * slot_count,
    )
    metrics["comparison"] = _cohort_projection(
        all_rows,
        config,
        "comparison",
        prompt_cohorts.count("comparison") * slot_count,
    )
    metrics["brand_diagnostic"] = _cohort_projection(
        all_rows,
        config,
        "brand_diagnostic",
        prompt_cohorts.count("brand_diagnostic") * slot_count,
    )
    metrics["per_engine"] = _per_engine_cohort_metrics(
        per_engine, config, ORGANIC_PROMPT_COHORTS
    )
    metrics["comparison"]["per_engine"] = _per_engine_cohort_metrics(
        per_engine, config, ("comparison",)
    )
    return metrics


def _composite_visibility_score(metrics):
    scores = [
        float(row.get("composite_score") or 0.0)
        for row in metrics.get("per_prompt", [])
    ]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


async def _metric_snapshot(session, audit, analyses, metrics, completed, failed):
    snapshot = await session.scalar(
        select(MetricSnapshot).where(MetricSnapshot.audit_id == audit.id)
    )
    if snapshot is None:
        snapshot = MetricSnapshot(
            workspace_id=audit.workspace_id,
            audit_id=audit.id,
            project_id=audit.project_id,
        )
        session.add(snapshot)
    snapshot.analyzer_version = ANALYZER_VERSION
    snapshot.scoring_rule_version = SCORING_RULE_VERSION
    snapshot.total_completed = completed
    snapshot.total_failed = failed
    snapshot.visibility_score = _composite_visibility_score(metrics)
    snapshot.metrics = metrics
    snapshot.source_analysis_ids = [str(item.id) for item in analyses]
    snapshot.source_artifact_ids = [
        str(item.artifact_id) for item in analyses if item.artifact_id is not None
    ]
    return snapshot


def _finish_audit(session, audit, metrics, completed, failed, visibility_score):
    audit.summary = metrics
    audit.analyzer_version = ANALYZER_VERSION
    audit.completed_count = completed
    audit.failed_count = failed
    apply_transition(
        session,
        audit=audit,
        target=AUDIT_STATUS_REPORTING,
        message="aggregating metrics",
    )
    terminal = (
        AUDIT_STATUS_PARTIALLY_COMPLETED if failed > 0 else AUDIT_STATUS_COMPLETED
    )
    apply_transition(
        session,
        audit=audit,
        target=terminal,
        message=f"audit {terminal}",
        payload={"completed": completed, "failed": failed},
    )
    audit.completed_at = audit.completed_at or datetime.now(UTC)
    record_event(
        session,
        audit_id=audit.id,
        event_type=EVENT_AUDIT_COMPLETED,
        message=f"audit {terminal}",
        payload={
            "status": terminal,
            "completed": completed,
            "failed": failed,
            "visibility_score": visibility_score,
        },
    )


async def finalize_audit_analysis(
    session: AsyncSession, *, audit: Audit
) -> MetricSnapshot | None:
    """Aggregate the ``MetricSnapshot`` and resolve the terminal status.

    Called once the audit has reached ANALYZING (execution boundary, >=1
    success). Ensures every succeeded task has an analysis, aggregates the
    metrics from persisted analyses only (invariant 7), writes the audit summary
    + provenance version, and drives ANALYZING -> REPORTING -> COMPLETED /
    PARTIALLY_COMPLETED. Caller owns the commit. Idempotent.
    """
    if audit.status != AUDIT_STATUS_ANALYZING:
        return None
    config = build_scoring_config(audit.configuration)

    # Defensively ensure every succeeded execution has a persisted analysis so
    # the aggregate always matches the per-execution signals. Measurement-only
    # (§7.1): finalize must never (re)create a skipped probe brand analysis.
    succeeded_tasks = list(
        (
            await session.scalars(
                select(AuditTask)
                .where(AuditTask.audit_id == audit.id)
                .where(AuditTask.status == TASK_STATUS_SUCCEEDED)
            )
        ).all()
    )
    for task in succeeded_tasks:
        await analyze_task(session, task=task, config=config)
    await session.flush()

    all_dicts, per_engine, analyses = await _execution_dicts(session, audit_id=audit.id)
    prompt_snapshots = list(
        (
            await session.scalars(
                select(AuditPromptSnapshot).where(
                    AuditPromptSnapshot.audit_id == audit.id
                )
            )
        ).all()
    )
    prompt_cohorts = [row.cohort for row in prompt_snapshots]
    engine_count = len(
        (
            await session.scalars(
                select(AuditTask.logical_engine)
                .where(AuditTask.audit_id == audit.id)
                .distinct()
            )
        ).all()
    )
    metrics = _finalized_metrics(
        all_dicts,
        per_engine,
        prompt_cohorts,
        engine_count,
        audit.repetitions,
        config,
    )

    completed = len(all_dicts)
    total = int(audit.requested_count or len(all_dicts))
    failed = max(0, total - completed)
    snapshot = await _metric_snapshot(
        session, audit, analyses, metrics, completed, failed
    )
    # Stable audit chronology must exist before prompt-history rows are queried.
    audit.completed_at = audit.completed_at or datetime.now(UTC)
    await _persist_prompt_metric_snapshots(
        session,
        audit=audit,
        metrics=metrics,
        analyses=analyses,
        prompt_snapshots=prompt_snapshots,
        engine_count=engine_count,
    )
    await _persist_observed_competitors(
        session,
        audit=audit,
        analyses=analyses,
        config=config,
    )

    _finish_audit(session, audit, metrics, completed, failed, snapshot.visibility_score)
    return snapshot
