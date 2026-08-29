"""Architecture tab read/correction surface, page sorts, and link projections."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_archetypes import (
    ARCHETYPE_POLICY_VERSION,
    ARCHITECTURE_FORMULA_VERSION,
)
from app.core.config.site_health_contracts import EXTRACTOR_VERSION
from app.core.config.site_health_link_metrics import (
    COVERAGE_STATE_COMPLETE,
    COVERAGE_STATE_PARTIAL,
    LINK_METRIC_FORMULA_VERSION,
)
from app.models.site_health.architecture import SiteObservedArchitecture
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import SiteUrl
from tests.component.site_health_api_helpers import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


async def _site_url_ids(
    session: AsyncSession, *, project_id: uuid.UUID
) -> list[SiteUrl]:
    return list(
        (
            await session.scalars(
                select(SiteUrl)
                .where(SiteUrl.project_id == project_id)
                .order_by(SiteUrl.normalized_url.asc())
            )
        ).all()
    )


async def _seed_architecture(
    session: AsyncSession,
    *,
    scn,
    coverage_state: str,
    archetype: dict,
) -> list[SiteUrl]:
    """Persist link metrics + one observed-architecture row for the crawl.

    The crawl's extractor version drives the metric join, so the seed reads it
    from the crawl rather than assuming the current constant.
    """
    crawl = await session.get(SiteCrawl, scn.crawl_id)
    assert crawl is not None
    crawl.extractor_version = crawl.extractor_version or EXTRACTOR_VERSION
    urls = await _site_url_ids(session, project_id=scn.project_id)
    metrics = [(9, 4, 0), (2, 1, 2), (0, 0, None)]
    for site_url, (inbound, main_inbound, depth) in zip(urls, metrics, strict=True):
        session.add(
            SitePageLinkMetric(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                crawl_id=scn.crawl_id,
                site_url_id=site_url.id,
                inbound_count=inbound,
                outbound_count=3,
                main_content_inbound_count=main_inbound,
                main_content_outbound_count=1,
                nofollow_inbound_count=0,
                depth_from_home=depth,
                source_page_count=2,
                top_inbound=[
                    {
                        "site_url_id": str(urls[0].id),
                        "url": urls[0].normalized_url,
                        "anchor_count": 2,
                        "main_content": True,
                        "nofollow": False,
                        "rel": [],
                    }
                ],
                top_outbound=[],
                extractor_version=crawl.extractor_version,
                formula_version=LINK_METRIC_FORMULA_VERSION,
            )
        )
    snapshot = SiteHealthSnapshot(
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        crawl_id=scn.crawl_id,
        coverage_state=coverage_state,
    )
    session.add(snapshot)
    await session.flush()
    session.add(
        SiteObservedArchitecture(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            crawl_id=scn.crawl_id,
            source_snapshot_id=snapshot.id,
            coverage_state=coverage_state,
            page_count=len(urls),
            page_kinds=[
                {
                    "page_kind": "product",
                    "page_count": 2,
                    "median_depth": 1.0,
                    "indexable_count": 2,
                    "duplicate_metadata_count": 0,
                    "orphan_count": 0
                    if coverage_state == COVERAGE_STATE_COMPLETE
                    else None,
                    "site_url_ids": [str(row.id) for row in urls[1:]],
                }
            ],
            internal_linking={
                "internal_link_count": 2,
                "pages_with_incoming_count": 2,
                "pages_with_incoming_percentage": 0.6667,
                "orphan_page_count": (
                    0 if coverage_state == COVERAGE_STATE_COMPLETE else None
                ),
            },
            structure_depth={
                "measured_page_count": 3,
                "unmeasured_page_count": 0,
                "buckets": [
                    {"key": "depth_0", "page_count": 1, "percentage": 0.3333},
                    {"key": "depth_1", "page_count": 2, "percentage": 0.6667},
                    {"key": "depth_2", "page_count": 0, "percentage": 0.0},
                    {"key": "depth_3_plus", "page_count": 0, "percentage": 0.0},
                ],
            },
            hierarchy=[
                {
                    "site_url_id": str(urls[0].id),
                    "url": urls[0].normalized_url,
                    "title": "Home",
                    "page_kind": "homepage",
                    "parent_site_url_id": None,
                    "parent_source": "unknown",
                    "depth_from_home": 0,
                },
                *(
                    {
                        "site_url_id": str(row.id),
                        "url": row.normalized_url,
                        "title": "Product",
                        "page_kind": "product",
                        "parent_site_url_id": str(urls[0].id),
                        "parent_source": "breadcrumb",
                        "depth_from_home": 1,
                    }
                    for row in urls[1:]
                ),
            ],
            archetype=archetype,
            architecture_formula_version=ARCHITECTURE_FORMULA_VERSION,
            archetype_policy_version=ARCHETYPE_POLICY_VERSION,
        )
    )
    await session.commit()
    return urls


_COMMERCE_ARCHETYPE = {
    "archetype": "commerce",
    "source": "onboarding_profile",
    "reason": "profile_supported",
    "business_model": "retail",
    "profile_evidence": {
        "knowledge_strength": "strong",
        "business_model_confidence": 0.9,
        "market_scope": "national",
    },
    "observed": [{"key": "products", "label": "Product pages"}],
    "not_observed": [{"key": "help_hub", "label": "Help / FAQ hub"}],
}


async def test_architecture_projects_persisted_model_and_coverage(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-read@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-read@example.com")
        urls = await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_COMPLETE,
            archetype=_COMMERCE_ARCHETYPE,
        )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health/architecture", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "available"
    assert body["crawl_id"] == str(scn.crawl_id)
    assert body["coverage_state"] == COVERAGE_STATE_COMPLETE
    assert body["page_count"] == 3
    assert "archetype" not in body
    assert body["page_kinds"][0]["orphan_count"] == 0
    assert body["internal_linking"]["internal_link_count"] == 2
    assert body["structure_depth"]["buckets"][1]["page_count"] == 2
    assert {node["site_url_id"] for node in body["nodes"]} == {
        str(row.id) for row in urls
    }
    assert body["architecture_formula_version"] == ARCHITECTURE_FORMULA_VERSION
    # Complete coverage states no limitation.
    assert body["limitations"] == []


async def test_partial_coverage_states_the_limit_and_withholds_absence(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A partial crawl cannot prove absence, so it must say so and stay quiet."""
    await _register(client, "arch-partial@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-partial@example.com")
        await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_PARTIAL,
            archetype={**_COMMERCE_ARCHETYPE, "not_observed": []},
        )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    body = (
        await client.get(
            f"/api/v1/projects/{scn.project_id}/site-health/architecture",
            headers=headers,
        )
    ).json()
    assert body["coverage_state"] == COVERAGE_STATE_PARTIAL
    assert body["page_kinds"][0]["orphan_count"] is None
    assert body["internal_linking"]["orphan_page_count"] is None
    assert body["limitations"] and "page budget" in body["limitations"][0]


