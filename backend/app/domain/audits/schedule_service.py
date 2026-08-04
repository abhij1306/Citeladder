"""Persistence operations for workspace-scoped audit schedules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audit_schedules import (
    CADENCE_EVERY_N_MINUTES,
    audit_schedule_settings,
)
from app.domain.audits.schedule_schemas import AuditScheduleCreate, AuditScheduleUpdate
from app.models.audit_schedule import AuditSchedule
from app.models.project import Project
from app.models.prompt import PromptSet


class AuditScheduleNotFoundError(LookupError):
    """The schedule is absent from the active workspace/project."""


class AuditScheduleValidationError(ValueError):
    """A referenced project or prompt set is not valid for the schedule."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _validate_cadence(cadence: str, interval_minutes: int | None) -> None:
    if cadence == CADENCE_EVERY_N_MINUTES:
        if (
            interval_minutes is None
            or interval_minutes < audit_schedule_settings.min_interval_minutes
        ):
            raise AuditScheduleValidationError(
                "every_n_minutes requires a configured-minimum interval or higher"
            )
    elif interval_minutes is not None:
        raise AuditScheduleValidationError(
            "interval_minutes is only valid for every_n_minutes"
        )


async def _validate_prompt_set(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
) -> None:
    project_id_found = await session.scalar(
        select(Project.id).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if project_id_found is None:
        raise AuditScheduleValidationError("Project not found")
    prompt_set_id_found = await session.scalar(
        select(PromptSet.id).where(
            PromptSet.id == prompt_set_id,
            PromptSet.project_id == project_id,
        )
    )
    if prompt_set_id_found is None:
        raise AuditScheduleValidationError("Prompt set not found for project")


async def create_schedule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: AuditScheduleCreate,
) -> AuditSchedule:
    await _validate_prompt_set(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=payload.prompt_set_id,
    )
    values = payload.model_dump()
    values["next_run_at"] = payload.next_run_at or _utcnow()
    schedule = AuditSchedule(
        workspace_id=workspace_id,
        project_id=project_id,
        **values,
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def list_schedules(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[AuditSchedule]:
    rows = await session.scalars(
        select(AuditSchedule)
        .where(
            AuditSchedule.workspace_id == workspace_id,
            AuditSchedule.project_id == project_id,
        )
        .order_by(AuditSchedule.created_at.asc(), AuditSchedule.id.asc())
    )
    return list(rows)


async def get_schedule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> AuditSchedule:
    schedule = await session.scalar(
        select(AuditSchedule).where(
            AuditSchedule.id == schedule_id,
            AuditSchedule.workspace_id == workspace_id,
            AuditSchedule.project_id == project_id,
        )
    )
    if schedule is None:
        raise AuditScheduleNotFoundError("Audit schedule not found")
    return schedule


async def update_schedule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: AuditScheduleUpdate,
) -> AuditSchedule:
    schedule = await get_schedule(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        schedule_id=schedule_id,
    )
    values = payload.model_dump(exclude_unset=True)
    prompt_set_id = values.get("prompt_set_id", schedule.prompt_set_id)
    if "prompt_set_id" in values:
        await _validate_prompt_set(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt_set_id=prompt_set_id,
        )
    merged_cadence = values.get("cadence", schedule.cadence)
    merged_interval = values.get("interval_minutes", schedule.interval_minutes)
    _validate_cadence(merged_cadence, merged_interval)
    if values.get("enabled") is True and "next_run_at" not in values:
        values["next_run_at"] = schedule.next_run_at or _utcnow()
    for field, value in values.items():
        setattr(schedule, field, value)
    await session.commit()
    await session.refresh(schedule)
    return schedule


async def delete_schedule(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
) -> None:
    schedule = await get_schedule(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        schedule_id=schedule_id,
    )
    await session.delete(schedule)
    await session.commit()
