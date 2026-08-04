"""Shared identity policy for neutral and named-comparison prompts."""

from __future__ import annotations

from collections.abc import Iterable

from app.analysis.normalization import alias_present, normalize_alias


def contains_tracked_name(text: str, names: Iterable[str]) -> bool:
    """Return whether text names any tracked identity using token boundaries."""
    normalized_text = normalize_alias(text)
    return any(
        normalized_name and alias_present(normalized_name, normalized_text)
        for name in names
        if (normalized_name := normalize_alias(name))
    )


def prompt_identity_is_valid(
    *,
    text: str,
    cohort: str,
    intent: str,
    brand_terms: Iterable[str],
    competitor_terms: Iterable[str],
) -> bool:
    """Enforce neutral measurement prompts and explicit diagnostic identity."""
    names_brand = contains_tracked_name(text, brand_terms)
    names_competitor = contains_tracked_name(text, competitor_terms)
    if cohort in {"core", "market_visibility"}:
        return not names_brand and not names_competitor
    if cohort == "brand_diagnostic":
        return names_brand
    return _is_named_comparison(intent, names_brand, names_competitor)


def _is_named_comparison(intent, names_brand, names_competitor):
    return intent == "comparison" and names_brand and names_competitor
