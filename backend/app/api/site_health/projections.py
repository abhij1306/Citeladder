"""Site Health dashboard, change, AEO readiness, and architecture routes.

Every route is workspace-authorized through ``_WorkspaceDep`` and projects
persisted rows via the service layer; nothing here crawls, re-scores, or
repairs state.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Query, status

from app.core.config.errors import CODE_VALIDATION_ERROR
from app.core.errors import ApiException
from app.domain.site_health import service
from app.domain.site_health.api_schemas import (
    AeoReadinessResponse,
    DashboardResponse,
)
from app.domain.site_health.architecture_schemas import (
    ArchetypeOverrideResponse,
    ArchitectureResponse,
    SetArchetypeRequest,
)
from app.domain.site_health.change_schemas import (
    ChangeObservationResponse,
    ChangesPage,
    ChangeSummaryResponse,
)
from app.domain.site_health.service import (
    InvalidArchetypeError,
    InvalidChangeSelectionError,
    InvalidCursorError,
    SiteHealthNotFoundError,
)

from .common import _bad_cursor, _not_found, _SessionDep, _WorkspaceDep, router


def _change_selection_error(exc: InvalidChangeSelectionError) -> ApiException:
    return ApiException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, CODE_VALIDATION_ERROR, str(exc)
    )


@router.get("/projects/{project_id}/site-health", response_model=DashboardResponse)
async def get_dashboard_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
) -> DashboardResponse:
    try:
        result = await service.get_dashboard(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return DashboardResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/changes/summary",
    response_model=ChangeSummaryResponse,
)
async def get_changes_summary_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_a_id: Annotated[uuid.UUID | None, Query()] = None,
    crawl_b_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ChangeSummaryResponse:
    try:
        result = await service.get_changes_summary(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_a_id=crawl_a_id,
            crawl_b_id=crawl_b_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidChangeSelectionError as exc:
        raise _change_selection_error(exc) from exc
    return ChangeSummaryResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/changes",
    response_model=ChangesPage,
)
async def list_changes_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_a_id: Annotated[uuid.UUID | None, Query()] = None,
    crawl_b_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> ChangesPage:
    try:
        result = await service.list_changes(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_a_id=crawl_a_id,
            crawl_b_id=crawl_b_id,
            limit=limit,
            cursor=cursor,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    except InvalidChangeSelectionError as exc:
        raise _change_selection_error(exc) from exc
    return ChangesPage.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/changes/{observation_id}",
    response_model=ChangeObservationResponse,
)
async def get_change_endpoint(
    project_id: uuid.UUID,
    observation_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ChangeObservationResponse:
    try:
        result = await service.get_change(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            observation_id=observation_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return ChangeObservationResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/aeo-readiness",
    response_model=AeoReadinessResponse,
)
async def get_aeo_readiness_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
) -> AeoReadinessResponse:
    try:
        result = await service.get_aeo_readiness(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return AeoReadinessResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/architecture",
    response_model=ArchitectureResponse,
)
async def get_architecture_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ArchitectureResponse:
    """The crawl's persisted observed-architecture model (never re-derived)."""
    try:
        result = await service.get_architecture(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return ArchitectureResponse.model_validate(result)


@router.put(
    "/projects/{project_id}/site-health/architecture/archetype",
    response_model=ArchetypeOverrideResponse,
)
async def set_archetype_endpoint(
    project_id: uuid.UUID,
    payload: SetArchetypeRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ArchetypeOverrideResponse:
    """Correct (or clear) the project's archetype.

    A presentation-layer correction only: it rewrites no evidence, re-evaluates
    no rule, and moves no score.
    """
    try:
        result = await service.set_archetype_override(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            archetype=payload.archetype,
        )
        await session.commit()
    except SiteHealthNotFoundError as exc:
        await session.rollback()
        raise _not_found(str(exc)) from exc
    except InvalidArchetypeError as exc:
        await session.rollback()
        raise ApiException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, CODE_VALIDATION_ERROR, str(exc)
        ) from exc
    return ArchetypeOverrideResponse.model_validate(result)
