"""PR2 Site Health measurement formula and aggregation fixtures."""

from __future__ import annotations

from app.analysis.site_health.rules import RuleEvaluation
from app.analysis.site_health.scoring import (
    AnalysisMeasurementInput,
    aggregate_measurements,
    score_analysis,
)
from app.core.config.site_health_measurement import (
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    SCORE_ROLE_AEO,
    SCORE_ROLE_TECHNICAL,
)


def _evaluation(
    rule_id: str,
    outcome: str,
    *,
    role: str,
    weight: float = 1.0,
    severity: str = "medium",
    family: str = "",
    dimension: str = "",
    readiness_weight: float = 0.0,
) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        rule_version="1",
        dimension="technical",
        category="test",
        severity=severity,
        finding_class="defect",
        weight=weight,
        outcome=outcome,
        expected_profile_membership=True,
        score_applicability=True,
        score_roles=(role,),
        checkpoint_family=family,
        readiness_dimension=dimension,
        readiness_weight=readiness_weight,
    )


def _technical(
    rule_id: str,
    outcome: str,
    *,
    weight: float = 1.0,
    severity: str = "medium",
) -> RuleEvaluation:
    return _evaluation(
        rule_id,
        outcome,
        role=SCORE_ROLE_TECHNICAL,
        weight=weight,
        severity=severity,
    )


def _aeo(
    rule_id: str,
    outcome: str,
    family: str,
    dimension: str,
    *,
    weight: float = 1.0,
) -> RuleEvaluation:
    return _evaluation(
        rule_id,
        outcome,
        role=SCORE_ROLE_AEO,
        family=family,
        dimension=dimension,
        readiness_weight=weight,
    )


def test_technical_boundary_requires_coverage_and_critical_completeness() -> None:
    below = score_analysis(
        [
            _technical("technical.indexable", "satisfied", severity="critical"),
            _technical("technical.title", "satisfied"),
            _technical("technical.description", "unknown"),
        ]
    )
    assert below.technical_integrity_score == 100.0
    assert below.technical_integrity_coverage == 0.6667
    assert below.technical_integrity_state == MEASUREMENT_STATE_LIMITED

    boundary = score_analysis(
        [
            _technical("technical.indexable", "satisfied", severity="critical"),
            _technical("technical.a", "satisfied"),
            _technical("technical.b", "satisfied"),
            _technical("technical.c", "missing"),
            _technical("technical.d", "unknown"),
        ]
    )
    assert boundary.technical_integrity_score == 75.0
    assert boundary.technical_integrity_coverage == 0.8
    assert boundary.technical_integrity_state == MEASUREMENT_STATE_MEASURED


def test_qualifying_faq_needs_breadth_and_coverage() -> None:
    scores = score_analysis(
        [
            _aeo("aeo.answer_first", "satisfied", "answer_content", "answerability"),
            _aeo(
                "aeo.question_headings",
                "partial",
                "semantic_structure",
                "structure",
            ),
            _aeo(
                "aeo.schema_expected_for_type",
                "satisfied",
                "structured_representation",
                "machine-readability",
            ),
            _aeo("aeo.author_present", "satisfied", "provenance", "authority"),
            _aeo(
                "technical.indexable",
                "satisfied",
                "indexability",
                "crawlability",
            ),
        ],
        page_kind="faq",
        page_kind_evidence={"tier": "structural"},
    )
    assert scores.aeo_measurement_coverage == 0.8
    assert scores.aeo_measurement_state == MEASUREMENT_STATE_MEASURED
    structure = next(
        row for row in scores.readiness_dimensions if row.key == "structure"
    )
    assert structure.score == 50.0
    assert scores.expected_checkpoint_profile


def test_healthy_non_faq_stays_limited_and_unresolved_dimensions_lower_coverage() -> (
    None
):
    scores = score_analysis(
        [
            _aeo(
                "aeo.schema_expected_for_type",
                "satisfied",
                "structured_representation",
                "machine-readability",
            ),
            _aeo(
                "aeo.organization_identity",
                "satisfied",
                "provenance",
                "authority",
            ),
            _aeo(
                "technical.indexable",
                "satisfied",
                "indexability",
                "crawlability",
            ),
        ],
        page_kind="homepage",
        page_kind_evidence={"tier": "structural"},
    )
    assert scores.aeo_measurement_state == MEASUREMENT_STATE_LIMITED
    dimensions = {row.key: row for row in scores.readiness_dimensions}
    assert dimensions["evidence"].applicability == "unresolved"
    assert dimensions["freshness"].applicability == "unresolved"
    assert dimensions["evidence"].coverage == 0.0
    assert scores.aeo_measurement_coverage == 0.6923


def _aggregate_input(
    technical_score: float,
    earned: float,
    determinate: float,
    expected: float,
) -> AnalysisMeasurementInput:
    return AnalysisMeasurementInput(
        page_kind="article",
        technical_integrity_score=technical_score,
        technical_integrity_coverage=determinate / expected,
        technical_integrity_state=MEASUREMENT_STATE_MEASURED,
        technical_earned_weight=earned,
        technical_determinate_weight=determinate,
        technical_expected_weight=expected,
        technical_critical_complete=True,
        aeo_readiness_score=None,
        aeo_measurement_coverage=0.0,
        aeo_measurement_state=MEASUREMENT_STATE_LIMITED,
        readiness_dimensions=(),
    )


def test_site_technical_score_pools_weights_instead_of_averaging_page_scores() -> None:
    aggregate = aggregate_measurements(
        [
            _aggregate_input(100.0, 9.0, 9.0, 9.0),
            _aggregate_input(0.0, 0.0, 1.0, 1.0),
        ]
    )
    assert aggregate.technical_integrity_score == 90.0
    assert aggregate.technical_integrity_coverage == 1.0


def test_site_readiness_pools_dimension_points_before_weighting() -> None:
    common = dict(
        page_kind="faq",
        technical_integrity_score=None,
        technical_integrity_coverage=None,
        technical_integrity_state="not_measured",
        technical_earned_weight=0.0,
        technical_determinate_weight=0.0,
        technical_expected_weight=0.0,
        technical_critical_complete=False,
        aeo_readiness_score=None,
        aeo_measurement_coverage=1.0,
        aeo_measurement_state=MEASUREMENT_STATE_LIMITED,
    )
    high = (
        {
            "key": "answerability",
            "dimension_applicability": "applicable",
            "coverage": 1.0,
            "earned_points": 9.0,
            "determinate_points": 9.0,
            "expected_points": 9.0,
            "determinate_checkpoint_ids": ["aeo.answer_first"],
            "checkpoint_families": ["answer_content"],
        },
    )
    low = (
        {
            **high[0],
            "earned_points": 0.0,
            "determinate_points": 1.0,
            "expected_points": 10.0,
            "coverage": 0.1,
        },
    )
    aggregate = aggregate_measurements(
        [
            AnalysisMeasurementInput(**common, readiness_dimensions=high),
            AnalysisMeasurementInput(**common, readiness_dimensions=low),
        ]
    )
    answerability = next(
        row for row in aggregate.readiness_dimensions if row["key"] == "answerability"
    )
    assert answerability["score"] == 90.0
    assert answerability["coverage"] == 0.55
    assert aggregate.aeo_measurement_coverage == 0.55
