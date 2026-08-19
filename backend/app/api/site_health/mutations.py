"""Site Health entitlement, crawl, phase-control, inventory, and selection routes.

Every route is workspace-authorized through ``_WorkspaceDep``. Coded planner,
phase-control, and selection failures are mapped here onto their stable HTTP
statuses and bodies by the module-local ``_*_error_response`` helpers.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.usage_limits import enforce_workspace_request
from app.core.config.abuse import abuse_settings
from app.core.config.site_health_contracts import (
    CODE_ADVANCED_CONTROLS_UNAVAILABLE,
    CODE_ANALYSIS_LIMIT_EXCEEDED,
    CODE_CRAWL_ALREADY_ACTIVE,
    CODE_DISCOVERY_LIMIT_EXCEEDED,
    CODE_PHASE_ALREADY_RUNNING,
    CODE_PHASE_NOT_RESUMABLE,
)
from app.core.errors import ApiException
from app.domain.site_health import service
from app.domain.site_health.api_schemas import (
    BulkSelectMonitoredRequest,
    CrawlListPage,
    CrawlResponse,
    CreateCrawlRequest,
    InventoryPage,
    MonitoredUrlsResponse,
    PhaseMutationResponse,
    ReplaceMonitoredRequest,
    SiteHealthEntitlementResponse,
    StartAnalysisRequest,
    StartDiscoveryRequest,
    UrlPreviewRequest,
    UrlPreviewResponse,
)
from app.domain.site_health.phase_analysis import (
    start_analysis,
    stop_analysis,
)
from app.domain.site_health.phase_common import (
    PhaseControlError,
    PhaseMutationResult,
)
from app.domain.site_health.phase_control import (
    start_discovery,
    stop_discovery,
)
from app.domain.site_health.planner import (
    CrawlAlreadyActiveError,
    CrawlPlanError,
    create_crawl,
    preview_crawl_urls,
)
from app.domain.site_health.selection import (
    MonitoringNotAllowedError,
    QuotaExceededError,
    SelectionValidationError,
    StaleSelectionVersionError,
    bulk_select_monitored_set,
    replace_monitored_set,
)
from app.domain.site_health.service import (
    InvalidCursorError,
    SiteHealthNotFoundError,
    project_phase_run,
)

from .common import _bad_cursor, _not_found, _SessionDep, _WorkspaceDep, router


def _selection_error_response(exc: Exception) -> ApiException:
    """Map a coded selection error onto the Task 2 HTTP contract.

    ``monitoring_not_allowed`` -> 403, ``site_health_quota_exceeded`` -> 403 (with
    ``limit``/``currently_used``), ``stale_selection_version`` -> 409 (with
    ``current_selection_version``), ``invalid_selection`` -> 422. Shared by
    the PUT replacement and the bulk-select endpoints so both speak the same
    coded-error dialect. ``ApiException.coded`` keeps the legacy ``detail``
    dict byte-identical while adding the canonical ``error`` block (WS-A A1).
    """
    if isinstance(exc, QuotaExceededError):
        return ApiException.coded(
            status.HTTP_403_FORBIDDEN,
            exc.code,
            str(exc),
            details={"limit": exc.limit, "currently_used": exc.currently_used},
        )
    if isinstance(exc, StaleSelectionVersionError):
        return ApiException.coded(
            status.HTTP_409_CONFLICT,
            exc.code,
            str(exc),
            details={"current_selection_version": exc.current_version},
        )
    if isinstance(exc, MonitoringNotAllowedError):
        return ApiException.coded(status.HTTP_403_FORBIDDEN, exc.code, str(exc))
    # SelectionValidationError (and any other coded selection error) -> 422.
    code = getattr(exc, "code", "invalid_selection")
    return ApiException.coded(status.HTTP_422_UNPROCESSABLE_ENTITY, code, str(exc))


def _phase_error_response(exc: PhaseControlError) -> ApiException:
    if exc.code == "not_found":
        return _not_found(str(exc))
    if exc.code in {
        CODE_PHASE_ALREADY_RUNNING,
        CODE_PHASE_NOT_RESUMABLE,
        "stale_selection_version",
    }:
        return ApiException.coded(status.HTTP_409_CONFLICT, exc.code, str(exc))
    if exc.code == "site_health_quota_exceeded":
        return ApiException.coded(status.HTTP_403_FORBIDDEN, exc.code, str(exc))
    if exc.code in {CODE_DISCOVERY_LIMIT_EXCEEDED, CODE_ANALYSIS_LIMIT_EXCEEDED}:
        return ApiException.coded(
            status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc)
        )
    return ApiException.coded(status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc))


async def _phase_mutation_view(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    result: PhaseMutationResult,
) -> dict:
    try:
        dashboard = await service.get_dashboard(
            session,
            workspace_id=workspace_id,
            project_id=result.crawl.project_id,
            crawl_id=result.crawl.id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    run = result.phase_run
    return {
        "crawl": dashboard["crawl"],
        "phase_run": (project_phase_run(run) if run is not None else None),
        "created_new_crawl": result.created_new_crawl,
        "selection_version": result.selection_version,
        "scheduled_count": result.scheduled_count,
    }


async def _require_advanced_controls(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> None:
    entitlement = await service.get_entitlement_view(session, workspace_id=workspace_id)
    if not entitlement["advanced_controls_enabled"]:
        raise ApiException.coded(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_ADVANCED_CONTROLS_UNAVAILABLE,
            "Advanced Site Health controls are unavailable",
        )


async def _enforce_phase_mutation_request(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    phase: Literal["discovery", "analysis"],
) -> None:
    if phase == "discovery":
        operation = "site_health.discovery_phase_mutation"
        limit = abuse_settings.discovery_phase_mutation_limit
        window_seconds = abuse_settings.discovery_phase_mutation_window_seconds
    else:
        operation = "site_health.analysis_phase_mutation"
        limit = abuse_settings.analysis_phase_mutation_limit
        window_seconds = abuse_settings.analysis_phase_mutation_window_seconds
    await enforce_workspace_request(
        session,
        workspace_id=workspace_id,
        operation=operation,
        limit=limit,
        window_seconds=window_seconds,
    )


def _crawl_requested_page_limit(payload: CreateCrawlRequest) -> int | None:
    if payload.discovery_count is not None:
        return payload.discovery_count
    return payload.requested_page_limit


@router.get("/entitlements", response_model=SiteHealthEntitlementResponse)
async def get_entitlements_endpoint(
    ctx: _WorkspaceDep, session: _SessionDep
) -> SiteHealthEntitlementResponse:
    # Read-only: the runtime projection refreshes lazily but the read commits
    # nothing (no seed commit).
    view = await service.get_entitlement_view(session, workspace_id=ctx.workspace_id)
    return SiteHealthEntitlementResponse.model_validate(view)


@router.post(
    "/site-crawls",
    response_model=CrawlResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_crawl_endpoint(
    payload: CreateCrawlRequest, ctx: _WorkspaceDep, session: _SessionDep
) -> CrawlResponse:
    await enforce_workspace_request(
        session,
        workspace_id=ctx.workspace_id,
        operation="site_health.crawl_create",
        limit=abuse_settings.crawl_create_limit,
        window_seconds=abuse_settings.crawl_create_window_seconds,
    )
    try:
        crawl = await create_crawl(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            include_globs=payload.include_globs,
            exclude_globs=payload.exclude_globs,
            random_seed=payload.seed,
            input_mode=payload.input_mode,
            requested_page_limit=_crawl_requested_page_limit(payload),
            seed_urls=payload.seed_urls,
            page_kinds=payload.page_kinds,
        )
    except CrawlAlreadyActiveError as exc:
        raise ApiException.coded(
            status.HTTP_409_CONFLICT, CODE_CRAWL_ALREADY_ACTIVE, str(exc)
        ) from exc
    except CrawlPlanError as exc:
        if exc.code == "project_not_found":
            raise _not_found("Project not found") from exc
        raise ApiException.coded(
            status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc)
        ) from exc
    return CrawlResponse.model_validate(service.project_crawl(crawl))


@router.post(
    "/site-crawls/{crawl_id}/discovery/start",
    response_model=PhaseMutationResponse,
)
async def start_discovery_endpoint(
    crawl_id: uuid.UUID,
    payload: StartDiscoveryRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> PhaseMutationResponse:
    await _require_advanced_controls(session, workspace_id=ctx.workspace_id)
    await _enforce_phase_mutation_request(
        session,
        workspace_id=ctx.workspace_id,
        phase="discovery",
    )
    try:
        result = await start_discovery(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            additional_url_count=payload.additional_url_count,
        )
    except PhaseControlError as exc:
        raise _phase_error_response(exc) from exc
    return PhaseMutationResponse.model_validate(
        await _phase_mutation_view(
            session, workspace_id=ctx.workspace_id, result=result
        )
    )


@router.post(
    "/site-crawls/{crawl_id}/discovery/stop",
    response_model=PhaseMutationResponse,
)
async def stop_discovery_endpoint(
    crawl_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> PhaseMutationResponse:
    await _require_advanced_controls(session, workspace_id=ctx.workspace_id)
    await _enforce_phase_mutation_request(
        session,
        workspace_id=ctx.workspace_id,
        phase="discovery",
    )
    try:
        result = await stop_discovery(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except PhaseControlError as exc:
        raise _phase_error_response(exc) from exc
    return PhaseMutationResponse.model_validate(
        await _phase_mutation_view(
            session, workspace_id=ctx.workspace_id, result=result
        )
    )


@router.post(
    "/site-crawls/{crawl_id}/analysis/start",
    response_model=PhaseMutationResponse,
)
async def start_analysis_endpoint(
    crawl_id: uuid.UUID,
    payload: StartAnalysisRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> PhaseMutationResponse:
    await _require_advanced_controls(session, workspace_id=ctx.workspace_id)
    await _enforce_phase_mutation_request(
        session,
        workspace_id=ctx.workspace_id,
        phase="analysis",
    )
    try:
        result = await start_analysis(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            requested_url_count=payload.requested_url_count,
            site_url_ids=payload.site_url_ids,
            expected_selection_version=payload.expected_selection_version,
        )
    except PhaseControlError as exc:
        raise _phase_error_response(exc) from exc
    return PhaseMutationResponse.model_validate(
        await _phase_mutation_view(
            session, workspace_id=ctx.workspace_id, result=result
        )
    )


@router.post(
    "/site-crawls/{crawl_id}/analysis/stop",
    response_model=PhaseMutationResponse,
)
async def stop_analysis_endpoint(
    crawl_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> PhaseMutationResponse:
    await _require_advanced_controls(session, workspace_id=ctx.workspace_id)
    await _enforce_phase_mutation_request(
        session,
        workspace_id=ctx.workspace_id,
        phase="analysis",
    )
    try:
        result = await stop_analysis(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except PhaseControlError as exc:
        raise _phase_error_response(exc) from exc
    return PhaseMutationResponse.model_validate(
        await _phase_mutation_view(
            session, workspace_id=ctx.workspace_id, result=result
        )
    )


@router.post("/site-crawls/url-preview", response_model=UrlPreviewResponse)
async def preview_crawl_urls_endpoint(
    payload: UrlPreviewRequest, ctx: _WorkspaceDep, session: _SessionDep
) -> UrlPreviewResponse:
    """Preview admission only; it never creates a crawl, task, or fetch."""
    try:
        preview = await preview_crawl_urls(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            content=payload.content,
            input_format=payload.input_format,
            include_globs=payload.include_globs,
            exclude_globs=payload.exclude_globs,
        )
    except CrawlPlanError as exc:
        if exc.code == "project_not_found":
            raise _not_found("Project not found") from exc
        raise ApiException.coded(
            status.HTTP_422_UNPROCESSABLE_ENTITY, exc.code, str(exc)
        ) from exc
    return UrlPreviewResponse.model_validate(preview)


@router.get("/site-crawls", response_model=CrawlListPage)
async def list_crawls_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> CrawlListPage:
    try:
        page = await service.list_crawls(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            limit=limit,
            cursor=cursor,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return CrawlListPage.model_validate(page)


@router.get("/site-crawls/{crawl_id}", response_model=CrawlResponse)
async def get_crawl_endpoint(
    crawl_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> CrawlResponse:
    try:
        crawl = await service.get_crawl_summary(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return CrawlResponse.model_validate(crawl)


@router.post("/site-crawls/{crawl_id}/cancel", response_model=CrawlResponse)
async def cancel_crawl_endpoint(
    crawl_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> CrawlResponse:
    try:
        crawl = await service.cancel_crawl(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return CrawlResponse.model_validate(crawl)


@router.get("/site-crawls/{crawl_id}/inventory", response_model=InventoryPage)
async def get_inventory_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    monitored: Annotated[bool | None, Query()] = None,
    page_kind: Annotated[str | None, Query()] = None,
) -> InventoryPage:
    try:
        page = await service.get_inventory(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            limit=limit,
            cursor=cursor,
            query=query,
            status=status_filter,
            monitored=monitored,
            page_kind=page_kind,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return InventoryPage.model_validate(page)


@router.get(
    "/projects/{project_id}/monitored-urls",
    response_model=MonitoredUrlsResponse,
)
async def get_monitored_urls_endpoint(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> MonitoredUrlsResponse:
    try:
        result = await service.get_monitored_set(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return MonitoredUrlsResponse.model_validate(result)


@router.put(
    "/projects/{project_id}/monitored-urls",
    response_model=MonitoredUrlsResponse,
)
async def replace_monitored_urls_endpoint(
    project_id: uuid.UUID,
    payload: ReplaceMonitoredRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> MonitoredUrlsResponse:
    # Authorize the project first so a foreign id is a 404 (not a coded error).
    try:
        await service.get_monitored_set(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    try:
        await replace_monitored_set(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            site_url_ids=payload.site_url_ids,
            expected_selection_version=payload.expected_selection_version,
        )
        await session.commit()
    except (
        MonitoringNotAllowedError,
        QuotaExceededError,
        StaleSelectionVersionError,
        SelectionValidationError,
    ) as exc:
        await session.rollback()
        raise _selection_error_response(exc) from exc

    result = await service.get_monitored_set(
        session, workspace_id=ctx.workspace_id, project_id=project_id
    )
    return MonitoredUrlsResponse.model_validate(result)


@router.post(
    "/projects/{project_id}/monitored-urls/bulk-select",
    response_model=MonitoredUrlsResponse,
)
async def bulk_select_monitored_urls_endpoint(
    project_id: uuid.UUID,
    payload: BulkSelectMonitoredRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> MonitoredUrlsResponse:
    """Server-resolved bulk selection (first N / all / clear).

    Resolves candidate ids server-side in the inventory's deterministic
    ``(normalized_url, id)`` order, then reuses the SAME atomic replacement
    path (locks, version check, workspace quota, coded errors) as the PUT.
    """
    # Authorize the project first so a foreign id is a 404 (not a coded error).
    try:
        await service.get_monitored_set(
            session, workspace_id=ctx.workspace_id, project_id=project_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    try:
        await bulk_select_monitored_set(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            crawl_id=payload.crawl_id,
            mode=payload.mode,
            count=payload.count,
            query=payload.query,
            expected_selection_version=payload.expected_selection_version,
        )
        await session.commit()
    except (
        MonitoringNotAllowedError,
        QuotaExceededError,
        StaleSelectionVersionError,
        SelectionValidationError,
    ) as exc:
        await session.rollback()
        raise _selection_error_response(exc) from exc

    result = await service.get_monitored_set(
        session, workspace_id=ctx.workspace_id, project_id=project_id
    )
    return MonitoredUrlsResponse.model_validate(result)
