"""Deterministic quality gate for the onboarding prompt portfolio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.analysis.normalization import normalize_alias
from app.core.config.brand_discovery import (
    MARKET_CONTEXT_TERMS,
    REQUIRED_ONBOARDING_PROMPT_INTENTS,
)
from app.domain.prompts.portfolio import prompt_identity_is_valid

MARKET_VISIBILITY = "market_visibility"
BRAND_DIAGNOSTIC = "brand_diagnostic"


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


def validate_portfolio(
    prompts: list[dict],
    *,
    brand_terms: list[str],
    competitor_terms: list[str],
    primary_market: str = "",
    context_terms: list[str] | None = None,
    expected_market_count: int = 5,
    expected_diagnostic_count: int = 5,
) -> PromptQualityResult:
    accepted: list[dict] = []
    accepted_text: list[str] = []
    errors: list[str] = []
    counts = {MARKET_VISIBILITY: 0, BRAND_DIAGNOSTIC: 0}
    intents: set[str] = set()
    expected_counts = {
        MARKET_VISIBILITY: expected_market_count,
        BRAND_DIAGNOSTIC: expected_diagnostic_count,
    }
    for index, prompt in enumerate(prompts):
        text = str(prompt.get("text") or "").strip()
        cohort = str(prompt.get("cohort") or "")
        error = _prompt_error(
            index=index,
            text=text,
            cohort=cohort,
            intent=str(prompt.get("intent") or ""),
            brand_terms=brand_terms,
            competitor_terms=competitor_terms,
            accepted_text=accepted_text,
            primary_market=primary_market,
        )
        if error:
            errors.append(error)
            continue
        counts[cohort] += 1
        intents.add(str(prompt.get("intent") or ""))
        accepted.append(prompt)
        accepted_text.append(normalize_alias(text))
    errors.extend(
        _portfolio_errors(
            counts=counts,
            expected_counts=expected_counts,
            accepted_text=accepted_text,
            intents=intents,
            primary_market=primary_market,
            context_terms=context_terms,
        )
    )
    return PromptQualityResult(tuple(accepted), tuple(errors))


def _prompt_error(
    *,
    index,
    text,
    cohort,
    intent,
    brand_terms,
    competitor_terms,
    accepted_text,
    primary_market,
) -> str:
    if cohort not in {MARKET_VISIBILITY, BRAND_DIAGNOSTIC}:
        return f"prompt[{index}].cohort"
    if len(text.split()) < 6 or not text.endswith("?"):
        return f"prompt[{index}].natural_question"
    if _is_near_duplicate(text, accepted_text):
        return f"prompt[{index}].duplicate"
    if not prompt_identity_is_valid(
        text=text,
        cohort=cohort,
        intent=intent,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
    ):
        reason = "neutrality" if cohort == MARKET_VISIBILITY else "brand_required"
        return f"prompt[{index}].{reason}"
    if primary_market and not _mentions_market(text, primary_market):
        return f"prompt[{index}].market"
    return ""


def _portfolio_errors(
    *, counts, expected_counts, accepted_text, intents, primary_market, context_terms
) -> list[str]:
    errors = [
        f"{cohort}.count:{count}"
        for cohort, count in counts.items()
        if count != expected_counts[cohort]
    ]
    if len(accepted_text) != sum(expected_counts.values()):
        errors.append(f"portfolio.count:{len(accepted_text)}")
    if primary_market and not REQUIRED_ONBOARDING_PROMPT_INTENTS.issubset(intents):
        errors.append("portfolio.intent_coverage")
    if context_terms and not _has_context_coverage(accepted_text, context_terms):
        errors.append("portfolio.context_coverage")
    return errors


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
    required = min(3, len(normalized_terms))
    covered = sum(term in combined for term in normalized_terms)
    return covered >= required
