"""Workspace-authorized Growth Agent API over persisted bounded task runs."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.api.usage_limits import enforce_workspace_request
from app.connectors.agent.factory import create_model_gateway
from app.core.config.abuse import abuse_settings
from app.core.config.agent import (
    AGENT_CONTEXT_POLICY_VERSION,
    AGENT_IDEMPOTENCY_KEY_MAX_CHARS,
    AGENT_LIST_DEFAULT_LIMIT,
    AGENT_LIST_MAX_LIMIT,
    AGENT_POLICY_VERSION,
    AGENT_TASK_POLICIES,
    AGENT_TOOL_REGISTRY_VERSION,
    default_agent_settings,
)
from app.core.errors import ApiException
from app.domain.agent.schemas import (
    AgentCapabilities,
    AgentDecisionConfirm,
    AgentTaskRunItem,
    AgentTaskSubmit,
    ConversationCreate,
    ConversationDetail,
    ConversationItem,
)
from app.domain.agent.service import (
    AgentConflictError,
    AgentNotFoundError,
    AgentValidationError,
    cancel_task,
    confirm_decision,
    create_conversation,
    get_conversation,
    get_task_run,
    list_conversations,
    list_task_runs,
    submit_task,
    task_run_projection,
    task_runs_projection,
)
from app.domain.agent.tools import tool_catalog

router = APIRouter(prefix="/agent", tags=["agent"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _configured_gateway():
    return create_model_gateway() if default_agent_settings.configured else None


def _error(exc: Exception) -> ApiException:
    if isinstance(exc, AgentNotFoundError):
        return ApiException(status.HTTP_404_NOT_FOUND, "agent_not_found", str(exc))
    if isinstance(exc, AgentValidationError):
        return ApiException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "agent_task_invalid", str(exc)
        )
    return ApiException(status.HTTP_409_CONFLICT, "agent_task_conflict", str(exc))


@router.get("/capabilities")
async def agent_capabilities_endpoint(_ctx: _WorkspaceDep) -> AgentCapabilities:
    configured = default_agent_settings.configured
    client = create_model_gateway() if configured else None
    return AgentCapabilities(
        configured=configured,
        provider_adapter=default_agent_settings.adapter if configured else "",
        endpoint_host=client.base_url_host if client else "",
        model=client.model if client else "",
        model_capabilities=client.capabilities().as_dict() if client else {},
        policy_version=AGENT_POLICY_VERSION,
        context_policy_version=AGENT_CONTEXT_POLICY_VERSION,
        tool_registry_version=AGENT_TOOL_REGISTRY_VERSION,
        task_catalog=[
            {
                "task_type": item.task_type,
                "title": item.title,
                "description": item.description,
                "allowed_tools": list(item.allowed_tools),
                "required_scope": list(item.required_scope),
                "requested_outputs": list(item.requested_outputs),
                "max_steps": item.max_steps,
                "max_tool_calls": item.max_tool_calls,
            }
            for item in AGENT_TASK_POLICIES.values()
        ],
        tool_catalog=tool_catalog(),
    )


@router.post(
    "/conversations",
    status_code=status.HTTP_201_CREATED,
)
async def create_conversation_endpoint(
    payload: ConversationCreate, ctx: _WorkspaceDep, session: _SessionDep
) -> ConversationItem:
    try:
        row = await create_conversation(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            user_id=ctx.user.id,
            title=payload.title,
        )
    except (AgentNotFoundError, AgentValidationError) as exc:
        raise _error(exc) from exc
    return ConversationItem.model_validate(row)


@router.get("/conversations")
async def list_conversations_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
    limit: Annotated[
        int, Query(ge=1, le=AGENT_LIST_MAX_LIMIT)
    ] = AGENT_LIST_DEFAULT_LIMIT,
) -> list[ConversationItem]:
    try:
        rows = await list_conversations(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
        )
    except AgentNotFoundError as exc:
        raise _error(exc) from exc
    return [ConversationItem.model_validate(row) for row in rows]


@router.get("/conversations/{conversation_id}")
async def get_conversation_endpoint(
    conversation_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> ConversationDetail:
    try:
        row, messages = await get_conversation(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            conversation_id=conversation_id,
        )
    except AgentNotFoundError as exc:
        raise _error(exc) from exc
    return ConversationDetail.model_validate(
        {**ConversationItem.model_validate(row).model_dump(), "messages": messages}
    )


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
async def submit_task_endpoint(
    payload: AgentTaskSubmit,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=AGENT_IDEMPOTENCY_KEY_MAX_CHARS),
    ] = None,
) -> AgentTaskRunItem:
    gateway = _configured_gateway()
    if gateway is not None:
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
            gateway=gateway,
        )
        return AgentTaskRunItem.model_validate(await task_run_projection(session, run))
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
) -> list[AgentTaskRunItem]:
    try:
        rows = await list_task_runs(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
        )
        projections = await task_runs_projection(session, rows)
        return [AgentTaskRunItem.model_validate(item) for item in projections]
    except AgentNotFoundError as exc:
        raise _error(exc) from exc


@router.get("/tasks/{run_id}")
async def get_task_endpoint(
    run_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> AgentTaskRunItem:
    try:
        run = await get_task_run(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        return AgentTaskRunItem.model_validate(await task_run_projection(session, run))
    except AgentNotFoundError as exc:
        raise _error(exc) from exc


@router.post("/tasks/{run_id}/decision")
async def confirm_task_decision_endpoint(
    run_id: uuid.UUID,
    payload: AgentDecisionConfirm,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> AgentTaskRunItem:
    try:
        run = await confirm_decision(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            run_id=run_id,
            user_id=ctx.user.id,
            decision=payload.decision,
            confirmed=payload.confirmed,
            gateway=_configured_gateway(),
        )
        return AgentTaskRunItem.model_validate(await task_run_projection(session, run))
    except (AgentNotFoundError, AgentValidationError, AgentConflictError) as exc:
        raise _error(exc) from exc


@router.post("/tasks/{run_id}/cancel")
async def cancel_task_endpoint(
    run_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> AgentTaskRunItem:
    try:
        run = await cancel_task(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            run_id=run_id,
        )
        return AgentTaskRunItem.model_validate(await task_run_projection(session, run))
    except (AgentNotFoundError, AgentValidationError, AgentConflictError) as exc:
        raise _error(exc) from exc


