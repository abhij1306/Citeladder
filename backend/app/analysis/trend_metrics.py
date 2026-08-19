"""Prompt trend calculations for persisted analysis projections."""

from __future__ import annotations

from app.core.config.analysis import (
    PROMPT_DECLINE_MATERIALITY_POINTS,
    PROMPT_DECLINE_MIN_ENGINES,
    PROMPT_DECLINE_REPETITION_AGREEMENT,
    PROMPT_DECLINE_REQUIRED_MOVEMENTS,
    PROMPT_DECLINE_WINDOW_MOVEMENTS,
)


def _engine_decline_agreement(
    current: dict[str, float], previous: dict[str, float]
) -> tuple[int, float]:
    overlapping = sorted(set(current).intersection(previous))
    if not overlapping:
        return 0, 0.0
    declining = sum(
        current[engine] - previous[engine] <= -PROMPT_DECLINE_MATERIALITY_POINTS
        for engine in overlapping
    )
    return declining, round(declining / len(overlapping), 4)


def _decline_is_confirmed(
    *,
    immediate_delta: float | None,
    recent_deltas: list[float],
    declining_engines: int,
    repetitions_confirm: bool,
) -> bool:
    return (
        immediate_delta is not None
        and immediate_delta <= -PROMPT_DECLINE_MATERIALITY_POINTS
        and len(recent_deltas) >= PROMPT_DECLINE_WINDOW_MOVEMENTS
        and sum(delta <= -PROMPT_DECLINE_MATERIALITY_POINTS for delta in recent_deltas)
        >= PROMPT_DECLINE_REQUIRED_MOVEMENTS
        and declining_engines >= PROMPT_DECLINE_MIN_ENGINES
        and repetitions_confirm
    )


def _prompt_trend_inputs(*, previous, row, engine_count, repetitions):
    current_score = float(row.get("composite_score") or 0.0)
    current_engines = {
        str(engine): round(float(score), 2)
        for engine, score in (row.get("per_engine_scores") or {}).items()
    }
    previous_score = previous[0].composite_score if previous else None
    immediate_delta = (
        round(current_score - previous_score, 2) if previous_score is not None else None
    )
    previous_engines = previous[0].per_engine_scores if previous else {}
    declining_engines, engine_agreement = _engine_decline_agreement(
        current_engines, previous_engines
    )
    recent_deltas = [
        value
        for value in [immediate_delta, *(item.immediate_delta for item in previous[:3])]
        if value is not None
    ]
    return (
        current_score,
        previous_score,
        immediate_delta,
        current_engines,
        recent_deltas,
        declining_engines,
        engine_agreement,
    )


def _prompt_trend_values(*, previous, row, repetitions, engine_count):
    (
        current_score,
        previous_score,
        immediate_delta,
        current_engines,
        recent_deltas,
        declining_engines,
        engine_agreement,
    ) = _prompt_trend_inputs(
        previous=previous,
        row=row,
        engine_count=engine_count,
        repetitions=repetitions,
    )
    repetition_agreement = float(row.get("mention_stability") or 0.0)
    evidence_coverage = _prompt_evidence_coverage(
        int(row.get("repetitions") or 0), engine_count, repetitions
    )
    return {
        "composite_score": current_score,
        "previous_score": previous_score,
        "immediate_delta": immediate_delta,
        "rolling_four": [
            current_score,
            *(item.composite_score for item in previous[:3]),
        ],
        "per_engine_scores": current_engines,
        "engine_agreement": engine_agreement,
        "repetition_agreement": repetition_agreement,
        "evidence_coverage": evidence_coverage,
        "trend_confidence": round(
            (engine_agreement + repetition_agreement + evidence_coverage) / 3, 4
        ),
        "decline_confirmed": _decline_is_confirmed(
            immediate_delta=immediate_delta,
            recent_deltas=recent_deltas,
            declining_engines=declining_engines,
            repetitions_confirm=(
                repetitions <= 1
                or repetition_agreement >= PROMPT_DECLINE_REPETITION_AGREEMENT
            ),
        ),
    }


def _prompt_evidence_coverage(observed, engine_count, repetitions):
    expected = engine_count * repetitions
    return round(observed / expected, 4) if expected else 0.0
