"""Durable Opportunities refresh admission."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
    analytics_settings,
)
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    FORMULA_VERSION,
    RULE_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.models.analytics import AnalyticsTask


async def enqueue_opportunity_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    trigger_kind: str,
    trigger_id: uuid.UUID,
) -> None:
    """Transactionally enqueue one versioned automatic projection refresh."""
    idempotency_key = (
        f"opportunity:{trigger_kind}:{trigger_id}:"
        f"{ANALYZER_VERSION}:{RULE_VERSION}:{FORMULA_VERSION}"
    )
    await session.execute(
        pg_insert(AnalyticsTask)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            task_kind=ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
            payload={"trigger_kind": trigger_kind, "trigger_id": str(trigger_id)},
            idempotency_key=idempotency_key,
            status=TASK_STATUS_QUEUED,
            max_attempts=analytics_settings.task_max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
