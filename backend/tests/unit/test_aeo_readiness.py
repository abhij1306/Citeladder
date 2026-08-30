"""PR2 readiness manifest and uncertainty vocabulary fixtures."""

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSIONS,
    RULE_OUTCOME_CONFLICTING,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PARTIAL,
)
from app.core.config.site_health_measurement import (
    READINESS_CHECKPOINTS,
    READINESS_DIMENSION_WEIGHTS,
    STRUCTURAL_NA_REASONS,
    UNAVAILABLE_REASONS,
    UNKNOWN_REASONS,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.domain.site_health.service import aeo_readiness
from app.domain.site_health.service.aeo_readiness import (
    _bounded_evaluations,
    _check_projection,
    _dimension_projection,
    _page_evidence,
)
from app.models.site_health.analysis import SiteRuleEvaluation


def test_pr2_manifest_uses_known_rules_and_scored_dimensions() -> None:
    assert set(READINESS_CHECKPOINTS) <= set(SITE_HEALTH_RULES_BY_ID)
    assert set(READINESS_DIMENSION_WEIGHTS) == set(AEO_READINESS_DIMENSIONS)
    assert sum(READINESS_DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)
    assert {item.dimension for item in READINESS_CHECKPOINTS.values()} == {
        "answerability",
        "structure",
        "machine-readability",
        "authority",
        "crawlability",
    }


def test_schema_check_repetition_does_not_manufacture_family_breadth() -> None:
    schema_families = {
        checkpoint.family
        for rule_id, checkpoint in READINESS_CHECKPOINTS.items()
        if rule_id.startswith("aeo.schema_")
    }
    assert schema_families == {"structured_representation"}


def test_uncertainty_reason_registries_are_disjoint() -> None:
    assert STRUCTURAL_NA_REASONS.isdisjoint(UNAVAILABLE_REASONS)
    assert STRUCTURAL_NA_REASONS.isdisjoint(UNKNOWN_REASONS)
    assert UNAVAILABLE_REASONS.isdisjoint(UNKNOWN_REASONS)
    assert "coverage_not_complete" in UNAVAILABLE_REASONS
    assert "no_checkable_alternates" in UNAVAILABLE_REASONS
    assert "insufficient_evidence" in UNKNOWN_REASONS


def test_only_declared_content_gaps_can_cross_the_content_boundary() -> None:
    addressable = {
        rule_id
        for rule_id, checkpoint in READINESS_CHECKPOINTS.items()
        if checkpoint.content_addressable
    }
    assert addressable == {
        "aeo.answer_first",
        "aeo.question_headings",
        "aeo.author_present",
        "aeo.organization_identity",
    }


def test_removed_readiness_checkpoints_are_filtered_from_projections() -> None:
    analysis_id = uuid4()
    unknown = SiteRuleEvaluation(
        workspace_id=uuid4(),
        analysis_id=analysis_id,
        source_artifact_id=uuid4(),
        rule_id="aeo.removed_checkpoint",
        readiness_dimension="answerability",
        outcome=RULE_OUTCOME_FAIL,
    )

    assert _check_projection(unknown.rule_id, [unknown]) is None
    assert _page_evidence("answerability", [unknown], {}) == []


def _evaluation(
    rule_id: str,
    outcome: str,
    analysis_id: UUID,
    *,
    dimension: str = "machine-readability",
) -> SiteRuleEvaluation:
    return SiteRuleEvaluation(
        workspace_id=uuid4(),
        analysis_id=analysis_id,
        source_artifact_id=uuid4(),
        rule_id=rule_id,
        readiness_dimension=dimension,
        outcome=outcome,
    )


def _analysis_pair(analysis_id: UUID, index: int):
    site_url_id = uuid4()
    return (
        SimpleNamespace(id=analysis_id),
        SimpleNamespace(
            id=site_url_id,
            normalized_url=f"https://example.test/{index:02d}",
        ),
    )


def test_errors_and_conflicts_are_uncertainty_not_actionable_failures() -> None:
    analysis_ids = [uuid4() for _ in range(4)]
    rows = [
        _evaluation("aeo.schema_expected_for_type", outcome, analysis_id)
        for outcome, analysis_id in zip(
            (
                RULE_OUTCOME_FAIL,
                RULE_OUTCOME_PARTIAL,
                RULE_OUTCOME_ERROR,
                RULE_OUTCOME_CONFLICTING,
            ),
            analysis_ids,
            strict=True,
        )
    ]
    analyses = {
        analysis_id: _analysis_pair(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["failing_page_count"] == 2
    assert {page["source_analysis_id"] for page in projection["evidence_pages"]} == set(
        analysis_ids[:2]
    )


def test_evidence_is_worst_first_bounded_and_reports_true_total() -> None:
    analysis_ids = [uuid4() for _ in range(26)]
    analyses = {
        analysis_id: _analysis_pair(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }
    rows = [
        _evaluation("aeo.schema_expected_for_type", RULE_OUTCOME_FAIL, analysis_id)
        for analysis_id in analysis_ids
    ]
    rows.append(
        _evaluation("aeo.schema_required_valid", RULE_OUTCOME_FAIL, analysis_ids[-1])
    )

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["failing_page_count"] == 26
    assert len(projection["evidence_pages"]) == 25
    assert projection["evidence_truncated"] is True
    assert projection["evidence_pages"][0]["source_analysis_id"] == analysis_ids[-1]


def test_exact_evidence_bound_is_not_reported_as_truncated() -> None:
    analysis_ids = [uuid4() for _ in range(25)]
    analyses = {
        analysis_id: _analysis_pair(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }
    rows = [
        _evaluation("aeo.schema_expected_for_type", RULE_OUTCOME_FAIL, analysis_id)
        for analysis_id in analysis_ids
    ]

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["evidence_truncated"] is False


def test_diagnostic_evaluation_cap_reports_truncation(monkeypatch) -> None:
    monkeypatch.setattr(aeo_readiness, "AEO_READINESS_MAX_EVALUATIONS", 2)
    rows = [
        _evaluation("aeo.answer_first", RULE_OUTCOME_FAIL, uuid4()) for _ in range(3)
    ]

    bounded, truncated = _bounded_evaluations(rows)

    assert bounded == rows[:2]
    assert truncated is True
