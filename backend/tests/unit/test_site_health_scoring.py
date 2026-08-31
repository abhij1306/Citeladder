"""PR4 Site Health family-normalized scoring and aggregation fixtures."""

from __future__ import annotations

import pytest

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
    MEASUREMENT_STATE_NOT_MEASURED,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_PAGE,
    SCORE_ROLE_AEO,
    SCORE_ROLE_WEB_FUNDAMENTALS,
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
        role=SCORE_ROLE_WEB_FUNDAMENTALS,
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
    scope: str = RULE_SCOPE_PAGE,
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
            _technical("technical.title_present", "satisfied"),
            _technical("technical.meta_description_present", "unknown"),
        ]
    )
    assert below.web_fundamentals_score == 100.0
    assert below.web_fundamentals_coverage == 0.6667
    assert below.web_fundamentals_state == MEASUREMENT_STATE_LIMITED

    boundary = score_analysis(
        [
            _technical("technical.indexable", "satisfied", severity="critical"),
            _technical("technical.title_present", "satisfied"),
            _technical("technical.meta_description_present", "satisfied"),
            _technical("technical.canonical_present", "missing"),
            _technical("technical.https", "unknown"),
        ]
    )
    assert boundary.web_fundamentals_score == 75.0
    assert boundary.web_fundamentals_coverage == 0.8
    assert boundary.web_fundamentals_state == MEASUREMENT_STATE_MEASURED


def test_page_web_fundamentals_partial_outcome_receives_half_credit() -> None:
    scores = score_analysis(
        [
            _technical("technical.indexable", "satisfied"),
            _technical("technical.title_present", "partial"),
        ]
    )

    assert scores.web_fundamentals_score == 75.0
    assert scores.web_fundamentals_coverage == 1.0
    assert scores.web_fundamentals_state == MEASUREMENT_STATE_MEASURED


def _page_dimension(scores, key: str):
    return next(row for row in scores.readiness_dimensions if row.key == key)


def test_zero_expected_and_measurement_gap_profiles_keep_distinct_denominators() -> (
    None
):
    no_profile = score_analysis([], page_kind="other")
    gap_profile = score_analysis([], page_kind="homepage")
    gap_dimension = _page_dimension(gap_profile, "evidence")

    assert no_profile.aeo_readiness_score is None
    assert no_profile.aeo_measurement_coverage is None
    assert no_profile.aeo_measurement_state == MEASUREMENT_STATE_NOT_MEASURED
    assert gap_dimension.score is None
    assert gap_dimension.coverage == 0.0
    assert gap_dimension.expected_points == 0.5
    assert gap_dimension.determinate_points == 0.0
    assert gap_dimension.measurement_state == MEASUREMENT_STATE_NOT_MEASURED


def test_duplicate_checkpoint_observation_does_not_change_family_or_dimension() -> None:
    observations = [
        _aeo(
            "aeo.heading_hierarchy",
            "missing",
            "semantic_structure",
            "structure",
        ),
        _aeo(
            "aeo.question_headings",
            "satisfied",
            "semantic_structure",
            "structure",
        ),
    ]
    baseline = score_analysis(observations, page_kind="faq")
    duplicated = score_analysis(
        [
            *observations,
            _aeo(
                "aeo.question_headings",
                "satisfied",
                "semantic_structure",
                "structure",
            ),
        ],
        page_kind="faq",
    )

    baseline_structure = _page_dimension(baseline, "structure")
    duplicated_structure = _page_dimension(duplicated, "structure")

    assert baseline_structure == duplicated_structure
    assert baseline_structure.score == 50.0
    assert baseline_structure.coverage == 1.0
    assert baseline_structure.measurement_state == MEASUREMENT_STATE_MEASURED
    assert baseline_structure.earned_points == 0.5
    assert baseline_structure.determinate_points == 1.0
    assert baseline_structure.expected_points == 1.0
    assert baseline_structure.checkpoint_families == ("semantic_structure",)
    assert baseline_structure.determinate_checkpoint_ids == (
        "aeo.heading_hierarchy",
        "aeo.question_headings",
    )
    assert baseline.aeo_readiness_score == duplicated.aeo_readiness_score
    assert baseline.aeo_measurement_coverage == duplicated.aeo_measurement_coverage
    assert baseline.aeo_measurement_state == duplicated.aeo_measurement_state


