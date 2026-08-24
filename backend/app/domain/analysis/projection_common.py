"""Shared persisted-analysis projection lookups."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import (
    AUDIT_SCOPE_BRAND,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.domain.analysis.errors import AnalysisNotFoundError
from app.domain.audits.schemas import ModelProvenance, model_provenance_for
from app.models.analysis import MetricSnapshot
from app.models.audit import Audit

_DASHBOARD_STATUSES = (AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED)
_AUDIT_NOT_FOUND = "Audit not found"


def aggregate_provenance(audit: Audit) -> list[ModelProvenance]:
    """Stable frozen route-provenance list for an aggregate surface."""
    return model_provenance_for(audit.engine_snapshots, audit.configuration)


async def load_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> MetricSnapshot:
    snapshot = await session.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.audit_id == audit_id,
            MetricSnapshot.workspace_id == workspace_id,
        )
    )
    if snapshot is None:
        raise AnalysisNotFoundError("Metrics not available for audit")
    return snapshot


async def latest_dashboard_audit_id(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(Audit.id)
        .where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.audit_scope == AUDIT_SCOPE_BRAND,
            Audit.status.in_(_DASHBOARD_STATUSES),
        )
        .order_by(Audit.completed_at.desc().nullslast(), Audit.created_at.desc())
        .limit(1)
    )
