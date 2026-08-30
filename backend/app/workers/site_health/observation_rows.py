"""Immutable URL observation persistence for Site Health acquisition."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    classify_url_admission,
    split_host_port,
)
from app.core.config.site_health_contracts import (
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import DiscoveryOutput
from app.models.site_health.crawl import SiteCrawl, SiteDiscoveryFrontier
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl, SiteUrlObservation
from app.workers.site_health.helpers import _utcnow


async def resolve_site_url_id(
    session: AsyncSession, *, crawl: SiteCrawl, url: str, depth: int
) -> uuid.UUID | None:
    try:
        canonical, url_hash_value = canonical_identity(url)
    except (TypeError, ValueError):
        return None
    try:
        host, _port = split_host_port(canonical)
    except ValueError:
        host = ""
    now = _utcnow()
    inserted_id = await session.scalar(
        pg_insert(SiteUrl)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            normalized_url=canonical,
            url_hash=url_hash_value,
            display_url=canonical,
            host=host[:255],
            depth=depth,
            discovery_status=DISCOVERY_STATUS_RUNNING,
            latest_source_kind=(
                OBSERVATION_SOURCE_ROOT if depth == 0 else OBSERVATION_SOURCE_LINK
            ),
            first_seen_crawl_id=crawl.id,
            last_seen_crawl_id=crawl.id,
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "url_hash"])
        .returning(SiteUrl.id)
    )
    if inserted_id is not None:
        return inserted_id
    return await session.scalar(
        select(SiteUrl.id).where(
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.url_hash == url_hash_value,
        )
    )


async def write_observation(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    output: DiscoveryOutput,
    depth: int,
    artifact_id: uuid.UUID | None,
) -> None:
    site_url_id = await resolve_site_url_id(
        session, crawl=crawl, url=output.requested_url, depth=depth
    )
    if site_url_id is None:
        return
    site_url = await session.get(SiteUrl, site_url_id)
    if site_url is not None:
        site_url.latest_title = (output.title or "")[:1024]
        site_url.latest_content_type = (output.content_type or "")[:128]
        site_url.last_seen_crawl_id = crawl.id
        site_url.discovery_status = DISCOVERY_STATUS_COMPLETED
    value = classify_url_admission(task.requested_url)
    rewrite = (
        await session.execute(
            select(
                SiteDiscoveryFrontier.rewrite_reason,
                SiteDiscoveryFrontier.rewrite_version,
            ).where(
                SiteDiscoveryFrontier.crawl_id == crawl.id,
                SiteDiscoveryFrontier.url_hash == task.url_hash,
            )
        )
    ).one_or_none()
    await session.execute(
        pg_insert(SiteUrlObservation)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            site_url_id=site_url_id,
            source_kind=(
                OBSERVATION_SOURCE_ROOT if depth == 0 else OBSERVATION_SOURCE_LINK
            ),
            parent_site_url_id=task.parent_site_url_id,
            source_artifact_id=artifact_id,
            value_kind=value.value_kind,
            value_priority=value.priority,
            rewrite_reason=rewrite[0] if rewrite else "",
            rewrite_version=rewrite[1] if rewrite else "",
            depth=depth,
            observed_url=output.requested_url,
            final_url=output.final_url,
            status_code=output.status_code,
            content_type=(output.content_type or "")[:128],
            title=(output.title or "")[:1024],
        )
        .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
    )
