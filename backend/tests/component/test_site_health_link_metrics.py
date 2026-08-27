"""Persistence, tenancy, and retry behavior for post-terminal link metrics."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import TASK_KIND_LINK_METRICS
from app.core.config.site_health_link_metrics import (
    COVERAGE_FORMULA_VERSION,
    COVERAGE_STATE_PARTIAL,
    LINK_METRIC_FORMULA_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED, TASK_STATUS_SUCCEEDED
from app.domain.site_health.link_metrics import persist_link_metrics
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from tests.component.site_health_worker_helpers import (
    _seed_analyze_phase_crawl,
    _worker,
)


@pytest.mark.asyncio
async def test_pipelined_worker_claims_queued_link_metrics_task(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(session, root=root, urls=(root,))

    worker = _worker(
        session_factory,
        {"/": b'<html><body><main><a href="/">Home</a></main></body></html>'},
        owner="pipelined-link-metrics",
    )
    assert await worker.run_once() == 1

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_METRICS,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert task is not None

    assert await worker.run_pipelined(drain=True) >= 1

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_METRICS,
            )
        )
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SitePageLinkMetric)
                .where(SitePageLinkMetric.crawl_id == seed.crawl_id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_post_terminal_metrics_are_scoped_versioned_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    product = "https://example.com/products/widget"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, product)
        )

    pages = {
        "/": (
            b"<html><head><title>Home</title></head><body><main>"
            b'<a href="/products/widget">Widget</a>'
            b'<a href="/products/widget" rel="nofollow">Widget duplicate</a>'
            b'<a href="/not-crawled">More</a>'
            b"</main></body></html>"
        ),
        "/products/widget": (
            b"<html><head><title>Widget</title></head><body><main>"
            b'<a href="/">Home</a>'
            b"</main></body></html>"
        ),
    }
    await _worker(session_factory, pages, owner="link-metrics").run_until_idle()

    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(SitePageLinkMetric)
                    .where(
                        SitePageLinkMetric.workspace_id == seed.workspace_id,
                        SitePageLinkMetric.project_id == seed.project_id,
                        SitePageLinkMetric.crawl_id == seed.crawl_id,
                    )
                    .order_by(SitePageLinkMetric.depth_from_home)
                )
            ).all()
        )
        assert len(rows) == 2
        home, product_row = rows
        assert home.depth_from_home == 0
        assert home.outbound_count == 2
        assert product_row.depth_from_home == 1
        assert product_row.inbound_count == 1
        assert product_row.main_content_inbound_count == 1
        assert product_row.nofollow_inbound_count == 1
        assert all(row.formula_version == LINK_METRIC_FORMULA_VERSION for row in rows)
        assert all(row.extractor_version for row in rows)
        assert all(len(row.source_artifact_ids or []) == 2 for row in rows)

        task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_METRICS,
            )
        )
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED

        snapshot = await session.scalar(
            select(SiteHealthSnapshot).where(
                SiteHealthSnapshot.crawl_id == seed.crawl_id
            )
        )
        assert snapshot is not None
        # This fixture starts at analysis with no discovery task, so it is a
        # bounded rerun rather than proof of complete site coverage.
        assert snapshot.coverage_state == COVERAGE_STATE_PARTIAL
        assert snapshot.coverage_formula_version == COVERAGE_FORMULA_VERSION

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert await persist_link_metrics(session, crawl=crawl) == 0
        await session.commit()

        count = await session.scalar(
            select(func.count())
            .select_from(SitePageLinkMetric)
            .where(SitePageLinkMetric.crawl_id == seed.crawl_id)
        )
        assert count == 2


@pytest.mark.asyncio
async def test_metric_composite_foreign_keys_reject_cross_workspace_urls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first, ((first_url_id, _),) = await _seed_analyze_phase_crawl(
            session,
            root="https://example.com/one",
            urls=("https://example.com/one",),
        )
        second, ((second_url_id, _),) = await _seed_analyze_phase_crawl(
            session,
            root="https://other.example/two",
            urls=("https://other.example/two",),
        )
        assert first_url_id != second_url_id
        session.add(
            SitePageLinkMetric(
                workspace_id=first.workspace_id,
                project_id=first.project_id,
                crawl_id=first.crawl_id,
                site_url_id=second_url_id,
                source_page_count=1,
                extractor_version="test",
                formula_version=LINK_METRIC_FORMULA_VERSION,
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
