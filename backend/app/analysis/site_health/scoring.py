"""Deterministic PR2 Technical Integrity and AEO Readiness measurement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.analysis.site_health.rules import RuleEvaluation
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    RULE_ID_TECHNICAL_INDEXABLE,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    SCORING_VERSION,
    SEVERITY_CRITICAL,
)
from app.core.config.site_health_measurement import (
    AEO_MEASURED_MIN_CHECKPOINTS,
    AEO_MEASURED_MIN_COVERAGE,
    AEO_MEASURED_MIN_DIMENSIONS,
    AEO_MEASURED_MIN_FAMILIES,
    DIMENSION_APPLICABLE,
    DIMENSION_NOT_APPLICABLE,
    MEASURED_AT_SITE_SCOPE_REASON,
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_MEASURED,
    PAGE_KIND_ROLLUP_WEIGHTS,
    READINESS_DIMENSION_WEIGHTS,
    TECHNICAL_MEASURED_MIN_COVERAGE,
    expected_checkpoints,
    relevant_dimensions,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_PAGE,
    RULE_SCOPE_SITE,
    SCORE_ROLE_AEO,
    SCORE_ROLE_TECHNICAL,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER, PAGE_KINDS

_DETERMINATE = frozenset(
    {RULE_OUTCOME_SATISFIED, RULE_OUTCOME_PARTIAL, RULE_OUTCOME_MISSING}
)


@dataclass(frozen=True)
class DimensionMeasurement:
    key: str
    applicability: str
    measurement_state: str
    score: float | None
    coverage: float | None
    earned_points: float
    determinate_points: float
    expected_points: float
    determinate_checkpoint_ids: tuple[str, ...]
    checkpoint_families: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": AEO_READINESS_DIMENSION_LABELS[self.key],
            "description": AEO_READINESS_DIMENSION_DESCRIPTIONS[self.key],
            "dimension_applicability": self.applicability,
            "dimension_measurement_state": self.measurement_state,
            "score": self.score,
            "coverage": self.coverage,
            "earned_points": self.earned_points,
            "determinate_points": self.determinate_points,
            "expected_points": self.expected_points,
            "determinate_checkpoint_ids": list(self.determinate_checkpoint_ids),
            "checkpoint_families": list(self.checkpoint_families),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class AnalysisScores:
    technical_integrity_score: float | None
    technical_integrity_coverage: float | None
    technical_integrity_state: str
    technical_earned_weight: float
    technical_determinate_weight: float
    technical_expected_weight: float
    technical_critical_complete: bool
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: str
    expected_checkpoint_profile: tuple[dict, ...]
    readiness_dimensions: tuple[DimensionMeasurement, ...]
    main_content_indexable: bool | None
    scoring_version: str = SCORING_VERSION


def _round_score(value: float) -> float:
    return round(value, 1)


def _round_coverage(value: float) -> float:
    return round(value, 4)


def _credit(outcome: str) -> float:
    if outcome == RULE_OUTCOME_SATISFIED:
        return 1.0
    if outcome == RULE_OUTCOME_PARTIAL:
        return 0.5
    return 0.0


def _profile_rows(evaluations: list[RuleEvaluation], role: str) -> list[RuleEvaluation]:
    return [
        row
        for row in evaluations
        if row.expected_profile_membership
        and row.scope == RULE_SCOPE_PAGE
        and role in row.score_roles
    ]


def _determinate_rows(rows: list[RuleEvaluation]) -> list[RuleEvaluation]:
    return [row for row in rows if row.outcome in _DETERMINATE]


def _rule_weight(rows: list[RuleEvaluation]) -> float:
    return sum(max(0.0, float(row.weight)) for row in rows)


def _technical_earned(rows: list[RuleEvaluation]) -> float:
    return _rule_weight([row for row in rows if row.outcome == RULE_OUTCOME_SATISFIED])


def _ratio(numerator: float, denominator: float, *, score: bool) -> float | None:
    if denominator <= 0:
        return None
    value = numerator / denominator
    return _round_score(100.0 * value) if score else _round_coverage(value)


def _technical_state(
    *, has_expected: bool, has_determinate: bool, coverage: float | None, complete: bool
) -> str:
    if not has_expected or not has_determinate:
        return MEASUREMENT_STATE_NOT_MEASURED
    if (
        coverage is not None
        and coverage >= TECHNICAL_MEASURED_MIN_COVERAGE
        and complete
    ):
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


def _technical_measurement(
    evaluations: list[RuleEvaluation],
) -> tuple[float | None, float | None, str, float, float, float, bool]:
    expected = _profile_rows(evaluations, SCORE_ROLE_TECHNICAL)
    determinate = _determinate_rows(expected)
    expected_weight = _rule_weight(expected)
    determinate_weight = _rule_weight(determinate)
    earned = _technical_earned(determinate)
    score = _ratio(earned, determinate_weight, score=True)
    coverage = _ratio(determinate_weight, expected_weight, score=False)
    critical_complete = all(
        row.outcome in _DETERMINATE
        for row in expected
        if row.severity == SEVERITY_CRITICAL
    )
    state = _technical_state(
        has_expected=bool(expected),
        has_determinate=bool(determinate),
        coverage=coverage,
        complete=critical_complete,
    )
    return (
        score,
        coverage,
        state,
        round(earned, 4),
        round(determinate_weight, 4),
        round(expected_weight, 4),
        critical_complete,
    )


def _dimension_applicability(key: str, *, relevant: tuple[str, ...]) -> tuple[str, str]:
    return (
        (DIMENSION_APPLICABLE, "")
        if key in relevant
        else (DIMENSION_NOT_APPLICABLE, "dimension_determinately_irrelevant")
    )


def _empty_dimension(key: str, applicability: str, reason: str) -> DimensionMeasurement:
    return DimensionMeasurement(
        key=key,
        applicability=applicability,
        measurement_state=MEASUREMENT_STATE_NOT_MEASURED,
        score=None,
        coverage=None if applicability == DIMENSION_NOT_APPLICABLE else 0.0,
        earned_points=0.0,
        determinate_points=0.0,
        expected_points=0.0,
        determinate_checkpoint_ids=(),
        checkpoint_families=(),
        reason=reason,
    )


def _dimension_expected(
    evaluations: list[RuleEvaluation], key: str
) -> list[RuleEvaluation]:
    return [
        row
        for row in _profile_rows(evaluations, SCORE_ROLE_AEO)
        if row.readiness_dimension == key
    ]


def _readiness_points(
    expected: list[RuleEvaluation], determinate: list[RuleEvaluation]
) -> tuple[float, float, float]:
    expected_points = sum(float(row.readiness_weight) for row in expected)
    determinate_points = sum(float(row.readiness_weight) for row in determinate)
    earned = sum(
        float(row.readiness_weight) * _credit(row.outcome) for row in determinate
    )
    return earned, determinate_points, expected_points


def _readiness_state(score: float | None, coverage: float) -> str:
    if score is not None and coverage >= AEO_MEASURED_MIN_COVERAGE:
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


def _checkpoint_ids(rows: list[RuleEvaluation]) -> tuple[str, ...]:
    return tuple(sorted({row.rule_id for row in rows}))


def _checkpoint_families(rows: list[RuleEvaluation]) -> tuple[str, ...]:
    return tuple(
        sorted({row.checkpoint_family for row in rows if row.checkpoint_family})
    )


def _dimension_measurement(
    key: str,
    *,
    evaluations: list[RuleEvaluation],
    expected_ids: tuple[str, ...],
    relevant: tuple[str, ...],
) -> DimensionMeasurement:
    applicability, reason = _dimension_applicability(key, relevant=relevant)
    if applicability == DIMENSION_NOT_APPLICABLE:
        return _empty_dimension(key, applicability, reason)
    expected = _dimension_expected(evaluations, key)
    if not expected:
        site_scoped = any(
            SITE_HEALTH_RULES_BY_ID[checkpoint_id].scope == RULE_SCOPE_SITE
            and SITE_HEALTH_RULES_BY_ID[checkpoint_id].readiness_dimension == key
            for checkpoint_id in expected_ids
        )
        bounded_reason = (
            MEASURED_AT_SITE_SCOPE_REASON
            if site_scoped
            else "no_expected_checkpoint_evaluator"
        )
        return _empty_dimension(key, applicability, bounded_reason)
    determinate = _determinate_rows(expected)
    earned, determinate_points, expected_points = _readiness_points(
        expected, determinate
    )
    score = _ratio(earned, determinate_points, score=True)
    coverage = _ratio(determinate_points, expected_points, score=False) or 0.0
    state = _readiness_state(score, coverage)
    return DimensionMeasurement(
        key=key,
        applicability=applicability,
        measurement_state=state,
        score=score,
        coverage=coverage,
        earned_points=round(earned, 4),
        determinate_points=round(determinate_points, 4),
        expected_points=round(expected_points, 4),
        determinate_checkpoint_ids=_checkpoint_ids(determinate),
        checkpoint_families=_checkpoint_families(determinate),
        reason=reason,
    )


def _breadth_sets(
    dimensions: tuple[DimensionMeasurement, ...],
) -> tuple[set[str], set[str], set[str]]:
    checkpoints = {
        checkpoint
        for row in dimensions
        for checkpoint in row.determinate_checkpoint_ids
    }
    families = {family for row in dimensions for family in row.checkpoint_families}
    measured_dimensions = {row.key for row in dimensions if row.determinate_points > 0}
    return checkpoints, families, measured_dimensions


def _aeo_state(
    *,
    coverage: float | None,
    checkpoints: set[str],
    families: set[str],
    measured_dimensions: set[str],
) -> str:
    if not checkpoints:
        return MEASUREMENT_STATE_NOT_MEASURED
    sufficient = (
        coverage is not None
        and coverage >= AEO_MEASURED_MIN_COVERAGE
        and len(checkpoints) >= AEO_MEASURED_MIN_CHECKPOINTS
        and len(families) >= AEO_MEASURED_MIN_FAMILIES
        and len(measured_dimensions) >= AEO_MEASURED_MIN_DIMENSIONS
        and RULE_ID_TECHNICAL_INDEXABLE in checkpoints
    )
    return MEASUREMENT_STATE_MEASURED if sufficient else MEASUREMENT_STATE_LIMITED


def _overall_aeo(
    dimensions: tuple[DimensionMeasurement, ...],
    *,
    allow_measured: bool = True,
) -> tuple[float | None, float | None, str]:
    expected = [
        row
        for row in dimensions
        if row.applicability != DIMENSION_NOT_APPLICABLE
        and row.reason != MEASURED_AT_SITE_SCOPE_REASON
    ]
    expected_weight = sum(READINESS_DIMENSION_WEIGHTS[row.key] for row in expected)
    measured = _dimension_contributions(expected)
    raw_score, measured_weight = _weighted_average(measured)
    score = None if raw_score is None else _round_score(raw_score)
    coverage = (
        None
        if expected_weight <= 0
        else _round_coverage(measured_weight / expected_weight)
    )
    checkpoints, families, measured_dimensions = _breadth_sets(dimensions)
    state = _aeo_state(
        coverage=coverage,
        checkpoints=checkpoints,
        families=families,
        measured_dimensions=measured_dimensions,
    )
    if state == MEASUREMENT_STATE_MEASURED and not allow_measured:
        state = MEASUREMENT_STATE_LIMITED
    return score, coverage, state


def score_analysis(
    evaluations: Iterable[RuleEvaluation],
    *,
    page_kind: str = "",
    page_traits: Iterable[str] = (),
    crawl_context: Mapping[str, object] | None = None,
) -> AnalysisScores:
    rows = list(evaluations)
    effective_page_kind = page_kind if page_kind in PAGE_KINDS else PAGE_KIND_OTHER
    effective_traits = tuple(page_traits)
    expected_ids = expected_checkpoints(
        effective_page_kind, effective_traits, crawl_context
    )
    relevant = relevant_dimensions(effective_page_kind, effective_traits, crawl_context)
    (
        technical_score,
        technical_coverage,
        technical_state,
        technical_earned,
        technical_determinate,
        technical_expected,
        technical_critical_complete,
    ) = _technical_measurement(rows)
    dimensions = tuple(
        _dimension_measurement(
            key,
            evaluations=rows,
            expected_ids=expected_ids,
            relevant=relevant,
        )
        for key in AEO_READINESS_DIMENSIONS
    )
    aeo_score, aeo_coverage, aeo_state = _overall_aeo(
        dimensions, allow_measured=effective_page_kind != PAGE_KIND_OTHER
    )
    profile = tuple(
        {
            "checkpoint_id": row.rule_id,
            "score_roles": list(row.score_roles),
            "checkpoint_family": row.checkpoint_family or None,
            "readiness_dimension": row.readiness_dimension or None,
            "readiness_weight": float(row.readiness_weight),
        }
        for row in rows
        if row.expected_profile_membership
    )
    return AnalysisScores(
        technical_integrity_score=technical_score,
        technical_integrity_coverage=technical_coverage,
        technical_integrity_state=technical_state,
        technical_earned_weight=technical_earned,
        technical_determinate_weight=technical_determinate,
        technical_expected_weight=technical_expected,
        technical_critical_complete=technical_critical_complete,
        aeo_readiness_score=aeo_score,
        aeo_measurement_coverage=aeo_coverage,
        aeo_measurement_state=aeo_state,
        expected_checkpoint_profile=profile,
        readiness_dimensions=dimensions,
        main_content_indexable=next(
            (
                row.outcome == RULE_OUTCOME_SATISFIED
                for row in rows
                if row.rule_id == RULE_ID_TECHNICAL_INDEXABLE
                and row.outcome in _DETERMINATE
            ),
            None,
        ),
    )


@dataclass(frozen=True)
class AnalysisMeasurementInput:
    analysis_id: str
    page_kind: str
    page_traits: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleMeasurementInput:
    analysis_id: str
    page_kind: str
    rule_id: str
    scope: str
    outcome: str
    expected: bool
    score_roles: tuple[str, ...]
    weight: float
    severity: str
    checkpoint_family: str
    readiness_dimension: str
    readiness_weight: float
    normalized_score: float | None = None
    normalized_coverage: float | None = None


@dataclass(frozen=True)
class _NormalizedRule:
    rule_id: str
    score: float | None
    coverage: float
    score_roles: tuple[str, ...]
    weight: float
    severity: str
    checkpoint_family: str
    readiness_dimension: str
    readiness_weight: float


@dataclass(frozen=True)
class AggregateMeasurements:
    technical_integrity_score: float | None
    technical_integrity_coverage: float | None
    technical_integrity_state: str
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: str
    readiness_dimensions: tuple[dict, ...]
    analyzed_url_count: int
    scoring_version: str = SCORING_VERSION


def _mean_credit(rows: list[RuleMeasurementInput]) -> float | None:
    determinate = [row for row in rows if row.outcome in _DETERMINATE]
    if not determinate:
        return None
    return sum(_credit(row.outcome) for row in determinate) / len(determinate)


def _weighted_average(values: list[tuple[float, float]]) -> tuple[float | None, float]:
    """Return the weighted value and absorbed participation weight."""
    total_weight = sum(weight for _, weight in values)
    if total_weight <= 0:
        return None, 0.0
    return (
        sum(value * weight for value, weight in values) / total_weight,
        total_weight,
    )


def _dimension_contributions(
    rows: list[DimensionMeasurement],
) -> list[tuple[float, float]]:
    return [
        (
            float(row.score),
            READINESS_DIMENSION_WEIGHTS[row.key] * float(row.coverage or 0.0),
        )
        for row in rows
        if row.score is not None and float(row.coverage or 0.0) > 0
    ]


def _page_rule_result(
    rows: list[RuleMeasurementInput],
) -> tuple[float | None, float]:
    by_kind: dict[str, list[RuleMeasurementInput]] = {}
    for row in rows:
        by_kind.setdefault(row.page_kind, []).append(row)
    expected_weight = sum(PAGE_KIND_ROLLUP_WEIGHTS.get(kind, 1.0) for kind in by_kind)
    measured: list[tuple[float, float]] = []
    covered_weight = 0.0
    for kind, kind_rows in by_kind.items():
        kind_weight = PAGE_KIND_ROLLUP_WEIGHTS.get(kind, 1.0)
        determinate = [row for row in kind_rows if row.outcome in _DETERMINATE]
        covered_weight += kind_weight * len(determinate) / len(kind_rows)
        score = _mean_credit(kind_rows)
        if score is not None:
            measured.append((kind_weight, score))
    measured_weight = sum(weight for weight, _ in measured)
    score = (
        None
        if measured_weight <= 0
        else sum(weight * value for weight, value in measured) / measured_weight
    )
    coverage = 0.0 if expected_weight <= 0 else covered_weight / expected_weight
    return score, coverage


def _site_rule_result(
    rows: list[RuleMeasurementInput],
) -> tuple[float | None, float]:
    # A site rule represents one entity. Repeated identical footer/root
    # observations are duplicates, never additional weight.
    determinate_outcomes = {row.outcome for row in rows if row.outcome in _DETERMINATE}
    if not determinate_outcomes:
        return None, 0.0
    if len(determinate_outcomes) > 1:
        return None, 0.0
    return _credit(next(iter(determinate_outcomes))), 1.0


def _entity_set_rule_result(
    rows: list[RuleMeasurementInput],
) -> tuple[float | None, float]:
    determinate = [row for row in rows if row.outcome in _DETERMINATE]
    coverage = len(determinate) / len(rows)
    return _mean_credit(rows), coverage


def _normalized_override(
    rule_id: str, observations: list[RuleMeasurementInput]
) -> tuple[float, float] | None:
    values = {
        (row.normalized_score, row.normalized_coverage)
        for row in observations
        if row.normalized_score is not None and row.normalized_coverage is not None
    }
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"Rule {rule_id} has conflicting normalized results")
    score, coverage = next(iter(values))
    if (
        score is None
        or coverage is None
        or not (0.0 <= score <= 1.0 and 0.0 <= coverage <= 1.0)
    ):
        raise ValueError(f"Rule {rule_id} has an invalid normalized result")
    return float(score), float(coverage)


def _rule_result(
    rule_id: str, observations: list[RuleMeasurementInput]
) -> tuple[float | None, float]:
    scopes = {row.scope for row in observations}
    if len(scopes) != 1:
        raise ValueError(f"Rule {rule_id} has inconsistent persisted scopes")
    override = _normalized_override(rule_id, observations)
    if override is not None:
        return override
    scope = next(iter(scopes))
    if scope == RULE_SCOPE_PAGE:
        return _page_rule_result(observations)
    if scope == RULE_SCOPE_SITE:
        return _site_rule_result(observations)
    return _entity_set_rule_result(observations)


def _normalized_rule(
    rule_id: str, observations: list[RuleMeasurementInput]
) -> _NormalizedRule:
    score, coverage = _rule_result(rule_id, observations)
    first = observations[0]
    return _NormalizedRule(
        rule_id=rule_id,
        score=score,
        coverage=coverage,
        score_roles=tuple(
            sorted({role for row in observations for role in row.score_roles})
        ),
        weight=max(0.0, *(row.weight for row in observations)),
        severity=first.severity,
        checkpoint_family=first.checkpoint_family,
        readiness_dimension=first.readiness_dimension,
        readiness_weight=max(0.0, *(row.readiness_weight for row in observations)),
    )


def _normalize_rules(rows: list[RuleMeasurementInput]) -> list[_NormalizedRule]:
    grouped: dict[str, list[RuleMeasurementInput]] = {}
    for row in rows:
        if row.expected and row.score_roles:
            grouped.setdefault(row.rule_id, []).append(row)
    return [
        _normalized_rule(rule_id, observations)
        for rule_id, observations in grouped.items()
    ]


def _readiness_contributions(
    rules: list[_NormalizedRule],
) -> list[tuple[float, float]]:
    return [
        (float(rule.score), rule.readiness_weight * rule.coverage)
        for rule in rules
        if rule.score is not None and rule.coverage > 0
    ]


def _dimension_rules(key: str, rules: list[_NormalizedRule]) -> list[_NormalizedRule]:
    return [
        rule
        for rule in rules
        if SCORE_ROLE_AEO in rule.score_roles and rule.readiness_dimension == key
    ]


def _measured_rules(rules: list[_NormalizedRule]) -> list[_NormalizedRule]:
    return [rule for rule in rules if rule.score is not None and rule.coverage > 0]


def _normalized_rule_families(rules: list[_NormalizedRule]) -> tuple[str, ...]:
    return tuple(
        sorted({rule.checkpoint_family for rule in rules if rule.checkpoint_family})
    )


def _aggregate_dimension(
    key: str, rules: list[_NormalizedRule], *, relevant: frozenset[str]
) -> DimensionMeasurement:
    expected = _dimension_rules(key, rules)
    if not expected:
        if key in relevant:
            return _empty_dimension(
                key, DIMENSION_APPLICABLE, "no_expected_checkpoint_evaluator"
            )
        return _empty_dimension(
            key, DIMENSION_NOT_APPLICABLE, "dimension_determinately_irrelevant"
        )
    measured_rules = _measured_rules(expected)
    contributions = _readiness_contributions(expected)
    expected_weight = sum(rule.readiness_weight for rule in expected)
    normalized_score, measured_weight = _weighted_average(contributions)
    earned = sum(value * weight for value, weight in contributions)
    score = None if normalized_score is None else _round_score(100.0 * normalized_score)
    coverage = _ratio(measured_weight, expected_weight, score=False) or 0.0
    state = _readiness_state(score, coverage)
    return DimensionMeasurement(
        key=key,
        applicability=DIMENSION_APPLICABLE,
        measurement_state=(
            MEASUREMENT_STATE_NOT_MEASURED if measured_weight <= 0 else state
        ),
        score=score,
        coverage=coverage,
        earned_points=round(earned, 4),
        determinate_points=round(measured_weight, 4),
        expected_points=round(expected_weight, 4),
        determinate_checkpoint_ids=tuple(
            sorted(rule.rule_id for rule in measured_rules)
        ),
        checkpoint_families=_normalized_rule_families(measured_rules),
        reason="",
    )


def _aggregate_technical(
    rules: list[_NormalizedRule],
) -> tuple[float | None, float | None, str]:
    expected_rules = [
        rule for rule in rules if SCORE_ROLE_TECHNICAL in rule.score_roles
    ]
    contributions = [
        (float(rule.score), rule.weight * rule.coverage)
        for rule in expected_rules
        if rule.score is not None and rule.coverage > 0
    ]
    expected = sum(rule.weight for rule in expected_rules)
    normalized_score, determinate = _weighted_average(contributions)
    earned = 0.0 if normalized_score is None else normalized_score * determinate
    score = _ratio(earned, determinate, score=True)
    coverage = _ratio(determinate, expected, score=False)
    critical_complete = all(
        rule.coverage >= 1.0 and rule.score is not None
        for rule in expected_rules
        if rule.severity == SEVERITY_CRITICAL
    )
    state = _technical_state(
        has_expected=expected > 0,
        has_determinate=determinate > 0,
        coverage=coverage,
        complete=critical_complete,
    )
    return score, coverage, state


def aggregate_measurements(
    inputs: Iterable[AnalysisMeasurementInput],
    rule_inputs: Iterable[RuleMeasurementInput],
) -> AggregateMeasurements:
    rows = list(inputs)
    rules = _normalize_rules(list(rule_inputs))
    aggregate_relevance = frozenset(
        dimension
        for row in rows
        for dimension in relevant_dimensions(row.page_kind, row.page_traits)
    )
    dimensions = tuple(
        _aggregate_dimension(key, rules, relevant=aggregate_relevance)
        for key in AEO_READINESS_DIMENSIONS
    )
    technical_score, technical_coverage, technical_state = _aggregate_technical(rules)
    aeo_score, aeo_coverage, aeo_state = _overall_aeo(
        dimensions,
        allow_measured=any(row.page_kind != PAGE_KIND_OTHER for row in rows),
    )
    return AggregateMeasurements(
        technical_integrity_score=technical_score,
        technical_integrity_coverage=technical_coverage,
        technical_integrity_state=technical_state,
        aeo_readiness_score=aeo_score,
        aeo_measurement_coverage=aeo_coverage,
        aeo_measurement_state=aeo_state,
        readiness_dimensions=tuple(item.to_dict() for item in dimensions),
        analyzed_url_count=len(rows),
    )
