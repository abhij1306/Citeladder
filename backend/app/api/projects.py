# Projects router: workspace-scoped CRUD (invariant 5).
#
# The API surface is flat (no workspace_id in the path); the active
# workspace is resolved by ``require_active_workspace`` from the
# ``X-Workspace-Id`` header (or the caller's default workspace). Every query
# filters by that workspace. ``/projects/{id}/visibility`` is added in B6.
from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    WorkspaceContext,
    get_db,
    require_active_workspace,
    require_project_member,
)
from app.api.usage_limits import enforce_workspace_request
from app.core.config.abuse import abuse_settings
from app.core.config.analysis import (
    VISIBILITY_EVIDENCE_DEFAULT_LIMIT,
    VISIBILITY_EVIDENCE_MAX_LIMIT,
    VISIBILITY_TREND_DEFAULT_GRANULARITY,
)
from app.core.config.brand_logos import BRAND_LOGO_CACHE_MAX_AGE_SECONDS
from app.core.errors import ApiException
from app.core.http_errors import raise_not_found
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.analysis.evidence import get_visibility_evidence
from app.domain.analysis.metrics import get_prompt_metrics
from app.domain.analysis.schemas import (
    PromptMetricItem,
    VisibilityEvidenceResponse,
    VisibilityResponse,
    VisibilityTrendPoint,
)
from app.domain.analysis.trends import get_visibility_trends
from app.domain.analysis.visibility import get_visibility
from app.domain.command_center.report import render_executive_pdf
from app.domain.command_center.schemas import CommandCenterResponse
from app.domain.command_center.service import get_command_center
from app.domain.entitlements.enforcement import OccupancyError
from app.domain.projects.brand_profile import (
    BrandProfileNotFoundError,
    brand_profile_to_response,
    get_brand_profile,
    upsert_manual_brand_profile,
)
from app.domain.projects.logos import (
    BrandLogoNotFoundError,
    get_project_logo_asset,
    refresh_project_logos,
)
from app.domain.projects.observed_competitors import (
    ObservedCandidateNotFoundError,
    accept_observed_candidate,
    list_observed_candidates,
)
from app.domain.projects.schemas import (
    BrandProfileResponse,
    BrandProfileUpsert,
    CompetitorResponse,
    ObservedCompetitorResponse,
    ProjectCreate,
    ProjectResponse,
    ProjectUpdate,
)
from app.domain.projects.service import (
    ProjectNotFoundError,
    create_project,
    delete_project,
    get_project,
    list_projects,
    project_to_response,
    update_project,
)

router = APIRouter(prefix="/projects", tags=["projects"])


async def _map_occupancy[T](call: Callable[[], Awaitable[T]]) -> T:
    """Run one occupancy-gated mutation, mapping a denial to the coded 403.

    The quota check lives in the domain service (never a route precheck);
    the router only translates the domain error into the API error contract.
    """
    try:
        return await call()
    except OccupancyError as exc:
        raise ApiException.coded(
            status.HTTP_403_FORBIDDEN, exc.code, str(exc), details=exc.details
        ) from exc


_RES_PROJECT = "Project"

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
# For routes the browser hits directly (no X-Workspace-Id header can ride on an
# <img src>), authorize through the project id already in the path.
_ProjectMemberDep = Annotated[WorkspaceContext, Depends(require_project_member)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def _get_project_or_404(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
):
    """Authorize the project, translating a cross-workspace/missing project
    into the API's 404 (mirrors ``_get_or_404`` in audits.py)."""
    try:
        return await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
    except ProjectNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)


