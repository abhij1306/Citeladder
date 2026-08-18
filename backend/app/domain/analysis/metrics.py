"""Persisted metric-snapshot readers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.analysis.errors import AnalysisNotFoundError
from app.domain.analysis.projection_common import (
    _AUDIT_NOT_FOUND,
    latest_dashboard_audit_id,
    load_snapshot,
)
from app.domain.analysis.schemas import MetricsResponse, PromptMetricItem
from app.models.analysis import PromptMetricSnapshot
from app.models.audit import Audit


async def get_metrics(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> MetricsResponse:
    """Serve the single-run ``MetricSnapshot`` projection."""
    snapshot = await load_snapshot(
        session, workspace_id=workspace_id, audit_id=audit_id
    )
    return MetricsResponse.model_validate(snapshot)


async def get_prompt_metrics(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> list[PromptMetricItem]:
    """Return one persisted prompt projection, strongest-to-weakest."""
    if audit_id is None:
        audit_id = await latest_dashboard_audit_id(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if audit_id is None:
            return []
    else:
        audit = await session.scalar(
            select(Audit.id).where(
                Audit.id == audit_id,
                Audit.workspace_id == workspace_id,
                Audit.project_id == project_id,
            )
        )
        if audit is None:
            raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    rows = list(
        (
            await session.scalars(
                select(PromptMetricSnapshot)
                .where(
                    PromptMetricSnapshot.workspace_id == workspace_id,
                    PromptMetricSnapshot.project_id == project_id,
                    PromptMetricSnapshot.audit_id == audit_id,
                )
                .order_by(
                    PromptMetricSnapshot.composite_score.desc(),
                    PromptMetricSnapshot.prompt_index.asc(),
                )
            )
        ).all()
    )
    return [PromptMetricItem.model_validate(row) for row in rows]
