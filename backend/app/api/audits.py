# Audits router: workspace-scoped audit lifecycle + executions + SSE (invariant 5).
#
# Flat API surface (no workspace_id in the path); the active workspace is
# resolved by ``require_active_workspace`` from the ``X-Workspace-Id`` header
# (or the caller's default workspace). Every query filters by that workspace.
#
#   POST /audits                -> create + enqueue an audit (deterministic)
#   GET  /audits                -> list the workspace's audits
#   GET  /audits/{id}           -> one audit (with engine provenance)
#   POST /audits/{id}/cancel    -> cooperative cancel
#   GET  /audits/{id}/executions-> the audit's execution/queue rows
#   GET  /audits/{id}/events    -> lifecycle events (SSE stream)
#
# Provider keys are NEVER carried here — the worker resolves the decrypted key
# from the workspace's ``ProviderConnection`` at execution time (invariant 6).
from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.exports import audit_to_csv, audit_to_markdown
from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.audits import (
    AUDIT_TERMINAL_STATUSES,
    AUDIT_TRIGGER_MANUAL,
    CODE_PROMPT_COUNT_EXCEEDED,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
    audit_settings,
)
from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.core.config.entitlements import (
    CODE_FUNDED_BUDGET_EXHAUSTED,
    CODE_FUNDED_COST_UNRESOLVED,
    CODE_FUNDED_CREDITS_EXHAUSTED,
    CODE_MANUAL_RUN_RATE_EXCEEDED,
)
from app.core.config.prompts import (
    CODE_BINDING_VOCABULARY_EMPTY,
    CODE_PROMPT_OFF_TOPIC,
)
from app.core.database import SessionLocal
from app.core.errors import ApiException
from app.core.http_errors import raise_not_found
from app.domain.abuse.service import UsageLimitExceededError
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.analysis.evidence import load_export_bundle
from app.domain.analysis.metrics import get_metrics
from app.domain.analysis.schemas import MetricsResponse
from app.domain.analysis.trends import validate_shopping_surface
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.cost_estimate import estimate_audit
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import (
    AuditNotFoundError,
    AuditValidationError,
    FundedAdmissionError,
    PromptCountPolicyError,
)
from app.domain.audits.estimate_errors import AuditEstimateError
from app.domain.audits.performance import audit_performance
from app.domain.audits.reads import (
    get_audit,
    list_audits,
    list_tasks,
)
from app.domain.audits.repair import AuditRepairError, create_repair_audit
from app.domain.audits.schemas import (
    AuditCreate,
    AuditEstimateRequest,
    AuditEstimateResponse,
    AuditEventResponse,
    AuditPerformanceResponse,
    AuditRepairRequest,
    AuditResponse,
    AuditTaskResponse,
    audit_event_response,
)
from app.domain.entitlements.enforcement import RateAdmissionDeniedError
from app.domain.entitlements.types import STATUS_ENTITLEMENT_UNRESOLVED
from app.domain.prompts.topical_binding import TopicalBindingError
from app.models.audit import Audit, AuditEvent

