"""Workspace-authorized Content generation API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.content import (
    CONTENT_IDEMPOTENCY_KEY_MAX_LEN,
    CONTENT_LIST_DEFAULT_LIMIT,
    CONTENT_LIST_MAX_LIMIT,
    ERROR_CANCEL_NOT_ALLOWED,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ERROR_WEBSITE_CONTEXT_UNAVAILABLE,
)
from app.domain.abuse.service import UsageLimitExceededError
from app.domain.content.schemas import (
    ContentFeedbackRequest,
    ContentGenerationCreate,
    ContentGenerationDetail,
    ContentGenerationListItem,
)
from app.domain.content.service import (
    CancelNotAllowedError,
    ContentGenerationNotFoundError,
    IdempotencyConflictError,
    ProviderNotConfiguredError,
    WebsiteContextUnavailableError,
    cancel_generation,
    enqueue_generation,
    get_generation,
    list_generations,
    record_feedback,
    regenerate,
    to_detail,
    to_list_item,
    try_again,
)

router = APIRouter(prefix="/content", tags=["content"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _usage_limited(exc: UsageLimitExceededError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="Workspace usage limit exceeded",
        headers={"Retry-After": str(exc.retry_after_seconds)},
    )


def _enqueue_conflict(exc: Exception) -> HTTPException:
    if isinstance(exc, ProviderNotConfiguredError):
        detail = ERROR_PROVIDER_NOT_CONFIGURED
    elif isinstance(exc, WebsiteContextUnavailableError):
        detail = ERROR_WEBSITE_CONTEXT_UNAVAILABLE
    else:
        detail = ERROR_IDEMPOTENCY_CONFLICT
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.get("/generations", response_model=list[ContentGenerationListItem])
async def list_generations_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
    limit: Annotated[
        int, Query(ge=1, le=CONTENT_LIST_MAX_LIMIT)
    ] = CONTENT_LIST_DEFAULT_LIMIT,
) -> list[ContentGenerationListItem]:
    try:
        rows = await list_generations(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    return [to_list_item(row) for row in rows]


@router.post(
    "/generations",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def enqueue_generation_endpoint(
    payload: ContentGenerationCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=CONTENT_IDEMPOTENCY_KEY_MAX_LEN),
    ] = None,
) -> ContentGenerationDetail:
    try:
        row, _created = await enqueue_generation(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            prompt=payload.prompt,
            output_type=payload.output_type,
            idempotency_key=(idempotency_key or "").strip(),
            skill_id=payload.skill_id,
            opportunity_id=payload.opportunity_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except (
        ProviderNotConfiguredError,
        IdempotencyConflictError,
        WebsiteContextUnavailableError,
    ) as exc:
        raise _enqueue_conflict(exc) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc
    return to_detail(row)


@router.get("/generations/{generation_id}", response_model=ContentGenerationDetail)
async def get_generation_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await get_generation(
            session, workspace_id=ctx.workspace_id, generation_id=generation_id
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/feedback", response_model=ContentGenerationDetail
)
async def content_feedback_endpoint(
    generation_id: uuid.UUID,
    payload: ContentFeedbackRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ContentGenerationDetail:
    try:
        row = await record_feedback(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
            feedback=payload.feedback,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return to_detail(row)


async def _repeat_generation(
    operation,
    *,
    generation_id: uuid.UUID,
    workspace_id: uuid.UUID,
    session: AsyncSession,
) -> ContentGenerationDetail:
    try:
        row = await operation(
            session, workspace_id=workspace_id, generation_id=generation_id
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except (ProviderNotConfiguredError, WebsiteContextUnavailableError) as exc:
        raise _enqueue_conflict(exc) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/regenerate",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    return await _repeat_generation(
        regenerate,
        generation_id=generation_id,
        workspace_id=ctx.workspace_id,
        session=session,
    )


@router.post(
    "/generations/{generation_id}/try-again",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def try_again_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    return await _repeat_generation(
        try_again,
        generation_id=generation_id,
        workspace_id=ctx.workspace_id,
        session=session,
    )


@router.post(
    "/generations/{generation_id}/cancel", response_model=ContentGenerationDetail
)
async def cancel_generation_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await cancel_generation(
            session, workspace_id=ctx.workspace_id, generation_id=generation_id
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except CancelNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_CANCEL_NOT_ALLOWED
        ) from exc
    return to_detail(row)
