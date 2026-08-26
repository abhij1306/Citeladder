"""Workspace-authorized Commerce replacement API under one project family."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.gateway import ModelGateway
from app.core.errors import ApiException
from app.core.http_errors import raise_not_found
from app.domain.commerce.competitors import (
    decide_candidate,
    enqueue_discoveries,
    list_candidates,
)
from app.domain.commerce.prompts import (
    BuyerPromptGenerationUnavailable,
    add_manual_buyer_prompt,
    decide_buyer_prompt,
    generate_buyer_prompts,
    list_buyer_prompts,
)
from app.domain.commerce.schemas import (
    BuyerPromptDecisionRequest,
    BuyerPromptGenerateRequest,
    BuyerPromptManualRequest,
    BuyerPromptResponse,
    CatalogEditRequest,
    CatalogImportRequest,
    CatalogImportResponse,
    CatalogResponse,
    CategoryEditRequest,
    CategoryResponse,
    CompetitorCandidateResponse,
    CompetitorDecisionRequest,
    DiscoveryRequest,
    DiscoveryResponse,
    ProductResponse,
    ShelfResponse,
)
from app.domain.commerce.service import (
    CommerceConflictError,
    CommerceImportError,
    CommerceNotFoundError,
    edit_category,
    edit_product,
    get_catalog,
    import_catalog,
)
from app.domain.commerce.shelf import get_shelf

router = APIRouter(prefix="/projects", tags=["commerce"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _map_error(exc: Exception) -> ApiException:
    if isinstance(exc, CommerceNotFoundError):
        return ApiException(status.HTTP_404_NOT_FOUND, "commerce_not_found", str(exc))
    if isinstance(exc, CommerceConflictError):
        return ApiException.coded(
            status.HTTP_409_CONFLICT, "commerce_conflict", str(exc)
        )
    return ApiException.coded(
        status.HTTP_422_UNPROCESSABLE_CONTENT, "commerce_invalid", str(exc)
    )


@router.get("/{project_id}/commerce/catalog", response_model=CatalogResponse)
async def catalog_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> CatalogResponse:
    try:
        return await get_catalog(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except CommerceNotFoundError as exc:
        raise_not_found("Project", cause=exc)


@router.post(
    "/{project_id}/commerce/catalog/import",
    response_model=CatalogImportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def catalog_import_endpoint(
    project_id: uuid.UUID,
    payload: CatalogImportRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> CatalogImportResponse:
    try:
        return await import_catalog(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            payload=payload,
        )
    except (CommerceNotFoundError, CommerceConflictError, CommerceImportError) as exc:
        raise _map_error(exc) from exc


@router.patch(
    "/{project_id}/commerce/catalog/categories/{category_id}",
    response_model=CategoryResponse,
)
async def category_edit_endpoint(
    project_id: uuid.UUID,
    category_id: uuid.UUID,
    payload: CategoryEditRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> CategoryResponse:
    try:
        return await edit_category(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            category_id=category_id,
            payload=payload,
        )
    except (CommerceNotFoundError, CommerceConflictError) as exc:
        raise _map_error(exc) from exc


@router.patch(
    "/{project_id}/commerce/catalog/products/{product_id}",
    response_model=ProductResponse,
)
async def catalog_edit_endpoint(
    project_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: CatalogEditRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ProductResponse:
    try:
        return await edit_product(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            product_id=product_id,
            payload=payload,
        )
    except (CommerceNotFoundError, CommerceConflictError) as exc:
        raise _map_error(exc) from exc


@router.post(
    "/{project_id}/commerce/competitors/discover",
    response_model=DiscoveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def competitor_discovery_endpoint(
    project_id: uuid.UUID,
    payload: DiscoveryRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> DiscoveryResponse:
    try:
        return await enqueue_discoveries(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            targets=payload.targets,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.get(
    "/{project_id}/commerce/competitors",
    response_model=list[CompetitorCandidateResponse],
)
async def competitors_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[CompetitorCandidateResponse]:
    try:
        return await list_candidates(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.patch(
    "/{project_id}/commerce/competitors/{candidate_id}",
    response_model=CompetitorCandidateResponse,
)
async def competitor_decision_endpoint(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: CompetitorDecisionRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> CompetitorCandidateResponse:
    try:
        return await decide_candidate(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            candidate_id=candidate_id,
            decision=payload.decision,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.get(
    "/{project_id}/commerce/buyer-prompts", response_model=list[BuyerPromptResponse]
)
async def buyer_prompts_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[BuyerPromptResponse]:
    try:
        return await list_buyer_prompts(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.post(
    "/{project_id}/commerce/buyer-prompts/generate",
    response_model=list[BuyerPromptResponse],
    status_code=status.HTTP_201_CREATED,
)
async def buyer_prompts_generate_endpoint(
    project_id: uuid.UUID,
    payload: BuyerPromptGenerateRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> list[BuyerPromptResponse]:
    try:
        gateway: ModelGateway = create_model_gateway()
    except AgentNotConfiguredError as exc:
        raise ApiException.coded(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "commerce_prompt_generation_unavailable",
            "No structured model is configured; manual prompt entry remains available.",
        ) from exc
    try:
        return await generate_buyer_prompts(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            targets=payload.targets,
            count=payload.count,
            gateway=gateway,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc
    except BuyerPromptGenerationUnavailable as exc:
        raise ApiException.coded(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "commerce_prompt_generation_unavailable",
            str(exc),
        ) from exc


@router.post(
    "/{project_id}/commerce/buyer-prompts/manual",
    response_model=BuyerPromptResponse,
    status_code=status.HTTP_201_CREATED,
)
async def buyer_prompt_manual_endpoint(
    project_id: uuid.UUID,
    payload: BuyerPromptManualRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> BuyerPromptResponse:
    try:
        return await add_manual_buyer_prompt(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            target=payload.target,
            text=payload.text,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.patch(
    "/{project_id}/commerce/buyer-prompts/{prompt_id}",
    response_model=BuyerPromptResponse,
)
async def buyer_prompt_decision_endpoint(
    project_id: uuid.UUID,
    prompt_id: uuid.UUID,
    payload: BuyerPromptDecisionRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> BuyerPromptResponse:
    try:
        return await decide_buyer_prompt(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            prompt_id=prompt_id,
            approved=payload.approved,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc


@router.get("/{project_id}/commerce/ai-shelf", response_model=ShelfResponse)
async def ai_shelf_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ShelfResponse:
    try:
        return await get_shelf(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
        )
    except CommerceNotFoundError as exc:
        raise _map_error(exc) from exc
