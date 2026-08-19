# Site Health router: workspace-scoped crawl/discovery/selection/analysis API.
#
# Flat API surface under ``/api/v1`` (no workspace_id in the path); the active
# workspace is resolved by ``require_active_workspace`` from the
# ``X-Workspace-Id`` header (or the caller's default workspace) and EVERY lookup
# is filtered by it, so a foreign/missing id is always a 404 (invariant 5). The
# router only projects persisted rows through the service layer — it never
# fetches, re-scores, or fabricates a metric. Coded selection/crawl failures are
# mapped to their stable HTTP statuses + bodies.
#
# This module owns ONLY what more than one route module needs: the shared
# router, the two request-scoped dependency aliases, and the two error helpers
# used across route modules. Everything else lives with its single caller, and
# route modules import stdlib/framework/schema/service names directly from
# their real owners rather than through here.
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.errors import CODE_INVALID_CURSOR, CODE_NOT_FOUND
from app.core.errors import ApiException
from app.domain.site_health.service import InvalidCursorError

router = APIRouter(prefix="", tags=["site-health"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


def _not_found(detail: str = "Not found") -> ApiException:
    return ApiException(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, detail)


def _bad_cursor(exc: InvalidCursorError) -> ApiException:
    return ApiException(status.HTTP_400_BAD_REQUEST, CODE_INVALID_CURSOR, str(exc))