def test_structured_guard_and_weighted_validators_keep_one_family_budget() -> None:
    guard = score_analysis(
        [
            _aeo(
                "aeo.schema_expected_for_type",
                "missing",
                "structured_representation",
                "machine-readability",
            )
        ],
        page_kind="article",
        crawl_context={"primary_schema_present": False},
    )
    validators = score_analysis(
        [
            _aeo(
                "aeo.schema_required_valid",
                "satisfied",
                "structured_representation",
                "machine-readability",
            ),
            _aeo(
                "aeo.schema_matches_content",
                "satisfied",
                "structured_representation",
                "machine-readability",
            ),
            _aeo(
                "aeo.schema_recommended_present",
                "satisfied",
                "structured_representation",
                "machine-readability",
            ),
        ],
        page_kind="article",
        crawl_context={"primary_schema_present": True},
    )

    guard_machine = _page_dimension(guard, "machine-readability")
    validator_machine = _page_dimension(validators, "machine-readability")

    assert guard_machine.score == 0.0
    assert validator_machine.score == 100.0
    assert guard_machine.coverage == validator_machine.coverage == 1.0
    assert (
        guard_machine.measurement_state
        == validator_machine.measurement_state
        == MEASUREMENT_STATE_MEASURED
    )
    assert guard_machine.expected_points == validator_machine.expected_points == 1.0
    assert (
        guard_machine.determinate_points == validator_machine.determinate_points == 1.0
    )
    assert guard_machine.earned_points == 0.0
    assert validator_machine.earned_points == 1.0
    assert guard_machine.checkpoint_families == validator_machine.checkpoint_families
    assert guard_machine.determinate_checkpoint_ids == ("aeo.schema_expected_for_type",)
    assert validator_machine.determinate_checkpoint_ids == (
        "aeo.schema_matches_content",
        "aeo.schema_recommended_present",
        "aeo.schema_required_valid",
    )
    assert guard.aeo_readiness_score == 0.0
    assert validators.aeo_readiness_score == 100.0
    assert guard.aeo_measurement_coverage == validators.aeo_measurement_coverage == 0.25
    assert (
        guard.aeo_measurement_state
        == validators.aeo_measurement_state
        == MEASUREMENT_STATE_LIMITED
    )


def test_other_has_no_aeo_profile_or_scalar_even_with_aeo_observations() -> None:
    page_scores = score_analysis(
        [
            _aeo(
                "technical.indexable",
                "satisfied",
                "indexability",
                "crawlability",
            )
        ],
        page_kind="other",
    )
    analysis = AnalysisMeasurementInput(
        analysis_id="other",
        page_kind="other",
        expected_family_profile=page_scores.expected_checkpoint_profile,
    )
    aggregate = aggregate_measurements(
        [analysis],
        [
            RuleMeasurementInput(
                analysis_id=analysis.analysis_id,
                page_kind=analysis.page_kind,
                rule_id="technical.indexable",
                scope=RULE_SCOPE_PAGE,
                outcome="satisfied",
                expected=True,
                score_roles=(SCORE_ROLE_AEO,),
                weight=1.0,
                severity="critical",
                checkpoint_family="indexability",
                readiness_dimension="crawlability",
                readiness_weight=1.0,
            )
        ],
    )

    assert page_scores.expected_checkpoint_profile == ()
    assert page_scores.aeo_readiness_score is None
    assert page_scores.aeo_measurement_coverage is None
    assert page_scores.aeo_measurement_state == MEASUREMENT_STATE_NOT_MEASURED
    assert page_scores.aeo_measurement_reason == "page_purpose_unresolved"
    assert aggregate.aeo_readiness_score is None
    assert aggregate.aeo_measurement_coverage is None
    assert aggregate.aeo_measurement_state == MEASUREMENT_STATE_NOT_MEASURED
    for dimension in aggregate.readiness_dimensions:
        assert dimension["score"] is None
        assert dimension["coverage"] is None
        assert (
            dimension["dimension_measurement_state"] == MEASUREMENT_STATE_NOT_MEASURED
        )
        assert dimension["expected_points"] == 0.0


def _analysis(
    analysis_id: str,
    page_kind: str,
    *,
    crawl_context: dict[str, object] | None = None,
) -> AnalysisMeasurementInput:
    scores = score_analysis(
        [],
        page_kind=page_kind,
        crawl_context=crawl_context,
    )
    return AnalysisMeasurementInput(
        analysis_id=analysis_id,
        page_kind=page_kind,
        expected_family_profile=scores.expected_checkpoint_profile,
    )


