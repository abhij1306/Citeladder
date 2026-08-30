"""Deterministic PR2 Technical Integrity and AEO Readiness measurement."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.analysis.site_health.rules import RuleEvaluation
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSIONS,
    RULE_ID_TECHNICAL_INDEXABLE,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_PASS,
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
    DIMENSION_UNRESOLVED,
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_MEASURED,
    PAGE_KIND_READINESS_CHECKPOINTS,
    READINESS_CHECKPOINTS,
    READINESS_DIMENSION_WEIGHTS,
    SCORE_ROLE_AEO,
    SCORE_ROLE_TECHNICAL,
    TECHNICAL_MEASURED_MIN_COVERAGE,
)
from app.core.config.site_health_taxonomy import PAGE_KIND_OTHER
from app.core.config.site_health_traits import PAGE_TRAIT_HAS_FAQ

_DETERMINATE = frozenset({RULE_OUTCOME_PASS, RULE_OUTCOME_PARTIAL, RULE_OUTCOME_FAIL})


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
    if outcome == RULE_OUTCOME_PASS:
        return 1.0
    if outcome == RULE_OUTCOME_PARTIAL:
        return 0.5
    return 0.0


def _profile_rows(evaluations: list[RuleEvaluation], role: str) -> list[RuleEvaluation]:
    return [
        row
        for row in evaluations
        if row.expected_profile_membership and role in row.score_roles
    ]


def _determinate_rows(rows: list[RuleEvaluation]) -> list[RuleEvaluation]:
    return [row for row in rows if row.outcome in _DETERMINATE]


def _rule_weight(rows: list[RuleEvaluation]) -> float:
    return sum(max(0.0, float(row.weight)) for row in rows)


def _technical_earned(rows: list[RuleEvaluation]) -> float:
    return _rule_weight([row for row in rows if row.outcome == RULE_OUTCOME_PASS])


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


def _dimension_applicability(
    key: str, *, page_kind: str, page_traits: frozenset[str], structural: bool
) -> tuple[str, str]:
    expected_ids = set(PAGE_KIND_READINESS_CHECKPOINTS.get(page_kind, ()))
    if PAGE_TRAIT_HAS_FAQ in page_traits:
        expected_ids.update(("aeo.answer_first", "aeo.question_headings"))
    dimension_expected = any(
        READINESS_CHECKPOINTS[checkpoint_id].dimension == key
        for checkpoint_id in expected_ids
    )
    if structural:
        return (
            (DIMENSION_APPLICABLE, "")
            if dimension_expected
            else (
                DIMENSION_NOT_APPLICABLE,
                "dimension_determinately_irrelevant",
            )
        )
    universal_ids = PAGE_KIND_READINESS_CHECKPOINTS[PAGE_KIND_OTHER]
    universal_dimension = any(
        READINESS_CHECKPOINTS[checkpoint_id].dimension == key
        for checkpoint_id in universal_ids
    )
    if universal_dimension:
        return DIMENSION_APPLICABLE, ""
    if dimension_expected and page_kind != PAGE_KIND_OTHER:
        return DIMENSION_UNRESOLVED, "dimension_relevance_unresolved"
    return DIMENSION_NOT_APPLICABLE, "dimension_determinately_irrelevant"


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
    page_kind: str,
    page_traits: frozenset[str],
    structural: bool,
) -> DimensionMeasurement:
    applicability, reason = _dimension_applicability(
        key, page_kind=page_kind, page_traits=page_traits, structural=structural
    )
    if applicability == DIMENSION_NOT_APPLICABLE:
        return _empty_dimension(key, applicability, reason)
    expected = _dimension_expected(evaluations, key)
    if not expected:
        bounded_reason = (
            "no_expected_checkpoint_evaluator"
            if applicability == DIMENSION_APPLICABLE
            else reason
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


def _weighted_dimension_average(
    rows: list[DimensionMeasurement], attribute: str, *, score: bool
) -> float | None:
    weight = sum(READINESS_DIMENSION_WEIGHTS[row.key] for row in rows)
    weighted_value = sum(
        READINESS_DIMENSION_WEIGHTS[row.key] * float(getattr(row, attribute) or 0.0)
        for row in rows
    )
    if weight <= 0:
        return None
    value = weighted_value / weight
    return _round_score(value) if score else _round_coverage(value)


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
    scored = [row for row in dimensions if row.score is not None]
    covered = [
        row for row in dimensions if row.applicability != DIMENSION_NOT_APPLICABLE
    ]
    score = _weighted_dimension_average(scored, "score", score=True)
    coverage = _weighted_dimension_average(covered, "coverage", score=False)
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
    page_kind_evidence: dict | None = None,
) -> AnalysisScores:
    rows = list(evaluations)
    effective_page_kind = (
        page_kind if page_kind in PAGE_KIND_READINESS_CHECKPOINTS else PAGE_KIND_OTHER
    )
    structural = str((page_kind_evidence or {}).get("tier") or "") in ("", "structural")
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
            page_kind=effective_page_kind,
            page_traits=frozenset(page_traits),
            structural=structural,
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
                row.outcome == RULE_OUTCOME_PASS
                for row in rows
                if row.rule_id == RULE_ID_TECHNICAL_INDEXABLE
                and row.outcome in _DETERMINATE
            ),
            None,
        ),
    )


@dataclass(frozen=True)
class AnalysisMeasurementInput:
    page_kind: str
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
    readiness_dimensions: tuple[dict, ...]


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


def _page_dimensions(key: str, rows: list[AnalysisMeasurementInput]) -> list[dict]:
    return [
        item
        for row in rows
        for item in row.readiness_dimensions
        if item.get("key") == key
        and item.get("dimension_applicability") != DIMENSION_NOT_APPLICABLE
    ]


def _persisted_points(page_dimensions: list[dict]) -> tuple[float, float, float]:
    earned = sum(float(item.get("earned_points") or 0.0) for item in page_dimensions)
    determinate = sum(
        float(item.get("determinate_points") or 0.0) for item in page_dimensions
    )
    expected = sum(
        float(item.get("expected_points") or 0.0) for item in page_dimensions
    )
    return earned, determinate, expected


def _normalized_page_coverage(page_dimensions: list[dict]) -> float:
    return sum(float(item.get("coverage") or 0.0) for item in page_dimensions) / len(
        page_dimensions
    )


def _persisted_values(page_dimensions: list[dict], key: str) -> tuple[str, ...]:
    return tuple(
        sorted({value for item in page_dimensions for value in item.get(key, [])})
    )


def _aggregate_applicability(page_dimensions: list[dict]) -> str:
    if any(
        item.get("dimension_applicability") == DIMENSION_APPLICABLE
        for item in page_dimensions
    ):
        return DIMENSION_APPLICABLE
    return DIMENSION_UNRESOLVED


def _aggregate_dimension_state(determinate: float, coverage: float) -> str:
    if determinate == 0:
        return MEASUREMENT_STATE_NOT_MEASURED
    if coverage >= AEO_MEASURED_MIN_COVERAGE:
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


def _aggregate_dimension(
    key: str, rows: list[AnalysisMeasurementInput]
) -> DimensionMeasurement:
    page_dimensions = _page_dimensions(key, rows)
    if not page_dimensions:
        return _empty_dimension(
            key, DIMENSION_NOT_APPLICABLE, "dimension_determinately_irrelevant"
        )
    earned, determinate, expected = _persisted_points(page_dimensions)
    coverage = _normalized_page_coverage(page_dimensions)
    checkpoint_ids = _persisted_values(page_dimensions, "determinate_checkpoint_ids")
    families = _persisted_values(page_dimensions, "checkpoint_families")
    applicability = _aggregate_applicability(page_dimensions)
    state = _aggregate_dimension_state(determinate, coverage)
    return DimensionMeasurement(
        key=key,
        applicability=applicability,
        measurement_state=state,
        score=None if determinate <= 0 else _round_score(100.0 * earned / determinate),
        coverage=_round_coverage(coverage),
        earned_points=round(earned, 4),
        determinate_points=round(determinate, 4),
        expected_points=round(expected, 4),
        determinate_checkpoint_ids=checkpoint_ids,
        checkpoint_families=families,
        reason="dimension_relevance_unresolved"
        if applicability == DIMENSION_UNRESOLVED
        else "",
    )


def _aggregate_technical(
    rows: list[AnalysisMeasurementInput],
) -> tuple[float | None, float | None, str]:
    earned = sum(row.technical_earned_weight for row in rows)
    determinate = sum(row.technical_determinate_weight for row in rows)
    expected = sum(row.technical_expected_weight for row in rows)
    score = _ratio(earned, determinate, score=True)
    coverage = _ratio(determinate, expected, score=False)
    state = _technical_state(
        has_expected=expected > 0,
        has_determinate=determinate > 0,
        coverage=coverage,
        complete=all(row.technical_critical_complete for row in rows),
    )
    return score, coverage, state


def aggregate_measurements(
    inputs: Iterable[AnalysisMeasurementInput],
) -> AggregateMeasurements:
    rows = list(inputs)
    dimensions = tuple(
        _aggregate_dimension(key, rows) for key in AEO_READINESS_DIMENSIONS
    )
    technical_score, technical_coverage, technical_state = _aggregate_technical(rows)
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
