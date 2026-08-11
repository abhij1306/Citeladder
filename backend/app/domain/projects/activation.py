"""Project activation owns the automatic first Site Health crawl."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.site_health.planner import create_crawl
from app.models.site_health import SiteCrawl


async def start_initial_site_review(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    commit: bool = True,
) -> SiteCrawl:
    """Queue the config-owned automatic page sample for a new project.

    The caller chooses the transaction boundary. Onboarding passes
    ``commit=False`` so project identity, prompts, and the first crawl are one
    atomic write; ordinary project creation uses the committing wrapper.
    """
    return await create_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        commit=commit,
    )
