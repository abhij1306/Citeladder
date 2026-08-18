"""Queued Demand projection writes and projection-only reads."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.demand import (
    DEMAND_ANALYZER_VERSION,
    DEMAND_FORMULA_VERSION,
    DEMAND_LIST_MAX_LIMIT,
    DEMAND_RULE_VERSION,
)
from app.domain.demand.detector_source import (
    classification_revision_material,
    load_query_detector_inputs,
)
from app.domain.demand.projection import (
    DemandSignalCandidate,
    DetectorEvaluation,
    SearchDemandInput,
    detect_search_signals,
    detect_striking_distance,
    stable_hash,
)
from app.domain.demand.query_detectors import (
    detect_cannibalization,
    detect_property_relative_ctr_gap,
    detect_query_trends,
)
from app.domain.demand.query_evidence import (
    build_query_evidence,
    query_evidence_source_revision,
)
from app.domain.demand.query_evidence_reads import latest_query_evidence_snapshot
from app.models.analytics import AnalyticsTask
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot


async def _traffic_source(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> tuple[TrafficSnapshot | None, list[SearchDemandInput]]:
    snapshot = await session.scalar(
        select(TrafficSnapshot)
        .where(
            TrafficSnapshot.workspace_id == workspace_id,
            TrafficSnapshot.project_id == project_id,
            TrafficSnapshot.window_start == window_start,
            TrafficSnapshot.window_end == window_end,
            TrafficSnapshot.granularity == "day",
        )
        .order_by(TrafficSnapshot.created_at.desc(), TrafficSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return None, []
    query_rows = list(
        (
            await session.scalars(
                select(TrafficQueryStat).where(
                    TrafficQueryStat.workspace_id == workspace_id,
                    TrafficQueryStat.project_id == project_id,
                    TrafficQueryStat.snapshot_id == snapshot.id,
                )
            )
        ).all()
    )
    page_rows = list(
        (
            await session.scalars(
                select(TrafficPageStat).where(
                    TrafficPageStat.workspace_id == workspace_id,
                    TrafficPageStat.project_id == project_id,
                    TrafficPageStat.snapshot_id == snapshot.id,
                )
            )
        ).all()
    )
    inputs = _search_inputs(query_rows, page_rows)
    return snapshot, inputs


def _search_inputs(
    query_rows: list[TrafficQueryStat], page_rows: list[TrafficPageStat]
) -> list[SearchDemandInput]:
    inputs: list[SearchDemandInput] = []
    for kind, target, row in [
        *(("query", row.normalized_query, row) for row in query_rows),
        *(("page", row.canonical_url, row) for row in page_rows),
    ]:
        row = cast(Any, row)
        metrics = row.metrics or {}
        impressions = metrics.get("impressions")
        clicks = metrics.get("clicks")
        if isinstance(impressions, int | float) and isinstance(clicks, int | float):
            inputs.append(
                SearchDemandInput(
                    tuple(row.source_metric_row_ids or []),
                    tuple(row.source_artifact_ids or []),
                    kind,
                    target,
                    int(impressions),
                    int(clicks),
                )
            )
    return inputs


def _source_material(
    *,
    window_start: date,
    window_end: date,
    traffic: TrafficSnapshot | None,
    search_inputs: list[SearchDemandInput],
) -> dict[str, Any]:
    metric_ids = sorted(
        {item for row in search_inputs for item in row.source_metric_row_ids}
    )
    return {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "traffic_snapshot_id": str(traffic.id) if traffic else None,
        "metric_ids": metric_ids,
        "analyzer_version": DEMAND_ANALYZER_VERSION,
        "formula_version": DEMAND_FORMULA_VERSION,
    }


def _snapshot_row(
    *,
    task: AnalyticsTask,
    window_start: date,
    window_end: date,
    source_hash: str,
    traffic: TrafficSnapshot | None,
    candidates: list[DemandSignalCandidate],
    source_ids: tuple[list[str], list[str]],
    prior: DemandSnapshot | None,
    detector_evaluations: dict[str, DetectorEvaluation],
) -> DemandSnapshot:
    metric_ids, artifact_ids = source_ids
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.signal_type] = counts.get(candidate.signal_type, 0) + 1
    comparison = None
    if prior is not None:
        comparison = {
            "prior_snapshot_id": str(prior.id),
            "signal_count_delta": len(candidates)
            - int((prior.summary or {}).get("signal_count", 0)),
            "causality": "not_asserted",
        }
    detector_summary = {
        name: {
            "state": evaluation.state,
            "counts_by_classification": evaluation.counts_by_classification,
            "limitations": list(evaluation.limitations),
        }
        for name, evaluation in sorted(detector_evaluations.items())
    }
    query_state = detector_evaluations["striking_distance"].state
    return DemandSnapshot(
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        window_start=window_start,
        window_end=window_end,
        source_hash=source_hash,
        prior_snapshot_id=prior.id if prior else None,
        source_artifact_ids=artifact_ids,
        source_metric_row_ids=metric_ids,
        coverage={
            "search": "observed" if traffic else "unavailable",
            "query_evidence": query_state,
        },
        summary={
            "signal_count": len(candidates),
            "counts_by_type": counts,
            "detectors": detector_summary,
        },
        comparison=comparison,
        formula_version=DEMAND_FORMULA_VERSION,
        analyzer_version=DEMAND_ANALYZER_VERSION,
    )


def _add_signals(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    snapshot: DemandSnapshot,
    candidates: list[DemandSignalCandidate],
) -> None:
    session.add_all(
        [
            DemandSignal(
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                snapshot_id=snapshot.id,
                identity_hash=candidate.identity_hash,
                signal_type=candidate.signal_type,
                state=candidate.state,
                topic_cluster=candidate.topic_cluster,
                page_url=candidate.page_url,
                evidence=candidate.evidence,
                metrics=candidate.metrics,
                coverage=candidate.coverage,
                limitations=candidate.limitations,
                priority_score=candidate.priority_score,
                priority_inputs=candidate.priority_inputs,
                analyzer_version=DEMAND_ANALYZER_VERSION,
                rule_version=DEMAND_RULE_VERSION,
                formula_version=DEMAND_FORMULA_VERSION,
            )
            for candidate in candidates
        ]
    )


def _evaluate_query_detectors(
    rows: list[Any], *, window_end: date
) -> dict[str, DetectorEvaluation]:
    return {
        "striking_distance": detect_striking_distance(rows),
        "cannibalization": detect_cannibalization(rows),
        "property_relative_ctr_gap": detect_property_relative_ctr_gap(rows),
        "query_trends": detect_query_trends(rows, window_end=window_end),
    }


def _all_candidates(
    search_inputs: list[SearchDemandInput],
    evaluations: dict[str, DetectorEvaluation],
) -> list[DemandSignalCandidate]:
    candidates = detect_search_signals(search_inputs)
    for evaluation in evaluations.values():
        candidates.extend(evaluation.candidates)
    return candidates


def _source_ids(
    search_inputs: list[SearchDemandInput], query_ids: list, query_artifact_ids: list
) -> tuple[list[str], list[str]]:
    metric_ids = {str(item) for item in query_ids}
    artifact_ids = {str(item) for item in query_artifact_ids}
    for row in search_inputs:
        metric_ids.update(row.source_metric_row_ids)
        artifact_ids.update(row.source_artifact_ids)
    return sorted(metric_ids), sorted(artifact_ids)


async def recompute_demand(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    if task.project_id is None:
        raise ValueError("demand snapshot refresh requires project_id")
    payload = task.payload or {}
    window_start = date.fromisoformat(str(payload["window_start"]))
    window_end = date.fromisoformat(str(payload["window_end"]))
    async with session_factory() as session:
        query_evidence = await build_query_evidence(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
        )
        traffic, search_inputs = await _traffic_source(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
        )
        query_detector_inputs = await load_query_detector_inputs(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            snapshot=query_evidence,
        )
        detector_evaluations = _evaluate_query_detectors(
            query_detector_inputs, window_end=window_end
        )
        candidates = _all_candidates(search_inputs, detector_evaluations)
        classification_material = await classification_revision_material(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            search_inputs=search_inputs,
            query_inputs=query_detector_inputs,
        )
        metric_ids, artifact_ids = _source_ids(
            search_inputs,
            query_evidence.source_metric_row_ids,
            query_evidence.source_artifact_ids,
        )
        source_material = {
            "traffic": _source_material(
                window_start=window_start,
                window_end=window_end,
                traffic=traffic,
                search_inputs=search_inputs,
            ),
            "query_evidence_revision": query_evidence.source_hash[:24],
            "query_classifications": classification_material,
        }
        source_hash = stable_hash(source_material)
        existing_snapshot_id = await session.scalar(
            select(DemandSnapshot.id).where(
                DemandSnapshot.workspace_id == task.workspace_id,
                DemandSnapshot.project_id == task.project_id,
                DemandSnapshot.source_hash == source_hash,
            )
        )
        if existing_snapshot_id is not None:
            await _enqueue_downstream_opportunity(
                session, task=task, demand_snapshot_id=existing_snapshot_id
            )
            await session.commit()
            return
        prior = await session.scalar(
            select(DemandSnapshot)
            .where(
                DemandSnapshot.workspace_id == task.workspace_id,
                DemandSnapshot.project_id == task.project_id,
            )
            .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
            .limit(1)
        )
        snapshot = _snapshot_row(
            task=task,
            window_start=window_start,
            window_end=window_end,
            source_hash=source_hash,
            traffic=traffic,
            candidates=candidates,
            source_ids=(metric_ids, artifact_ids),
            prior=prior,
            detector_evaluations=detector_evaluations,
        )
        session.add(snapshot)
        await session.flush()
        _add_signals(session, task=task, snapshot=snapshot, candidates=candidates)
        await _enqueue_downstream_opportunity(
            session, task=task, demand_snapshot_id=snapshot.id
        )
        await session.commit()


async def _enqueue_downstream_opportunity(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    demand_snapshot_id: uuid.UUID,
) -> None:
    """Continue Demand's DAG using an optional originating trigger."""
    from app.domain.opportunities.queue import enqueue_opportunity_refresh

    if task.project_id is None:
        raise ValueError("demand snapshot refresh requires project_id")
    owns_snapshot = await session.scalar(
        select(DemandSnapshot.id).where(
            DemandSnapshot.id == demand_snapshot_id,
            DemandSnapshot.workspace_id == task.workspace_id,
            DemandSnapshot.project_id == task.project_id,
        )
    )
    if owns_snapshot is None:
        raise ValueError("demand snapshot is outside the task workspace/project")
    payload = task.payload or {}
    trigger_kind = str(payload.get("downstream_trigger_kind") or "demand_snapshot")
    raw_trigger_id = payload.get("downstream_trigger_id")
    trigger_id = (
        uuid.UUID(str(raw_trigger_id)) if raw_trigger_id else demand_snapshot_id
    )
    await enqueue_opportunity_refresh(
        session,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
    )


