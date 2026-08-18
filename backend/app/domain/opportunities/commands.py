"""Mutable Opportunities workflow commands."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import OPPORTUNITY_STATUSES
from app.domain.opportunities.common import (
    _OPPORTUNITY_NOT_FOUND,
    _PROJECT_NOT_FOUND,
)
from app.domain.opportunities.errors import (
    OpportunityNotFoundError,
    OpportunityOrderConflictError,
    OpportunitySupersededError,
    OpportunityValidationError,
)
from app.domain.opportunities.projection import _stable_key, project_item
from app.models.opportunity import Opportunity, OpportunityOrder, OpportunityStatusEvent
from app.models.project import Project


async def update_status(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    status: str,
    changed_by_user_id: uuid.UUID,
) -> dict:
    """Mutate the human workflow status, the only mutable row field."""
    _validate_status(status)
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    if row.superseded_at is not None:
        raise OpportunitySupersededError(
            "Opportunity was superseded by a newer recompute"
        )
    previous_status = row.status
    if previous_status != status:
        row.status = status
        session.add(
            OpportunityStatusEvent(
                workspace_id=workspace_id,
                project_id=row.project_id,
                opportunity_id=row.id,
                stable_key=_stable_key(row),
                previous_status=previous_status,
                next_status=status,
                changed_by_user_id=changed_by_user_id,
            )
        )
    await session.commit()
    return project_item(row)


def _validate_status(status: str) -> None:
    if status not in OPPORTUNITY_STATUSES:
        raise OpportunityValidationError(f"unknown opportunity status: {status!r}")


async def _lock_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    locked_id = await session.scalar(
        select(Project.id)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if locked_id is None:
        raise OpportunityNotFoundError(_PROJECT_NOT_FOUND)


async def update_order(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    ordered_opportunity_ids: list[uuid.UUID],
    expected_version: int,
    updated_by_user_id: uuid.UUID,
) -> dict:
    """Persist one shared project order without mutating derived evidence."""
    await _lock_project(session, workspace_id=workspace_id, project_id=project_id)
    if len(set(ordered_opportunity_ids)) != len(ordered_opportunity_ids):
        raise OpportunityValidationError("ordered opportunity ids must be unique")

    rows = list(
        (
            await session.scalars(
                select(Opportunity).where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.project_id == project_id,
                    Opportunity.id.in_(ordered_opportunity_ids),
                    Opportunity.superseded_at.is_(None),
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(ordered_opportunity_ids):
        raise OpportunityValidationError(
            "ordered opportunity ids must identify live project opportunities"
        )

    order = await session.scalar(
        select(OpportunityOrder)
        .where(
            OpportunityOrder.workspace_id == workspace_id,
            OpportunityOrder.project_id == project_id,
        )
        .with_for_update()
    )
    current_version = order.version if order is not None else 0
    if expected_version != current_version:
        raise OpportunityOrderConflictError(
            f"queue version changed from {expected_version} to {current_version}"
        )

    ordered_keys = [_stable_key(by_id[item_id]) for item_id in ordered_opportunity_ids]
    if order is None:
        order = OpportunityOrder(
            workspace_id=workspace_id,
            project_id=project_id,
            ordered_keys=ordered_keys,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(order)
    else:
        order.ordered_keys = ordered_keys
        order.version += 1
        order.updated_by_user_id = updated_by_user_id
    await session.commit()
    return {
        "version": order.version,
        "ordered_opportunity_ids": ordered_opportunity_ids,
    }
