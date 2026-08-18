"""Persisted audit execution performance projections."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED
from app.domain.audits.schemas import (
    AuditEnginePerformance,
    AuditPerformanceResponse,
    AuditUsageSummary,
)
from app.models.audit import Audit, AuditTask, ExecutionCostProjection


async def audit_performance(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> AuditPerformanceResponse:
    audit, tasks, costs = await _performance_rows(
        session, workspace_id=workspace_id, audit_id=audit_id
    )
    return _performance_response(audit, tasks=tasks, costs=costs)


async def _performance_rows(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> tuple[Audit, list[AuditTask], list[ExecutionCostProjection]]:
    audit = await session.scalar(
        select(Audit).where(Audit.id == audit_id, Audit.workspace_id == workspace_id)
    )
    if audit is None:
        raise LookupError("Audit not found")
    tasks = list(
        (
            await session.scalars(
                select(AuditTask).where(AuditTask.audit_id == audit_id)
            )
        ).all()
    )
    costs = list(
        (
            await session.scalars(
                select(ExecutionCostProjection).where(
                    ExecutionCostProjection.audit_id == audit_id
                )
            )
        ).all()
    )
    return audit, tasks, costs


def _performance_response(
    audit: Audit,
    *,
    tasks: list[AuditTask],
    costs: list[ExecutionCostProjection],
) -> AuditPerformanceResponse:
    completed, failed, retries, search_calls = _task_counts(tasks)
    first_result = _first_completed_at(tasks)
    projected_cost = _total_projected_cost(costs)
    return AuditPerformanceResponse(
        audit_id=audit.id,
        queue_wait_ms=_elapsed_ms(audit.started_at, audit.created_at),
        total_run_duration_ms=_elapsed_ms(audit.completed_at, audit.created_at),
        time_to_first_result_ms=_elapsed_ms(first_result, audit.created_at),
        execution_count=len(tasks),
        completed_count=completed,
        failed_count=failed,
        coverage=completed / len(tasks) if tasks else 0.0,
        retry_count=retries,
        usage=_usage_summary(costs),
        search_calls=search_calls,
        projected_cost_microusd=projected_cost,
        engines=_performance_by_engine(tasks, costs),
    )


def _tasks_by_engine(tasks: list[AuditTask]) -> dict[str, list[AuditTask]]:
    by_engine: dict[str, list[AuditTask]] = defaultdict(list)
    for task in tasks:
        by_engine[task.logical_engine].append(task)
    return by_engine


def _performance_by_engine(
    tasks: list[AuditTask], costs: list[ExecutionCostProjection]
) -> list[AuditEnginePerformance]:
    cost_by_task = {row.task_id: row for row in costs}
    return [
        _engine_performance(engine, rows=rows, cost_by_task=cost_by_task)
        for engine, rows in sorted(_tasks_by_engine(tasks).items())
    ]


def _first_completed_at(tasks: list[AuditTask]) -> datetime | None:
    return min(
        (task.completed_at for task in tasks if task.completed_at is not None),
        default=None,
    )


def _total_projected_cost(costs: list[ExecutionCostProjection]) -> int | None:
    projected = [
        row.projected_total_cost_microusd
        for row in costs
        if row.projected_total_cost_microusd is not None
    ]
    return sum(projected) if projected else None


def _elapsed_ms(end: datetime | None, start: datetime) -> int | None:
    if end is None:
        return None
    return int((end - start).total_seconds() * 1000)


def _engine_performance(
    engine: str,
    *,
    rows: list[AuditTask],
    cost_by_task: dict[uuid.UUID, ExecutionCostProjection],
) -> AuditEnginePerformance:
    completed, failed, retries, search_calls = _task_counts(rows)
    latencies = _task_latencies(rows)
    projected = _projected_costs(rows, cost_by_task)
    return AuditEnginePerformance(
        logical_engine=engine,
        execution_count=len(rows),
        completed_count=completed,
        failed_count=failed,
        retry_count=retries,
        search_calls=search_calls,
        average_provider_latency_ms=(
            sum(latencies) / len(latencies) if latencies else None
        ),
        projected_cost_microusd=sum(projected) if projected else None,
    )


def _task_counts(rows: list[AuditTask]) -> tuple[int, int, int, int]:
    return (
        sum(row.status == TASK_STATUS_SUCCEEDED for row in rows),
        sum(row.status == TASK_STATUS_FAILED for row in rows),
        sum(max(0, row.attempt_count - 1) for row in rows),
        sum(len(row.search_events or []) for row in rows),
    )


def _task_latencies(rows: list[AuditTask]) -> list[int]:
    return [row.latency_ms for row in rows if row.latency_ms is not None]


def _projected_costs(
    rows: list[AuditTask],
    cost_by_task: dict[uuid.UUID, ExecutionCostProjection],
) -> list[int]:
    projected: list[int] = []
    for row in rows:
        cost = cost_by_task.get(row.id)
        if cost is not None and cost.projected_total_cost_microusd is not None:
            projected.append(cost.projected_total_cost_microusd)
    return projected


def _usage_summary(costs: list[ExecutionCostProjection]) -> AuditUsageSummary:
    if not costs:
        return AuditUsageSummary(
            input_tokens=None, output_tokens=None, total_tokens=None
        )
    return AuditUsageSummary(
        input_tokens=sum(
            (row.uncached_input_tokens or 0) + (row.cached_input_tokens or 0)
            for row in costs
        ),
        output_tokens=sum(row.output_tokens or 0 for row in costs),
        total_tokens=sum(row.total_tokens or 0 for row in costs),
    )
