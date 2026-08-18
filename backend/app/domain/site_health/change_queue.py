"""Exactly-once queue admission for post-graph change analysis."""

import hashlib

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_change_intel import CHANGE_ANALYZER_VERSION
from app.core.config.site_health_contracts import (
    TASK_KIND_CHANGE_INTEL,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.models.site_health import SiteCrawl, SiteCrawlTask


async def enqueue_change_refresh(session: AsyncSession, *, crawl: SiteCrawl) -> None:
    token = hashlib.sha256(
        f"change-intel:{crawl.id}:{CHANGE_ANALYZER_VERSION}".encode()
    ).hexdigest()
    await session.execute(
        pg_insert(SiteCrawlTask)
        .values(
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            task_kind=TASK_KIND_CHANGE_INTEL,
            requested_url=crawl.root_url,
            url_hash=token,
            idempotency_key=(
                f"{crawl.id}:{TASK_KIND_CHANGE_INTEL}:{CHANGE_ANALYZER_VERSION}"
            ),
            status=TASK_STATUS_QUEUED,
            max_attempts=site_health_settings.max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


__all__ = ["enqueue_change_refresh"]
