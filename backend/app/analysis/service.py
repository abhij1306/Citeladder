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
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.scoring import (
    ScoringConfig,
    aggregate_run,
    classify_citation,
    score_execution,
)
from app.core.config.analysis import ANALYZER_VERSION, SCORING_RULE_VERSION
from app.core.config.audits import (
    AUDIT_STATUS_ANALYZING,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
    AUDIT_STATUS_REPORTING,
    EVENT_AUDIT_COMPLETED,
    TASK_STATUS_SUCCEEDED,
)
from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.domain.audits.state_events import apply_transition, record_event
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    MetricSnapshot,
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

    analysis = ResponseAnalysis(
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
        # Defense-in-depth (§7.1): brand-metric denominators filter on this
        # column, so even a direct/retry/legacy write path cannot leak a
        # probe analysis into brand metrics.
        shopping_surface=task.shopping_surface,
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
        # Roadmap (B-2): no LLM analysis yet, so these stay null.
        sentiment=None,
        avg_position=None,
        score=score,
    )
    session.add(analysis)
    await session.flush()  # assign analysis.id for child rows

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
    # Brand denominators are MEASUREMENT-ONLY (§7.1): probe analyses never
    # enter the overall/per-engine aggregate inputs.
    analyses = list(
        (
            await session.scalars(
                select(ResponseAnalysis).where(
                    ResponseAnalysis.audit_id == audit_id,
                    ResponseAnalysis.shopping_surface == SHOPPING_SURFACE_MEASUREMENT,
                )
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
                AuditTask.audit_id == audit_id,
                # Measurement-only: probe usage never enters brand cost/token
                # aggregation.
                AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT,
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
            "citations": citations_by_analysis.get(analysis.id, []),
            "score": analysis.score or {},
            "provider_metadata": provider_metadata_by_task.get(analysis.task_id, {}),
            "usage": usage_by_task.get(analysis.task_id, {}),
        }
        all_dicts.append(execution)
        per_engine.setdefault(analysis.logical_engine, []).append(execution)
    return all_dicts, per_engine, analyses


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
                .where(AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT)
            )
        ).all()
    )
    for task in succeeded_tasks:
        await analyze_task(session, task=task, config=config)
    await session.flush()

    all_dicts, per_engine, analyses = await _execution_dicts(session, audit_id=audit.id)
    core_dicts = [row for row in all_dicts if row.get("cohort") == "core"]
    comparison_dicts = [row for row in all_dicts if row.get("cohort") == "comparison"]
    prompt_cohorts = list(
        (
            await session.scalars(
                select(AuditPromptSnapshot.cohort).where(
                    AuditPromptSnapshot.audit_id == audit.id
                )
            )
        ).all()
    )
    engine_count = len(
        (
            await session.scalars(
                select(AuditTask.logical_engine)
                .where(AuditTask.audit_id == audit.id)
                .distinct()
            )
        ).all()
    )
    metrics = aggregate_run(core_dicts, config)
    metrics["cohort"] = "core"
    metrics["coverage"] = {
        "completed": len(core_dicts),
        "requested": prompt_cohorts.count("core") * engine_count * audit.repetitions,
    }
    requested_core = metrics["coverage"]["requested"]
    metrics["coverage"]["rate"] = (
        round(len(core_dicts) / requested_core, 4) if requested_core else 0.0
    )
    metrics["comparison"] = aggregate_run(comparison_dicts, config)
    metrics["comparison"]["cohort"] = "comparison"
    requested_comparison = (
        prompt_cohorts.count("comparison") * engine_count * audit.repetitions
    )
    metrics["comparison"]["coverage"] = {
        "completed": len(comparison_dicts),
        "requested": requested_comparison,
        "rate": (
            round(len(comparison_dicts) / requested_comparison, 4)
            if requested_comparison
            else 0.0
        ),
    }
    metrics["comparison"]["per_engine"] = {
        engine: aggregate_run(
            [row for row in rows if row.get("cohort") == "comparison"], config
        )
        for engine, rows in sorted(per_engine.items())
    }
    metrics["per_engine"] = {
        engine: aggregate_run(
            [row for row in rows if row.get("cohort") == "core"], config
        )
        for engine, rows in sorted(per_engine.items())
    }

    completed = len(all_dicts)
    total = int(audit.requested_count or len(all_dicts))
    failed = max(0, total - completed)
    visibility_score = round(float(metrics.get("brand_mention_rate") or 0.0) * 100, 2)

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
    snapshot.visibility_score = visibility_score
    snapshot.metrics = metrics
    # Invariant 4: trace the snapshot back to the exact evidence set it
    # aggregated — the ResponseAnalysis rows and their raw response artifacts.
    snapshot.source_analysis_ids = [str(a.id) for a in analyses]
    snapshot.source_artifact_ids = [
        str(a.artifact_id) for a in analyses if a.artifact_id is not None
    ]

    audit.summary = metrics
    audit.analyzer_version = ANALYZER_VERSION
    audit.completed_count = completed
    audit.failed_count = failed

    # ANALYZING -> REPORTING -> terminal.
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
    from datetime import UTC, datetime

    audit.completed_at = datetime.now(UTC)
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
    return snapshot
