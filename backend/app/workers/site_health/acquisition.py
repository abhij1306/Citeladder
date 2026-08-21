"""Reusable discover artifacts for the Site Health crawler.

Every request uses the impersonating curl transport, so this owner only
resolves immutable discovery evidence that analysis can safely reuse.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_acquisition import (
    FETCH_PURPOSE_DISCOVER,
)
from app.core.config.site_health_contracts import (
    EXTRACTOR_VERSION,
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import TASK_ACTIVE_STATUSES
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask


async def reusable_discover_artifact(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
) -> tuple[tuple[uuid.UUID, dict] | None, bool]:
    """Resolve reusable discover facts or an in-flight prerequisite."""
    if task.site_url_id is None:
        return None, False
    row = (
        await session.execute(
            select(SiteFetchArtifact.id, SiteFetchArtifact.normalized_facts)
            .join(SiteCrawlTask, SiteCrawlTask.id == SiteFetchArtifact.task_id)
            .where(
                SiteFetchArtifact.crawl_id == crawl.id,
                SiteFetchArtifact.fetch_purpose == FETCH_PURPOSE_DISCOVER,
                SiteFetchArtifact.extractor_version
                == (crawl.extractor_version or EXTRACTOR_VERSION),
                SiteFetchArtifact.normalized_facts.is_not(None),
                SiteCrawlTask.url_hash == task.url_hash,
            )
            .order_by(SiteFetchArtifact.fetched_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is not None:
        return (row[0], dict(row[1])), False
    pending = await session.scalar(
        select(SiteCrawlTask.id)
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.url_hash == task.url_hash,
            SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            SiteCrawlTask.status.in_(sorted(TASK_ACTIVE_STATUSES)),
        )
        .limit(1)
    )
    return None, pending is not None
