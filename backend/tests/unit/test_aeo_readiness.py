"""PR2 readiness manifest and uncertainty vocabulary fixtures."""

from uuid import UUID, uuid4

import pytest

from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSIONS,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_UNKNOWN,
)
from app.core.config.site_health_measurement import (
    CAPABILITY_FAMILY_MANIFEST,
    CHECKPOINT_FAMILY_BY_ID,
    READINESS_DIMENSION_WEIGHTS,
    STRUCTURAL_NA_REASONS,
    UNAVAILABLE_REASONS,
    UNKNOWN_REASONS,
    expected_checkpoints,
    relevant_dimensions,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.domain.site_health import aeo_readiness_projection
from app.domain.site_health.aeo_readiness_projection import (
    ReadinessPage,
    _bounded_evaluations,
    _check_projection,
    _dimension_projection,
    _failing_entity_count,
    _page_evidence,
)
from app.models.site_health.analysis import SiteRuleEvaluation


def test_readiness_manifest_uses_known_rules_and_scored_dimensions() -> None:
    assert set(READINESS_DIMENSION_WEIGHTS) == set(AEO_READINESS_DIMENSIONS)
    assert sum(READINESS_DIMENSION_WEIGHTS.values()) == pytest.approx(1.0)
    assert {family.dimension_id for family in CAPABILITY_FAMILY_MANIFEST} == {
        "answerability",
        "structure",
        "machine-readability",
        "authority",
        "crawlability",
        "evidence",
        "freshness",
    }
    assert set(CHECKPOINT_FAMILY_BY_ID) <= set(SITE_HEALTH_RULES_BY_ID)


def test_schema_check_repetition_does_not_manufacture_family_breadth() -> None:
    schema_families = {
        CHECKPOINT_FAMILY_BY_ID[rule_id]
        for rule_id in SITE_HEALTH_RULES_BY_ID
        if rule_id.startswith("aeo.schema_")
    }
    assert schema_families == {"structured_representation"}


def test_uncertainty_reason_registries_are_disjoint() -> None:
    assert STRUCTURAL_NA_REASONS.isdisjoint(UNKNOWN_REASONS)
    assert UNAVAILABLE_REASONS.isdisjoint(UNKNOWN_REASONS)
    assert "coverage_not_complete" in UNAVAILABLE_REASONS
    assert "no_checkable_alternates" in UNAVAILABLE_REASONS
    assert "insufficient_evidence" in UNKNOWN_REASONS


def test_observed_faq_trait_never_changes_scoring_applicability() -> None:
    assert expected_checkpoints("article", ["has_faq"]) == expected_checkpoints(
        "article"
    )
    assert relevant_dimensions("article", ["has_faq"]) == relevant_dimensions("article")


def test_only_declared_content_gaps_can_cross_the_content_boundary() -> None:
    addressable = {
        rule_id
        for rule_id, rule in SITE_HEALTH_RULES_BY_ID.items()
        if rule.content_addressable
    }
    assert addressable == {
        "aeo.answer_first",
        "aeo.question_headings",
        "aeo.visible_attribution",
        "aeo.content_date_present",
        "aeo.editorial_lead_present",
        "aeo.entity_value_proposition",
        "aeo.heading_hierarchy",
        "aeo.listing_answer_set",
        "aeo.listing_item_facts",
        "aeo.offer_freshness_signal",
        "aeo.assortment_freshness_signal",
        "aeo.organization_identity",
        "aeo.source_support_present",
        "aeo.product_answer_facts",
        "aeo.product_brand_identity",
        "aeo.product_evidence_facts",
    }


def test_readiness_profiles_match_evidence_independent_context() -> None:
    context = {
        "research_sensitive": True,
        "freshness_sensitive": True,
    }
    docs = set(expected_checkpoints("docs", crawl_context=context))
    case_study = set(expected_checkpoints("case_study_review", crawl_context=context))

    assert "aeo.visible_attribution" not in docs
    assert "aeo.source_support_present" in docs
    assert "aeo.content_date_present" in docs
    assert "aeo.visible_attribution" in case_study
    assert "aeo.content_date_present" in case_study
    assert "aeo.source_support_present" in case_study


def test_removed_readiness_checkpoints_are_filtered_from_projections() -> None:
    analysis_id = uuid4()
    unknown = SiteRuleEvaluation(
        workspace_id=uuid4(),
        analysis_id=analysis_id,
        source_artifact_id=uuid4(),
        rule_id="aeo.removed_checkpoint",
        readiness_dimension="answerability",
        outcome=RULE_OUTCOME_MISSING,
    )

    assert _check_projection(unknown.rule_id, [unknown]) is None
    assert _page_evidence("answerability", [unknown], {}) == []


def _evaluation(
    rule_id: str,
    outcome: str,
    analysis_id: UUID,
    *,
    dimension: str = "machine-readability",
    scope: str = "page",
    evidence: dict[str, object] | None = None,
) -> SiteRuleEvaluation:
    return SiteRuleEvaluation(
        workspace_id=uuid4(),
        analysis_id=analysis_id,
        source_artifact_id=uuid4(),
        rule_id=rule_id,
        readiness_dimension=dimension,
        outcome=outcome,
        scope=scope,
        evidence=evidence,
    )


def test_site_scope_failure_is_an_entity_not_a_page_failure() -> None:
    analysis_id = uuid4()
    evaluation = _evaluation(
        "aeo.organization_identity",
        RULE_OUTCOME_MISSING,
        analysis_id,
        dimension="authority",
        scope="site",
    )
    projection = _check_projection(evaluation.rule_id, [evaluation])

    assert projection is not None
    assert projection["scope"] == "site"
    assert projection["failing_entity_count"] == 1
    assert _page_evidence("authority", [evaluation], {}) == []


@pytest.mark.parametrize(
    ("failure_count", "expected"),
    [
        (3, 3),
        (2.8, 2),
        ("3", 3),
        ("not-a-number", 1),
        (float("nan"), 1),
        ({"count": 5}, 1),
        (None, 1),
    ],
)
def test_non_page_failure_counts_validate_persisted_evidence(
    failure_count: object, expected: int
) -> None:
    analysis_id = uuid4()
    evaluation = SiteRuleEvaluation(
        workspace_id=uuid4(),
        analysis_id=analysis_id,
        source_artifact_id=uuid4(),
        rule_id="technical.broken_internal_link",
        readiness_dimension="crawlability",
        outcome=RULE_OUTCOME_MISSING,
        scope="graph",
        evidence={"failure_count": failure_count},
    )
    assert _failing_entity_count("graph", [evaluation]) == expected


def _analysis_page(analysis_id: UUID, index: int) -> ReadinessPage:
    return ReadinessPage(
        analysis_id=analysis_id,
        site_url_id=uuid4(),
        normalized_url=f"https://example.test/{index:02d}",
    )


def test_errors_and_unknowns_are_uncertainty_not_actionable_failures() -> None:
    analysis_ids = [uuid4() for _ in range(4)]
    rows = [
        _evaluation(
            "aeo.schema_expected_for_type",
            outcome,
            analysis_id,
            evidence={"reason": "conflicting_schema_entities"}
            if outcome == RULE_OUTCOME_UNKNOWN
            else None,
        )
        for outcome, analysis_id in zip(
            (
                RULE_OUTCOME_MISSING,
                RULE_OUTCOME_PARTIAL,
                RULE_OUTCOME_ERROR,
                RULE_OUTCOME_UNKNOWN,
            ),
            analysis_ids,
            strict=True,
        )
    ]
    analyses = {
        analysis_id: _analysis_page(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["failing_page_count"] == 2
    assert {page["source_analysis_id"] for page in projection["evidence_pages"]} == {
        str(value) for value in analysis_ids[:2]
    }


def test_evidence_is_worst_first_bounded_and_reports_true_total() -> None:
    analysis_ids = [uuid4() for _ in range(26)]
    analyses = {
        analysis_id: _analysis_page(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }
    rows = [
        _evaluation("aeo.schema_expected_for_type", RULE_OUTCOME_MISSING, analysis_id)
        for analysis_id in analysis_ids
    ]
    rows.append(
        _evaluation("aeo.schema_required_valid", RULE_OUTCOME_MISSING, analysis_ids[-1])
    )

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["failing_page_count"] == 26
    assert len(projection["evidence_pages"]) == 25
    assert projection["evidence_truncated"] is True
    assert projection["evidence_pages"][0]["source_analysis_id"] == str(
        analysis_ids[-1]
    )


def test_exact_evidence_bound_is_not_reported_as_truncated() -> None:
    analysis_ids = [uuid4() for _ in range(25)]
    analyses = {
        analysis_id: _analysis_page(analysis_id, index)
        for index, analysis_id in enumerate(analysis_ids)
    }
    rows = [
        _evaluation("aeo.schema_expected_for_type", RULE_OUTCOME_MISSING, analysis_id)
        for analysis_id in analysis_ids
    ]

    projection = _dimension_projection({"key": "machine-readability"}, rows, analyses)

    assert projection["evidence_truncated"] is False


def test_diagnostic_evaluation_cap_reports_truncation(monkeypatch) -> None:
    monkeypatch.setattr(aeo_readiness_projection, "AEO_READINESS_MAX_EVALUATIONS", 2)
    rows = [
        _evaluation("aeo.answer_first", RULE_OUTCOME_MISSING, uuid4()) for _ in range(3)
    ]

    bounded, truncated = _bounded_evaluations(rows)

    assert bounded == rows[:2]
    assert truncated is True
