"""Read-only, workspace-authorized evidence tools for Growth Agent tasks."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import Audit
from app.models.demand import DemandSnapshot
from app.models.opportunity import Opportunity
from app.models.site_health.graph import SiteHealthSnapshot

TOOL_VERSION: Final = "2.0.0"
MAX_ROADMAP_ITEMS: Final = 10


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    session: AsyncSession
    workspace_id: uuid.UUID
    project_id: uuid.UUID


ToolExecutor = Callable[
    [ToolExecutionContext, dict[str, Any]], Awaitable[dict[str, Any]]
]


async def execute_tool(
    name: str, context: ToolExecutionContext, payload: dict[str, Any]
) -> dict[str, Any]:
    executor = _EXECUTORS.get(name)
    if executor is None:
        raise ValueError(f"unknown agent tool: {name}")
    return await executor(context, payload)


async def _site_snapshot(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    row = await context.session.scalar(
        select(SiteHealthSnapshot)
        .where(
            SiteHealthSnapshot.workspace_id == context.workspace_id,
            SiteHealthSnapshot.project_id == context.project_id,
        )
        .order_by(SiteHealthSnapshot.created_at.desc(), SiteHealthSnapshot.id.desc())
        .limit(1)
    )
    if row is None:
        return _unavailable("no_site_snapshot")
    return {
        "state": "available",
        "scores": {
            "technical": row.technical_score,
            "aeo": row.aeo_score,
            "overall": row.overall_score,
        },
        "coverage": {
            "selected_urls": row.selected_url_count,
            "analyzed_urls": row.analyzed_url_count,
        },
        "versions": {
            "analyzer": row.analyzer_version,
            "scoring": row.scoring_version,
        },
        "artifact_refs": [
            {"kind": "site_snapshot", "id": str(row.id)},
            {"kind": "site_crawl", "id": str(row.crawl_id)},
        ],
        "omissions": [],
    }


async def _demand_snapshot(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    row = await context.session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == context.workspace_id,
            DemandSnapshot.project_id == context.project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )
    if row is None:
        return _unavailable("no_demand_snapshot")
    source_refs = [
        {"kind": "integration_artifact", "id": str(source_id)}
        for source_id in row.source_artifact_ids
    ]
    source_refs.extend(
        {"kind": "integration_metric_row", "id": str(source_id)}
        for source_id in row.source_metric_row_ids
    )
    return {
        "state": "available",
        "window": {
            "start": row.window_start.isoformat(),
            "end": row.window_end.isoformat(),
        },
        "summary": row.summary,
        "coverage": row.coverage,
        "comparison": row.comparison,
        "artifact_refs": [
            {"kind": "demand_snapshot", "id": str(row.id)},
            *source_refs,
        ],
        "omissions": [],
    }


async def _ranked_opportunities(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    rows = list(
        (
            await context.session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.workspace_id == context.workspace_id,
                    Opportunity.project_id == context.project_id,
                    Opportunity.superseded_at.is_(None),
                )
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.asc())
                .limit(MAX_ROADMAP_ITEMS + 1)
            )
        ).all()
    )
    emitted = rows[:MAX_ROADMAP_ITEMS]
    if not emitted:
        return _unavailable("no_opportunities")
    items = [
        {
            "rank": rank,
            "priority_score": row.priority_score,
            "severity": row.severity,
            "type": row.opportunity_type,
            "title": row.title,
            "remediation": row.remediation,
            "target_url": row.target_url,
        }
        for rank, row in enumerate(emitted, start=1)
    ]
    omissions = (
        [{"reason": "roadmap_item_limit", "count": len(rows) - len(emitted)}]
        if len(rows) > len(emitted)
        else []
    )
    return {
        "state": "available",
        "ordering": "priority_score_desc_then_id",
        "items": items,
        "artifact_refs": [
            {"kind": "opportunity", "id": str(row.id)} for row in emitted
        ],
        "omissions": omissions,
    }


async def _latest_audit(
    context: ToolExecutionContext, _payload: dict[str, Any]
) -> dict[str, Any]:
    row = await context.session.scalar(
        select(Audit)
        .where(
            Audit.workspace_id == context.workspace_id,
            Audit.project_id == context.project_id,
        )
        .order_by(Audit.created_at.desc(), Audit.id.desc())
        .limit(1)
    )
    if row is None:
        return _unavailable("no_audit")
    return {
        "state": "available",
        "status": row.status,
        "summary": row.summary,
        "counts": {
            "requested": row.requested_count,
            "completed": row.completed_count,
            "failed": row.failed_count,
        },
        "analyzer_version": row.analyzer_version,
        "artifact_refs": [{"kind": "audit", "id": str(row.id)}],
        "omissions": [],
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "state": "unavailable",
        "reason": reason,
        "artifact_refs": [],
        "omissions": [{"reason": reason, "count": 1}],
    }


_EXECUTORS: Final[dict[str, ToolExecutor]] = {
    "site.read_snapshot": _site_snapshot,
    "demand.read_snapshot": _demand_snapshot,
    "opportunities.read_ranked": _ranked_opportunities,
    "audits.read_latest": _latest_audit,
}
