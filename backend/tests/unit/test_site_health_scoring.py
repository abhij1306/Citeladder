"""PR2 Site Health measurement formula and aggregation fixtures."""

from __future__ import annotations

from app.analysis.site_health.rules import RuleEvaluation
from app.analysis.site_health.scoring import (
    AnalysisMeasurementInput,
    RuleMeasurementInput,
    aggregate_measurements,
    score_analysis,
)
from app.core.config.site_health_measurement import (
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_PAGE,
    RULE_SCOPE_SITE,
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
    scope: str = RULE_SCOPE_PAGE,
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
        scope=scope,
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
    readiness_dimension: str,
    *,
    weight: float = 1.0,
    scope: str = "page",
) -> RuleEvaluation:
    return _evaluation(
        rule_id,
        outcome,
        role=SCORE_ROLE_AEO,
        family=family,
        dimension=readiness_dimension,
        readiness_weight=weight,
        scope=scope,
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
    )
    assert scores.aeo_measurement_coverage == 1.0
    assert scores.aeo_measurement_state == MEASUREMENT_STATE_MEASURED
    structure = next(
        row for row in scores.readiness_dimensions if row.key == "structure"
    )
    assert structure.score == 50.0
    assert scores.expected_checkpoint_profile


def test_homepage_keeps_relevant_unsupported_evidence_in_coverage() -> None:
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
                scope="site",
            ),
            _aeo(
                "technical.indexable",
                "satisfied",
                "indexability",
                "crawlability",
            ),
        ],
        page_kind="homepage",
    )
    assert scores.aeo_measurement_state == MEASUREMENT_STATE_LIMITED
    dimensions = {row.key: row for row in scores.readiness_dimensions}
    assert dimensions["evidence"].applicability == "applicable"
    assert dimensions["freshness"].applicability == "not_applicable"
    assert dimensions["evidence"].coverage == 0.0
    assert dimensions["evidence"].reason == "no_expected_checkpoint_evaluator"
    assert dimensions["authority"].reason == "measured_at_site_scope"
    assert scores.aeo_measurement_coverage == 0.4118


def test_unknown_page_kind_uses_the_universal_other_profile() -> None:
    scores = score_analysis(
        [
            _aeo(
                "technical.indexable",
                "satisfied",
                "indexability",
                "crawlability",
            ),
            _aeo(
                "aeo.server_rendered_content",
                "satisfied",
                "primary_content",
                "machine-readability",
            ),
        ],
        page_kind="unknown-kind",
    )

    dimensions = {row.key: row for row in scores.readiness_dimensions}
    assert dimensions["crawlability"].applicability == "applicable"
    assert dimensions["machine-readability"].applicability == "applicable"
    assert scores.aeo_measurement_state == MEASUREMENT_STATE_LIMITED


def _analyses(kinds: list[str]) -> list[AnalysisMeasurementInput]:
    return [
        AnalysisMeasurementInput(analysis_id=str(index), page_kind=kind)
        for index, kind in enumerate(kinds)
    ]


def _rule_input(
    analysis: AnalysisMeasurementInput,
    *,
    rule_id: str,
    outcome: str,
    dimension: str = "authority",
    scope: str = RULE_SCOPE_PAGE,
    role: str = SCORE_ROLE_AEO,
    weight: float = 1.0,
) -> RuleMeasurementInput:
    return RuleMeasurementInput(
        analysis_id=analysis.analysis_id,
        page_kind=analysis.page_kind,
        rule_id=rule_id,
        scope=scope,
        outcome=outcome,
        expected=True,
        score_roles=(role,),
        weight=weight,
        severity="medium",
        checkpoint_family="fixture",
        readiness_dimension=dimension if role == SCORE_ROLE_AEO else "",
        readiness_weight=weight if role == SCORE_ROLE_AEO else 0.0,
    )


def _dimension(aggregate, key: str) -> dict:
    return next(row for row in aggregate.readiness_dimensions if row["key"] == key)


def test_coverage_increase_does_not_mechanically_improve_component_score() -> None:
    analyses = _analyses(["article"] * 10)
    thin = [
        _rule_input(
            analysis,
            rule_id="aeo.coverage_fixture",
            outcome="satisfied" if index == 0 else "unknown",
        )
        for index, analysis in enumerate(analyses)
    ]
    broad = [
        _rule_input(
            analysis,
            rule_id="aeo.coverage_fixture",
            outcome="unknown" if index == 9 else "satisfied",
        )
        for index, analysis in enumerate(analyses)
    ]

    thin_dimension = _dimension(aggregate_measurements(analyses, thin), "authority")
    broad_dimension = _dimension(aggregate_measurements(analyses, broad), "authority")

    assert thin_dimension["score"] == broad_dimension["score"] == 100.0
    assert thin_dimension["coverage"] == 0.1
    assert broad_dimension["coverage"] == 0.9


def test_rule_contributions_are_weighted_by_their_own_coverage() -> None:
    analyses = _analyses(["article"] * 10)
    rules = [
        _rule_input(
            analysis,
            rule_id="aeo.thin_high",
            outcome="satisfied" if index == 0 else "unknown",
        )
        for index, analysis in enumerate(analyses)
    ]
    rules.extend(
        _rule_input(
            analysis,
            rule_id="aeo.full_low",
            outcome="satisfied" if index < 4 else "missing",
        )
        for index, analysis in enumerate(analyses)
    )

    authority = _dimension(aggregate_measurements(analyses, rules), "authority")

    assert authority["score"] == 45.5
    assert authority["coverage"] == 0.55


def test_duplicate_site_evidence_does_not_change_rule_or_dimension() -> None:
    analyses = _analyses(["homepage"] * 100)
    one = [
        _rule_input(
            analyses[0],
            rule_id="aeo.organization_identity",
            outcome="satisfied",
            scope=RULE_SCOPE_SITE,
        )
    ]
    repeated = [
        _rule_input(
            analysis,
            rule_id="aeo.organization_identity",
            outcome="satisfied",
            scope=RULE_SCOPE_SITE,
        )
        for analysis in analyses
    ]

    first = _dimension(aggregate_measurements(analyses, one), "authority")
    duplicated = _dimension(aggregate_measurements(analyses, repeated), "authority")

    assert first == duplicated
    assert first["score"] == 100.0
    assert first["coverage"] == 1.0


def test_page_mix_does_not_weight_a_rule_by_crawl_composition() -> None:
    balanced = _analyses(["article"] * 10 + ["product"] * 10 + ["category"] * 10)
    skewed = _analyses(["article"] * 10 + ["product"] * 10 + ["category"] * 110)

    def observations(analyses: list[AnalysisMeasurementInput]):
        outcome = {"article": "missing", "product": "partial", "category": "satisfied"}
        return [
            _rule_input(
                analysis,
                rule_id="aeo.page_mix_fixture",
                outcome=outcome[analysis.page_kind],
            )
            for analysis in analyses
        ]

    balanced_aggregate = aggregate_measurements(balanced, observations(balanced))
    skewed_aggregate = aggregate_measurements(skewed, observations(skewed))

    assert _dimension(balanced_aggregate, "authority") == _dimension(
        skewed_aggregate, "authority"
    )
    assert (
        balanced_aggregate.aeo_readiness_score == skewed_aggregate.aeo_readiness_score
    )
