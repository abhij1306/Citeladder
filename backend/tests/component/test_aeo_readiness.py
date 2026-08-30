from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSIONS,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    READINESS_CHECKPOINTS,
    SCHEMA_CONTRACT_VERSION,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.snapshot import SiteHealthSnapshot
from tests.component.site_health_api_helpers import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


def _dimension(key: str) -> dict:
    unresolved = key in {"evidence", "freshness", "authority"}
    return {
        "key": key,
        "dimension_applicability": "unresolved" if unresolved else "applicable",
        "dimension_measurement_state": (
            "not_measured" if unresolved else "limited_evidence"
        ),
        "score": None if unresolved else (0.0 if key == "answerability" else 100.0),
        "coverage": 0.0 if unresolved else 1.0,
        "earned_points": (
            0.0 if key == "answerability" else (0.0 if unresolved else 1.0)
        ),
        "determinate_points": 0.0 if unresolved else 1.0,
        "expected_points": 0.0 if unresolved else 1.0,
        "determinate_checkpoint_ids": [],
        "checkpoint_families": [],
        "reason": "dimension_relevance_unresolved" if unresolved else "",
    }


async def _seed_readiness(session: AsyncSession, *, email: str):
    scenario = await _seed_scenario(session, email=email)
    crawl = await session.get(SiteCrawl, scenario.crawl_id)
    assert crawl is not None
    crawl.analyzer_version = "sh-analyzer-1"
    crawl.extractor_version = "sh-extractor-1"
    crawl.scoring_version = "sh-scoring-1"

    analysis = await session.scalar(
        select(SitePageAnalysis).where(
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.site_url_id == scenario.monitored_url_id,
        )
    )
    assert analysis is not None
    analysis.page_kind = "faq"
    analysis.page_traits = ["has_faq"]
    analysis.profile_version = PROFILE_VERSION
    analysis.schema_contract_version = SCHEMA_CONTRACT_VERSION
    analysis.presentation_version = PRESENTATION_VERSION
    analysis.readiness_dimensions = [
        _dimension(key) for key in AEO_READINESS_DIMENSIONS
    ]

    artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
    assert artifact is not None
    artifact.extractor_version = "sh-extractor-1"

    evaluation_specs = (
        ("aeo.answer_first", RULE_OUTCOME_FAIL, "advisory", {"opening": "context"}),
        ("aeo.question_headings", RULE_OUTCOME_PASS, "defect", {"questions": 3}),
        (
            "aeo.schema_expected_for_type",
            RULE_OUTCOME_PASS,
            "advisory",
            {"schema_type": "FAQPage"},
        ),
        ("technical.indexable", RULE_OUTCOME_PASS, "defect", {"noindex": False}),
    )
    evaluations: list[SiteRuleEvaluation] = []
    for rule_id, outcome, finding_class, evidence in evaluation_specs:
        checkpoint = READINESS_CHECKPOINTS[rule_id]
        evaluation = SiteRuleEvaluation(
            workspace_id=scenario.workspace_id,
            analysis_id=analysis.id,
            source_artifact_id=analysis.artifact_id,
            rule_id=rule_id,
            dimension="aeo",
            category="content",
            severity="medium",
            finding_class=finding_class,
            weight=1.0,
            outcome=outcome,
            display_applicability=True,
            score_applicability=True,
            expected_profile_membership=True,
            score_roles=["aeo_readiness"],
            checkpoint_family=checkpoint.family,
            readiness_dimension=checkpoint.dimension,
            readiness_weight=checkpoint.weight,
            evidence=evidence,
            extractor_version="sh-extractor-1",
            analyzer_version="sh-analyzer-1",
            rule_version="sh-rules-1",
        )
        session.add(evaluation)
        evaluations.append(evaluation)
    await session.flush()

    snapshot = SiteHealthSnapshot(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        crawl_id=scenario.crawl_id,
        selected_url_count=1,
        analyzed_url_count=1,
        technical_integrity_score=100.0,
        technical_integrity_coverage=1.0,
        technical_integrity_state="measured",
        aeo_readiness_score=75.0,
        aeo_measurement_coverage=0.6,
        aeo_measurement_state="limited_evidence",
        readiness_dimensions=analysis.readiness_dimensions,
        search_eligibility="eligible",
        eligibility_totals={"eligible": 1, "blocked": 0, "unknown": 0, "excluded": 0},
        eligibility_reasons=[],
        status_counts={"audited": 1, "blocked": 0, "error": 0, "pending": 0},
        top_issues=[],
        web_fundamentals={
            "state": "not_measured",
            "areas": [],
            "field_data": {
                "state": "unavailable",
                "reason": "provider_not_configured",
                "lcp": None,
                "inp": None,
                "cls": None,
            },
            "source_analysis_ids": [],
            "source_artifact_ids": [],
            "source_evaluation_ids": [],
            "limitations": [],
        },
        trend={"state": "unavailable", "reason": "no_comparable_snapshot"},
        change_summary={"state": "unavailable", "reason": "no_comparable_snapshot"},
        coverage_state="partial",
        coverage_evidence={"reason": "fixture"},
        coverage_formula_version="sh-coverage-1",
        source_analysis_ids=[analysis.id],
        source_artifact_ids=[analysis.artifact_id],
        source_evaluation_ids=[row.id for row in evaluations],
        analyzer_version="sh-analyzer-1",
        scoring_version="sh-scoring-1",
        profile_version=PROFILE_VERSION,
        schema_contract_version=SCHEMA_CONTRACT_VERSION,
        presentation_version=PRESENTATION_VERSION,
    )
    session.add(snapshot)
    await session.commit()
    return scenario, analysis, snapshot


