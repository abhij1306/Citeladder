"""Workspace-scoped persisted onboarding discovery API."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.errors import ApiException
from app.domain.entitlements.enforcement import OccupancyError
from app.domain.projects.discovery import (
    BrandDiscoveryError,
    complete_discovery,
    create_discovery,
    discovery_catalog,
    get_discovery,
)
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryCatalogResponse,
    BrandDiscoveryComplete,
    BrandDiscoveryCompleteResponse,
    BrandDiscoveryCreate,
    BrandDiscoveryResponse,
)

router = APIRouter(tags=["brand-discoveries"])
_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _page_limit(configuration: dict) -> int:
    value = configuration.get("requested_page_limit")
    if not isinstance(value, int):
        raise RuntimeError("Initial crawl is missing its page limit")
    return value


@router.get("/brand-discovery-catalog")
async def get_brand_discovery_catalog() -> BrandDiscoveryCatalogResponse:
    return BrandDiscoveryCatalogResponse(**discovery_catalog())


@router.post(
    "/brand-discoveries",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_brand_discovery(
    payload: BrandDiscoveryCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> BrandDiscoveryResponse:
    try:
        row = await create_discovery(
            session,
            workspace_id=ctx.workspace_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except BrandDiscoveryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return BrandDiscoveryResponse.model_validate(row)


@router.get("/brand-discoveries/{discovery_id}")
async def get_brand_discovery(
    discovery_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> BrandDiscoveryResponse:
    try:
        row = await get_discovery(
            session, workspace_id=ctx.workspace_id, discovery_id=discovery_id
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return BrandDiscoveryResponse.model_validate(row)


@router.post(
    "/brand-discoveries/{discovery_id}/complete",
    status_code=status.HTTP_201_CREATED,
)
async def complete_brand_discovery(
    discovery_id: uuid.UUID,
    payload: BrandDiscoveryComplete,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> BrandDiscoveryCompleteResponse:
    try:
        row, crawl = await complete_discovery(
            session,
            workspace_id=ctx.workspace_id,
            discovery_id=discovery_id,
            payload=payload,
            idempotency_key=idempotency_key,
        )
    except LookupError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except BrandDiscoveryError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except OccupancyError as exc:
        await session.rollback()
        raise ApiException.coded(
            status.HTTP_403_FORBIDDEN, exc.code, str(exc), details=exc.details
        ) from exc
    return _completion_response(row, crawl)


def _completion_response(row, crawl) -> BrandDiscoveryCompleteResponse:
    if row.project_id is None:
        raise RuntimeError("Discovery completion is missing its project identity")
    return BrandDiscoveryCompleteResponse(
        project_id=row.project_id,
        crawl_id=crawl.id if crawl is not None else None,
        page_limit=(
            _page_limit(crawl.configuration or {}) if crawl is not None else None
        ),
        warnings=list(row.warnings),
    )
