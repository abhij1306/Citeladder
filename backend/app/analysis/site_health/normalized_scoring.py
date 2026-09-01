"""Validation helpers for bounded normalized rule score evidence."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _validated(
    rule_id: str, values: set[tuple[Any, Any]]
) -> tuple[float, float] | None:
    if not values:
        return None
    if len(values) != 1:
        raise ValueError(f"Rule {rule_id} has conflicting normalized results")
    score, coverage = next(iter(values))
    numeric = (
        isinstance(score, (int, float))
        and not isinstance(score, bool)
        and isinstance(coverage, (int, float))
        and not isinstance(coverage, bool)
    )
    if not numeric or not (0.0 <= score <= 1.0 and 0.0 <= coverage <= 1.0):
        raise ValueError(f"Rule {rule_id} has an invalid normalized result")
    return float(score), float(coverage)


def normalized_measurement_result(
    rule_id: str, observations: Iterable[Any]
) -> tuple[float, float] | None:
    return _validated(
        rule_id,
        {
            (row.normalized_score, row.normalized_coverage)
            for row in observations
            if row.normalized_score is not None and row.normalized_coverage is not None
        },
    )


def normalized_evaluation_result(
    rule_id: str, evaluations: Iterable[Any]
) -> tuple[float, float] | None:
    return _validated(
        rule_id,
        {
            (
                row.evidence.get("normalized_score"),
                row.evidence.get("normalized_coverage"),
            )
            for row in evaluations
            if getattr(row, "rule_id", "") == rule_id
            and getattr(row, "expected_profile_membership", False)
            and hasattr(row, "evidence")
            and row.evidence.get("normalized_score") is not None
            and row.evidence.get("normalized_coverage") is not None
        },
    )


__all__ = ["normalized_evaluation_result", "normalized_measurement_result"]