def _analyses(
    kinds: list[str],
    *,
    crawl_context: dict[str, object] | None = None,
) -> list[AnalysisMeasurementInput]:
    return [
        _analysis(str(index), kind, crawl_context=crawl_context)
        for index, kind in enumerate(kinds)
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("family_id", "retired_family"),
        ("dimension_id", "authority"),
        ("status", "retired_status"),
        ("scope", "site"),
    ),
)
def test_persisted_family_profile_rejects_invalid_contract_fields(
    field: str, value: str
) -> None:
    analysis = _analysis("invalid-profile", "article")
    profile = [dict(row) for row in analysis.expected_family_profile]
    profile[0][field] = value
    invalid = AnalysisMeasurementInput(
        analysis_id=analysis.analysis_id,
        page_kind=analysis.page_kind,
        expected_family_profile=tuple(profile),
    )

    with pytest.raises(ValueError):
        aggregate_measurements([invalid], [])


def _aeo_input(
    analysis: AnalysisMeasurementInput,
    checkpoint_id: str,
    outcome: str,
) -> RuleMeasurementInput:
    family = next(
        row
        for row in analysis.expected_family_profile
        if any(
            checkpoint["checkpoint_id"] == checkpoint_id
            for checkpoint in row["checkpoints"]
        )
    )
    checkpoint = next(
        checkpoint
        for checkpoint in family["checkpoints"]
        if checkpoint["checkpoint_id"] == checkpoint_id
    )
    return RuleMeasurementInput(
        analysis_id=analysis.analysis_id,
        page_kind=analysis.page_kind,
        rule_id=checkpoint_id,
        scope=family["scope"],
        outcome=outcome,
        expected=True,
        score_roles=(SCORE_ROLE_AEO,),
        weight=1.0,
        severity="medium",
        checkpoint_family=family["family_id"],
        readiness_dimension=family["dimension_id"],
        readiness_weight=checkpoint["internal_weight"],
    )


def _technical_input(
    analysis: AnalysisMeasurementInput,
    *,
    rule_id: str,
    outcome: str,
) -> RuleMeasurementInput:
    return RuleMeasurementInput(
        analysis_id=analysis.analysis_id,
        page_kind=analysis.page_kind,
        rule_id=rule_id,
        scope=RULE_SCOPE_PAGE,
        outcome=outcome,
        expected=True,
        score_roles=(SCORE_ROLE_WEB_FUNDAMENTALS,),
        weight=1.0,
        severity="medium",
        checkpoint_family="",
        readiness_dimension="",
        readiness_weight=0.0,
    )


def _dimension(aggregate, key: str) -> dict:
    return next(row for row in aggregate.readiness_dimensions if row["key"] == key)


def _family_observations(
    analyses: list[AnalysisMeasurementInput],
    checkpoint_id: str,
    outcomes: list[str],
) -> list[RuleMeasurementInput]:
    return [
        _aeo_input(analysis, checkpoint_id, outcome)
        for analysis, outcome in zip(analyses, outcomes, strict=True)
    ]


def test_repeating_page_kind_cohort_preserves_mean_and_equal_macro_vote() -> None:
    baseline_analyses = _analyses(["article", "article", "product"])
    baseline_rules = _family_observations(
        baseline_analyses,
        "aeo.heading_hierarchy",
        ["missing", "satisfied", "satisfied"],
    )
    repeated_analyses = _analyses(
        ["article", "article"] * 5 + ["product"],
    )
    repeated_rules = _family_observations(
        repeated_analyses,
        "aeo.heading_hierarchy",
        ["missing", "satisfied"] * 5 + ["satisfied"],
    )

    baseline = aggregate_measurements(baseline_analyses, baseline_rules)
    repeated = aggregate_measurements(repeated_analyses, repeated_rules)
    baseline_structure = _dimension(baseline, "structure")
    repeated_structure = _dimension(repeated, "structure")

    assert baseline_structure == repeated_structure
    assert baseline_structure["score"] == 75.0
    assert baseline_structure["coverage"] == 1.0
    assert (
        baseline_structure["dimension_measurement_state"] == MEASUREMENT_STATE_MEASURED
    )
    assert baseline_structure["earned_points"] == 0.75
    assert baseline_structure["determinate_points"] == 1.0
    assert baseline_structure["expected_points"] == 1.0
    assert baseline.aeo_readiness_score == repeated.aeo_readiness_score == 75.0
    assert (
        baseline.aeo_measurement_coverage == repeated.aeo_measurement_coverage == 0.15
    )
    assert (
        baseline.aeo_measurement_state
        == repeated.aeo_measurement_state
        == MEASUREMENT_STATE_LIMITED
    )


