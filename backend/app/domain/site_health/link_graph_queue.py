"""Exactly-once Site Health queue admission for post-crawl graph work."""

from __future__ import annotations

import hashlib

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health import (
    LINK_GRAPH_ANALYZER_VERSION,
    TASK_KIND_LINK_GRAPH,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.models.site_health import SiteCrawl, SiteCrawlTask


async def enqueue_link_graph_refresh(
    session: AsyncSession, *, crawl: SiteCrawl, usable_evidence: bool
) -> None:
    """Queue one graph task after terminal crawl evidence becomes usable."""
    if not usable_evidence:
        return
    token = hashlib.sha256(f"link-graph:{crawl.id}".encode()).hexdigest()
    await session.execute(
        pg_insert(SiteCrawlTask)
        .values(
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            task_kind=TASK_KIND_LINK_GRAPH,
            requested_url=crawl.root_url,
            url_hash=token,
            idempotency_key=(
                f"{crawl.id}:{TASK_KIND_LINK_GRAPH}:{LINK_GRAPH_ANALYZER_VERSION}"
            ),
            status=TASK_STATUS_QUEUED,
            max_attempts=site_health_settings.max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


__all__ = ["enqueue_link_graph_refresh"]