@router.get("", response_model=list[ProjectResponse])
async def list_projects_endpoint(
    ctx: _WorkspaceDep, session: _SessionDep
) -> list[ProjectResponse]:
    projects = await list_projects(session, workspace_id=ctx.workspace_id)
    return [project_to_response(project) for project in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project_endpoint(
    payload: ProjectCreate, ctx: _WorkspaceDep, session: _SessionDep
) -> ProjectResponse:
    project = await _map_occupancy(
        lambda: create_project(
            session,
            workspace_id=ctx.workspace_id,
            payload=payload,
            reviewer_id=ctx.user.id,
        )
    )
    return project_to_response(project)


@router.get(
    "/{project_id}/brand-profile",
    response_model=BrandProfileResponse,
)
async def get_brand_profile_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> BrandProfileResponse:
    # Authorize through the owning project before reading the denormalized row.
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        profile = await get_brand_profile(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except BrandProfileNotFoundError as exc:
        raise_not_found("Brand profile", cause=exc)
    return brand_profile_to_response(profile)


@router.put(
    "/{project_id}/brand-profile",
    response_model=BrandProfileResponse,
)
async def put_brand_profile_endpoint(
    project_id: uuid.UUID,
    payload: BrandProfileUpsert,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> BrandProfileResponse:
    try:
        profile = await upsert_manual_brand_profile(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            user_id=ctx.user.id,
            payload=payload,
        )
    except (ProjectNotFoundError, BrandProfileNotFoundError) as exc:
        raise_not_found("Brand profile", cause=exc)
    return brand_profile_to_response(profile)


@router.get(
    "/{project_id}/visibility/prompts",
    response_model=list[PromptMetricItem],
)
async def get_prompt_metrics_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[PromptMetricItem]:
    """Prompt scores and comparable-run movements from persisted evidence."""
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_prompt_metrics(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Audit", cause=exc)


@router.get(
    "/{project_id}/visibility/trends",
    response_model=list[VisibilityTrendPoint],
)
async def get_visibility_trends_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    engine: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    granularity: Annotated[str, Query()] = VISIBILITY_TREND_DEFAULT_GRANULARITY,
    measurement_mode: Annotated[str | None, Query()] = None,
    transport_model: Annotated[str | None, Query()] = None,
    retrieval_enabled: Annotated[bool | None, Query()] = None,
    cohort: Annotated[Literal["core", "comparison"], Query()] = "core",
) -> list[VisibilityTrendPoint]:
    """Cross-run Visibility trend projection for a project (invariant 7).

    An ordered series of ``VisibilityTrendPoint``s projected from the project's
    persisted dashboard-ready ``MetricSnapshot`` rows — optionally filtered by
    ``engine`` (``logical_engine``) and an inclusive UTC ``from``/``to`` window,
    and bucketed by ``granularity=run|week|month``. No provider is called and no
    historical run is re-scored. A valid project with no matching history
    returns ``[]`` (not 404); invalid engine/granularity/range or naive
    timestamps return 422.

    Folding may combine points only inside one ``(measurement_mode,
    transport_model, retrieval_enabled)`` identity partition, so unlike
    identities return separate ordered points. The optional
    ``measurement_mode``/``transport_model``/``retrieval_enabled`` query
    params request an explicit identity slice, applied before folding; an
    unsupported ``measurement_mode`` returns 422.
    """
    # Authorize the project first (404 for a cross-workspace/missing project).
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_visibility_trends(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            logical_engine=engine,
            from_at=from_at,
            to_at=to_at,
            granularity=granularity,
            measurement_mode=measurement_mode,
            transport_model=transport_model,
            retrieval_enabled=retrieval_enabled,
            cohort=cohort,
        )
    except TrendQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/{project_id}/visibility/evidence",
    response_model=VisibilityEvidenceResponse,
)
async def get_visibility_evidence_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
    prompt_id: Annotated[uuid.UUID | None, Query()] = None,
    engine: Annotated[str | None, Query()] = None,
    from_at: Annotated[datetime | None, Query(alias="from")] = None,
    to_at: Annotated[datetime | None, Query(alias="to")] = None,
    limit: Annotated[
        int, Query(ge=1, le=VISIBILITY_EVIDENCE_MAX_LIMIT)
    ] = VISIBILITY_EVIDENCE_DEFAULT_LIMIT,
    cohort: Annotated[Literal["core", "comparison"], Query()] = "core",
) -> VisibilityEvidenceResponse:
    """Persisted execution-evidence projection for a project (invariant 7).

    The shared read-only dataset behind the Mentions & Citations and Query
    Fanout tabs: persisted brand/competitor mentions, classified citations, and
    normalized query-fanout events for the project's dashboard-ready audits —
    optionally filtered by ``audit_id``, ``prompt_id`` (source prompt on the
    frozen snapshot), ``engine`` (``logical_engine``), and an inclusive UTC
    ``from``/``to`` completion window. When both ``audit_id`` and a date window
    are supplied the filters intersect. No provider is called and no evidence is
    inferred/backfilled. A valid project with no matching evidence returns an
    empty ``items`` list (not 404); an unknown engine/range or naive timestamp
    returns 422; an ``audit_id`` outside the project/workspace returns 404
    without leaking whether it exists elsewhere.
    """
    # Authorize the project first (404 for a cross-workspace/missing project).
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_visibility_evidence(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
            prompt_id=prompt_id,
            logical_engine=engine,
            from_at=from_at,
            to_at=to_at,
            limit=limit,
            cohort=cohort,
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    except TrendQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


def _logo_response(
    content: bytes,
    content_type: str,
    asset_sha256: str,
    if_none_match: str | None,
) -> Response:
    etag = f'"{asset_sha256}"'
    headers = {
        "Cache-Control": f"private, max-age={BRAND_LOGO_CACHE_MAX_AGE_SECONDS}",
        "Content-Disposition": "inline",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "ETag": etag,
        "X-Content-Type-Options": "nosniff",
    }
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    return Response(
        content=content,
        media_type=content_type,
        headers=headers,
    )


@router.post("/{project_id}/logos/refresh", response_model=ProjectResponse)
async def refresh_project_logos_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ProjectResponse:
    await enforce_workspace_request(
        session,
        workspace_id=ctx.workspace_id,
        operation="brand_logo_refresh",
        limit=abuse_settings.brand_logo_refresh_limit,
        window_seconds=abuse_settings.brand_logo_refresh_window_seconds,
    )
    try:
        project = await refresh_project_logos(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
        )
    except ProjectNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    return project_to_response(project)


@router.get("/{project_id}/logo", response_class=Response)
async def get_brand_logo_endpoint(
    project_id: uuid.UUID,
    request: Request,
    ctx: _ProjectMemberDep,
    session: _SessionDep,
) -> Response:
    try:
        asset = await get_project_logo_asset(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
        )
    except BrandLogoNotFoundError as exc:
        raise_not_found("Brand logo", cause=exc)
    return _logo_response(
        asset.image_data or b"",
        asset.content_type,
        asset.sha256,
        request.headers.get("if-none-match"),
    )


@router.get(
    "/{project_id}/competitors/{competitor_id}/logo",
    response_class=Response,
)
async def get_competitor_logo_endpoint(
    project_id: uuid.UUID,
    competitor_id: uuid.UUID,
    request: Request,
    ctx: _ProjectMemberDep,
    session: _SessionDep,
) -> Response:
    try:
        asset = await get_project_logo_asset(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            competitor_id=competitor_id,
        )
    except BrandLogoNotFoundError as exc:
        raise_not_found("Competitor logo", cause=exc)
    return _logo_response(
        asset.image_data or b"",
        asset.content_type,
        asset.sha256,
        request.headers.get("if-none-match"),
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ProjectResponse:
    project = await _get_project_or_404(session, ctx.workspace_id, project_id)
    return project_to_response(project)


@router.get("/{project_id}/command-center", response_model=CommandCenterResponse)
async def get_command_center_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> CommandCenterResponse:
    project = await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_command_center(
            session,
            workspace_id=ctx.workspace_id,
            project=project,
            audit_id=audit_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed command-center measurement is available",
        ) from exc


@router.get("/{project_id}/reports/executive.pdf", response_class=Response)
async def get_executive_report_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Response:
    project = await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        command_center = await get_command_center(
            session,
            workspace_id=ctx.workspace_id,
            project=project,
            audit_id=audit_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed command-center measurement is available",
        ) from exc
    if not command_center.report_available or command_center.measurement is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed command-center measurement is available",
        )
    slug = re.sub(r"[^a-z0-9]+", "-", project.brand_name.lower()).strip("-")
    date = command_center.measurement.completed_at.date().isoformat()
    filename = f"citeladder-{slug or 'report'}-{date}.pdf"
    pdf = await asyncio.to_thread(render_executive_pdf, command_center)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{project_id}/visibility", response_model=VisibilityResponse)
async def get_visibility_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    audit_id: Annotated[uuid.UUID | None, Query()] = None,
    cohort: Annotated[Literal["core", "comparison"], Query()] = "core",
) -> VisibilityResponse:
    """Selected-run dashboard projection for a project (invariant 7).

    Visibility Score + per-engine comparison + brand-vs-competitor rankings,
    computed server-side from the persisted ``MetricSnapshot``. Defaults to the
    project's latest completed audit when ``audit_id`` is omitted. No provider
    is called; no cross-run trend in this payload (see /visibility/trends).
    """
    # Authorize the project first (404 for a cross-workspace/missing project).
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_visibility(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            audit_id=audit_id,
            cohort=cohort,
        )
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No visibility metrics available for project",
        ) from exc


@router.get(
    "/{project_id}/competitor-suggestions",
    response_model=list[ObservedCompetitorResponse],
)
async def list_observed_competitors_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[ObservedCompetitorResponse]:
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    rows = await list_observed_candidates(
        session, workspace_id=ctx.workspace_id, project_id=project_id
    )
    return [ObservedCompetitorResponse.model_validate(row) for row in rows]


@router.post(
    "/{project_id}/competitor-suggestions/{candidate_id}/accept",
    response_model=CompetitorResponse,
)
async def accept_observed_competitor_endpoint(
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> CompetitorResponse:
    try:
        competitor = await accept_observed_candidate(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            candidate_id=candidate_id,
        )
    except ObservedCandidateNotFoundError as exc:
        raise_not_found("Competitor suggestion", cause=exc)
    return CompetitorResponse.model_validate(competitor)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project_endpoint(
    project_id: uuid.UUID,
    payload: ProjectUpdate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> ProjectResponse:
    try:
        project = await update_project(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            payload=payload,
        )
    except ProjectNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    return project_to_response(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> None:
    try:
        await delete_project(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except ProjectNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
