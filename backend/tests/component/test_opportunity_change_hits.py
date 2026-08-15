from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_change_intel import CHANGE_ANALYZER_VERSION
from app.domain.opportunities.change_hits import load_change_hits
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health import SiteCrawl, SiteUrl
from tests.component.site_health_helpers import seed_site_crawl

pytestmark = pytest.mark.asyncio


async def test_only_unexpected_persisted_regressions_become_hits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        crawl_b = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl_b is not None
        crawl_b.analyzer_version = "page-v1"
        crawl_b.extractor_version = "extract-v1"
        crawl_a = SiteCrawl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            profile_id=seed.profile_id,
            status="completed",
            root_url=crawl_b.root_url,
            random_seed="0",
            analyzed_url_count=1,
            analyzer_version="page-v1",
            extractor_version="extract-v1",
        )
        session.add(crawl_a)
        await session.flush()
        site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url="https://example.com/page",
            url_hash="a" * 64,
            display_url="https://example.com/page",
            host="example.com",
        )
        session.add(site_url)
        await session.flush()
        snapshot = SiteChangeSnapshot(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_a_id=crawl_a.id,
            crawl_b_id=crawl_b.id,
            state="available",
            root_origin="https://example.com",
            crawl_scope_hash="b" * 64,
            source_hash="c" * 64,
            source_analysis_ids=[],
            source_artifact_ids=[],
            analyzer_version=CHANGE_ANALYZER_VERSION,
            page_analyzer_version="page-v1",
            extractor_version="extract-v1",
            complete_pair=True,
            coverage={"shared_pages": 1},
            summary={},
            limitations=[],
        )
        session.add(snapshot)
        await session.flush()
        for change_class, expected, field in (
            ("critical-regression", False, "http_status"),
            ("potential-regression", False, "canonical"),
            ("potential-regression", True, "title"),
            ("neutral-change", False, "h1"),
        ):
            session.add(
                SiteChangeObservation(
                    snapshot_id=snapshot.id,
                    workspace_id=seed.workspace_id,
                    site_url_id=site_url.id,
                    normalized_url=site_url.normalized_url,
                    field=field,
                    change_class=change_class,
                    before_value="before",
                    after_value="after",
                    expected=expected,
                )
            )
        await session.flush()

        hits = await load_change_hits(
            session, workspace_id=seed.workspace_id, crawl=crawl_b
        )
        foreign_hits = await load_change_hits(
            session, workspace_id=uuid.uuid4(), crawl=crawl_b
        )

    assert foreign_hits == []
    assert [hit.rule_id for hit in hits] == [
        "site_change_potential_regression",
        "site_change_critical_regression",
    ]
    assert all(hit.source_metric_ids[0] == str(snapshot.id) for hit in hits)
