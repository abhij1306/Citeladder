"""Workspace-scoped CRUD API for recurring audit schedules."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_project_member
from app.core.http_errors import raise_not_found
from app.domain.audits.schedule_schemas import (
    AuditScheduleCreate,
    AuditScheduleResponse,
    AuditScheduleUpdate,
)
from app.domain.audits.schedule_service import (
    AuditScheduleNotFoundError,
    AuditScheduleValidationError,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)

router = APIRouter(prefix="/projects", tags=["audit-schedules"])
_ProjectDep = Annotated[WorkspaceContext, Depends(require_project_member)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.post(
    "/{project_id}/audit-schedules",
    response_model=AuditScheduleResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_audit_schedule_endpoint(
    project_id: uuid.UUID,
    payload: AuditScheduleCreate,
    ctx: _ProjectDep,
    session: _SessionDep,
) -> AuditScheduleResponse:
    try:
        schedule = await create_schedule(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            payload=payload,
        )
    except AuditScheduleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return AuditScheduleResponse.model_validate(schedule)


@router.get("/{project_id}/audit-schedules", response_model=list[AuditScheduleResponse])
async def list_audit_schedules_endpoint(
    project_id: uuid.UUID, ctx: _ProjectDep, session: _SessionDep
) -> list[AuditScheduleResponse]:
    schedules = await list_schedules(
        session, workspace_id=ctx.workspace_id, project_id=project_id
    )
    return [AuditScheduleResponse.model_validate(item) for item in schedules]


@router.get(
    "/{project_id}/audit-schedules/{schedule_id}", response_model=AuditScheduleResponse
)
async def get_audit_schedule_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    ctx: _ProjectDep,
    session: _SessionDep,
) -> AuditScheduleResponse:
    try:
        schedule = await get_schedule(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            schedule_id=schedule_id,
        )
    except AuditScheduleNotFoundError as exc:
        raise_not_found("Audit schedule", cause=exc)
    return AuditScheduleResponse.model_validate(schedule)


@router.patch(
    "/{project_id}/audit-schedules/{schedule_id}", response_model=AuditScheduleResponse
)
async def update_audit_schedule_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    payload: AuditScheduleUpdate,
    ctx: _ProjectDep,
    session: _SessionDep,
) -> AuditScheduleResponse:
    try:
        schedule = await update_schedule(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            schedule_id=schedule_id,
            payload=payload,
        )
    except AuditScheduleNotFoundError as exc:
        raise_not_found("Audit schedule", cause=exc)
    except AuditScheduleValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return AuditScheduleResponse.model_validate(schedule)


@router.delete(
    "/{project_id}/audit-schedules/{schedule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_audit_schedule_endpoint(
    project_id: uuid.UUID,
    schedule_id: uuid.UUID,
    ctx: _ProjectDep,
    session: _SessionDep,
) -> None:
    try:
        await delete_schedule(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            schedule_id=schedule_id,
        )
    except AuditScheduleNotFoundError as exc:
        raise_not_found("Audit schedule", cause=exc)
