# Executions router: single-execution evidence (B6, invariants 5/7).
#
# ``GET /executions/{execution_id}`` serves one execution's persisted
# ``ResponseAnalysis`` + its classified citation evidence. ``execution_id`` is
# the *execution* (``AuditTask``) id — the id clients receive from
# ``GET /audits/{id}/executions`` — so the two endpoints share one id space.
# Workspace-scoped and projection-only — reads persisted rows, never a provider.
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.http_errors import raise_api_error
from app.domain.analysis.errors import AnalysisNotFoundError
from app.domain.analysis.evidence import get_execution_evidence
from app.domain.analysis.schemas import ExecutionEvidenceResponse

router = APIRouter(prefix="/executions", tags=["executions"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


@router.get("/{execution_id}", response_model=ExecutionEvidenceResponse)
async def get_execution_endpoint(
    execution_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> ExecutionEvidenceResponse:
    """Serve one execution's persisted analysis + citation evidence.

    ``execution_id`` is the ``AuditTask`` id from the executions list.
    """
    try:
        return await get_execution_evidence(
            session, workspace_id=ctx.workspace_id, task_id=execution_id
        )
    except AnalysisNotFoundError as exc:
        raise_api_error(status.HTTP_404_NOT_FOUND, "Execution not found", cause=exc)
