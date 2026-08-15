"""Workspace-safe Demand Intelligence API over persisted projections."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.demand import (
    QUERY_EVIDENCE_DEFAULT_LIMIT,
    QUERY_EVIDENCE_MAX_LIMIT,
)
from app.core.http_errors import raise_not_found
from app.domain.analytics.enqueue import enqueue_demand_snapshot_refresh
from app.domain.demand.query_classification import append_override
from app.domain.demand.query_evidence_reads import (
    QueryEvidenceCursorError,
    latest_query_evidence_snapshot,
    list_query_evidence,
    query_evidence_resolution_counts,
)
from app.domain.demand.schemas import (
    BrandedQueryClassificationView,
    BrandedQueryOverrideRequest,
    DemandRecomputeRequest,
    DemandRecomputeResponse,
    DemandSignalView,
    DemandSnapshotView,
    QueryEvidencePageView,
    QueryEvidenceRowView,
    QueryEvidenceSnapshotView,
    QueryEvidenceSummaryView,
)
from app.domain.demand.service import (
    demand_source_revision,
    latest_snapshot,
    list_signals,
)
from app.domain.projects.service import ProjectNotFoundError, get_project

router = APIRouter(prefix="/projects", tags=["demand"])
_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _query_snapshot_view(row) -> QueryEvidenceSnapshotView:
    return QueryEvidenceSnapshotView.model_validate(row)


async def _authorize(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    try:
        await get_project(session, workspace_id=workspace_id, project_id=project_id)
    except ProjectNotFoundError as exc:
        raise_not_found("Project", cause=exc)


async def _snapshot_view(session: AsyncSession, row) -> DemandSnapshotView:
    signals = await list_signals(
        session,
        workspace_id=row.workspace_id,
        project_id=row.project_id,
        snapshot_id=row.id,
    )
    return DemandSnapshotView(
        id=row.id,
        project_id=row.project_id,
        window_start=row.window_start,
        window_end=row.window_end,
        source_hash=row.source_hash,
        prior_snapshot_id=row.prior_snapshot_id,
        source_artifact_ids=list(row.source_artifact_ids or []),
        source_metric_row_ids=list(row.source_metric_row_ids or []),
        coverage=dict(row.coverage or {}),
        summary=dict(row.summary or {}),
        comparison=row.comparison,
        formula_version=row.formula_version,
        analyzer_version=row.analyzer_version,
        created_at=row.created_at,
        signals=[DemandSignalView.model_validate(signal) for signal in signals],
    )


@router.get("/{project_id}/demand/latest")
async def latest(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> DemandSnapshotView:
    await _authorize(session, ctx.workspace_id, project_id)
    row = await latest_snapshot(
        session, workspace_id=ctx.workspace_id, project_id=project_id
    )
    if row is None:
        raise_not_found("Demand snapshot")
    return await _snapshot_view(session, row)


@router.post(
    "/{project_id}/demand/recompute",
    status_code=status.HTTP_202_ACCEPTED,
)
async def recompute(
    project_id: uuid.UUID,
    payload: DemandRecomputeRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> DemandRecomputeResponse:
    await _authorize(session, ctx.workspace_id, project_id)
    revision = await demand_source_revision(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
    )
    task_id = await enqueue_demand_snapshot_refresh(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
        source_revision=revision,
    )
    await session.commit()
    return DemandRecomputeResponse(
        task_id=task_id, status="queued" if task_id else "already_queued"
    )


async def _required_query_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start,
    window_end,
):
    row = await latest_query_evidence_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    if row is None:
        raise_not_found("Query evidence snapshot")
    return row


@router.get("/{project_id}/demand/query-evidence", response_model=QueryEvidencePageView)
async def query_evidence(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    window_start: Annotated[date, Query()],
    window_end: Annotated[date, Query()],
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=QUERY_EVIDENCE_MAX_LIMIT)] = (
        QUERY_EVIDENCE_DEFAULT_LIMIT
    ),
    query: Annotated[str | None, Query(max_length=512)] = None,
    site_url_id: Annotated[uuid.UUID | None, Query()] = None,
    resolution_outcome: Annotated[
        Literal["exact", "resolved", "ambiguous", "unresolved"] | None, Query()
    ] = None,
) -> QueryEvidencePageView:
    await _authorize(session, ctx.workspace_id, project_id)
    snapshot = await _required_query_snapshot(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    try:
        page = await list_query_evidence(
            session,
            snapshot=snapshot,
            limit=limit,
            cursor=cursor,
            query=query,
            site_url_id=site_url_id,
            resolution_outcome=resolution_outcome,
        )
    except QueryEvidenceCursorError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="query_evidence_cursor_invalid",
        ) from exc
    return QueryEvidencePageView(
        snapshot=_query_snapshot_view(snapshot),
        items=[QueryEvidenceRowView.model_validate(row) for row in page.rows],
        next_cursor=page.next_cursor,
    )


@router.get(
    "/{project_id}/demand/query-evidence/summary",
    response_model=QueryEvidenceSummaryView,
)
async def query_evidence_summary(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    window_start: Annotated[date, Query()],
    window_end: Annotated[date, Query()],
) -> QueryEvidenceSummaryView:
    await _authorize(session, ctx.workspace_id, project_id)
    snapshot = await _required_query_snapshot(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    return QueryEvidenceSummaryView(
        snapshot=_query_snapshot_view(snapshot),
        counts_by_resolution=await query_evidence_resolution_counts(
            session, snapshot=snapshot
        ),
    )


@router.post(
    "/{project_id}/demand/query-classification-overrides",
    response_model=BrandedQueryClassificationView,
    status_code=status.HTTP_201_CREATED,
)
async def create_query_classification_override(
    project_id: uuid.UUID,
    payload: BrandedQueryOverrideRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> BrandedQueryClassificationView:
    await _authorize(session, ctx.workspace_id, project_id)
    row = await append_override(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        actor_user_id=ctx.user.id,
        query=payload.query,
        classification=payload.classification,
    )
    await session.commit()
    return BrandedQueryClassificationView(
        normalized_query=row.normalized_query,
        classification=row.classification,
        matched_terms=[],
        classifier_version=row.classifier_version,
        override_id=row.id,
    )
