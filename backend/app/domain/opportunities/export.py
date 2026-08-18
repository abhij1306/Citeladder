"""Bounded Opportunities export query."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import MAX_EXPORT_ITEMS
from app.domain.opportunities.projection import project_export_row
from app.domain.opportunities.queries import load_filtered_rows


async def load_export_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_id: str | None = None,
    min_priority: float | None = None,
) -> list[dict]:
    """Return the bounded, filtered persisted catalog used by exports."""
    rows = await load_filtered_rows(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
        limit=MAX_EXPORT_ITEMS,
    )
    return [project_export_row(row) for row in rows]
