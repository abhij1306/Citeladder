"""Pure seven-dimension AEO Readiness presentation projection."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass

from app.core.config.site_health import (
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    AEO_READINESS_MAX_EVIDENCE_LINKS_PER_DIMENSION,
    AEO_READINESS_RULE_DIMENSIONS,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)

_OUTCOME_ORDER = {
    RULE_OUTCOME_FAIL: 0,
    RULE_OUTCOME_ERROR: 1,
    RULE_OUTCOME_PASS: 2,
    RULE_OUTCOME_NOT_APPLICABLE: 3,
}


@dataclass(frozen=True)
class ReadinessEvaluationInput:
    evaluation_id: uuid.UUID
    analysis_id: uuid.UUID
    site_url_id: uuid.UUID
    normalized_url: str
    rule_id: str
    outcome: str


@dataclass(frozen=True)
class ReadinessDimension:
    key: str
    label: str
    rule_ids: tuple[str, ...]
    pass_count: int
    fail_count: int
    not_applicable_count: int
    error_count: int
    observed_evaluation_count: int
    expected_evaluation_count: int
    coverage: float | None
    evidence: tuple[ReadinessEvaluationInput, ...]


@dataclass(frozen=True)
class ReadinessResult:
    dimensions: tuple[ReadinessDimension, ...]
    observed_evaluation_count: int
    expected_evaluation_count: int
    coverage: float | None
    limitations: tuple[str, ...]


def _dimension(
    key: str,
    *,
    analysis_count: int,
    evaluations: list[ReadinessEvaluationInput],
) -> ReadinessDimension:
    rules = tuple(
        rule_id
        for rule_id, dimension in AEO_READINESS_RULE_DIMENSIONS.items()
        if dimension == key
    )
    rows = [
        row for row in evaluations if AEO_READINESS_RULE_DIMENSIONS[row.rule_id] == key
    ]
    counts = Counter(row.outcome for row in rows)
    expected = analysis_count * len(rules)
    evidence = tuple(
        sorted(
            rows,
            key=lambda row: (
                _OUTCOME_ORDER.get(row.outcome, 4),
                row.normalized_url,
                row.rule_id,
                str(row.evaluation_id),
            ),
        )[:AEO_READINESS_MAX_EVIDENCE_LINKS_PER_DIMENSION]
    )
    return ReadinessDimension(
        key=key,
        label=AEO_READINESS_DIMENSION_LABELS[key],
        rule_ids=rules,
        pass_count=counts[RULE_OUTCOME_PASS],
        fail_count=counts[RULE_OUTCOME_FAIL],
        not_applicable_count=counts[RULE_OUTCOME_NOT_APPLICABLE],
        error_count=counts[RULE_OUTCOME_ERROR],
        observed_evaluation_count=len(rows),
        expected_evaluation_count=expected,
        coverage=round(len(rows) / expected, 4) if expected else None,
        evidence=evidence,
    )


def project_aeo_readiness(
    evaluations: list[ReadinessEvaluationInput], *, analysis_count: int
) -> ReadinessResult:
    """Group only explicitly mapped persisted evaluations; never guess."""
    mapped = [
        row for row in evaluations if row.rule_id in AEO_READINESS_RULE_DIMENSIONS
    ]
    dimensions = tuple(
        _dimension(key, analysis_count=analysis_count, evaluations=mapped)
        for key in AEO_READINESS_DIMENSIONS
    )
    observed = sum(item.observed_evaluation_count for item in dimensions)
    expected = sum(item.expected_evaluation_count for item in dimensions)
    limitations: list[str] = []
    if observed < expected:
        limitations.append(
            f"Observed {observed} of {expected} mapped rule evaluations."
        )
    error_count = sum(item.error_count for item in dimensions)
    if error_count:
        limitations.append(
            f"{error_count} mapped evaluations ended in error and are not "
            "passes or failures."
        )
    return ReadinessResult(
        dimensions=dimensions,
        observed_evaluation_count=observed,
        expected_evaluation_count=expected,
        coverage=round(observed / expected, 4) if expected else None,
        limitations=tuple(limitations),
    )


__all__ = ["ReadinessEvaluationInput", "ReadinessResult", "project_aeo_readiness"]
