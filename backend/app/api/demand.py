"""Workspace-safe Demand Intelligence API over persisted projections."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.http_errors import raise_not_found
from app.domain.analytics.enqueue import enqueue_demand_snapshot_refresh
from app.domain.demand.query_classification import append_override
from app.domain.demand.schemas import (
    BrandedQueryClassificationView,
    BrandedQueryOverrideRequest,
    DemandRecomputeRequest,
    DemandRecomputeResponse,
    DemandSignalView,
    DemandSnapshotView,
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
