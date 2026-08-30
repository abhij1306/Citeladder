from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from app.domain.site_health.aeo_readiness_projection import (
    ReadinessPage,
    build_aeo_readiness_descriptor,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.domain.site_health.overview_snapshot import build_overview_history
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import SiteUrl
from tests.component.site_health_api_helpers import _register, _seed_scenario

pytestmark = pytest.mark.asyncio


def _dimension(key: str) -> dict:
    unmeasured = key in {"evidence", "freshness", "authority"}
    return {
        "key": key,
        "label": AEO_READINESS_DIMENSION_LABELS[key],
        "description": AEO_READINESS_DIMENSION_DESCRIPTIONS[key],
        "dimension_applicability": "applicable",
        "dimension_measurement_state": (
            "not_measured" if unmeasured else "limited_evidence"
        ),
        "score": None if unmeasured else (0.0 if key == "answerability" else 100.0),
        "coverage": 0.0 if unmeasured else 1.0,
        "earned_points": (
            0.0 if key == "answerability" else (0.0 if unmeasured else 1.0)
        ),
        "determinate_points": 0.0 if unmeasured else 1.0,
        "expected_points": 1.0,
        "determinate_checkpoint_ids": [],
        "checkpoint_families": [],
        "reason": "no_expected_checkpoint_evaluator" if unmeasured else "",
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
        ("aeo.answer_first", RULE_OUTCOME_MISSING, "advisory", {"opening": "context"}),
        ("aeo.question_headings", RULE_OUTCOME_SATISFIED, "defect", {"questions": 3}),
        (
            "aeo.schema_expected_for_type",
            RULE_OUTCOME_SATISFIED,
            "advisory",
            {"schema_type": "FAQPage"},
        ),
        ("technical.indexable", RULE_OUTCOME_SATISFIED, "defect", {"noindex": False}),
    )
    evaluations: list[SiteRuleEvaluation] = []
    for rule_id, outcome, finding_class, evidence in evaluation_specs:
        checkpoint = SITE_HEALTH_RULES_BY_ID[rule_id]
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
            checkpoint_family=checkpoint.checkpoint_family,
            readiness_dimension=checkpoint.readiness_dimension,
            readiness_weight=checkpoint.readiness_weight,
            evidence=evidence,
            extractor_version="sh-extractor-1",
            analyzer_version="sh-analyzer-1",
            rule_version="sh-rules-1",
        )
        session.add(evaluation)
        evaluations.append(evaluation)
    await session.flush()

    site_url = await session.get(SiteUrl, analysis.site_url_id)
    assert site_url is not None
    aeo_readiness_diagnostic = build_aeo_readiness_descriptor(
        crawl_id=scenario.crawl_id,
        score=75.0,
        coverage=0.6,
        state="limited_evidence",
        coverage_state="partial",
        readiness_dimensions=analysis.readiness_dimensions,
        evaluations=evaluations,
        pages={
            analysis.id: ReadinessPage(
                analysis_id=analysis.id,
                site_url_id=site_url.id,
                normalized_url=site_url.normalized_url,
            )
        },
        profile_version=PROFILE_VERSION,
        schema_contract_version=SCHEMA_CONTRACT_VERSION,
        scoring_version="sh-scoring-1",
        presentation_version=PRESENTATION_VERSION,
        analyzer_version="sh-analyzer-1",
        source_analysis_ids=[analysis.id],
    )

    snapshot = SiteHealthSnapshot(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        crawl_id=scenario.crawl_id,
        selected_url_count=1,
        analyzed_url_count=1,
        web_fundamentals_score=100.0,
        web_fundamentals_coverage=1.0,
        web_fundamentals_state="measured",
        aeo_readiness_score=75.0,
        aeo_measurement_coverage=0.6,
        aeo_measurement_state="limited_evidence",
        readiness_dimensions=analysis.readiness_dimensions,
        aeo_readiness_diagnostic=aeo_readiness_diagnostic,
        search_eligibility="eligible",
        eligibility_totals={"eligible": 1, "blocked": 0, "unknown": 0, "excluded": 0},
        eligibility_reasons=[],
        status_counts={"audited": 1, "blocked": 0, "error": 0, "pending": 0},
        top_issues=[
            {
                "rule_id": f"technical.fixture_{index}",
                "finding_class": "defect",
                "severity": "high",
                "category": "technical",
                "description": f"Fixture issue {index}",
                "remediation": "Fix the fixture.",
                "affected_pages": index,
                "eligibility_blocker": False,
                "impact_band": 3,
                "impact_label": "High",
            }
            for index in range(1, 7)
        ],
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
        trend={
            "state": "unavailable",
            "reason": "no_comparable_snapshot",
            "metric": "aeo_readiness_score",
            "series": [{"label": "2026-08-30", "value": 75.0}],
        },
        change_summary={
            "state": "unavailable",
            "reason": "no_comparable_snapshot",
            "metrics": [
                {
                    "key": "web_fundamentals_score",
                    "label": "Web Fundamentals",
                    "previous": None,
                    "current": 100.0,
                    "delta": None,
                    "direction": "unavailable",
                },
                {
                    "key": "web_fundamentals_coverage",
                    "label": "Web Fundamentals coverage",
                    "previous": None,
                    "current": 1.0,
                    "delta": None,
                    "direction": "unavailable",
                },
                {
                    "key": "aeo_readiness_score",
                    "label": "AEO Readiness",
                    "previous": None,
                    "current": 75.0,
                    "delta": None,
                    "direction": "unavailable",
                },
                {
                    "key": "aeo_measurement_coverage",
                    "label": "AEO coverage",
                    "previous": None,
                    "current": 0.6,
                    "delta": None,
                    "direction": "unavailable",
                },
            ],
        },
        issue_count=7,
        technical_defect_count=2,
        technical_defect_affected_page_count=1,
        aeo_readiness_gap_count=5,
        aeo_readiness_gap_affected_page_count=1,
        severity_counts={"high": 2, "medium": 5},
        category_counts={"technical": 2, "content": 5},
        coverage_state="partial",
        coverage_evidence={
            "reason": "fixture",
            "measured_check_count": 3,
            "expected_check_count": 4,
        },
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


async def test_readiness_does_not_drift_after_terminal_snapshot(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "immutable-readiness@example.com")
    async with session_factory() as session:
        scenario, analysis, _snapshot = await _seed_readiness(
            session, email="immutable-readiness@example.com"
        )

    endpoint = f"/api/v1/projects/{scenario.project_id}/site-health/aeo-readiness"
    request = {
        "headers": {"X-Workspace-Id": str(scenario.workspace_id)},
        "params": {"crawl_id": scenario.crawl_id},
    }
    before = await client.get(endpoint, **request)
    assert before.status_code == 200

    async with session_factory() as session:
        current_analysis = await session.get(SitePageAnalysis, analysis.id)
        assert current_analysis is not None
        current_analysis.readiness_dimensions = []
        evaluations = list(
            await session.scalars(
                select(SiteRuleEvaluation).where(
                    SiteRuleEvaluation.analysis_id == analysis.id
                )
            )
        )
        for evaluation in evaluations:
            evaluation.outcome = RULE_OUTCOME_SATISFIED
            evaluation.evidence = {"mutated_after_snapshot": True}
        await session.commit()

    after = await client.get(endpoint, **request)
    assert after.status_code == 200
    assert after.json() == before.json()


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
    assert len(snapshot.top_issues) == 6
    assert body["snapshot_id"] == str(snapshot.id)
    assert body["search_eligibility"] == "eligible"
    assert body["web_fundamentals_score"] == 100.0
    assert body["aeo_measurement_state"] == "limited_evidence"
    assert body["audited_page_count"] == 1
    assert body["selected_page_count"] == 1
    assert body["issue_count"] == 7
    assert body["technical_defect_count"] == 2
    assert body["technical_defect_affected_page_count"] == 1
    assert body["aeo_readiness_gap_count"] == 5
    assert body["aeo_readiness_gap_affected_page_count"] == 1
    assert body["severity_counts"] == {"high": 2, "medium": 5}
    assert body["category_counts"] == {"technical": 2, "content": 5}
    assert body["measured_check_count"] == 3
    assert body["expected_check_count"] == 4
    assert len(body["top_issues"]) == 5
    assert body["top_issues"][-1]["rule_id"] == "technical.fixture_5"
    assert body["aeo_dimensions"][0]["label"] == "Answerability"
    assert "answers its question" in body["aeo_dimensions"][0]["description"]
    assert body["trend"]["series"] == [{"label": "2026-08-30", "value": 75.0}]
    assert len(body["change_summary"]["metrics"]) == 4


async def test_overview_backfills_legacy_issue_and_null_history_fields(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "legacy-overview@example.com")
    async with session_factory() as session:
        scenario, _analysis, snapshot = await _seed_readiness(
            session, email="legacy-overview@example.com"
        )
        legacy_issue = {
            **snapshot.top_issues[0],
            "rule_id": "technical.indexable",
            "finding_class": "defect",
            "severity": "critical",
        }
        for field in ("score_roles", "impact_band", "impact_label"):
            legacy_issue.pop(field, None)
        complete_issue = {
            **snapshot.top_issues[1],
            "score_roles": [],
            "impact_band": 99,
            "impact_label": "Frozen",
        }
        snapshot.top_issues = [legacy_issue, complete_issue]
        snapshot.trend = None
        snapshot.change_summary = None
        await session.commit()

    response = await client.get(
        f"/api/v1/projects/{scenario.project_id}/site-health/overview",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
        params={"crawl_id": scenario.crawl_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["top_issues"][0]["score_roles"] == [
        "aeo_readiness",
        "web_fundamentals",
    ]
    assert body["top_issues"][0]["impact_band"] == 4
    assert body["top_issues"][0]["impact_label"] == "Critical"
    assert body["top_issues"][1]["impact_band"] == 99
    assert body["top_issues"][1]["impact_label"] == "Frozen"
    assert body["trend"] == {
        "state": "unavailable",
        "reason": "no_comparable_snapshot",
        "metric": "aeo_readiness_score",
        "series": [],
    }
    assert body["change_summary"] == {
        "state": "unavailable",
        "reason": "no_comparable_snapshot",
        "metrics": [],
    }


async def test_overview_history_requires_the_complete_measurement_identity(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "history@example.com")
    async with session_factory() as session:
        scenario, _analysis, _snapshot = await _seed_readiness(
            session, email="history@example.com"
        )
        previous_crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert previous_crawl is not None
        current_crawl = SiteCrawl(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            profile_id=previous_crawl.profile_id,
            root_url=previous_crawl.root_url,
        )
        session.add(current_crawl)
        await session.flush()

        current_metrics = {
            "web_fundamentals_score": 80.0,
            "web_fundamentals_coverage": 0.9,
            "aeo_readiness_score": 70.0,
            "aeo_measurement_coverage": 0.8,
        }
        trend, changes = await build_overview_history(
            session,
            crawl=current_crawl,
            analyzer_version="sh-analyzer-1",
            scoring_version="sh-scoring-1",
            current_metrics=current_metrics,
            observed_at=datetime.now(UTC),
        )
        assert trend["state"] == "measured"
        assert [point["value"] for point in trend["series"]] == [75.0, 70.0]
        assert [item["direction"] for item in changes["metrics"]] == [
            "decreased",
            "decreased",
            "decreased",
            "increased",
        ]

        incompatible_trend, incompatible_changes = await build_overview_history(
            session,
            crawl=current_crawl,
            analyzer_version="sh-analyzer-1",
            scoring_version="different-scoring-version",
            current_metrics=current_metrics,
            observed_at=datetime.now(UTC),
        )
        assert incompatible_trend["reason"] == "no_comparable_snapshot"
        assert len(incompatible_trend["series"]) == 1
        assert all(
            item["direction"] == "unavailable"
            for item in incompatible_changes["metrics"]
        )


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
