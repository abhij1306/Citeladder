# Content router: workspace-scoped AI content generation (invariant 5).
#
# Flat surface under /api/v1/content; the active workspace comes from
# ``require_active_workspace``. Every handler filters by that workspace, so a
# record in another workspace is a 404, never a 403.
#
#   GET  /content/generations?project_id=&limit=  -> bounded history list
#   POST /content/generations                     -> enqueue (Idempotency-Key)
#   GET  /content/generations/{id}                -> full detail
#   POST /content/generations/{id}/regenerate     -> new record, fresh context
#   POST /content/generations/{id}/try-again      -> new record, frozen context
#   POST /content/generations/{id}/cancel         -> cooperative cancel
#
# The provider API key is env-driven and worker-resolved; it never enters
# this surface (invariant 6).
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.content import (
    CONTENT_IDEMPOTENCY_KEY_MAX_LEN,
    CONTENT_LIST_DEFAULT_LIMIT,
    CONTENT_LIST_MAX_LIMIT,
    ERROR_CANCEL_NOT_ALLOWED,
    ERROR_IDEMPOTENCY_CONFLICT,
    ERROR_PROVIDER_NOT_CONFIGURED,
)
from app.domain.abuse.service import UsageLimitExceededError
from app.domain.content.intelligence import (
    ContentConflictError,
    ContentNotFoundError,
    ContentValidationBlockedError,
    build_task_context,
    create_faq_brief,
    create_revision,
    get_brief,
    get_revision,
    get_validation,
    latest_strategy,
    list_briefs,
    list_inventory,
    list_revisions,
    list_verifications,
    recompute_strategy,
    transition_revision,
    update_revision,
    verify_revision,
)
from app.domain.content.schemas import (
    BriefGenerationCreate,
    ContentBriefCreate,
    ContentBriefResponse,
    ContentFeedbackRequest,
    ContentGenerationCreate,
    ContentGenerationDetail,
    ContentGenerationListItem,
    ContentInventoryResponse,
    ContentRevisionCreate,
    ContentRevisionResponse,
    ContentRevisionTransitionRequest,
    ContentRevisionUpdate,
    ContentStrategyResponse,
    ContentValidationResponse,
    ContentVerificationCreate,
    ContentVerificationResponse,
    TaskContextResponse,
)
from app.domain.content.service import (
    CancelNotAllowedError,
    ContentGenerationNotFoundError,
    IdempotencyConflictError,
    ProviderNotConfiguredError,
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


def _content_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (ContentNotFoundError, ContentGenerationNotFoundError)):
        return _not_found(exc)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _enqueue_conflict(exc: Exception) -> HTTPException:
    detail = (
        ERROR_PROVIDER_NOT_CONFIGURED
        if isinstance(exc, ProviderNotConfiguredError)
        else ERROR_IDEMPOTENCY_CONFLICT
    )
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


