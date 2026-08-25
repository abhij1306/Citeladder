"""Workspace-authorized API for bounded Growth Agent task runs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.api.usage_limits import enforce_workspace_request
from app.core.config.abuse import abuse_settings
from app.core.config.agent import (
    AGENT_IDEMPOTENCY_KEY_MAX_CHARS,
    AGENT_LIST_DEFAULT_LIMIT,
    AGENT_LIST_MAX_LIMIT,
)
from app.core.errors import ApiException
from app.domain.agent.schemas import (
    AgentTaskRunDetail,
    AgentTaskRunSummary,
    AgentTaskSubmit,
)
from app.domain.agent.service import (
    AgentConflictError,
    AgentNotFoundError,
    AgentValidationError,
    cancel_task,
    get_task_run,
    list_task_runs,
    submit_task,
    task_run_projection,
)

router = APIRouter(prefix="/agent", tags=["agent"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _error(exc: Exception) -> ApiException:
    if isinstance(exc, AgentNotFoundError):
        return ApiException(status.HTTP_404_NOT_FOUND, "agent_not_found", str(exc))
    if isinstance(exc, AgentValidationError):
        return ApiException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "agent_task_invalid", str(exc)
        )
    return ApiException(status.HTTP_409_CONFLICT, "agent_task_conflict", str(exc))


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def submit_task_endpoint(
    payload: AgentTaskSubmit,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=AGENT_IDEMPOTENCY_KEY_MAX_CHARS),
    ] = None,
) -> AgentTaskRunDetail:
    await enforce_workspace_request(
        session,
        workspace_id=ctx.workspace_id,
        operation="agent.provider_call",
        limit=abuse_settings.agent_call_limit,
        window_seconds=abuse_settings.agent_call_window_seconds,
    )
    try:
        run, _created = await submit_task(
            session,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user.id,
            payload=payload,
            idempotency_key=(idempotency_key or "").strip(),
        )
        return AgentTaskRunDetail.model_validate(task_run_projection(run))
    except (AgentNotFoundError, AgentValidationError, AgentConflictError) as exc:
        raise _error(exc) from exc


@router.get("/tasks")
async def list_tasks_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
    limit: Annotated[
        int, Query(ge=1, le=AGENT_LIST_MAX_LIMIT)
    ] = AGENT_LIST_DEFAULT_LIMIT,
) -> list[AgentTaskRunSummary]:
    try:
        rows = await list_task_runs(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
        )
        return [AgentTaskRunSummary.model_validate(row) for row in rows]
    except AgentNotFoundError as exc:
        raise _error(exc) from exc


@router.get("/tasks/{run_id}")
async def get_task_endpoint(
    run_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> AgentTaskRunDetail:
    try:
        run = await get_task_run(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        return AgentTaskRunDetail.model_validate(task_run_projection(run))
    except AgentNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/tasks/{run_id}/cancel")
async def cancel_task_endpoint(
    run_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> AgentTaskRunDetail:
    try:
        run = await cancel_task(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        return AgentTaskRunDetail.model_validate(task_run_projection(run))
    except AgentNotFoundError as exc:
        raise _error(exc) from exc
