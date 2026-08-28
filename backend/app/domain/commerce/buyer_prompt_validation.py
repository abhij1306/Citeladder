"""Deterministic admission for generated Commerce buyer prompts.

The generator is asked for what a shopper types into an assistant. It was
previously asked, in two lines, for "buyer discovery/comparison questions" and
returned a market-research survey addressed to the shopper -- five prompts of
"What do you prefer", "How important is", "What's your budget range". Every one
passed, because nothing checked. Instructions are advisory; this is not.

Same contract as `prompts/portfolio_validation.py`: a candidate that fails is
dropped with a reason, never rewritten.
"""

from __future__ import annotations

import re

from app.core.config.commerce_catalog import (
    COMMERCE_BUYER_PROMPT_MAX_WORDS,
    COMMERCE_BUYER_PROMPT_MIN_WORDS,
    COMMERCE_BUYER_PROMPT_SURVEY_MARKERS,
)

_WORD = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def buyer_prompt_error(text: str, *, prior: list[str]) -> str:
    """Why this prompt is not admissible, or an empty string if it is.

    `prior` is the batch admitted so far, so the two portfolio-wide rules --
    no duplicates and no single sentence frame applied to every row -- can be
    enforced across a batch generated in one call.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return "empty"
    lowered = cleaned.casefold()
    if any(marker in lowered for marker in COMMERCE_BUYER_PROMPT_SURVEY_MARKERS):
        # The whole failure mode in one rule: a question put TO the shopper.
        return "survey_framing"
    count = len(_words(cleaned))
    if not COMMERCE_BUYER_PROMPT_MIN_WORDS <= count <= COMMERCE_BUYER_PROMPT_MAX_WORDS:
        return "length"
    normalized = _normalized(lowered)
    if any(normalized == _normalized(item.casefold()) for item in prior):
        return "duplicate"
    opening = _opening(lowered)
    if opening and sum(_opening(item.casefold()) == opening for item in prior) >= 2:
        # Three rows opening the same way is the one-sentence-frame batch the
        # exemplars exist to prevent.
        return "repeated_opening"
    return ""


def _normalized(text: str) -> str:
    return " ".join(_words(text))


def _opening(text: str) -> str:
    return " ".join(_words(text)[:3])


def admitted_buyer_prompts(texts: list[str]) -> tuple[list[str], list[str]]:
    """Split a generated batch into admitted prompts and rejection reasons."""
    admitted: list[str] = []
    reasons: list[str] = []
    for text in texts:
        error = buyer_prompt_error(text, prior=admitted)
        if error:
            reasons.append(error)
        else:
            admitted.append(" ".join(text.split()))
    return admitted, reasons