def test_distinct_page_changes_only_its_kind_mean_not_macro_weight() -> None:
    baseline_analyses = _analyses(["article", "product"])
    baseline = aggregate_measurements(
        baseline_analyses,
        _family_observations(
            baseline_analyses,
            "aeo.heading_hierarchy",
            ["missing", "satisfied"],
        ),
    )
    expanded_analyses = _analyses(["article", "article", "product"])
    expanded = aggregate_measurements(
        expanded_analyses,
        _family_observations(
            expanded_analyses,
            "aeo.heading_hierarchy",
            ["missing", "satisfied", "satisfied"],
        ),
    )

    baseline_structure = _dimension(baseline, "structure")
    expanded_structure = _dimension(expanded, "structure")

    assert baseline_structure["score"] == 50.0
    assert expanded_structure["score"] == 75.0
    assert baseline_structure["coverage"] == expanded_structure["coverage"] == 1.0
    assert (
        baseline_structure["dimension_measurement_state"]
        == expanded_structure["dimension_measurement_state"]
        == MEASUREMENT_STATE_MEASURED
    )
    assert (
        baseline_structure["expected_points"]
        == expanded_structure["expected_points"]
        == 1.0
    )
    assert (
        baseline_structure["determinate_points"]
        == expanded_structure["determinate_points"]
        == 1.0
    )
    assert baseline.aeo_readiness_score == 50.0
    assert expanded.aeo_readiness_score == 75.0
    assert (
        baseline.aeo_measurement_coverage == expanded.aeo_measurement_coverage == 0.15
    )
    assert (
        baseline.aeo_measurement_state
        == expanded.aeo_measurement_state
        == MEASUREMENT_STATE_LIMITED
    )


def test_missing_and_unknown_split_quality_from_coverage() -> None:
    analysis = _analysis("article", "article")
    missing = aggregate_measurements(
        [analysis],
        [_aeo_input(analysis, "aeo.visible_attribution", "missing")],
    )
    unknown = aggregate_measurements(
        [analysis],
        [_aeo_input(analysis, "aeo.visible_attribution", "unknown")],
    )

    missing_authority = _dimension(missing, "authority")
    unknown_authority = _dimension(unknown, "authority")

    assert missing_authority["score"] == 0.0
    assert missing_authority["coverage"] == 0.5
    assert missing_authority["dimension_measurement_state"] == MEASUREMENT_STATE_LIMITED
    assert missing_authority["earned_points"] == 0.0
    assert missing_authority["determinate_points"] == 0.5
    assert missing_authority["expected_points"] == 1.0
    assert unknown_authority["score"] is None
    assert unknown_authority["coverage"] == 0.0
    assert (
        unknown_authority["dimension_measurement_state"]
        == MEASUREMENT_STATE_NOT_MEASURED
    )
    assert unknown_authority["earned_points"] == 0.0
    assert unknown_authority["determinate_points"] == 0.0
    assert unknown_authority["expected_points"] == 1.0
    assert missing.aeo_readiness_score == 0.0
    assert missing.aeo_measurement_coverage == 0.0625
    assert missing.aeo_measurement_state == MEASUREMENT_STATE_LIMITED
    assert unknown.aeo_readiness_score is None
    assert unknown.aeo_measurement_coverage == 0.0
    assert unknown.aeo_measurement_state == MEASUREMENT_STATE_NOT_MEASURED