async def test_readiness_reconciles_persisted_measurement_and_page_evidence(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "readiness@example.com")
    async with session_factory() as session:
        scenario, analysis, _snapshot = await _seed_readiness(
            session, email="readiness@example.com"
        )

    response = await client.get(
        f"/api/v1/projects/{scenario.project_id}/site-health/aeo-readiness",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        params={"crawl_id": scenario.crawl_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "limited_evidence"
    assert body["profile_version"] == PROFILE_VERSION
    assert body["analysis_count"] == 1
    assert body["source_analysis_ids"] == [str(analysis.id)]
    assert body["affected_page_count"] == 1
    assert body["limitations"][0] == (
        "Readiness evidence is limited; review dimension coverage below."
    )
    assert all(
        "PR2" not in limitation and "PR3" not in limitation
        for limitation in body["limitations"]
    )
    assert len(body["dimensions"]) == 7
    answerability = next(
        row for row in body["dimensions"] if row["key"] == "answerability"
    )
    assert answerability["missing_count"] == 1
    assert answerability["failing_page_count"] == 1
    assert answerability["evidence_truncated"] is False
    assert answerability["evidence_pages"][0]["source_analysis_id"] == str(analysis.id)
    assert (
        answerability["evidence_pages"][0]["failed_checks"][0]["content_addressable"]
        is True
    )


async def test_overview_reads_the_same_persisted_snapshot(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "overview@example.com")
    async with session_factory() as session:
        scenario, _analysis, snapshot = await _seed_readiness(
            session, email="overview@example.com"
        )

    response = await client.get(
        f"/api/v1/projects/{scenario.project_id}/site-health/overview",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        params={"crawl_id": scenario.crawl_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["snapshot_id"] == str(snapshot.id)
    assert body["search_eligibility"] == "eligible"
    assert body["technical_integrity_score"] == 100.0
    assert body["aeo_measurement_state"] == "limited_evidence"
    assert body["audited_page_count"] == 1
    assert body["selected_page_count"] == 1


async def test_content_handoff_returns_exact_authorized_gap(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "handoff@example.com")
    async with session_factory() as session:
        scenario, analysis, _snapshot = await _seed_readiness(
            session, email="handoff@example.com"
        )

    response = await client.get(
        f"/api/v1/projects/{scenario.project_id}/site-health/content-handoff",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        params={
            "crawl_id": scenario.crawl_id,
            "site_url_id": scenario.monitored_url_id,
            "source_analysis_id": analysis.id,
            "dimension": "answerability",
            "checkpoint_ids": ["aeo.answer_first"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_analysis_id"] == str(analysis.id)
    assert body["checkpoint_ids"] == ["aeo.answer_first"]
    assert body["observed_evidence"] == [{"opening": "context"}]
    assert body["normalized_url"].endswith("/a")
    assert body["scoring_policy_version"] == "1"


async def test_measurement_reads_are_workspace_isolated(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "readiness-owner@example.com")
    await _register(client, "readiness-foreign@example.com")
    async with session_factory() as session:
        owner, analysis, _snapshot = await _seed_readiness(
            session, email="readiness-owner@example.com"
        )
        foreign = await _seed_scenario(session, email="readiness-foreign@example.com")

    headers = {"X-Workspace-Id": str(foreign.workspace_id)}
    readiness = await client.get(
        f"/api/v1/projects/{owner.project_id}/site-health/aeo-readiness",
        headers=headers,
    )
    handoff = await client.get(
        f"/api/v1/projects/{owner.project_id}/site-health/content-handoff",
        headers=headers,
        params={
            "crawl_id": owner.crawl_id,
            "site_url_id": owner.monitored_url_id,
            "source_analysis_id": analysis.id,
            "dimension": "answerability",
            "checkpoint_ids": ["aeo.answer_first"],
        },
    )

    assert readiness.status_code == 404
    assert handoff.status_code == 404
