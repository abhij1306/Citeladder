from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_change_intel import CHANGE_ANALYZER_VERSION
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.site_health.change_intel import (
    build_change_snapshot,
    select_previous_comparable_crawl,
)
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SitePageAnalysis,
    SiteUrlObservation,
)
from tests.component.test_site_health_api import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


async def _seed_changes(session: AsyncSession, *, email: str):
    scenario = await _seed_scenario(session, email=email)
    crawl_b = await session.get(SiteCrawl, scenario.crawl_id)
    assert crawl_b is not None
    crawl_b.analyzer_version = "v1"
    crawl_b.inventory_complete = False
    crawl_b.completed_at = datetime.now(UTC)
    crawl_a = SiteCrawl(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        profile_id=crawl_b.profile_id,
        status="completed",
        root_url=crawl_b.root_url,
        random_seed="0",
        inventory_complete=True,
        analyzed_url_count=1,
        analyzer_version="v1",
        extractor_version="",
        created_at=crawl_b.created_at - timedelta(days=1),
        completed_at=crawl_b.created_at - timedelta(hours=23),
    )
    session.add(crawl_a)
    await session.flush()
    analysis = await session.scalar(
        select(SitePageAnalysis)
        .where(SitePageAnalysis.crawl_id == crawl_b.id)
        .order_by(SitePageAnalysis.id)
        .limit(1)
    )
    assert analysis is not None
    snapshot = SiteChangeSnapshot(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        crawl_a_id=crawl_a.id,
        crawl_b_id=crawl_b.id,
        state="available",
        root_origin="https://acme.test",
        crawl_scope_hash="a" * 64,
        source_hash="b" * 64,
        source_analysis_ids=[analysis.id],
        source_artifact_ids=[analysis.artifact_id],
        analyzer_version=CHANGE_ANALYZER_VERSION,
        page_analyzer_version="v1",
        extractor_version="",
        complete_pair=False,
        coverage={"shared_pages": 1},
        summary={"total": 2, "counts_by_class": {"critical-regression": 2}},
        limitations=["partial_crawl_shared_urls_only"],
    )
    session.add(snapshot)
    await session.flush()
    for field in ("http_status", "title"):
        session.add(
            SiteChangeObservation(
                snapshot_id=snapshot.id,
                workspace_id=scenario.workspace_id,
                site_url_id=analysis.site_url_id,
                normalized_url="https://acme.test/a",
                field=field,
                change_class="critical-regression",
                before_value=200 if field == "http_status" else "Before",
                after_value=503 if field == "http_status" else "After",
                source_analysis_b_id=analysis.id,
                source_artifact_b_id=analysis.artifact_id,
                expected=False,
            )
        )
    await session.commit()
    return scenario, crawl_a.id, snapshot.id


