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
from app.domain.prompts.topical_binding import binding_tokens

_WORD = re.compile(r"[a-z0-9']+", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def buyer_prompt_error(
    text: str, *, prior: list[str], vocabulary: frozenset[str] = frozenset()
) -> str:
    """Why this prompt is not admissible, or an empty string if it is.

    `prior` is the batch admitted so far, so the two portfolio-wide rules --
    no duplicates and no single sentence frame applied to every row -- can be
    enforced across a batch generated in one call.

    `vocabulary` is what the target actually sells. The rules here all judge
    REGISTER, and a prompt can be a flawless buyer prompt about the wrong
    industry entirely: "phone case with magsafe for iphone 15 pro" passed every
    check above for a linen-fashion shelf. Register without topicality is the
    exact inverse of what that failure needed. Empty vocabulary disables the
    rule rather than rejecting everything, so a target we know nothing about
    degrades to the previous behaviour instead of generating nothing.
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
    if vocabulary and not (vocabulary & binding_tokens(cleaned)):
        return "off_topic"
    return ""


def _normalized(text: str) -> str:
    return " ".join(_words(text))


def _opening(text: str) -> str:
    return " ".join(_words(text)[:3])


def admitted_buyer_prompts(
    texts: list[str], *, vocabulary: frozenset[str] = frozenset()
) -> tuple[list[str], list[str]]:
    """Split a generated batch into admitted prompts and rejection reasons."""
    admitted: list[str] = []
    reasons: list[str] = []
    for text in texts:
        error = buyer_prompt_error(text, prior=admitted, vocabulary=vocabulary)
        if error:
            reasons.append(error)
        else:
            admitted.append(" ".join(text.split()))
    return admitted, reasons
