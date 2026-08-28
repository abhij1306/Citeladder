# Opportunities deterministic priority scoring (pure, invariant 9).
#
# The priority score is a pure function of a detector hit's factors:
#
#   priority = SEVERITY_WEIGHTS[severity] * value_factor * gap_factor
#              * PRIORITY_SCALE        (rounded to PRIORITY_ROUNDING_DECIMALS)
#
# Every table + knob is read from ``core/config/opportunities.py`` (invariant
# 1); nothing here touches the DB, the network, or an LLM (invariants 7 + 9).
# Same inputs + same ``FORMULA_VERSION`` -> same score, always.
from __future__ import annotations

from app.core.config.opportunities import (
    BUYER_STAGE_VALUE_WEIGHTS,
    GAP_COMPETITOR_CAP,
    GAP_COMPETITOR_WEIGHT,
    GAP_OWNED_CITATION_WEIGHT,
    INTENT_VALUE_DEFAULT,
    INTENT_VALUE_WEIGHTS,
    PRIORITY_ROUNDING_DECIMALS,
    PRIORITY_SCALE,
    PROMPT_INTENT_VALUE_WEIGHTS,
    RECOMMENDATION_STRENGTH_FACTORS,
    SEVERITY_WEIGHT_DEFAULT,
    SEVERITY_WEIGHTS,
)


def value_factor_for_intent(intent: str | None) -> float:
    """Config-weighted value of the prompt's intent (unknown/empty -> default)."""
    key = (intent or "").strip().lower()
    return INTENT_VALUE_WEIGHTS.get(key, INTENT_VALUE_DEFAULT)


def value_factor_for_prompt(
    buyer_stage: str | None,
    prompt_intent: str | None,
    legacy_intent: str | None,
) -> tuple[float, str, str]:
    """Choose one frozen prompt value signal without treating empty as zero."""
    stage = (buyer_stage or "").strip().lower()
    if stage in BUYER_STAGE_VALUE_WEIGHTS:
        return BUYER_STAGE_VALUE_WEIGHTS[stage], "buyer_stage", stage
    intent = (prompt_intent or "").strip().lower()
    if intent in PROMPT_INTENT_VALUE_WEIGHTS:
        return PROMPT_INTENT_VALUE_WEIGHTS[intent], "prompt_intent", intent
    legacy = (legacy_intent or "").strip().lower()
    return value_factor_for_intent(legacy), "legacy_intent", legacy


def recommendation_strength_factor(assessments) -> float:
    """Strongest explicit competitor recommendation observed (>= 1.0).

    An answer that names a competitor as the pick is a wider gap than one
    that merely mentions it. Unknown states fail safe to the neutral 1.0.
    """
    return max(
        (
            RECOMMENDATION_STRENGTH_FACTORS.get(str(item.get("state")), 1.0)
            for item in assessments
        ),
        default=1.0,
    )


def gap_factor_visibility(
    *,
    competitor_count: int,
    owned_citation_rate: float,
    recommendation_strength: float = 1.0,
) -> float:
    """Bounded visibility gap factor (always >= 1.0).

    Grows with the number of distinct competitors present (capped at
    ``GAP_COMPETITOR_CAP``), scales with the strongest explicit competitor
    recommendation observed, and shrinks as the owned-citation rate approaches
    full coverage: at an owned rate of 1.0 the gap is the neutral 1.0 no
    matter how many competitors appear (there is no citation gap to close).
    """
    competitors = min(max(int(competitor_count), 0), GAP_COMPETITOR_CAP)
    owned_rate = min(max(float(owned_citation_rate), 0.0), 1.0)
    owned_gap = 1.0 - owned_rate
    base = 1.0 + (
        GAP_COMPETITOR_WEIGHT * competitors * GAP_OWNED_CITATION_WEIGHT * owned_gap
    )
    return base * max(float(recommendation_strength), 1.0)


def priority_score(*, severity: str, value_factor: float, gap_factor: float) -> float:
    """The rounded deterministic priority score for one detector hit.

    An unknown severity fails safe to ``SEVERITY_WEIGHT_DEFAULT`` rather than
    raising (scoring never invents new severity semantics — the catalog owns
    the vocabulary; this only guards the arithmetic).
    """
    severity_weight = SEVERITY_WEIGHTS.get(severity, SEVERITY_WEIGHT_DEFAULT)
    return round(
        severity_weight * value_factor * gap_factor * PRIORITY_SCALE,
        PRIORITY_ROUNDING_DECIMALS,
    )
