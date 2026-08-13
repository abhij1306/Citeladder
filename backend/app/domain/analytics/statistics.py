"""Small deterministic statistics used by analytics projections."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from app.core.config.analytics import (
    CORRELATION_MIN_SAMPLE,
    CORRELATION_STATE_INSUFFICIENT_DATA,
    CORRELATION_STATE_OK,
)

_CORRELATION_DECIMALS = 6
_SCORE_DECIMALS = 2
_VARIANCE_EPSILON = 1e-12


def select_latest_referral_facts(facts: Sequence[Any]) -> list[Any]:
    """Keep the highest revision per non-null metric-row identity."""
    latest: dict[object, Any] = {}
    for fact in facts:
        if fact.row_identity is None:
            continue
        current = latest.get(fact.row_identity)
        if current is None or fact.resync_seq > current.resync_seq:
            latest[fact.row_identity] = fact
    return sorted(
        latest.values(),
        key=lambda fact: (fact.occurred_date, str(fact.classification_id)),
    )


def pearson_coefficient(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys):
        raise ValueError("pearson inputs must have equal lengths")
    if not xs:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    syy = sum((y - mean_y) ** 2 for y in ys)
    if math.isclose(sxx, 0.0, rel_tol=0.0, abs_tol=_VARIANCE_EPSILON):
        return None
    if math.isclose(syy, 0.0, rel_tol=0.0, abs_tol=_VARIANCE_EPSILON):
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    return sxy / math.sqrt(sxx * syy)


def correlation_summary(pairs: Sequence[tuple[float, float]]) -> dict[str, Any]:
    sample_size = len(pairs)
    insufficient = {
        "state": CORRELATION_STATE_INSUFFICIENT_DATA,
        "coefficient": None,
        "sample_size": sample_size,
    }
    if sample_size < CORRELATION_MIN_SAMPLE:
        return insufficient
    coefficient = pearson_coefficient([x for x, _ in pairs], [y for _, y in pairs])
    if coefficient is None:
        return insufficient
    return {
        "state": CORRELATION_STATE_OK,
        "coefficient": round(coefficient, _CORRELATION_DECIMALS),
        "sample_size": sample_size,
    }


def weighted_mean(pairs: Sequence[tuple[float, int]]) -> float | None:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in pairs) / total_weight


def rounded_weighted_mean(pairs: Sequence[tuple[float, int]]) -> float | None:
    mean = weighted_mean(pairs)
    return round(mean, _SCORE_DECIMALS) if mean is not None else None
