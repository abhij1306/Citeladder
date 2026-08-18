"""Small shared primitives for Opportunities leaf owners."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import LIST_DEFAULT_LIMIT, LIST_MAX_LIMIT
from app.domain.opportunities.errors import OpportunityNotFoundError
from app.models.project import Project

_PROJECT_NOT_FOUND = "Project not found"
_OPPORTUNITY_NOT_FOUND = "Opportunity not found"
_AUDIT_NOT_FOUND = "Audit not found"
_CRAWL_NOT_FOUND = "Crawl not found"
_LIST_SCOPE = "opportunities"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return LIST_DEFAULT_LIMIT
    return max(1, min(int(limit), LIST_MAX_LIMIT))


async def _require_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(Project.id).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if exists is None:
        raise OpportunityNotFoundError(_PROJECT_NOT_FOUND)
