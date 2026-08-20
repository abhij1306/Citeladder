from __future__ import annotations

from collections import Counter, defaultdict

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    AEO_READINESS_RULE_DIMENSIONS,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from tests.component.site_health_api_helpers import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


async def _seed_readiness(session: AsyncSession, *, email: str):
    scenario = await _seed_scenario(session, email=email)
    crawl = await session.get(SiteCrawl, scenario.crawl_id)
    assert crawl is not None
    crawl.analyzer_version = "v1"
    crawl.extractor_version = "extract-v1"
    analyses = list(
        (
            await session.scalars(
                select(SitePageAnalysis)
                .where(SitePageAnalysis.crawl_id == crawl.id)
                .order_by(SitePageAnalysis.id)
            )
        ).all()
    )
    expected: dict[str, Counter[str]] = defaultdict(Counter)
    for analysis_index, analysis in enumerate(analyses):
        artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
        assert artifact is not None
        artifact.extractor_version = "extract-v1"
        if analysis_index == 1:
            analysis.page_kind = "case_study_review"
        for rule_index, (rule_id, dimension) in enumerate(
            AEO_READINESS_RULE_DIMENSIONS.items()
        ):
            outcome = ("pass", "fail", "not_applicable")[
                (analysis_index + rule_index) % 3
            ]
            if analysis_index == 1 and rule_id in {
                "aeo.answer_first",
                "aeo.outbound_citations",
            }:
                outcome = "fail"
            session.add(
                SiteRuleEvaluation(
                    workspace_id=scenario.workspace_id,
                    analysis_id=analysis.id,
                    source_artifact_id=analysis.artifact_id,
                    rule_id=rule_id,
                    dimension="aeo",
                    category="content",
                    severity="medium",
                    weight=1.0,
                    outcome=outcome,
                    evidence={"fixture": True},
                    extractor_version="extract-v1",
                    analyzer_version="v1",
                    rule_version="rules-v1",
                )
            )
            expected[dimension][outcome] += 1
    await session.commit()
    return scenario, analyses, expected


async def test_seven_dimensions_exactly_reconcile_and_trace_failing_page(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "readiness@example.com")
    async with session_factory() as session:
        scenario, analyses, expected = await _seed_readiness(
            session, email="readiness@example.com"
        )

    response = await client.get(
        f"/api/v1/projects/{scenario.project_id}/site-health/aeo-readiness",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        params={"crawl_id": scenario.crawl_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "available"
    assert body["taxonomy_version"] == "aeo-readiness-v1"
    assert body["analysis_count"] == 2
    assert body["source_analysis_ids"] == sorted(str(row.id) for row in analyses)
    assert len(body["dimensions"]) == 7
    for dimension in body["dimensions"]:
        counts = expected[dimension["key"]]
        assert dimension["pass_count"] == counts["pass"]
        assert dimension["fail_count"] == counts["fail"]
        assert dimension["not_applicable_count"] == counts["not_applicable"]
        assert dimension["error_count"] == counts["error"]
        assert dimension["observed_evaluation_count"] == sum(counts.values())
        assert dimension["expected_evaluation_count"] == sum(counts.values())
        assert dimension["coverage"] == 1.0
    failing_links = [
        link
        for dimension in body["dimensions"]
        for link in dimension["evidence_links"]
        if link["outcome"] == "fail"
    ]
    assert any(link["rule_id"] == "aeo.answer_first" for link in failing_links)
    assert any(link["rule_id"] == "aeo.outbound_citations" for link in failing_links)


async def test_readiness_read_is_workspace_isolated(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "readiness-owner@example.com")
    await _register(client, "readiness-foreign@example.com")
    async with session_factory() as session:
        owner, _analyses, _expected = await _seed_readiness(
            session, email="readiness-owner@example.com"
        )
        foreign = await _seed_scenario(session, email="readiness-foreign@example.com")

    response = await client.get(
        f"/api/v1/projects/{owner.project_id}/site-health/aeo-readiness",
        headers={"X-Workspace-Id": str(foreign.workspace_id)},
    )
    assert response.status_code == 404
