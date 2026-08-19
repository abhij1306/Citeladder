# Recrawl seeding of the persistent monitored set.
#
# Every manual recrawl re-analyzes the project's persistent monitored selection
# so last-audited facts and scores refresh. The seeding also re-admits each
# monitored URL into the NEW crawl's observed set, because the pages/inventory
# read paths scope strictly through observations.
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health_contracts import (
    INITIAL_TASK_GENERATION,
    OBSERVATION_SOURCE_LINK,
    TASK_KIND_ANALYZE,
)
from app.domain.site_health.selection import enqueue_analyze_task
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation


async def seed_monitored_targets(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
) -> list[uuid.UUID]:
    """Seed ``analyze`` tasks for every active monitored URL of a new crawl.

    Called on every manual recrawl (plan §4): the persistent monitored set is
    re-analyzed so last-audited facts/scores refresh. Newly discovered URLs are
    left unselected (they get no analyze task here). Missing/redirected
    monitored records are preserved — they remain monitored until the user
    removes them, so they are seeded like any other active row.

    Seeds at ``INITIAL_TASK_GENERATION`` because a fresh crawl owns a fresh
    slot namespace. Idempotent: an already-seeded slot is skipped so a retry
    never violates the unique ``(crawl_id, task_kind, url_hash, generation)``.

    Every seeded URL is also admitted into the NEW crawl's observed set
    (``SiteUrlObservation``, conflict-safe): the pages/inventory read paths
    scope strictly through observations, so without this row the monitored
    pages are INVISIBLE on the new crawl until re-discovery happens to
    re-observe them — the dashboard's page table starts (nearly) empty while
    the analysis counters already move. Same pattern as the system sample
    admission and the single-page rerun crawl.
    """
    rows = await _monitored_seed_rows(session, crawl.project_id)
    if not rows:
        return []
    already_seeded = await _already_seeded_hashes(session, crawl_id=crawl.id, rows=rows)
    remaining_budget = await _remaining_seed_budget(session, crawl)
    seeded: list[uuid.UUID] = []
    position = 0
    for _monitored, site_url in rows:
        if not _seed_url_is_admissible(crawl, site_url):
            continue
        await _write_seed_observation(session, crawl=crawl, site_url=site_url)
        if site_url.url_hash in already_seeded:
            continue
        if remaining_budget is not None and len(seeded) >= remaining_budget:
            break
        task = enqueue_analyze_task(
            session,
            crawl=crawl,
            site_url=site_url,
            generation=INITIAL_TASK_GENERATION,
            position=position,
        )
        position += 1
        already_seeded.add(site_url.url_hash)
        await session.flush()
        seeded.append(task.id)
    return seeded


async def _monitored_seed_rows(
    session: AsyncSession, project_id: uuid.UUID
) -> list[tuple[MonitoredSiteUrl, SiteUrl]]:
    result = await session.execute(
        select(MonitoredSiteUrl, SiteUrl)
        .join(SiteUrl, SiteUrl.id == MonitoredSiteUrl.site_url_id)
        .where(
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.active.is_(True),
        )
        .order_by(SiteUrl.normalized_url.asc())
    )
    return list(result.tuples().all())


async def _already_seeded_hashes(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    rows: list[tuple[MonitoredSiteUrl, SiteUrl]],
) -> set[str]:
    url_hashes = [site_url.url_hash for _monitored, site_url in rows]
    existing = await session.execute(
        select(SiteCrawlTask.url_hash).where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            SiteCrawlTask.generation == INITIAL_TASK_GENERATION,
            SiteCrawlTask.url_hash.in_(url_hashes),
        )
    )
    return {row[0] for row in existing.all()}


async def _remaining_seed_budget(session: AsyncSession, crawl: SiteCrawl) -> int | None:
    requested_limit = (crawl.configuration or {}).get("requested_page_limit")
    existing_task_count = await session.scalar(
        select(func.count())
        .select_from(SiteCrawlTask)
        .where(SiteCrawlTask.crawl_id == crawl.id)
    )
    return (
        max(int(requested_limit) - int(existing_task_count or 0), 0)
        if requested_limit is not None
        else None
    )


def _seed_url_is_admissible(crawl: SiteCrawl, site_url: SiteUrl) -> bool:
    configuration = dict(crawl.configuration or {})
    decision = classify_url_admission(
        site_url.normalized_url,
        root_registrable_domain=configuration.get("root_registrable_domain") or None,
        include_globs=configuration.get("include_globs"),
        exclude_globs=configuration.get("exclude_globs"),
    )
    return decision.accepted


async def _write_seed_observation(
    session: AsyncSession, *, crawl: SiteCrawl, site_url: SiteUrl
) -> None:
    await session.execute(
        pg_insert(SiteUrlObservation)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            site_url_id=site_url.id,
            source_kind=site_url.latest_source_kind or OBSERVATION_SOURCE_LINK,
            depth=site_url.depth,
            observed_url=site_url.normalized_url,
            final_url=site_url.normalized_url,
            content_type=site_url.latest_content_type or "",
            title=site_url.latest_title or "",
        )
        .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
    )
