# Workspaces router: list the caller's workspaces + create a new one.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_current_user,
    get_db,
    require_workspace_member,
)
from app.core.config.workspaces import CODE_WORKSPACE_LIMIT_EXCEEDED
from app.core.errors import ApiException
from app.domain.workspaces.schemas import (
    ProductTourResponse,
    ProductTourUpdate,
    WorkspaceCreate,
    WorkspaceResponse,
)
from app.domain.workspaces.service import (
    WorkspaceLimitExceededError,
    create_workspace,
    list_workspaces_for_user,
    product_tour_response,
    update_product_tour,
)
from app.models.user import User

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[WorkspaceResponse]:
    rows = await list_workspaces_for_user(session, user)
    return [
        WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            role=member.role,
            created_at=workspace.created_at,
            updated_at=workspace.updated_at,
        )
        for workspace, member in rows
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace_endpoint(
    payload: WorkspaceCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    try:
        workspace, member = await create_workspace(session, user, payload.name)
    except WorkspaceLimitExceededError as exc:
        raise ApiException.coded(
            status.HTTP_403_FORBIDDEN,
            CODE_WORKSPACE_LIMIT_EXCEEDED,
            str(exc),
            details={"limit": exc.limit},
        ) from exc
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        role=member.role,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


@router.get("/{workspace_id}/product-tour", response_model=ProductTourResponse)
async def get_product_tour(
    ctx: Annotated[WorkspaceContext, Depends(require_workspace_member)],
) -> ProductTourResponse:
    return product_tour_response(ctx.member)


@router.patch("/{workspace_id}/product-tour", response_model=ProductTourResponse)
async def patch_product_tour(
    payload: ProductTourUpdate,
    ctx: Annotated[WorkspaceContext, Depends(require_workspace_member)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> ProductTourResponse:
    return await update_product_tour(session, ctx.member, payload)
