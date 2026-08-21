# What a realistic buyer prompt looks like, in one place.
#
# Both generation paths need these rules -- the onboarding portfolio and the
# "Generate prompts" button on an existing project -- and when they lived only
# in onboarding, the manual path kept shipping the register this contract
# exists to eliminate.
#
# Every rule here corresponds to something a model demonstrably did after being
# asked in prose not to. The old system prompt said "avoid padded lead-ins such
# as 'what are my best options for'" and the model emitted that exact string;
# it said "never paste the business summary into a query" and the model pasted
# it. Instruction sets the register, this enforces it.
from __future__ import annotations

import unicodedata

from app.core.config.visibility_prompts import (
    TEMPLATE_LEAD_INS,
    VISIBILITY_POSITIONING_SHINGLE_WORDS,
)

OPENING_WORDS = 3


def words(text: str) -> list[str]:
    """Case-folded word tokens, in any script.

    Splits on punctuation, symbols and separators and keeps letters, digits and
    combining marks. A regex word class is not enough: ``[^\\W_]+`` drops the
    vowel signs that Devanagari, Thai and Arabic words are built from, so a
    Hindi prompt tokenized into meaningless fragments and every check below
    quietly stopped working in exactly the markets this product sells into.
    """
    cleaned = "".join(
        " " if unicodedata.category(char)[0] in "PSZC" else char
        for char in text.casefold()
    )
    return cleaned.split()


def starts_with_template(text: str) -> bool:
    """Whether a prompt opens with a survey frame rather than a real question."""
    normalized = " ".join(words(text))
    return any(normalized.startswith(lead) for lead in TEMPLATE_LEAD_INS)


def positioning_shingles(values: list[str]) -> frozenset[str]:
    """Every N-word run of the confirmed positioning, for paste-in detection."""
    span = VISIBILITY_POSITIONING_SHINGLE_WORDS
    shingles: set[str] = set()
    for value in values:
        tokens = words(str(value or ""))
        for start in range(0, max(0, len(tokens) - span + 1)):
            shingles.add(" ".join(tokens[start : start + span]))
    return frozenset(shingles)


def repeats_positioning(text: str, shingles: frozenset[str]) -> bool:
    """Whether a prompt restates the company's own marketing copy."""
    if not shingles:
        return False
    span = VISIBILITY_POSITIONING_SHINGLE_WORDS
    tokens = words(text)
    return any(
        " ".join(tokens[start : start + span]) in shingles
        for start in range(0, max(0, len(tokens) - span + 1))
    )


def names_market(text: str, market_words: tuple[str, ...]) -> bool:
    """Whole-word market match.

    Substring matching made "IN" a hit inside "running", "finding" and
    "shipping", so nearly every prompt registered as naming its market and the
    one-per-topic cap rejected good prompts wholesale.
    """
    joined = f" {' '.join(words(text))} "
    return any(
        f" {' '.join(words(term))} " in joined for term in market_words if words(term)
    )


def opening_key(text: str) -> str:
    """The first few words, as the identity of a sentence frame."""
    return " ".join(words(text)[:OPENING_WORDS])
