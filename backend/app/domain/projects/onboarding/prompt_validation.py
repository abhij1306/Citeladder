"""Deterministic quality gate for the onboarding prompt portfolio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.analysis.normalization import normalize_alias
from app.core.config.brand_discovery import (
    BUYER_PERSPECTIVE_TERMS,
    MARKET_CONTEXT_TERMS,
    REQUIRED_ONBOARDING_PROMPT_INTENTS,
)
from app.domain.prompts.portfolio import contains_tracked_name

MARKET_VISIBILITY = "market_visibility"
BRAND_RELEVANT = "brand_relevant"


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


def _uses_buyer_perspective(text: str) -> bool:
    return any(
        re.search(
            rf"\b{re.escape(term)}\b",
            text,
            0 if term == "us" else re.IGNORECASE,
        )
        for term in BUYER_PERSPECTIVE_TERMS
    )


def validate_portfolio(
    prompts: list[dict],
    *,
    brand_terms: list[str],
    competitor_terms: list[str],
    primary_market: str = "",
    context_terms: list[str] | None = None,
    expected_market_count: int = 5,
    expected_brand_relevant_count: int = 5,
) -> PromptQualityResult:
    (
        accepted,
        accepted_text,
        accepted_brand_relevant_text,
        errors,
        counts,
        intents,
    ) = _accepted_portfolio_rows(
        prompts,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
    )
    expected_counts = {
        MARKET_VISIBILITY: expected_market_count,
        BRAND_RELEVANT: expected_brand_relevant_count,
    }
    errors.extend(
        _portfolio_errors(
            counts=counts,
            expected_counts=expected_counts,
            accepted_text=accepted_text,
            accepted_brand_relevant_text=accepted_brand_relevant_text,
            intents=intents,
            primary_market=primary_market,
            context_terms=context_terms,
        )
    )
    return PromptQualityResult(tuple(accepted), tuple(errors))


def _accepted_portfolio_rows(prompts, *, brand_terms, competitor_terms):
    accepted: list[dict] = []
    accepted_text: list[str] = []
    accepted_brand_relevant_text: list[str] = []
    errors: list[str] = []
    counts = {MARKET_VISIBILITY: 0, BRAND_RELEVANT: 0}
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
        )
        if error:
            errors.append(error)
            continue
        counts[cohort] += 1
        intents.add(str(prompt.get("intent") or ""))
        accepted.append(prompt)
        normalized_text = normalize_alias(text)
        accepted_text.append(normalized_text)
        if cohort == BRAND_RELEVANT:
            accepted_brand_relevant_text.append(normalized_text)
    return (
        accepted,
        accepted_text,
        accepted_brand_relevant_text,
        errors,
        counts,
        intents,
    )


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
) -> str:
    if cohort not in {MARKET_VISIBILITY, BRAND_RELEVANT}:
        return f"prompt[{index}].cohort"
    if not theme:
        return f"prompt[{index}].topic"
    if len(text.split()) < 6:
        return f"prompt[{index}].natural_search"
    if _is_near_duplicate(text, accepted_text):
        return f"prompt[{index}].duplicate"
    if intent not in REQUIRED_ONBOARDING_PROMPT_INTENTS:
        return f"prompt[{index}].intent"
    tracked_terms = [*brand_terms, *competitor_terms]
    if contains_tracked_name(text, tracked_terms):
        return f"prompt[{index}].tracked_name"
    if contains_tracked_name(theme, tracked_terms):
        return f"prompt[{index}].tracked_topic_name"
    if not _uses_buyer_perspective(text):
        return f"prompt[{index}].buyer_perspective"
    return ""


def _portfolio_errors(
    *,
    counts,
    expected_counts,
    accepted_text,
    accepted_brand_relevant_text,
    intents,
    primary_market,
    context_terms,
) -> list[str]:
    errors = [
        f"{cohort}.count:{count}"
        for cohort, count in counts.items()
        if count != expected_counts[cohort]
    ]
    if len(accepted_text) != sum(expected_counts.values()):
        errors.append(f"portfolio.count:{len(accepted_text)}")
    if _lacks_market_coverage(primary_market, accepted_text):
        errors.append("portfolio.market_coverage")
    if _lacks_intent_coverage(primary_market, intents):
        errors.append("portfolio.intent_coverage")
    if _lacks_context_coverage(context_terms, accepted_brand_relevant_text):
        errors.append("portfolio.context_coverage")
    return errors


def _lacks_market_coverage(primary_market: str, prompts: list[str]) -> bool:
    return bool(primary_market) and not any(
        _mentions_market(text, primary_market) for text in prompts
    )


def _lacks_intent_coverage(primary_market: str, intents: set[str]) -> bool:
    return bool(primary_market) and not REQUIRED_ONBOARDING_PROMPT_INTENTS.issubset(
        intents
    )


def _lacks_context_coverage(
    context_terms: list[str] | None, brand_relevant_prompts: list[str]
) -> bool:
    return bool(context_terms) and not _has_context_coverage(
        brand_relevant_prompts, context_terms or []
    )


def _mentions_market(text: str, primary_market: str) -> bool:
    terms = MARKET_CONTEXT_TERMS.get(primary_market)
    if terms is None:
        return bool(re.search(rf"\b{re.escape(primary_market)}\b", text))
    return any(
        normalize_alias(term) in normalize_alias(text)
        for term in terms
        if normalize_alias(term)
    )


def _has_context_coverage(prompts: list[str], context_terms: list[str]) -> bool:
    combined = " ".join(prompts)
    normalized_terms = {
        normalize_alias(term) for term in context_terms if normalize_alias(term)
    }
    # Requiring every supplied phrase made otherwise natural searches repeat
    # mechanical context clauses. Two distinct verified concepts are enough
    # to prove grounding while leaving the portfolio conversational.
    required = min(2, len(normalized_terms))
    covered = sum(term in combined for term in normalized_terms)
    return covered >= required
