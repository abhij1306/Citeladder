"""Site Health dashboard, link-graph, change, and AEO readiness read routes.

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
    LinkGraphEdgesPage,
    LinkGraphNodesPage,
    LinkGraphSnapshotResponse,
)
from app.domain.site_health.change_schemas import (
    ChangeObservationResponse,
    ChangesPage,
    ChangeSummaryResponse,
)
from app.domain.site_health.service import (
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
    "/projects/{project_id}/site-health/link-graph",
    response_model=LinkGraphSnapshotResponse,
)
async def get_link_graph_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
) -> LinkGraphSnapshotResponse:
    try:
        result = await service.get_link_graph(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return LinkGraphSnapshotResponse.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/link-graph/nodes",
    response_model=LinkGraphNodesPage,
)
async def get_link_graph_nodes_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> LinkGraphNodesPage:
    try:
        result = await service.list_link_graph_nodes(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
            limit=limit,
            cursor=cursor,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return LinkGraphNodesPage.model_validate(result)


@router.get(
    "/projects/{project_id}/site-health/link-graph/edges",
    response_model=LinkGraphEdgesPage,
)
async def get_link_graph_edges_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    crawl_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> LinkGraphEdgesPage:
    try:
        result = await service.list_link_graph_edges(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=crawl_id,
            limit=limit,
            cursor=cursor,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return LinkGraphEdgesPage.model_validate(result)


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
