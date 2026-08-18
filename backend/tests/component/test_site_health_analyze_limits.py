"""Site Health membership and automatic-analysis limit contracts."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    SELECTION_SOURCE_BOOTSTRAP,
    SELECTION_SOURCE_FREE_SAMPLE,
)
from app.domain.site_health.discovery import add_automatic_root, admit_candidates
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import FrontierCandidate
from app.models.site_health import MonitoredSiteUrl, SiteCrawl, SiteCrawlTask
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import _configure_crawl, _seed_runtime


async def _sample_count(session, workspace_id) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.active.is_(True),
            MonitoredSiteUrl.selection_source == SELECTION_SOURCE_FREE_SAMPLE,
        )
    )


@pytest.mark.asyncio
async def test_sample_recrawl_allowance_only_decrements_on_new_activation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(
            session, task_count=0, root_url="https://example.com/"
        )
        await _seed_runtime(session, seed.workspace_id, monitored_urls=0)
        await session.commit()
        await _configure_crawl(
            session, crawl_id=seed.crawl_id, sample_mode=True, count_disclosure=False
        )

    url, url_hash = canonical_identity("https://example.com/page")
    candidate = FrontierCandidate(
        url=url,
        url_hash=url_hash,
        depth=1,
        source_kind="link",
        parent_position=0,
        link_ordinal=0,
    )
    for expected in (1, 1):
        async with session_factory() as session:
            crawl = await session.get(SiteCrawl, seed.crawl_id)
            assert crawl is not None
            await admit_candidates(session, crawl=crawl, candidates=[candidate])
            await session.commit()
            assert await _sample_count(session, seed.workspace_id) == expected

    async with session_factory() as session:
        await session.execute(
            update(MonitoredSiteUrl)
            .where(MonitoredSiteUrl.workspace_id == seed.workspace_id)
            .values(active=False, deselected_at=datetime.now(UTC))
        )
        await session.commit()
        assert await _sample_count(session, seed.workspace_id) == 0

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        await admit_candidates(session, crawl=crawl, candidates=[candidate])
        await session.commit()
        membership = await session.scalar(
            select(MonitoredSiteUrl).where(
                MonitoredSiteUrl.workspace_id == seed.workspace_id
            )
        )
        assert membership is not None
        assert await _sample_count(session, seed.workspace_id) == 1
        assert (
            membership.active,
            membership.deselected_at,
            membership.selection_source,
        ) == (
            True,
            None,
            SELECTION_SOURCE_FREE_SAMPLE,
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MonitoredSiteUrl)
                .where(MonitoredSiteUrl.workspace_id == seed.workspace_id)
            )
            == 1
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("sample_mode", [False, True])
async def test_automatic_analysis_stops_at_frozen_limit_across_batches(
    session_factory: async_sessionmaker[AsyncSession], sample_mode: bool
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(
            session, task_count=1, root_url="https://example.com/"
        )
        await _seed_runtime(
            session, seed.workspace_id, monitored_urls=0 if sample_mode else 50
        )
        await session.commit()
        await _configure_crawl(
            session,
            crawl_id=seed.crawl_id,
            sample_mode=sample_mode,
            count_disclosure=True,
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.configuration = {
            **crawl.configuration,
            AUTOMATIC_MONITOR_LIMIT_KEY: 10,
            "requested_page_limit": 10,
        }
        await add_automatic_root(session, crawl)
        await session.commit()

    for batch_start in (0, 12):
        candidates = [
            FrontierCandidate(
                url=canonical_identity(f"https://example.com/page-{index}")[0],
                url_hash=canonical_identity(f"https://example.com/page-{index}")[1],
                depth=1,
                source_kind="link",
                parent_position=0,
                link_ordinal=index,
            )
            for index in range(batch_start, batch_start + 12)
        ]
        async with session_factory() as session:
            crawl = await session.get(SiteCrawl, seed.crawl_id)
            assert crawl is not None
            await admit_candidates(session, crawl=crawl, candidates=candidates)
            await session.commit()

    async with session_factory() as session:
        analyze_tasks = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            )
        )
        memberships = await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.project_id == seed.project_id,
                MonitoredSiteUrl.active.is_(True),
                MonitoredSiteUrl.selection_source == SELECTION_SOURCE_BOOTSTRAP,
            )
        )
    assert analyze_tasks == memberships == 10
