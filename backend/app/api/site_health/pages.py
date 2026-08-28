"""Site Health page, rerun, and issue read routes.

Every route is workspace-authorized through ``_WorkspaceDep`` and projects
persisted rows via the service layer; nothing here crawls, re-scores, or
repairs state.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import Query, status

from app.core.errors import ApiException
from app.domain.site_health import service
from app.domain.site_health.api_schemas import (
    GroupedIssueHistoryPage,
    IssueHistoryPage,
    PageDetail,
    PagesPage,
    RerunPageResponse,
    SiteIssueDetail,
    SiteIssuesPage,
)
from app.domain.site_health.rerun import (
    RerunNotAllowedError,
    rerun_page,
)
from app.domain.site_health.selection import (
    MonitoringNotAllowedError,
    SelectionValidationError,
)
from app.domain.site_health.service import InvalidCursorError, SiteHealthNotFoundError

from .common import _bad_cursor, _not_found, _SessionDep, _WorkspaceDep, router


@router.get("/site-crawls/{crawl_id}/pages", response_model=PagesPage)
async def get_pages_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    monitored: Annotated[bool | None, Query()] = None,
    page_kind: Annotated[str | None, Query()] = None,
    sort: Annotated[
        Literal["url", "inbound", "main_content_inbound", "depth"], Query()
    ] = "url",
) -> PagesPage:
    try:
        page = await service.get_pages(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            limit=limit,
            cursor=cursor,
            status=status_filter,
            monitored=monitored,
            page_kind=page_kind,
            sort=sort,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return PagesPage.model_validate(page)


@router.get("/site-crawls/{crawl_id}/pages/{site_url_id}", response_model=PageDetail)
async def get_page_detail_endpoint(
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> PageDetail:
    try:
        detail = await service.get_page_detail(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            site_url_id=site_url_id,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    return PageDetail.model_validate(detail)


@router.post(
    "/site-crawls/{crawl_id}/pages/{site_url_id}/rerun",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RerunPageResponse,
)
async def rerun_page_endpoint(
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> RerunPageResponse:
    """Enqueue an explicit rerun of one page's analysis (202).

    Workspace-authorized via the same page-detail lookup as the GET route (a
    foreign/missing crawl or URL is a 404, never a coded selection error), so
    the rerun can never target another workspace's evidence.

    "Re-audit this page" is normally invoked from a COMPLETED (terminal) crawl.
    Because enqueuing into a terminal crawl would be cancelled by the worker,
    the domain layer mints a fresh single-page rerun crawl in that case. The
    202 body therefore carries the (possibly new) crawl identity + analysis
    status so the client polls the fresh run rather than the terminal source
    crawl: ``{crawl_id, site_url_id, task_id, created_new_crawl,
    analysis_status}``.
    """
    try:
        await service.get_page_detail(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            site_url_id=site_url_id,
        )
        crawl_summary = await service.get_crawl_summary(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc

    try:
        result = await rerun_page(
            session,
            workspace_id=ctx.workspace_id,
            project_id=crawl_summary["project_id"],
            site_url_id=site_url_id,
        )
        await session.commit()
    except MonitoringNotAllowedError as exc:
        await session.rollback()
        raise ApiException.coded(status.HTTP_403_FORBIDDEN, exc.code, str(exc)) from exc
    except RerunNotAllowedError as exc:
        await session.rollback()
        raise ApiException.coded(status.HTTP_409_CONFLICT, exc.code, str(exc)) from exc
    except SelectionValidationError as exc:
        await session.rollback()
        raise ApiException.coded(
            status.HTTP_422_UNPROCESSABLE_CONTENT, exc.code, str(exc)
        ) from exc

    return RerunPageResponse(
        crawl_id=result.crawl_id,
        site_url_id=result.site_url_id,
        task_id=result.task_id,
        created_new_crawl=result.created_new_crawl,
        analysis_status=result.analysis_status,
    )


@router.get(
    "/site-crawls/{crawl_id}/pages/{site_url_id}/issue-history",
    response_model=IssueHistoryPage | GroupedIssueHistoryPage,
)
async def get_issue_history_endpoint(
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    view: Annotated[Literal["occurrences", "grouped"], Query()] = "occurrences",
) -> IssueHistoryPage | GroupedIssueHistoryPage:
    try:
        if view == "grouped":
            page = await service.get_grouped_issue_history(
                session,
                workspace_id=ctx.workspace_id,
                crawl_id=crawl_id,
                site_url_id=site_url_id,
                limit=limit,
                cursor=cursor,
            )
        else:
            page = await service.get_issue_history(
                session,
                workspace_id=ctx.workspace_id,
                crawl_id=crawl_id,
                site_url_id=site_url_id,
                limit=limit,
                cursor=cursor,
            )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    if view == "grouped":
        return GroupedIssueHistoryPage.model_validate(page)
    return IssueHistoryPage.model_validate(page)


@router.get("/site-crawls/{crawl_id}/issues", response_model=SiteIssuesPage)
async def get_issues_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    dimension: Annotated[str | None, Query()] = None,
    rule: Annotated[str | None, Query()] = None,
    site_url_id: Annotated[uuid.UUID | None, Query()] = None,
    page_kind: Annotated[str | None, Query()] = None,
    finding_class: Annotated[Literal["defect", "advisory"], Query()] = "defect",
) -> SiteIssuesPage:
    try:
        page = await service.get_issues(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            limit=limit,
            cursor=cursor,
            query=query,
            severity=severity,
            category=category,
            dimension=dimension,
            rule=rule,
            site_url_id=site_url_id,
            page_kind=page_kind,
            finding_class=finding_class,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return SiteIssuesPage.model_validate(page)


@router.get(
    "/site-crawls/{crawl_id}/issues/{canonical_id}",
    response_model=SiteIssueDetail,
)
async def get_issue_detail_endpoint(
    crawl_id: uuid.UUID,
    canonical_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
) -> SiteIssueDetail:
    try:
        detail = await service.get_issue_detail(
            session,
            workspace_id=ctx.workspace_id,
            crawl_id=crawl_id,
            canonical_id=canonical_id,
            limit=limit,
            cursor=cursor,
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    except InvalidCursorError as exc:
        raise _bad_cursor(exc) from exc
    return SiteIssueDetail.model_validate(detail)
