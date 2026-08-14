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
from app.domain.demand.projection import (
    DemandSignalCandidate,
    SearchDemandInput,
    detect_search_signals,
    stable_hash,
)
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
    return DemandSnapshot(
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        window_start=window_start,
        window_end=window_end,
        source_hash=source_hash,
        prior_snapshot_id=prior.id if prior else None,
        source_artifact_ids=artifact_ids,
        source_metric_row_ids=metric_ids,
        coverage={"search": "observed" if traffic else "unavailable"},
        summary={
            "signal_count": len(candidates),
            "counts_by_type": counts,
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


async def recompute_demand(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    if task.project_id is None:
        raise ValueError("demand snapshot refresh requires project_id")
    payload = task.payload or {}
    window_start = date.fromisoformat(str(payload["window_start"]))
    window_end = date.fromisoformat(str(payload["window_end"]))
    async with session_factory() as session:
        traffic, search_inputs = await _traffic_source(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
        )
        candidates = detect_search_signals(search_inputs)
        metric_ids = sorted(
            {item for row in search_inputs for item in row.source_metric_row_ids}
        )
        artifact_ids = sorted(
            {item for row in search_inputs for item in row.source_artifact_ids}
        )
        source_material = _source_material(
            window_start=window_start,
            window_end=window_end,
            traffic=traffic,
            search_inputs=search_inputs,
        )
        source_hash = stable_hash(source_material)
        if await session.scalar(
            select(DemandSnapshot.id).where(
                DemandSnapshot.project_id == task.project_id,
                DemandSnapshot.source_hash == source_hash,
            )
        ):
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
        )
        session.add(snapshot)
        await session.flush()
        _add_signals(session, task=task, snapshot=snapshot, candidates=candidates)
        from app.domain.opportunities.service import enqueue_opportunity_refresh

        await enqueue_opportunity_refresh(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            trigger_kind="demand_snapshot",
            trigger_id=snapshot.id,
        )
        await session.commit()


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
    return stable_hash(
        _source_material(
            window_start=window_start,
            window_end=window_end,
            traffic=traffic,
            search_inputs=search_inputs,
        )
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