async def test_changes_summary_cursor_detail_and_exact_pair(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "changes-api@example.com")
    async with session_factory() as session:
        scenario, crawl_a_id, snapshot_id = await _seed_changes(
            session, email="changes-api@example.com"
        )
    headers = {"X-Workspace-Id": str(scenario.workspace_id)}
    base = f"/api/v1/projects/{scenario.project_id}/site-health/changes"
    summary = await client.get(f"{base}/summary", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["snapshot_id"] == str(snapshot_id)
    assert summary.json()["complete_pair"] is False

    first = await client.get(base, headers=headers, params={"limit": 1})
    assert first.status_code == 200
    assert first.json()["next_cursor"]
    second = await client.get(
        base,
        headers=headers,
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert len(second.json()["items"]) == 1
    observation_id = first.json()["items"][0]["id"]
    detail = await client.get(f"{base}/{observation_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["source_analysis_b_id"]

    exact = await client.get(
        f"{base}/summary",
        headers=headers,
        params={"crawl_a_id": crawl_a_id, "crawl_b_id": scenario.crawl_id},
    )
    assert exact.status_code == 200
    one_sided = await client.get(
        f"{base}/summary", headers=headers, params={"crawl_a_id": crawl_a_id}
    )
    assert one_sided.status_code == 422


async def test_changes_are_workspace_authorized(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "changes-owner@example.com")
    await _register(client, "changes-foreign@example.com")
    async with session_factory() as session:
        owner, _crawl_a, _snapshot = await _seed_changes(
            session, email="changes-owner@example.com"
        )
        foreign = await _seed_scenario(session, email="changes-foreign@example.com")
    response = await client.get(
        f"/api/v1/projects/{owner.project_id}/site-health/changes/summary",
        headers={"X-Workspace-Id": str(foreign.workspace_id)},
    )
    assert response.status_code == 404


async def test_build_noop_pair_is_idempotent_with_exact_provenance(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "changes-build@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="changes-build@example.com")
        crawl_a = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl_a is not None
        crawl_a.analyzer_version = "v1"
        crawl_a.inventory_complete = True
        crawl_a.created_at = datetime.now(UTC) - timedelta(hours=3)
        crawl_a.completed_at = datetime.now(UTC) - timedelta(hours=2)
        crawl_b = SiteCrawl(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            profile_id=crawl_a.profile_id,
            status="completed",
            root_url=crawl_a.root_url,
            random_seed="2",
            configuration=dict(crawl_a.configuration or {}),
            inventory_complete=True,
            analyzed_url_count=2,
            analyzer_version="v1",
            extractor_version="",
            created_at=datetime.now(UTC) - timedelta(hours=1),
            completed_at=datetime.now(UTC),
        )
        session.add(crawl_b)
        await session.flush()
        source_analyses = list(
            (
                await session.scalars(
                    select(SitePageAnalysis).where(
                        SitePageAnalysis.crawl_id == crawl_a.id
                    )
                )
            ).all()
        )
        for source in source_analyses:
            source_artifact = await session.get(SiteFetchArtifact, source.artifact_id)
            assert source_artifact is not None
            task = SiteCrawlTask(
                crawl_id=crawl_b.id,
                workspace_id=scenario.workspace_id,
                task_kind="analyze",
                requested_url=source_artifact.requested_url,
                url_hash=source.site_url_id.hex * 2,
                site_url_id=source.site_url_id,
                idempotency_key=f"{crawl_b.id}:analyze:{source.site_url_id}:0",
                status=TASK_STATUS_SUCCEEDED,
            )
            session.add(task)
            await session.flush()
            artifact = SiteFetchArtifact(
                task_id=task.id,
                crawl_id=crawl_b.id,
                workspace_id=scenario.workspace_id,
                fetch_purpose="analyze",
                requested_url=source_artifact.requested_url,
                final_url=source_artifact.final_url,
                status_code=source_artifact.status_code,
                content_type=source_artifact.content_type,
                extractor_version="",
                normalized_facts=dict(source_artifact.normalized_facts or {}),
            )
            session.add(artifact)
            await session.flush()
            analysis = SitePageAnalysis(
                workspace_id=scenario.workspace_id,
                project_id=scenario.project_id,
                crawl_id=crawl_b.id,
                site_url_id=source.site_url_id,
                artifact_id=artifact.id,
                status="completed",
                analyzer_version="v1",
                scoring_version="v1",
                page_kind=source.page_kind,
                classifier_version=source.classifier_version,
            )
            session.add(analysis)
            session.add(
                SiteUrlObservation(
                    workspace_id=scenario.workspace_id,
                    project_id=scenario.project_id,
                    crawl_id=crawl_b.id,
                    site_url_id=source.site_url_id,
                    source_kind="link",
                    observed_url=source_artifact.requested_url,
                    final_url=source_artifact.final_url,
                    status_code=source_artifact.status_code,
                    content_type=source_artifact.content_type,
                )
            )
        await session.flush()

        first = await build_change_snapshot(session, crawl_b=crawl_b)
        second = await build_change_snapshot(session, crawl_b=crawl_b)

        assert first.id == second.id
        assert first.state == "available"
        assert first.summary["total"] == 0
        assert len(first.source_analysis_ids) == 4
        assert len(first.source_artifact_ids) == 4

        current = await session.scalar(
            select(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == crawl_b.id)
            .order_by(SitePageAnalysis.id)
            .limit(1)
        )
        assert current is not None
        current_artifact = await session.get(SiteFetchArtifact, current.artifact_id)
        assert current_artifact is not None
        current.is_current = False
        revision_task = SiteCrawlTask(
            crawl_id=crawl_b.id,
            workspace_id=scenario.workspace_id,
            task_kind="analyze",
            requested_url=current_artifact.requested_url,
            url_hash="f" * 64,
            site_url_id=current.site_url_id,
            idempotency_key=f"{crawl_b.id}:analyze:{current.site_url_id}:revision",
            status=TASK_STATUS_SUCCEEDED,
        )
        session.add(revision_task)
        await session.flush()
        revision_artifact = SiteFetchArtifact(
            task_id=revision_task.id,
            crawl_id=crawl_b.id,
            workspace_id=scenario.workspace_id,
            fetch_purpose="analyze",
            requested_url=current_artifact.requested_url,
            final_url=current_artifact.final_url,
            status_code=current_artifact.status_code,
            content_type=current_artifact.content_type,
            extractor_version="",
            normalized_facts=dict(current_artifact.normalized_facts or {}),
        )
        session.add(revision_artifact)
        await session.flush()
        session.add(
            SitePageAnalysis(
                workspace_id=scenario.workspace_id,
                project_id=scenario.project_id,
                crawl_id=crawl_b.id,
                site_url_id=current.site_url_id,
                artifact_id=revision_artifact.id,
                status="completed",
                analyzer_version="v1",
                scoring_version="v1",
                page_kind=current.page_kind,
                classifier_version=current.classifier_version,
            )
        )
        await session.flush()

        revised = await build_change_snapshot(session, crawl_b=crawl_b)

        assert revised.id != first.id
        assert revised.supersedes_id == first.id
        assert revised.summary["total"] == 0


async def test_selection_skips_newer_incompatible_crawl_and_codes_no_match(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "changes-selection@example.com")
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email="changes-selection@example.com")
        crawl_b = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl_b is not None
        crawl_b.analyzer_version = "v1"
        crawl_b.extractor_version = "e1"
        crawl_b.configuration = {"discovery_mode": "automatic"}
        crawl_b.created_at = datetime.now(UTC)
        compatible = SiteCrawl(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            profile_id=crawl_b.profile_id,
            status="completed",
            root_url=crawl_b.root_url,
            random_seed="1",
            configuration=dict(crawl_b.configuration),
            inventory_complete=True,
            analyzed_url_count=1,
            analyzer_version="v1",
            extractor_version="e1",
            created_at=crawl_b.created_at - timedelta(days=2),
        )
        incompatible = SiteCrawl(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            profile_id=crawl_b.profile_id,
            status="completed",
            root_url=crawl_b.root_url,
            random_seed="2",
            configuration={"discovery_mode": "manual"},
            inventory_complete=True,
            analyzed_url_count=1,
            analyzer_version="v2",
            extractor_version="e1",
            created_at=crawl_b.created_at - timedelta(days=1),
        )
        session.add_all([compatible, incompatible])
        await session.flush()

        selected = await select_previous_comparable_crawl(session, crawl_b=crawl_b)
        assert selected is not None and selected.id == compatible.id

        compatible.analyzer_version = "v2"
        await session.flush()
        selected = await select_previous_comparable_crawl(session, crawl_b=crawl_b)
        assert selected is not None and selected.id == incompatible.id
        snapshot = await build_change_snapshot(session, crawl_b=crawl_b)
        assert snapshot.state == "non_comparable"
        assert snapshot.reason_code == "crawl_scope_mismatch"