@router.get("/strategy", response_model=ContentStrategyResponse | None)
async def content_strategy_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> ContentStrategyResponse | None:
    try:
        row = await latest_strategy(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
        return None if row is None else ContentStrategyResponse.model_validate(row)
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/strategy/recompute", response_model=ContentStrategyResponse)
async def recompute_content_strategy_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentStrategyResponse:
    try:
        row, _created = await recompute_strategy(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
        return ContentStrategyResponse.model_validate(row)
    except (ContentNotFoundError, ContentConflictError) as exc:
        raise _content_error(exc) from exc


@router.get("/inventory", response_model=list[ContentInventoryResponse])
async def content_inventory_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=250)] = 250,
) -> list[ContentInventoryResponse]:
    try:
        rows = await list_inventory(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
        )
        return [ContentInventoryResponse.model_validate(row) for row in rows]
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/briefs", response_model=list[ContentBriefResponse])
async def content_briefs_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> list[ContentBriefResponse]:
    try:
        rows = await list_briefs(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
        return [ContentBriefResponse.model_validate(row) for row in rows]
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/briefs", response_model=ContentBriefResponse, status_code=201)
async def create_content_brief_endpoint(
    payload: ContentBriefCreate, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentBriefResponse:
    try:
        row, _created = await create_faq_brief(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            question_id=payload.question_id,
            kind=payload.kind,
            target_url=payload.target_url,
            title=payload.title,
        )
        return ContentBriefResponse.model_validate(row)
    except (ContentNotFoundError, ContentConflictError) as exc:
        raise _content_error(exc) from exc


@router.get("/briefs/{brief_id}", response_model=ContentBriefResponse)
async def content_brief_detail_endpoint(
    brief_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentBriefResponse:
    try:
        return ContentBriefResponse.model_validate(
            await get_brief(session, workspace_id=ctx.workspace_id, brief_id=brief_id)
        )
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/briefs/{brief_id}/context", response_model=TaskContextResponse)
async def content_brief_context_endpoint(
    brief_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> TaskContextResponse:
    try:
        row, _created = await build_task_context(
            session, workspace_id=ctx.workspace_id, brief_id=brief_id
        )
        return TaskContextResponse.model_validate(row)
    except (ContentNotFoundError, ContentConflictError) as exc:
        raise _content_error(exc) from exc


@router.post(
    "/briefs/{brief_id}/generate",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def generate_content_brief_endpoint(
    brief_id: uuid.UUID,
    payload: BriefGenerationCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=CONTENT_IDEMPOTENCY_KEY_MAX_LEN),
    ] = None,
) -> ContentGenerationDetail:
    return await _generate_content_brief(
        brief_id=brief_id,
        skill_id=payload.skill_id,
        workspace_id=ctx.workspace_id,
        idempotency_key=(idempotency_key or "").strip(),
        session=session,
    )


async def _generate_content_brief(
    *,
    brief_id: uuid.UUID,
    skill_id: str,
    workspace_id: uuid.UUID,
    idempotency_key: str,
    session: AsyncSession,
) -> ContentGenerationDetail:
    try:
        brief = await get_brief(session, workspace_id=workspace_id, brief_id=brief_id)
        row, _created = await enqueue_generation(
            session,
            workspace_id=workspace_id,
            project_id=brief.project_id,
            prompt="brief-driven",
            output_type="website_page",
            website_context_enabled=True,
            idempotency_key=idempotency_key,
            skill_id=skill_id,
            brief_id=brief.id,
        )
        return to_detail(row)
    except (ContentNotFoundError, ContentGenerationNotFoundError) as exc:
        raise _not_found(exc) from exc
    except (ProviderNotConfiguredError, IdempotencyConflictError) as exc:
        raise _enqueue_conflict(exc) from exc
    except (ContentConflictError, ValueError) as exc:
        raise _content_error(exc) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc


@router.get(
    "/generations/{generation_id}/validation",
    response_model=ContentValidationResponse,
)
async def content_validation_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentValidationResponse:
    try:
        return ContentValidationResponse.model_validate(
            await get_validation(
                session, workspace_id=ctx.workspace_id, generation_id=generation_id
            )
        )
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post(
    "/generations/{generation_id}/revision",
    response_model=ContentRevisionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_content_revision_endpoint(
    generation_id: uuid.UUID,
    payload: ContentRevisionCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ContentRevisionResponse:
    try:
        row, _created = await create_revision(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
            user_id=ctx.user.id,
            visible_content=payload.visible_content,
            structured_data=payload.structured_data,
        )
        return ContentRevisionResponse.model_validate(row)
    except (ContentNotFoundError, ContentConflictError) as exc:
        raise _content_error(exc) from exc


@router.get("/revisions", response_model=list[ContentRevisionResponse])
async def content_revisions_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> list[ContentRevisionResponse]:
    try:
        rows = await list_revisions(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
        return [ContentRevisionResponse.model_validate(row) for row in rows]
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


@router.put("/revisions/{revision_id}", response_model=ContentRevisionResponse)
async def update_content_revision_endpoint(
    revision_id: uuid.UUID,
    payload: ContentRevisionUpdate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ContentRevisionResponse:
    try:
        return ContentRevisionResponse.model_validate(
            await update_revision(
                session,
                workspace_id=ctx.workspace_id,
                revision_id=revision_id,
                user_id=ctx.user.id,
                visible_content=payload.visible_content,
                structured_data=payload.structured_data,
            )
        )
    except (
        ContentNotFoundError,
        ContentConflictError,
        ContentValidationBlockedError,
    ) as exc:
        raise _content_error(exc) from exc


@router.post(
    "/revisions/{revision_id}/transition", response_model=ContentRevisionResponse
)
async def transition_content_revision_endpoint(
    revision_id: uuid.UUID,
    payload: ContentRevisionTransitionRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ContentRevisionResponse:
    try:
        return ContentRevisionResponse.model_validate(
            await transition_revision(
                session,
                workspace_id=ctx.workspace_id,
                revision_id=revision_id,
                user_id=ctx.user.id,
                state=payload.state,
                target_url=payload.target_url,
                reason=payload.reason,
            )
        )
    except (
        ContentNotFoundError,
        ContentConflictError,
        ContentValidationBlockedError,
    ) as exc:
        raise _content_error(exc) from exc


@router.get("/revisions/{revision_id}/export", response_class=PlainTextResponse)
async def export_content_revision_endpoint(
    revision_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> PlainTextResponse:
    try:
        revision = await get_revision(
            session, workspace_id=ctx.workspace_id, revision_id=revision_id
        )
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc
    return PlainTextResponse(
        revision.visible_content,
        headers={
            "Content-Disposition": f'attachment; filename="content-{revision.id}.md"'
        },
    )


@router.post(
    "/revisions/{revision_id}/verifications",
    response_model=ContentVerificationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def verify_content_revision_endpoint(
    revision_id: uuid.UUID,
    payload: ContentVerificationCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ContentVerificationResponse:
    try:
        row, _created = await verify_revision(
            session,
            workspace_id=ctx.workspace_id,
            revision_id=revision_id,
            site_snapshot_id=payload.site_snapshot_id,
        )
        return ContentVerificationResponse.model_validate(row)
    except (ContentNotFoundError, ContentConflictError) as exc:
        raise _content_error(exc) from exc


@router.get("/verifications", response_model=list[ContentVerificationResponse])
async def content_verifications_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID, Query()],
) -> list[ContentVerificationResponse]:
    try:
        rows = await list_verifications(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
        return [ContentVerificationResponse.model_validate(row) for row in rows]
    except ContentNotFoundError as exc:
        raise _not_found(exc) from exc


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
    # Cap matches the DB column width so an overlong header fails 422 here
    # instead of a DataError at insert time.
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
            website_context_enabled=payload.website_context_enabled,
            idempotency_key=(idempotency_key or "").strip(),
            skill_id=payload.skill_id,
            opportunity_id=payload.opportunity_id,
            brief_id=payload.brief_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_PROVIDER_NOT_CONFIGURED,
        ) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_IDEMPOTENCY_CONFLICT,
        ) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/feedback",
    response_model=ContentGenerationDetail,
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


@router.get("/generations/{generation_id}", response_model=ContentGenerationDetail)
async def get_generation_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await get_generation(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/regenerate",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def regenerate_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await regenerate(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_PROVIDER_NOT_CONFIGURED,
        ) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/try-again",
    response_model=ContentGenerationDetail,
    status_code=status.HTTP_201_CREATED,
)
async def try_again_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await try_again(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except ProviderNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_PROVIDER_NOT_CONFIGURED,
        ) from exc
    except UsageLimitExceededError as exc:
        raise _usage_limited(exc) from exc
    return to_detail(row)


@router.post(
    "/generations/{generation_id}/cancel",
    response_model=ContentGenerationDetail,
)
async def cancel_generation_endpoint(
    generation_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ContentGenerationDetail:
    try:
        row = await cancel_generation(
            session,
            workspace_id=ctx.workspace_id,
            generation_id=generation_id,
        )
    except ContentGenerationNotFoundError as exc:
        raise _not_found(exc) from exc
    except CancelNotAllowedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_CANCEL_NOT_ALLOWED,
        ) from exc
    return to_detail(row)
