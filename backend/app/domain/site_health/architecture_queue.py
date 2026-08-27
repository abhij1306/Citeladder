"""Exactly-once admission for post-link-metric architecture derivation."""

from __future__ import annotations

import hashlib

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_archetypes import (
    ARCHETYPE_POLICY_VERSION,
    ARCHITECTURE_FORMULA_VERSION,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    EXTRACTOR_VERSION,
    RULE_CATALOG_VERSION,
    TASK_KIND_ARCHITECTURE,
)
from app.core.config.site_health_runtime import site_health_settings
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask


async def enqueue_architecture_refresh(
    session: AsyncSession, *, crawl: SiteCrawl
) -> None:
    extractor_version = crawl.extractor_version or EXTRACTOR_VERSION
    analyzer_version = crawl.analyzer_version or ANALYZER_VERSION
    rule_version = crawl.rule_catalog_version or RULE_CATALOG_VERSION
    version = (
        f"{extractor_version}:{analyzer_version}:"
        f"{rule_version}:{ARCHITECTURE_FORMULA_VERSION}:"
        f"{ARCHETYPE_POLICY_VERSION}"
    )
    token = hashlib.sha256(f"architecture:{crawl.id}:{version}".encode()).hexdigest()
    await session.execute(
        pg_insert(SiteCrawlTask)
        .values(
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            task_kind=TASK_KIND_ARCHITECTURE,
            requested_url=crawl.root_url,
            url_hash=token,
            idempotency_key=f"{crawl.id}:{TASK_KIND_ARCHITECTURE}:{version}",
            status=TASK_STATUS_QUEUED,
            max_attempts=site_health_settings.max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


__all__ = ["enqueue_architecture_refresh"]