async def latest_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> DemandSnapshot | None:
    return await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )


async def demand_source_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> str:
    """Stable queue revision for the exact currently persisted source set."""
    traffic, search_inputs = await _traffic_source(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    query_revision = await query_evidence_source_revision(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    query_evidence = await latest_query_evidence_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    query_detector_inputs = (
        await load_query_detector_inputs(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            snapshot=query_evidence,
        )
        if query_evidence is not None
        else []
    )
    classification_material = await classification_revision_material(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        search_inputs=search_inputs,
        query_inputs=query_detector_inputs,
    )
    return stable_hash(
        {
            "traffic": _source_material(
                window_start=window_start,
                window_end=window_end,
                traffic=traffic,
                search_inputs=search_inputs,
            ),
            "query_evidence_revision": query_revision,
            "query_classifications": classification_material,
        }
    )[:24]


async def list_signals(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    limit: int = DEMAND_LIST_MAX_LIMIT,
) -> list[DemandSignal]:
    return list(
        (
            await session.scalars(
                select(DemandSignal)
                .where(
                    DemandSignal.workspace_id == workspace_id,
                    DemandSignal.project_id == project_id,
                    DemandSignal.snapshot_id == snapshot_id,
                )
                .order_by(
                    DemandSignal.priority_score.desc().nullslast(), DemandSignal.id
                )
                .limit(limit)
            )
        ).all()
    )
