"""Site Health event replay/SSE tail and CSV/Markdown export routes.

Every route is workspace-authorized through ``_WorkspaceDep`` and only renders
persisted, redacted projections; nothing here crawls, re-scores, or repairs
state.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Annotated

from fastapi import Query, Request, status
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.exports import (
    EXPORT_VIEWS,
    rows_to_csv,
    rows_to_markdown,
)
from app.core.config.errors import CODE_VALIDATION_ERROR
from app.core.config.site_health_contracts import CRAWL_TERMINAL_STATUSES
from app.core.config.site_health_runtime import site_health_settings
from app.core.database import SessionLocal
from app.core.errors import ApiException
from app.domain.site_health import service
from app.domain.site_health.service import SiteHealthNotFoundError
from app.domain.site_health.state_events import redact_event_payload

from .common import _not_found, _SessionDep, _WorkspaceDep, router

_SSE_TERMINAL_GRACE_POLLS = 2


def _sse_payload(event, *, count_disclosure: bool) -> str:
    payload = redact_event_payload(event.payload, count_disclosure=count_disclosure)
    body = {
        "id": str(event.id),
        "crawl_id": str(event.crawl_id),
        "event_type": event.event_type,
        "message": event.message or "",
        "payload": payload or {},
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
    return f"event: {event.event_type}\nid: {event.id}\ndata: {json.dumps(body)}\n\n"


async def _event_stream(
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    *,
    last_event_id: uuid.UUID | None,
):  # pragma: no cover - streaming loop
    """Tail a crawl's redacted events until terminal grace or max duration.

    Opens its own short-lived sessions (the request session is closed once the
    handler returns the ``StreamingResponse``). Redacts every payload with the
    crawl's frozen ``count_disclosure`` so a Free stream never leaks a total.
    """
    last_id = last_event_id
    terminal_polls = 0
    elapsed = 0.0
    poll = float(site_health_settings.sse_poll_interval_seconds)
    max_duration = float(site_health_settings.sse_max_duration_seconds)
    while True:
        page_size = site_health_settings.max_event_page
        async with SessionLocal() as session:
            try:
                crawl = await service.load_crawl_for_stream(
                    session, workspace_id=workspace_id, crawl_id=crawl_id
                )
            except SiteHealthNotFoundError:
                return
            disclose = service.crawl_count_disclosure(crawl)
            new_events = await service.load_events(
                session, crawl_id=crawl_id, after=last_id, limit=page_size
            )
            for event in new_events:
                last_id = event.id
                yield _sse_payload(event, count_disclosure=disclose)
            terminal = crawl.status in CRAWL_TERMINAL_STATUSES
        if len(new_events) == page_size:
            # Drain a full backlog page immediately. Otherwise terminal grace
            # could close the stream before the client receives later pages.
            continue
        if terminal:
            terminal_polls += 1
            if terminal_polls >= _SSE_TERMINAL_GRACE_POLLS:
                break
        if elapsed >= max_duration:
            break
        await asyncio.sleep(poll)
        elapsed += poll


@router.get("/site-crawls/{crawl_id}/events")
async def get_events_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    request: Request,
    stream: Annotated[bool, Query()] = False,
) -> Response:
    # Authorize first (404 for a cross-workspace / missing crawl).
    try:
        crawl = await service.load_crawl_for_stream(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc

    disclose = service.crawl_count_disclosure(crawl)

    # Resume from Last-Event-ID (header or query) so neither a reconnecting
    # stream NOR a JSON replay re-sends what the client already rendered.
    last_event_id: uuid.UUID | None = None
    raw_last = request.headers.get("Last-Event-ID") or request.query_params.get(
        "last_event_id"
    )
    if raw_last:
        try:
            last_event_id = uuid.UUID(raw_last)
        except ValueError:
            last_event_id = None

    if not stream:
        events = await service.load_events(
            session,
            crawl_id=crawl_id,
            after=last_event_id,
            limit=site_health_settings.max_event_page,
        )
        body = [
            {
                "id": str(e.id),
                "crawl_id": str(e.crawl_id),
                "event_type": e.event_type,
                "message": e.message or "",
                "payload": redact_event_payload(e.payload, count_disclosure=disclose)
                or {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in events
        ]
        return JSONResponse(content=body)

    return StreamingResponse(
        _event_stream(ctx.workspace_id, crawl_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _export_items(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    view: str,
) -> tuple[list[dict], bool]:
    """Collect projected rows for an export view (workspace-scoped).

    Bounded by ``max_export_items`` (config-owned): once the cap is reached
    the loop stops paging and reports truncation, so a very large inventory
    can never be materialized entirely into memory for one export request.
    """
    items: list[dict] = []
    cursor: str | None = None
    limit = site_health_settings.max_export_items
    truncated = False
    while True:
        if view == "inventory":
            page = await service.get_inventory(
                session,
                workspace_id=workspace_id,
                crawl_id=crawl_id,
                limit=200,
                cursor=cursor,
            )
        elif view == "pages":
            page = await service.get_pages(
                session,
                workspace_id=workspace_id,
                crawl_id=crawl_id,
                limit=200,
                cursor=cursor,
            )
        else:  # issues
            page = await service.get_issues(
                session,
                workspace_id=workspace_id,
                crawl_id=crawl_id,
                limit=200,
                cursor=cursor,
            )
        items.extend(page["items"])
        if len(items) >= limit:
            items = items[:limit]
            truncated = bool(page.get("next_cursor"))
            break
        cursor = page.get("next_cursor")
        if not cursor:
            break
    if view == "issues" and items:
        # v2 P1: the issues export carries a page_kind column listing the
        # distinct classified types of each group's affected analyses (a
        # group can span types, so the JSON issue DTO has no single badge).
        # Pages/inventory rows already carry their scalar page_kind.
        page_kinds_by_rule = await service.issue_group_page_kinds(
            session, workspace_id=workspace_id, crawl_id=crawl_id
        )
        for item in items:
            item["page_kind"] = ", ".join(
                page_kinds_by_rule.get(str(item.get("rule_id") or ""), [])
            )
    return items, truncated


def _validate_view(view: str) -> str:
    if view not in EXPORT_VIEWS:
        raise ApiException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION_ERROR,
            f"unknown export view: {view}",
        )
    return view


@router.get("/site-crawls/{crawl_id}/export.csv")
async def export_csv_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    view: Annotated[str, Query()] = "inventory",
) -> Response:
    view = _validate_view(view)
    try:
        items, truncated = await _export_items(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id, view=view
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    body = rows_to_csv(view, items)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="site-health-{crawl_id}-{view}.csv"'
        )
    }
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return Response(
        content=body,
        media_type="text/csv",
        headers=headers,
    )


@router.get("/site-crawls/{crawl_id}/export.md")
async def export_markdown_endpoint(
    crawl_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    view: Annotated[str, Query()] = "inventory",
) -> PlainTextResponse:
    view = _validate_view(view)
    try:
        items, truncated = await _export_items(
            session, workspace_id=ctx.workspace_id, crawl_id=crawl_id, view=view
        )
    except SiteHealthNotFoundError as exc:
        raise _not_found(str(exc)) from exc
    body = rows_to_markdown(view, items)
    headers = {
        "Content-Disposition": (
            f'attachment; filename="site-health-{crawl_id}-{view}.md"'
        )
    }
    if truncated:
        headers["X-Export-Truncated"] = "true"
    return PlainTextResponse(
        content=body,
        media_type="text/markdown",
        headers=headers,
    )