router = APIRouter(prefix="/audits", tags=["audits"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]

# Admission denial code -> HTTP status. Codes are config-owned; only the
# status mapping lives here. Rate denials are 429; an unresolvable
# entitlement is 403 (never data); commercial budget/credit exhaustion is a
# graceful 403; an unresolvable funded cost estimate is a 422 fail-closed.
# Topical-binding rejections are 422 (request-content validation); an unset
# prompt-count policy is a 422 fail-closed (like an unresolved cost), while
# breaching a configured count is a graceful 403 (like budget exhaustion).
_ADMISSION_STATUS: dict[str, int] = {
    CODE_MANUAL_RUN_RATE_EXCEEDED: status.HTTP_429_TOO_MANY_REQUESTS,
    STATUS_ENTITLEMENT_UNRESOLVED: status.HTTP_403_FORBIDDEN,
    CODE_FUNDED_COST_UNRESOLVED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    CODE_FUNDED_BUDGET_EXHAUSTED: status.HTTP_403_FORBIDDEN,
    CODE_FUNDED_CREDITS_EXHAUSTED: status.HTTP_403_FORBIDDEN,
    CODE_PROMPT_OFF_TOPIC: status.HTTP_422_UNPROCESSABLE_ENTITY,
    CODE_BINDING_VOCABULARY_EMPTY: status.HTTP_422_UNPROCESSABLE_ENTITY,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED: status.HTTP_422_UNPROCESSABLE_ENTITY,
    CODE_PROMPT_COUNT_EXCEEDED: status.HTTP_403_FORBIDDEN,
}


@contextmanager
def _translate_create_audit_errors() -> Iterator[None]:
    """Map ``create_audit`` domain errors to HTTP responses.

    One collaborator keeps the endpoint on its complexity budget while
    admission denials (rate + funded) render through the unified
    ``ApiException`` envelope.
    """
    try:
        yield
    except AuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except UsageLimitExceededError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Workspace usage limit exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    except (
        RateAdmissionDeniedError,
        FundedAdmissionError,
        PromptCountPolicyError,
        TopicalBindingError,
    ) as exc:
        raise ApiException.coded(
            _ADMISSION_STATUS.get(exc.code, status.HTTP_403_FORBIDDEN),
            exc.code,
            str(exc),
            details=exc.details,
        ) from exc


@router.post("", response_model=AuditResponse, status_code=status.HTTP_201_CREATED)
async def create_audit_endpoint(
    payload: AuditCreate, ctx: _WorkspaceDep, session: _SessionDep
) -> AuditResponse:
    with _translate_create_audit_errors():
        audit = await create_audit(
            session,
            workspace_id=ctx.workspace_id,
            project_id=payload.project_id,
            engines=payload.engines,
            # API-created runs are user-initiated: the manual trigger.
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=payload.prompt_set_id,
            prompt_ids=payload.prompt_ids,
            repetitions=payload.repetitions,
            benchmark_mode=payload.benchmark_mode,
            measurement_mode=payload.measurement_mode,
            random_seed=payload.random_seed,
        )
    return AuditResponse.model_validate(audit)


@router.post("/estimate")
async def estimate_audit_endpoint(
    payload: AuditEstimateRequest, ctx: _WorkspaceDep, session: _SessionDep
) -> AuditEstimateResponse:
    """Return a deterministic preview without calling any provider."""
    try:
        return await estimate_audit(
            session, workspace_id=ctx.workspace_id, payload=payload
        )
    except AuditEstimateError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("", response_model=list[AuditResponse])
async def list_audits_endpoint(
    ctx: _WorkspaceDep,
    session: _SessionDep,
    project_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[AuditResponse]:
    audits = await list_audits(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        limit=limit,
    )
    return [AuditResponse.model_validate(a) for a in audits]


@router.get("/{audit_id}", response_model=AuditResponse)
async def get_audit_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> AuditResponse:
    audit = await _get_or_404(session, ctx.workspace_id, audit_id)
    return AuditResponse.model_validate(audit)


@router.get("/{audit_id}/performance")
async def audit_performance_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> AuditPerformanceResponse:
    try:
        return await audit_performance(
            session, workspace_id=ctx.workspace_id, audit_id=audit_id
        )
    except LookupError as exc:
        raise_not_found("Audit", cause=exc)


@router.post("/{audit_id}/cancel", response_model=AuditResponse)
async def cancel_audit_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> AuditResponse:
    try:
        audit = await cancel_audit(
            session, workspace_id=ctx.workspace_id, audit_id=audit_id
        )
    except AuditNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    except AuditValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return AuditResponse.model_validate(audit)


@router.post(
    "/{audit_id}/rerun-failures",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    responses={status.HTTP_200_OK: {"model": AuditResponse}},
)
async def rerun_failures_endpoint(
    audit_id: uuid.UUID,
    payload: AuditRepairRequest,
    response: Response,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> AuditResponse:
    """Create an immutable child audit for selected failed execution slots."""
    try:
        child, created = await create_repair_audit(
            session,
            workspace_id=ctx.workspace_id,
            audit_id=audit_id,
            provider=payload.provider,
            engine=payload.engine,
            prompt_id=payload.prompt_id,
            task_ids=payload.task_ids,
        )
        child = await get_audit(
            session, workspace_id=ctx.workspace_id, audit_id=child.id
        )
        if not created:
            response.status_code = status.HTTP_200_OK
    except LookupError as exc:
        raise_not_found("Audit", cause=exc)
    except AuditRepairError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    return AuditResponse.model_validate(child)


@router.get("/{audit_id}/executions", response_model=list[AuditTaskResponse])
async def list_executions_endpoint(
    audit_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    surface: Annotated[str, Query()] = SHOPPING_SURFACE_MEASUREMENT,
) -> list[AuditTaskResponse]:
    try:
        tasks = await list_tasks(
            session,
            workspace_id=ctx.workspace_id,
            audit_id=audit_id,
            surface=validate_shopping_surface(surface),
        )
    except AuditNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    except TrendQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return [AuditTaskResponse.model_validate(t) for t in tasks]


@router.get("/{audit_id}/metrics", response_model=MetricsResponse)
async def get_metrics_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> MetricsResponse:
    """Single-run ``MetricSnapshot`` projection (invariant 7 — no provider).

    Reads only the persisted aggregate; 404 until the audit has been analyzed
    or for a cross-workspace/missing audit (invariant 5).
    """
    # Authorize the audit first so a cross-workspace id is a 404, not a leak.
    await _get_or_404(session, ctx.workspace_id, audit_id)
    try:
        return await get_metrics(
            session, workspace_id=ctx.workspace_id, audit_id=audit_id
        )
    except AnalysisNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Metrics not available for audit",
        ) from exc


@router.get("/{audit_id}/export.csv")
async def export_csv_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> Response:
    """Download the per-execution evidence as CSV (renders persisted rows)."""
    try:
        audit, tasks = await load_export_bundle(
            session, workspace_id=ctx.workspace_id, audit_id=audit_id
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    body = audit_to_csv(audit, tasks)
    return Response(
        content=body,
        media_type="text/csv",
        headers={
            "Content-Disposition": (f'attachment; filename="audit-{audit_id}.csv"')
        },
    )


@router.get("/{audit_id}/export.md")
async def export_markdown_endpoint(
    audit_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> PlainTextResponse:
    """Download the benchmark report as Markdown (renders persisted summary)."""
    try:
        audit, tasks = await load_export_bundle(
            session, workspace_id=ctx.workspace_id, audit_id=audit_id
        )
    except AnalysisNotFoundError as exc:
        raise_not_found("Audit", cause=exc)
    body = audit_to_markdown(audit, tasks)
    return PlainTextResponse(
        content=body,
        media_type="text/markdown",
        headers={
            "Content-Disposition": (f'attachment; filename="audit-{audit_id}.md"')
        },
    )


@router.get("/{audit_id}/events", response_model=list[AuditEventResponse])
async def list_events_endpoint(
    audit_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    stream: Annotated[bool, Query()] = False,
    last_event_id: Annotated[uuid.UUID | None, Header()] = None,
) -> list[AuditEventResponse] | StreamingResponse:
    """Return the audit's lifecycle events (strict discriminated DTOs).

    With ``?stream=true`` returns a ``text/event-stream`` (SSE) that replays
    the existing events and then tails new ones until the audit reaches a
    terminal status. Otherwise returns the event list as JSON. Both surfaces
    serialize through the same discriminated schema (invariant 2): SSE
    ``event:`` is the JSON ``event_type`` and SSE ``id:`` is the event UUID.

    ``Last-Event-ID`` (the SSE resume cursor) restarts strictly AFTER the
    referenced event in both modes. A malformed value is a 422; an event
    unknown to THIS audit gets the same safe 404 as a foreign audit — never
    a silent replay from the beginning (invariant 5).
    """
    # Authorize first (404 for a cross-workspace / missing audit — invariant 5).
    await _get_or_404(session, ctx.workspace_id, audit_id)
    if last_event_id is not None:
        await _authorize_resume_cursor(session, audit_id, last_event_id)
    if not stream:
        return await _list_event_responses(session, audit_id, after=last_event_id)
    return StreamingResponse(
        _event_stream(audit_id, last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _list_event_responses(
    session: AsyncSession, audit_id: uuid.UUID, *, after: uuid.UUID | None
) -> list[AuditEventResponse]:
    """The JSON event list (optionally after the resume cursor)."""
    events = await _load_events(session, audit_id, after=after)
    return [audit_event_response(e) for e in events]


async def _get_or_404(
    session: AsyncSession, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> Audit:
    try:
        return await get_audit(session, workspace_id=workspace_id, audit_id=audit_id)
    except AuditNotFoundError as exc:
        raise_not_found("Audit", cause=exc)


async def _authorize_resume_cursor(
    session: AsyncSession, audit_id: uuid.UUID, event_id: uuid.UUID
) -> None:
    """404 (audit-shaped) unless the cursor names an event of THIS audit.

    An unknown or cross-audit cursor must never degrade into a replay from
    the beginning (invariant 5): it fails with exactly the not-found a
    foreign audit gets, so the response shape leaks nothing about which
    side of the boundary the id fell on.
    """
    event = await session.get(AuditEvent, event_id)
    if event is None or event.audit_id != audit_id:
        raise_not_found("Audit")


async def _load_events(
    session: AsyncSession, audit_id: uuid.UUID, *, after: uuid.UUID | None
) -> list[AuditEvent]:
    stmt = (
        select(AuditEvent)
        .where(AuditEvent.audit_id == audit_id)
        .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
    )
    events = list((await session.scalars(stmt)).all())
    if after is None:
        return events
    seen = False
    tail: list[AuditEvent] = []
    for event in events:
        if seen:
            tail.append(event)
        elif event.id == after:
            seen = True
    return tail if seen else events


def _sse_payload(event: AuditEvent) -> str:
    """One SSE frame from the SAME discriminated DTO the JSON list emits.

    ``event:`` / ``id:`` are read off the serialized body, so the frame
    metadata can never drift from the JSON ``event_type`` / ``id`` (the
    resume cursor) it wraps.
    """
    body = audit_event_response(event).model_dump(mode="json")
    return (
        f"event: {body['event_type']}\nid: {body['id']}\ndata: {json.dumps(body)}\n\n"
    )


async def _event_stream(
    audit_id: uuid.UUID,
    *,
    last_event_id: uuid.UUID | None = None,
):
    """Tail an audit's events until it terminalizes.

    Opens its own short-lived sessions (the request session is closed once the
    handler returns the ``StreamingResponse``). Resumes strictly AFTER
    ``last_event_id`` when given — the endpoint has already authorized the
    cursor against this audit. Stops shortly after the audit reaches a
    terminal status (config-owned grace, invariant 1) so the connection does
    not hang forever.
    """
    last_id = last_event_id
    terminal_polls = 0
    while True:
        async with SessionLocal() as session:
            new_events = await _load_events(session, audit_id, after=last_id)
            for event in new_events:
                last_id = event.id
                yield _sse_payload(event)
            audit = await session.get(Audit, audit_id)
        if audit is None:
            break
        if audit.status in AUDIT_TERMINAL_STATUSES:
            terminal_polls += 1
            if terminal_polls >= audit_settings.sse_terminal_grace_polls:
                break
        await asyncio.sleep(audit_settings.sse_poll_seconds)