async def test_architecture_is_unavailable_without_a_persisted_model(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-empty@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-empty@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    body = (
        await client.get(
            f"/api/v1/projects/{scn.project_id}/site-health/architecture",
            headers=headers,
        )
    ).json()
    assert body["state"] == "unavailable"
    assert body["nodes"] == []
    assert body["limitations"]


async def test_pages_expose_link_metrics_and_sort_over_them(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-sort@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-sort@example.com")
        urls = await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_COMPLETE,
            archetype=_COMMERCE_ARCHETYPE,
        )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    base = f"/api/v1/site-crawls/{scn.crawl_id}/pages"

    default_order = (await client.get(base, headers=headers)).json()["items"]
    assert [row["site_url_id"] for row in default_order] == [
        str(row.id) for row in urls
    ]
    assert default_order[0]["inbound_count"] == 9
    assert default_order[0]["main_content_inbound_count"] == 4
    assert default_order[0]["depth_from_home"] == 0
    # A page with a metric row but no computed depth reports None, not 0.
    assert default_order[2]["depth_from_home"] is None

    by_inbound = (await client.get(f"{base}?sort=inbound", headers=headers)).json()
    assert [row["inbound_count"] for row in by_inbound["items"]] == [9, 2, 0]

    by_main = (
        await client.get(f"{base}?sort=main_content_inbound", headers=headers)
    ).json()
    assert [row["main_content_inbound_count"] for row in by_main["items"]] == [4, 1, 0]

    # Depth ascends and an unmeasured depth sorts last rather than first.
    by_depth = (await client.get(f"{base}?sort=depth", headers=headers)).json()
    assert [row["depth_from_home"] for row in by_depth["items"]] == [0, 2, None]

    # Sorted pages still paginate by keyset, and the cursor is sort-bound.
    first = (await client.get(f"{base}?sort=inbound&limit=2", headers=headers)).json()
    assert [row["inbound_count"] for row in first["items"]] == [9, 2]
    assert first["next_cursor"]
    second = (
        await client.get(
            f"{base}?sort=inbound&limit=2&cursor={first['next_cursor']}",
            headers=headers,
        )
    ).json()
    assert [row["inbound_count"] for row in second["items"]] == [0]
    # Replaying that cursor under a different sort is rejected, not silently
    # reinterpreted against a different ordering.
    replayed = await client.get(
        f"{base}?sort=depth&limit=2&cursor={first['next_cursor']}", headers=headers
    )
    assert replayed.status_code == 400


async def test_page_detail_projects_internal_links(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-links@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-links@example.com")
        urls = await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_COMPLETE,
            archetype=_COMMERCE_ARCHETYPE,
        )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages/{urls[0].id}", headers=headers
    )
    assert detail.status_code == 200
    links = detail.json()["internal_links"]
    assert links["inbound_count"] == 9
    assert links["main_content_inbound_count"] == 4
    assert links["depth_from_home"] == 0
    assert links["formula_version"] == LINK_METRIC_FORMULA_VERSION
    assert links["top_inbound"][0]["url"] == urls[0].normalized_url


async def test_architecture_markdown_export_renders_the_tree(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-export@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-export@example.com")
        urls = await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_PARTIAL,
            archetype={**_COMMERCE_ARCHETYPE, "not_observed": []},
        )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.md?view=architecture",
        headers=headers,
    )
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    body = resp.text
    assert "# Site Health — Observed architecture" in body
    assert "Coverage: partial" in body
    assert urls[1].normalized_url in body
    # An absence advisory a partial crawl cannot prove is never exported.
    assert "Common structures not observed" not in body

    # A tree is not a table: CSV rejects the view rather than emitting one.
    csv_resp = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/export.csv?view=architecture",
        headers=headers,
    )
    assert csv_resp.status_code == 422


async def test_architecture_is_workspace_isolated(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "arch-tenant@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="arch-tenant@example.com")
        await _seed_architecture(
            session,
            scn=scn,
            coverage_state=COVERAGE_STATE_COMPLETE,
            archetype=_COMMERCE_ARCHETYPE,
        )
    foreign = {"X-Workspace-Id": str(uuid.uuid4())}
    assert (
        await client.get(
            f"/api/v1/projects/{scn.project_id}/site-health/architecture",
            headers=foreign,
        )
    ).status_code in {403, 404}
