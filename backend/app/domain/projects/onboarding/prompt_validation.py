"""Deterministic quality gate for the onboarding prompt portfolio.

The gate is built around one goal: the portfolio must read like queries the
brand's actual customers would type. Three earlier rules were removed because
measurement showed they enforced the opposite -- hand-authored gold prompts
written the way real buyers speak *failed* them:

``buyer_perspective``
    demanded an i/me/my/we/us/our pronoun. "best mattress for back pain india
    under 20000" contains none, and is exactly what a real buyer types. The rule
    mandated the stilted "...should I consider..." register it was meant to
    prevent.
``natural_search`` (>= 6 words)
    rejected the terse queries that dominate real usage: "feedonomics
    alternatives", "plumber near me".
``market_coverage``
    forced a country name into the text, producing "... in United States" on
    queries no American writes.

What replaces them is a check the old gate could not make at all: a prompt that
matches a slot-template skeleton is rejected outright, because template output
is the one form of synthetic language that is machine-detectable with certainty.
Counts are bounded rather than exact, so a brand the model barely knows ships
fewer honest prompts instead of padded ones.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.analysis.normalization import normalize_alias
from app.core.config.brand_discovery import (
    BRAND_RELEVANT_PROMPT_MAX,
    BRANDED_PROMPT_MAX,
    MARKET_VISIBILITY_PROMPT_MAX,
    MIN_ONBOARDING_DISTINCT_INTENTS,
    PORTFOLIO_PROMPT_MIN,
)
from app.core.config.projects import PROMPT_INTENTS
from app.domain.prompts.portfolio import contains_tracked_name

MARKET_VISIBILITY = "market_visibility"
BRAND_RELEVANT = "brand_relevant"
BRAND_DIAGNOSTIC = "brand_diagnostic"
COMPARISON = "comparison"

NEUTRAL_COHORTS = (MARKET_VISIBILITY, BRAND_RELEVANT)
BRANDED_COHORTS = (BRAND_DIAGNOSTIC, COMPARISON)
COHORT_MAXIMUMS = {
    MARKET_VISIBILITY: MARKET_VISIBILITY_PROMPT_MAX,
    BRAND_RELEVANT: BRAND_RELEVANT_PROMPT_MAX,
    BRAND_DIAGNOSTIC: BRANDED_PROMPT_MAX,
    COMPARISON: BRANDED_PROMPT_MAX,
}

# A single word is not a query anyone types into an answer engine, but two often
# is ("feedonomics alternatives"). This is a floor against empty output, not a
# style rule.
MIN_PROMPT_WORDS = 2
MAX_PROMPT_WORDS = 30
_SLOT_PATTERN = re.compile(r"\{[a-z_]+\}")
_SLOT_SENTINEL = "zzslotzz"

# The marketer-voice tell, stated precisely. The old rule tested for the
# *absence* of an i/me/my pronoun, which condemned "best mattress for back pain"
# -- a perfectly real query -- while a genuine giveaway is asking about the
# audience in the third person: "Where can shoppers buy ...". Matching the
# audience noun only in subject position after a modal keeps legitimate queries
# such as "best crm for small businesses" intact.
_THIRD_PERSON_SUBJECT = re.compile(
    r"\b(?:can|should|do|does|would|might|will)\s+"
    r"(?:shoppers|customers|users|buyers|consumers|clients|businesses|"
    r"companies|people|brands|retailers)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PromptQualityResult:
    accepted: tuple[dict, ...]
    errors: tuple[str, ...]


def _is_near_duplicate(candidate: str, accepted: list[str]) -> bool:
    normalized = normalize_alias(candidate)
    return any(
        normalized == prior or SequenceMatcher(None, normalized, prior).ratio() >= 0.88
        for prior in accepted
    )


def template_patterns(templates: Sequence[str]) -> list[re.Pattern[str]]:
    """Compile archetype templates into anchored skeleton matchers.

    The sentinel must survive ``normalize_alias``, which strips punctuation and
    control characters, so it has to be an ordinary alphanumeric word.
    """
    patterns: list[re.Pattern[str]] = []
    for template in templates:
        normalized = normalize_alias(_SLOT_PATTERN.sub(f" {_SLOT_SENTINEL} ", template))
        if _SLOT_SENTINEL not in normalized:
            continue
        escaped = "".join(
            ".+?" if part == _SLOT_SENTINEL else re.escape(part)
            for part in re.split(f"({_SLOT_SENTINEL})", normalized)
        )
        patterns.append(re.compile(f"^{escaped}$"))
    return patterns


def validate_portfolio(
    prompts: list[dict],
    *,
    brand_terms: list[str],
    competitor_terms: list[str],
    primary_market: str = "",
    context_terms: list[str] | None = None,
    banned_patterns: list[re.Pattern[str]] | None = None,
) -> PromptQualityResult:
    accepted, errors, counts, intents = _accepted_portfolio_rows(
        prompts,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
        banned_patterns=banned_patterns or [],
    )
    errors.extend(
        _portfolio_errors(
            counts=counts,
            accepted_count=len(accepted),
            accepted_text=[normalize_alias(str(p.get("text") or "")) for p in accepted],
            intents=intents,
            primary_market=primary_market,
            context_terms=context_terms,
        )
    )
    return PromptQualityResult(tuple(accepted), tuple(errors))


def _accepted_portfolio_rows(
    prompts, *, brand_terms, competitor_terms, banned_patterns
):
    accepted: list[dict] = []
    accepted_text: list[str] = []
    errors: list[str] = []
    counts = dict.fromkeys(COHORT_MAXIMUMS, 0)
    intents: set[str] = set()
    for index, prompt in enumerate(prompts):
        text = str(prompt.get("text") or "").strip()
        cohort = str(prompt.get("cohort") or "")
        error = _prompt_error(
            index=index,
            text=text,
            theme=str(prompt.get("theme") or "").strip(),
            cohort=cohort,
            intent=str(prompt.get("intent") or ""),
            brand_terms=brand_terms,
            competitor_terms=competitor_terms,
            accepted_text=accepted_text,
            banned_patterns=banned_patterns,
        )
        if error:
            errors.append(error)
            continue
        if counts[cohort] >= COHORT_MAXIMUMS[cohort]:
            # A generous model is not a broken one. Trim the surplus rather than
            # failing a portfolio whose only fault is having too much of a good
            # cohort; the ceiling is about cost and UI, not correctness.
            continue
        counts[cohort] += 1
        intents.add(str(prompt.get("intent") or ""))
        accepted.append(prompt)
        accepted_text.append(normalize_alias(text))
    return accepted, errors, counts, intents


def _prompt_error(
    *,
    index,
    text,
    theme,
    cohort,
    intent,
    brand_terms,
    competitor_terms,
    accepted_text,
    banned_patterns,
) -> str:
    if cohort not in COHORT_MAXIMUMS:
        return f"prompt[{index}].cohort"
    if not theme:
        return f"prompt[{index}].topic"
    words = len(text.split())
    if words < MIN_PROMPT_WORDS:
        return f"prompt[{index}].too_short"
    if words > MAX_PROMPT_WORDS:
        # Long prompts are how raw profile text leaks into a question: an entire
        # target-audience paragraph spliced mid-sentence.
        return f"prompt[{index}].too_long"
    if _is_near_duplicate(text, accepted_text):
        return f"prompt[{index}].duplicate"
    if intent not in PROMPT_INTENTS or not intent:
        return f"prompt[{index}].intent"
    normalized = normalize_alias(text)
    if any(pattern.match(normalized) for pattern in banned_patterns):
        return f"prompt[{index}].template_tell"
    if _THIRD_PERSON_SUBJECT.search(text):
        return f"prompt[{index}].third_person_audience"
    return _identity_error(
        index=index,
        text=text,
        theme=theme,
        cohort=cohort,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
    )


def _identity_error(
    *, index, text, theme, cohort, brand_terms, competitor_terms
) -> str:
    """Neutral cohorts must not name the brand; branded cohorts must.

    Neutrality is load-bearing only where it measures something: a prompt that
    names the brand cannot show whether an answer engine recommends it
    *unprompted*. The branded cohorts measure a different question -- whether the
    brand is described accurately and wins its comparisons -- so there the brand
    name is required rather than forbidden.
    """
    if cohort in NEUTRAL_COHORTS:
        tracked = [*brand_terms, *competitor_terms]
        if contains_tracked_name(text, tracked):
            return f"prompt[{index}].tracked_name"
        if contains_tracked_name(theme, tracked):
            return f"prompt[{index}].tracked_topic_name"
        return ""
    if not contains_tracked_name(text, brand_terms):
        return f"prompt[{index}].missing_brand_name"
    if cohort == COMPARISON and not contains_tracked_name(text, competitor_terms):
        return f"prompt[{index}].missing_competitor_name"
    return ""


def _portfolio_errors(
    *,
    counts,
    accepted_count,
    accepted_text,
    intents,
    primary_market,
    context_terms,
) -> list[str]:
    """Bound the portfolio; never require it to be full.

    A brand with thin evidence should ship a short honest portfolio, so only
    ceilings are enforced. The floor exists to catch an empty result, not to
    force padding.
    """
    del counts  # cohort ceilings are applied by trimming, not by erroring
    errors: list[str] = []
    if accepted_count < PORTFOLIO_PROMPT_MIN:
        errors.append(f"portfolio.count:{accepted_count}")
    if _lacks_intent_coverage(primary_market, intents):
        errors.append("portfolio.intent_coverage")
    if _lacks_grounding(context_terms, accepted_text):
        errors.append("portfolio.grounding")
    return errors


def _lacks_grounding(context_terms: list[str] | None, accepted_text: list[str]) -> bool:
    """Is the portfolio about this brand's subject matter at all?

    Deliberately weaker than the rule it replaces, which demanded each supplied
    phrase appear *verbatim* and so rewarded keyword stuffing. Sharing a content
    word with two distinct confirmed terms is enough to show the portfolio is
    grounded, while leaving the wording free to sound like a person.
    """
    if not context_terms or not accepted_text:
        return False
    # Threshold off the *usable* terms: counting blank or duplicate entries made
    # the requirement depend on how the caller happened to pad the list.
    terms = {
        normalized
        for term in context_terms
        if (normalized := normalize_alias(term).strip())
    }
    if not terms:
        return False
    words = {word for text in accepted_text for word in text.split()}
    covered = sum(1 for term in terms if words & set(term.split()))
    return covered < min(2, len(terms))


def _lacks_intent_coverage(primary_market: str, intents: set[str]) -> bool:
    return (
        bool(primary_market)
        and len({intent for intent in intents if intent})
        < MIN_ONBOARDING_DISTINCT_INTENTS
    )
