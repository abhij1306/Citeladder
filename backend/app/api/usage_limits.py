"""FastAPI boundary helpers for uniform durable 429 responses."""

from __future__ import annotations

import uuid

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.http_errors import raise_api_error
from app.domain.abuse.service import UsageLimitExceededError, enforce_and_commit


async def enforce_workspace_request(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    operation: str,
    limit: int,
    window_seconds: int,
) -> None:
    try:
        await enforce_and_commit(
            session,
            subject_kind="workspace",
            subject=workspace_id,
            operation=operation,
            limit=limit,
            window_seconds=window_seconds,
        )
    except UsageLimitExceededError as exc:
        raise_api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Workspace usage limit exceeded",
            headers={"Retry-After": str(exc.retry_after_seconds)},
            cause=exc,
        )