def test_readiness_is_measured_only_when_every_expected_point_is_determinate() -> None:
    context = {"is_site_root": True}
    profile = score_analysis(
        [],
        page_kind="article",
        crawl_context=context,
    ).expected_checkpoint_profile
    checkpoints = sorted(
        (
            (
                row["family_id"],
                row["dimension_id"],
                checkpoint["checkpoint_id"],
                float(row["budget"]) * float(checkpoint["internal_weight"]),
            )
            for row in profile
            if row["status"] == "measured" and row["evaluation_scope"]
            for checkpoint in row["checkpoints"]
        ),
        key=lambda row: row[3],
    )
    complete = [
        _aeo(checkpoint_id, "satisfied", family_id, dimension_id)
        for family_id, dimension_id, checkpoint_id, _weight in checkpoints
    ]
    incomplete = [
        _aeo(
            checkpoint_id,
            "unknown" if index == 0 else "satisfied",
            family_id,
            dimension_id,
        )
        for index, (family_id, dimension_id, checkpoint_id, _weight) in enumerate(
            checkpoints
        )
    ]

    complete_scores = score_analysis(
        complete,
        page_kind="article",
        crawl_context=context,
    )
    incomplete_scores = score_analysis(
        incomplete,
        page_kind="article",
        crawl_context=context,
    )

    assert complete_scores.aeo_measurement_coverage == 1.0
    assert complete_scores.aeo_measurement_state == MEASUREMENT_STATE_MEASURED
    assert 0.8 <= (incomplete_scores.aeo_measurement_coverage or 0.0) < 1.0
    assert incomplete_scores.aeo_measurement_state == MEASUREMENT_STATE_LIMITED


def test_site_scoped_family_evidence_is_not_multiplied_by_page_count() -> None:
    single_analysis = _analyses(
        ["article"],
        crawl_context={"is_site_root": True},
    )
    repeated_analyses = _analyses(
        ["article"] * 50,
        crawl_context={"is_site_root": True},
    )

    def site_identity(
        analyses: list[AnalysisMeasurementInput],
    ) -> list[RuleMeasurementInput]:
        return [
            observation
            for analysis in analyses
            for observation in (
                _aeo_input(analysis, "aeo.organization_identity", "satisfied"),
                _aeo_input(analysis, "aeo.trust_path_present", "missing"),
            )
        ]

    single = aggregate_measurements(
        single_analysis,
        site_identity(single_analysis),
    )
    repeated = aggregate_measurements(
        repeated_analyses,
        site_identity(repeated_analyses),
    )
    single_authority = _dimension(single, "authority")
    repeated_authority = _dimension(repeated, "authority")

    assert single_authority == repeated_authority
    assert single_authority["score"] == 50.0
    assert single_authority["coverage"] == 0.5
    assert single_authority["dimension_measurement_state"] == MEASUREMENT_STATE_LIMITED
    assert single_authority["earned_points"] == 0.25
    assert single_authority["determinate_points"] == 0.5
    assert single_authority["expected_points"] == 1.0
    assert single_authority["checkpoint_families"] == ["site_identity"]
    assert single_authority["determinate_checkpoint_ids"] == [
        "aeo.organization_identity",
        "aeo.trust_path_present",
    ]
    assert single.aeo_readiness_score == repeated.aeo_readiness_score == 50.0
    assert (
        single.aeo_measurement_coverage == repeated.aeo_measurement_coverage == 0.0625
    )
    assert (
        single.aeo_measurement_state
        == repeated.aeo_measurement_state
        == MEASUREMENT_STATE_LIMITED
    )


def test_site_family_uses_root_evidence_when_root_page_kind_is_other() -> None:
    article = _analysis(
        "article",
        "article",
        crawl_context={"is_site_root": False},
    )
    root = _analysis(
        "root",
        "other",
        crawl_context={"is_site_root": True},
    )

    def root_observation(checkpoint_id: str, outcome: str) -> RuleMeasurementInput:
        template = _aeo_input(article, checkpoint_id, outcome)
        return RuleMeasurementInput(
            **{
                **template.__dict__,
                "analysis_id": root.analysis_id,
                "page_kind": root.page_kind,
            }
        )

    aggregate = aggregate_measurements(
        [article, root],
        [
            root_observation("aeo.organization_identity", "satisfied"),
            root_observation("aeo.trust_path_present", "missing"),
        ],
    )
    authority = _dimension(aggregate, "authority")

    assert "site_identity" in authority["checkpoint_families"]
    assert authority["determinate_checkpoint_ids"] == [
        "aeo.organization_identity",
        "aeo.trust_path_present",
    ]


def test_normalized_result_rejects_non_numeric_json_values() -> None:
    analysis = _analysis("article", "article")
    invalid = _technical_input(
        analysis,
        rule_id="technical.title_present",
        outcome="satisfied",
    )
    invalid = RuleMeasurementInput(
        **{
            **invalid.__dict__,
            "normalized_score": "1.0",
            "normalized_coverage": 1.0,
        }
    )

    try:
        aggregate_measurements([analysis], [invalid])
    except ValueError as error:
        assert str(error) == (
            "Rule technical.title_present has an invalid normalized result"
        )
    else:
        raise AssertionError("non-numeric normalized result was accepted")
