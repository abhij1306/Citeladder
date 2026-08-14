# LLM Analytics router (A9): the three read endpoints behind /analytics.
#
# Projections only (invariant 7): every endpoint serves persisted evidence —
# the ``AnalyticsSnapshot`` rows built by the A8 refresh executor (headline +
# themes) and the persisted ``ReferralClassification`` + ``ReferralEvent``
# rows (referrals drill-down, keyset-paged per contract C4). No provider is
# ever called and nothing is recomputed at read time: an absent snapshot
# yields an empty payload (the trends empty-history precedent).
#
# The surface is flat like the other routers: the active workspace is
# resolved by ``require_active_workspace`` (``X-Workspace-Id`` header or the
# caller's default workspace) and the project is authorized through the
# workspace before any read (invariant 5).
from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.analytics import ANALYTICS_DEFAULT_GRANULARITY
from app.core.http_errors import raise_not_found
from app.domain.analytics.schemas import AiReferralsResponse
from app.domain.analytics.service import (
    AnalyticsQueryError,
    get_ai_referrals,
)
from app.domain.projects.service import ProjectNotFoundError, get_project

router = APIRouter(prefix="/projects", tags=["ai-referrals"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def _get_project_or_404(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
):
    """Authorize the project, translating a cross-workspace/missing project
    into the API's 404 (mirrors ``_get_project_or_404`` in projects.py)."""
    try:
        return await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )
    except ProjectNotFoundError as exc:
        raise_not_found("Project", cause=exc)


def _unprocessable(exc: AnalyticsQueryError) -> HTTPException:
    # Query-validation contract (the trends ``TrendQueryError`` precedent):
    # a bad granularity/window/source is a 422, never a 404 or a 500.
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
    )


@router.get("/{project_id}/ai-referrals", response_model=AiReferralsResponse)
async def get_ai_referrals_endpoint(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    granularity: Annotated[str, Query()] = ANALYTICS_DEFAULT_GRANULARITY,
) -> AiReferralsResponse:
    """Referral volume, share, and AI-source totals from a persisted snapshot."""
    # Authorize the project first (404 for a cross-workspace/missing project).
    await _get_project_or_404(session, ctx.workspace_id, project_id)
    try:
        return await get_ai_referrals(
            session,
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
            granularity=granularity,
        )
    except AnalyticsQueryError as exc:
        raise _unprocessable(exc) from exc
