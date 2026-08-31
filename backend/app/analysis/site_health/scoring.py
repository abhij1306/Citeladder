"""Deterministic PR2 Web Fundamentals and AEO Readiness measurement."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.analysis.site_health.rules import RuleEvaluation
from app.analysis.site_health.web_fundamentals_scoring import (
    aggregate_web_fundamentals,
    measurement_ratio,
    score_page_web_fundamentals,
)
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    RULE_ID_TECHNICAL_INDEXABLE,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
    SCORING_VERSION,
)
from app.core.config.site_health_measurement import (
    CAPABILITY_FAMILIES_BY_ID,
    DIMENSION_APPLICABLE,
    DIMENSION_NOT_APPLICABLE,
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_MEASURED,
    PAGE_KIND_ROLLUP_WEIGHTS,
    PROFILE_STATUS_MEASURED,
    PROFILE_STATUS_NOT_APPLICABLE,
    READINESS_DIMENSION_WEIGHTS,
    expected_checkpoint_expressions,
    profile_rows,
)
from app.core.config.site_health_rule_types import (
    RULE_SCOPE_PAGE,
    RULE_SCOPE_SITE,
)
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
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: str
    technical_earned_weight: float
    technical_determinate_weight: float
    technical_expected_weight: float
    technical_critical_complete: bool
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: str
    aeo_measurement_reason: str
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


@dataclass(frozen=True, slots=True)
class _FamilyResult:
    family_id: str
    dimension_id: str
    budget: float
    scope: str
    score: float | None
    coverage: float
    earned_points: float
    determinate_points: float
    expected_points: float
    determinate_checkpoint_ids: tuple[str, ...]


def _frozen_family_profile(
    page_kind: str,
    page_traits: tuple[str, ...],
    context: Mapping[str, object],
) -> tuple[dict, ...]:
    active_by_family: dict[str, list[dict]] = {}
    profile_context = {**context, "is_site_root": True}
    for family_id, checkpoint_id, internal_weight in expected_checkpoint_expressions(
        page_kind, page_traits, profile_context
    ):
        active_by_family.setdefault(family_id, []).append(
            {
                "checkpoint_id": checkpoint_id,
                "internal_weight": float(internal_weight),
            }
        )
    artifact = []
    for row in profile_rows(page_kind, page_traits, context):
        family = CAPABILITY_FAMILIES_BY_ID[row.family_id]
        artifact.append(
            {
                "family_id": row.family_id,
                "dimension_id": family.dimension_id,
                "budget": float(family.budget),
                "scope": family.scope,
                "status": row.status,
                "reason": row.reason,
                "trait_condition": row.trait_condition,
                "evaluation_scope": family.scope == RULE_SCOPE_PAGE
                or bool(context.get("is_site_root")),
                "checkpoints": active_by_family.get(row.family_id, []),
            }
        )
    return tuple(artifact)


def _checkpoint_outcome(
    checkpoint_id: str, evaluations: Iterable[RuleEvaluation | RuleMeasurementInput]
) -> str:
    outcomes = {
        row.outcome
        for row in evaluations
        if isinstance(row, RuleMeasurementInput)
        and row.rule_id == checkpoint_id
        and row.expected
    }
    if not outcomes:
        outcomes = {
            row.outcome
            for row in evaluations
            if isinstance(row, RuleEvaluation)
            and row.rule_id == checkpoint_id
            and row.expected_profile_membership
        }
    return next(iter(outcomes)) if len(outcomes) == 1 else ""


def _family_artifact_values(
    artifact: Mapping[str, object],
) -> tuple[str, str, str, float, list[object]]:
    family_id = str(artifact.get("family_id") or "")
    budget_value = artifact.get("budget")
    if not isinstance(budget_value, (int, float)) or isinstance(budget_value, bool):
        raise ValueError(f"Family budget must be numeric: {family_id}")
    checkpoints = artifact.get("checkpoints")
    if not isinstance(checkpoints, (list, tuple)):
        raise ValueError(f"Family checkpoints must be a sequence: {family_id}")
    return (
        family_id,
        str(artifact.get("dimension_id") or ""),
        str(artifact.get("scope") or ""),
        float(budget_value),
        list(checkpoints),
    )


def _checkpoint_tally(
    checkpoints: list[object],
    evaluations: Iterable[RuleEvaluation | RuleMeasurementInput],
) -> tuple[float, float, list[str]]:
    determinate = 0.0
    earned = 0.0
    determinate_ids: list[str] = []
    for checkpoint in checkpoints:
        if not isinstance(checkpoint, Mapping):
            continue
        checkpoint_id = str(checkpoint.get("checkpoint_id") or "")
        weight = float(checkpoint.get("internal_weight") or 0.0)
        outcome = _checkpoint_outcome(checkpoint_id, evaluations)
        if outcome not in _DETERMINATE:
            continue
        determinate += weight
        earned += weight * _credit(outcome)
        determinate_ids.append(checkpoint_id)
    return determinate, earned, determinate_ids


def _family_result(
    artifact: Mapping[str, object],
    evaluations: Iterable[RuleEvaluation | RuleMeasurementInput],
) -> _FamilyResult | None:
    if (
        not bool(artifact.get("evaluation_scope"))
        or artifact.get("status") == PROFILE_STATUS_NOT_APPLICABLE
    ):
        return None
    family_id, dimension_id, scope, budget, checkpoints = _family_artifact_values(
        artifact
    )
    expected_internal = sum(
        float(checkpoint.get("internal_weight") or 0.0)
        for checkpoint in checkpoints
        if isinstance(checkpoint, Mapping)
    )
    if artifact.get("status") == PROFILE_STATUS_MEASURED:
        if abs(expected_internal - 1.0) > 1e-9:
            raise ValueError(f"Family expression must normalize to one: {family_id}")
    else:
        expected_internal = 1.0
    determinate_internal, earned_internal, determinate_ids = _checkpoint_tally(
        checkpoints, evaluations
    )
    coverage = (
        0.0
        if expected_internal <= 0
        else min(1.0, determinate_internal / expected_internal)
    )
    score = (
        None if determinate_internal <= 0 else earned_internal / determinate_internal
    )
    return _FamilyResult(
        family_id=family_id,
        dimension_id=dimension_id,
        budget=budget,
        scope=scope,
        score=score,
        coverage=coverage,
        earned_points=budget * earned_internal,
        determinate_points=budget * determinate_internal,
        expected_points=budget,
        determinate_checkpoint_ids=tuple(sorted(determinate_ids)),
    )


def _family_results(
    profile: Iterable[Mapping[str, object]],
    evaluations: Iterable[RuleEvaluation | RuleMeasurementInput],
) -> tuple[_FamilyResult, ...]:
    rows = tuple(evaluations)
    return tuple(
        result
        for artifact in profile
        if (result := _family_result(artifact, rows)) is not None
    )


def _measured_family_evidence(
    families: list[_FamilyResult],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    measured = [
        family
        for family in families
        if family.determinate_points > 0 and family.score is not None
    ]
    checkpoint_ids = {
        checkpoint_id
        for family in measured
        for checkpoint_id in family.determinate_checkpoint_ids
    }
    return (
        tuple(sorted(checkpoint_ids)),
        tuple(sorted(family.family_id for family in measured)),
    )


def _dimension_measurement(
    key: str, *, families: tuple[_FamilyResult, ...]
) -> DimensionMeasurement:
    expected = [family for family in families if family.dimension_id == key]
    if not expected:
        return _empty_dimension(
            key, DIMENSION_NOT_APPLICABLE, "dimension_determinately_irrelevant"
        )
    expected_points = sum(family.expected_points for family in expected)
    determinate_points = sum(family.determinate_points for family in expected)
    earned_points = sum(family.earned_points for family in expected)
    score = measurement_ratio(earned_points, determinate_points, score=True)
    coverage = (
        measurement_ratio(determinate_points, expected_points, score=False) or 0.0
    )
    checkpoint_ids, family_ids = _measured_family_evidence(expected)
    return DimensionMeasurement(
        key=key,
        applicability=DIMENSION_APPLICABLE,
        measurement_state=(
            MEASUREMENT_STATE_NOT_MEASURED
            if determinate_points <= 0
            else _readiness_state(score, coverage)
        ),
        score=score,
        coverage=coverage,
        earned_points=round(earned_points, 4),
        determinate_points=round(determinate_points, 4),
        expected_points=round(expected_points, 4),
        determinate_checkpoint_ids=checkpoint_ids,
        checkpoint_families=family_ids,
        reason="",
    )


def _readiness_state(score: float | None, coverage: float) -> str:
    if score is not None and coverage >= 1.0:
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


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


def _aeo_state(*, coverage: float | None, checkpoints: set[str]) -> str:
    if not checkpoints:
        return MEASUREMENT_STATE_NOT_MEASURED
    if coverage is not None and coverage >= 1.0:
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


def _overall_aeo(
    dimensions: tuple[DimensionMeasurement, ...],
) -> tuple[float | None, float | None, str]:
    expected = [
        row for row in dimensions if row.applicability != DIMENSION_NOT_APPLICABLE
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
    checkpoints, _families, _measured_dimensions = _breadth_sets(dimensions)
    state = _aeo_state(coverage=coverage, checkpoints=checkpoints)
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
    context = crawl_context or {}
    frozen_profile = _frozen_family_profile(
        effective_page_kind, effective_traits, context
    )
    families = _family_results(frozen_profile, rows)
    (
        web_fundamentals_score,
        web_fundamentals_coverage,
        web_fundamentals_state,
        technical_earned,
        technical_determinate,
        technical_expected,
        technical_critical_complete,
    ) = score_page_web_fundamentals(rows)
    dimensions = tuple(
        _dimension_measurement(key, families=families)
        for key in AEO_READINESS_DIMENSIONS
    )
    aeo_score, aeo_coverage, aeo_state = _overall_aeo(dimensions)
    return AnalysisScores(
        web_fundamentals_score=web_fundamentals_score,
        web_fundamentals_coverage=web_fundamentals_coverage,
        web_fundamentals_state=web_fundamentals_state,
        technical_earned_weight=technical_earned,
        technical_determinate_weight=technical_determinate,
        technical_expected_weight=technical_expected,
        technical_critical_complete=technical_critical_complete,
        aeo_readiness_score=aeo_score,
        aeo_measurement_coverage=aeo_coverage,
        aeo_measurement_state=aeo_state,
        aeo_measurement_reason=(
            "page_purpose_unresolved" if effective_page_kind == PAGE_KIND_OTHER else ""
        ),
        expected_checkpoint_profile=frozen_profile,
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
    expected_family_profile: tuple[dict, ...] = ()


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


@dataclass(frozen=True)
class AggregateMeasurements:
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: str
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
        not isinstance(score, (int, float))
        or isinstance(score, bool)
        or not isinstance(coverage, (int, float))
        or isinstance(coverage, bool)
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


def _aggregate_checkpoint_ids(results: Iterable[_FamilyResult]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                checkpoint_id
                for result in results
                for checkpoint_id in result.determinate_checkpoint_ids
            }
        )
    )


def _kind_family_contribution(
    kind: str, results: list[_FamilyResult]
) -> tuple[float, float]:
    kind_weight = PAGE_KIND_ROLLUP_WEIGHTS.get(kind, 1.0)
    expected = sum(result.expected_points for result in results)
    determinate = sum(result.determinate_points for result in results)
    earned = sum(result.earned_points for result in results)
    coverage = 0.0 if expected <= 0 else determinate / expected
    score = 0.0 if determinate <= 0 else earned / determinate
    return kind_weight * coverage, kind_weight * coverage * score


def _page_family_aggregate(
    results: list[tuple[AnalysisMeasurementInput, _FamilyResult]],
) -> _FamilyResult:
    first = results[0][1]
    by_kind: dict[str, list[_FamilyResult]] = {}
    for analysis, result in results:
        by_kind.setdefault(analysis.page_kind, []).append(result)
    expected_kind_weight = sum(
        PAGE_KIND_ROLLUP_WEIGHTS.get(kind, 1.0) for kind in by_kind
    )
    contributions = [
        _kind_family_contribution(kind, kind_results)
        for kind, kind_results in by_kind.items()
    ]
    covered_kind_weight = sum(covered for covered, _earned in contributions)
    earned_kind_weight = sum(earned for _covered, earned in contributions)
    coverage = (
        0.0 if expected_kind_weight <= 0 else covered_kind_weight / expected_kind_weight
    )
    score = (
        None if covered_kind_weight <= 0 else earned_kind_weight / covered_kind_weight
    )
    determinate_points = first.budget * coverage
    return _FamilyResult(
        family_id=first.family_id,
        dimension_id=first.dimension_id,
        budget=first.budget,
        scope=first.scope,
        score=score,
        coverage=coverage,
        earned_points=(0.0 if score is None else score * determinate_points),
        determinate_points=determinate_points,
        expected_points=first.budget,
        determinate_checkpoint_ids=_aggregate_checkpoint_ids(
            result for _analysis, result in results
        ),
    )


def _aggregate_site_families(
    analyses: list[AnalysisMeasurementInput],
    rows: list[RuleMeasurementInput],
) -> tuple[_FamilyResult, ...]:
    results: list[_FamilyResult] = []
    seen: set[str] = set()
    for analysis in analyses:
        if analysis.page_kind == PAGE_KIND_OTHER:
            continue
        for artifact in analysis.expected_family_profile:
            family_id = str(artifact.get("family_id") or "")
            if artifact.get("scope") != RULE_SCOPE_SITE or family_id in seen:
                continue
            enabled = dict(artifact)
            enabled["evaluation_scope"] = True
            result = _family_result(enabled, rows)
            if result is not None:
                results.append(result)
                seen.add(family_id)
    return tuple(results)


def _aggregate_families(
    analyses: list[AnalysisMeasurementInput],
    rows: list[RuleMeasurementInput],
) -> tuple[_FamilyResult, ...]:
    if len({analysis.analysis_id for analysis in analyses}) != len(analyses):
        raise ValueError("Duplicate analysis measurement input")
    rows_by_analysis: dict[str, list[RuleMeasurementInput]] = {}
    for row in rows:
        rows_by_analysis.setdefault(row.analysis_id, []).append(row)
    grouped: dict[str, list[tuple[AnalysisMeasurementInput, _FamilyResult]]] = {}
    for analysis in analyses:
        if analysis.page_kind == PAGE_KIND_OTHER:
            continue
        results = _family_results(
            analysis.expected_family_profile,
            rows_by_analysis.get(analysis.analysis_id, []),
        )
        for result in results:
            if result.scope == RULE_SCOPE_PAGE:
                grouped.setdefault(result.family_id, []).append((analysis, result))
    aggregate = [
        _page_family_aggregate(family_results) for family_results in grouped.values()
    ]
    aggregate.extend(_aggregate_site_families(analyses, rows))
    return tuple(aggregate)


def aggregate_measurements(
    inputs: Iterable[AnalysisMeasurementInput],
    rule_inputs: Iterable[RuleMeasurementInput],
) -> AggregateMeasurements:
    rows = list(inputs)
    persisted_rules = list(rule_inputs)
    rules = _normalize_rules(persisted_rules)
    families = _aggregate_families(rows, persisted_rules)
    dimensions = tuple(
        _dimension_measurement(key, families=families)
        for key in AEO_READINESS_DIMENSIONS
    )
    web_fundamentals_score, web_fundamentals_coverage, web_fundamentals_state = (
        aggregate_web_fundamentals(rules)
    )
    aeo_score, aeo_coverage, aeo_state = _overall_aeo(dimensions)
    return AggregateMeasurements(
        web_fundamentals_score=web_fundamentals_score,
        web_fundamentals_coverage=web_fundamentals_coverage,
        web_fundamentals_state=web_fundamentals_state,
        aeo_readiness_score=aeo_score,
        aeo_measurement_coverage=aeo_coverage,
        aeo_measurement_state=aeo_state,
        readiness_dimensions=tuple(item.to_dict() for item in dimensions),
        analyzed_url_count=len(rows),
    )
