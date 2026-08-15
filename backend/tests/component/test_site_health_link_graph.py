from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import LINK_GRAPH_ANALYZER_VERSION
from app.domain.site_health.link_graph import build_link_graph_snapshot
from app.models.site_health import (
    SiteCrawl,
    SiteLinkGraphEdge,
    SiteLinkGraphNode,
    SiteLinkGraphSnapshot,
    SiteLinkReference,
    SitePageAnalysis,
)
from tests.component.test_site_health_api import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


async def _seed_graph(
    session: AsyncSession, *, email: str
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    scenario = await _seed_scenario(session, email=email)
    analyses = list(
        (
            await session.scalars(
                select(SitePageAnalysis)
                .where(SitePageAnalysis.crawl_id == scenario.crawl_id)
                .order_by(SitePageAnalysis.site_url_id)
            )
        ).all()
    )
    snapshot = SiteLinkGraphSnapshot(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        crawl_id=scenario.crawl_id,
        state="available",
        root_site_url_id=analyses[0].site_url_id,
        source_analysis_hash="a" * 64,
        source_analysis_ids=[row.id for row in analyses],
        source_artifact_ids=[row.artifact_id for row in analyses],
        analyzer_version=LINK_GRAPH_ANALYZER_VERSION,
        page_analyzer_version="v1",
        extractor_version="v1",
        coverage={"complete": True, "analysis_ratio": 1.0},
        limitations=[],
        summary={"node_count": 2, "edge_count": 1},
    )
    session.add(snapshot)
    await session.flush()
    for index, analysis in enumerate(analyses):
        session.add(
            SiteLinkGraphNode(
                snapshot_id=snapshot.id,
                workspace_id=scenario.workspace_id,
                site_url_id=analysis.site_url_id,
                source_analysis_id=analysis.id,
                normalized_url=f"https://acme.test/{index}",
                title=f"Page {index}",
                indexable=True,
                pagerank=0.5,
                click_depth=index,
                followed_inbound_count=index,
                followed_outbound_count=1 - index,
                near_orphan=index == 1,
                weak_authority=False,
                over_linked=False,
                hub=False,
                suggested_source_ids=[analyses[0].site_url_id] if index else [],
            )
        )
    session.add(
        SiteLinkGraphEdge(
            snapshot_id=snapshot.id,
            workspace_id=scenario.workspace_id,
            source_site_url_id=analyses[0].site_url_id,
            target_site_url_id=analyses[1].site_url_id,
            target_key=str(analyses[1].site_url_id),
            target_url="https://acme.test/1",
            followed=True,
            occurrence_count=2,
            followed_occurrence_count=1,
            nofollow_occurrence_count=1,
            anchor_texts=["Page one"],
        )
    )
    await session.commit()
    return scenario.workspace_id, scenario.project_id, scenario.crawl_id


async def test_graph_summary_nodes_edges_and_cursor_are_snapshot_bound(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "graph-api@example.com")
    async with session_factory() as session:
        workspace_id, project_id, crawl_id = await _seed_graph(
            session, email="graph-api@example.com"
        )
    headers = {"X-Workspace-Id": str(workspace_id)}
    base = f"/api/v1/projects/{project_id}/site-health/link-graph"

    summary = await client.get(base, headers=headers, params={"crawl_id": crawl_id})
    assert summary.status_code == 200
    assert summary.json()["summary"] == {"node_count": 2, "edge_count": 1}
    first = await client.get(f"{base}/nodes", headers=headers, params={"limit": 1})
    assert first.status_code == 200
    assert len(first.json()["items"]) == 1
    cursor = first.json()["next_cursor"]
    second = await client.get(
        f"{base}/nodes", headers=headers, params={"limit": 1, "cursor": cursor}
    )
    assert len(second.json()["items"]) == 1
    edges = await client.get(f"{base}/edges", headers=headers)
    assert edges.json()["items"][0]["nofollow_occurrence_count"] == 1


async def test_graph_reads_do_not_cross_workspace(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "graph-owner@example.com")
    await _register(client, "graph-foreign@example.com")
    async with session_factory() as session:
        owner_workspace, project_id, _crawl_id = await _seed_graph(
            session, email="graph-owner@example.com"
        )
        foreign_workspace, _other_project, _other_crawl = await _seed_graph(
            session, email="graph-foreign@example.com"
        )
    assert owner_workspace != foreign_workspace
    response = await client.get(
        f"/api/v1/projects/{project_id}/site-health/link-graph",
        headers={"X-Workspace-Id": str(foreign_workspace)},
    )
    assert response.status_code == 404


async def test_graph_build_is_idempotent_and_freezes_exact_analysis_provenance(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "graph-build@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="graph-build@example.com")
        analyses = list(
            (
                await session.scalars(
                    select(SitePageAnalysis)
                    .where(SitePageAnalysis.crawl_id == scenario.crawl_id)
                    .order_by(SitePageAnalysis.site_url_id)
                )
            ).all()
        )
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl is not None
        crawl.analyzer_version = "v1"
        for index, _analysis in enumerate(analyses):
            session.add(
                SiteLinkReference(
                    workspace_id=scenario.workspace_id,
                    source_analysis_id=analyses[0].id,
                    source_artifact_id=analyses[0].artifact_id,
                    kind="anchor",
                    target_url=f"https://acme.test/{'b' if index else 'a'}",
                    target_hash=str(index).zfill(64),
                    is_internal=True,
                    rel="nofollow" if index == 0 else "",
                    anchor_text="Page link",
                    evidence_fingerprint=str(index + 10).zfill(64),
                    analyzer_version="v1",
                )
            )
        await session.flush()
        first = await build_link_graph_snapshot(session, crawl=crawl)
        second = await build_link_graph_snapshot(session, crawl=crawl)
        assert first is not None and second is not None
        assert first.id == second.id
        assert first.source_analysis_ids == [row.id for row in analyses]
        assert first.summary["node_count"] == 2
        assert first.summary["edge_count"] == 2
        await session.commit()
