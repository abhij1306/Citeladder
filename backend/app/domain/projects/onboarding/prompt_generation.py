"""Hybrid industry-library and model-personalized prompt generation."""

from __future__ import annotations

import re

from app.core.config.brand_discovery import (
    MARKET_CONTEXT_TERMS,
    PRICE_TIER_QUERY_MODIFIERS,
    brand_discovery_settings,
)
from app.domain.projects.onboarding.industry_library import load_industry_library
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_RELEVANT,
    MARKET_VISIBILITY,
    PromptQualityResult,
    validate_portfolio,
)

_INTENTS = ("discovery", "service", "comparison", "purchase", "local")


def _render_search(template: str, values: dict[str, str]) -> str:
    """Render one complete search without bolting extra clauses onto it."""
    rendered = " ".join(template.format(**values).split())
    return re.sub(r"\b(\w+)\s+\1\b", r"\1", rendered, flags=re.IGNORECASE)


def fallback_portfolio(
    *,
    primary_market: str,
    industry: str,
    industry_context: dict,
    products_services: list[str],
    target_audience: str = "",
    price_tier: str = "unknown",
) -> list[dict]:
    """Build a complete editable portfolio when application-model research fails."""
    market_categories, brand_categories, uses, persona = _fallback_context(
        industry, industry_context, products_services, target_audience
    )
    library = load_industry_library()
    market_templates, brand_templates = _fallback_templates(library, industry_context)
    market = _build_fallback_cohort(
        count=brand_discovery_settings.market_prompt_count,
        templates=market_templates,
        categories=market_categories,
        uses=uses,
        persona=persona,
        primary_market=primary_market,
        price_tier=price_tier,
        cohort=MARKET_VISIBILITY,
    )
    brand_relevant = _build_fallback_cohort(
        count=brand_discovery_settings.brand_relevant_prompt_count,
        templates=brand_templates,
        categories=brand_categories,
        uses=uses,
        persona=persona,
        primary_market=primary_market,
        price_tier=price_tier,
        cohort=BRAND_RELEVANT,
    )
    return [*market, *brand_relevant]


def _fallback_templates(library: dict, industry_context: dict):
    general = library.get("industries", {}).get("General", {}) or {}
    market_templates = list(industry_context.get("archetypes") or []) or list(
        general.get("archetypes") or []
    )
    brand_templates = list(library.get("brand_relevant_archetypes") or [])
    missing_template_groups = [
        name
        for name, templates in (
            ("market archetypes", market_templates),
            ("brand-relevant archetypes", brand_templates),
        )
        if not templates
    ]
    if missing_template_groups:
        raise RuntimeError(
            "Industry prompt library is missing " + ", ".join(missing_template_groups)
        )
    return market_templates, brand_templates


def _build_fallback_cohort(
    *, count, templates, categories, uses, persona, primary_market, price_tier, cohort
):
    return [
        _fallback_prompt(
            index=index,
            template=templates[index % len(templates)],
            categories=categories,
            uses=uses,
            persona=persona,
            primary_market=primary_market,
            price_tier=price_tier,
            cohort=cohort,
        )
        for index in range(count)
    ]


def _fallback_prompt(
    *, index, template, categories, uses, persona, primary_market, price_tier, cohort
):
    return {
        "text": _render_search(
            template,
            _fallback_values(
                index,
                primary_market,
                categories,
                uses,
                persona,
                price_tier,
            ),
        ),
        "theme": _topic_name(categories[index % len(categories)]),
        "intent": _INTENTS[index % len(_INTENTS)],
        "cohort": cohort,
    }


def _fallback_values(index, market, categories, uses, persona, price_tier):
    return {
        "market": MARKET_CONTEXT_TERMS.get(market, (market,))[0],
        "category": categories[index % len(categories)],
        "use_case": uses[index % len(uses)],
        "persona": persona,
        "quality": PRICE_TIER_QUERY_MODIFIERS.get(
            price_tier, PRICE_TIER_QUERY_MODIFIERS["unknown"]
        ),
    }


def _fallback_context(industry, industry_context, products_services, target_audience):
    generic_category = {"General": "general options"}.get(industry, industry.casefold())
    market_categories = _normalized_categories(industry_context.get("topics"))
    if not market_categories:
        market_categories = [generic_category]
    brand_categories = _normalized_categories(products_services)
    if not brand_categories:
        brand_categories = list(market_categories)
    uses = _values_or_default(industry_context.get("use_cases"), "their needs")
    reviewed_audience = str(target_audience).strip()
    persona = (
        f"my needs as {reviewed_audience}"
        if reviewed_audience
        else str(industry_context.get("buyer_persona") or "my needs").strip()
    )
    return market_categories, brand_categories, uses, persona


def _normalized_categories(values) -> list[str]:
    return [
        _natural_category(normalized)
        for item in values or []
        if (normalized := str(item).strip())
    ]


def _natural_category(category: str) -> str:
    category = re.sub(r"\bwomens\b", "women's", category, flags=re.IGNORECASE)
    category = re.sub(r"\bmens\b", "men's", category, flags=re.IGNORECASE)
    category = re.sub(r"\bchildrens\b", "children's", category, flags=re.IGNORECASE)
    return category


def _topic_name(category: str) -> str:
    """Turn a verified offering into a concise topic label for the review rail."""
    return category.strip().rstrip(".?!").title().replace("'S", "'s")


def _values_or_default(values, fallback):
    normalized = list(values or [])
    return normalized or [fallback]


def validated_portfolio(
    model_prompts: list[dict],
    *,
    fallback_prompts: list[dict],
    brand_name: str,
    primary_market: str,
    competitor_terms: list[str],
    context_terms: list[str],
) -> list[dict]:
    result: PromptQualityResult = validate_portfolio(
        model_prompts,
        brand_terms=[brand_name],
        competitor_terms=competitor_terms,
        primary_market=primary_market,
        context_terms=context_terms,
        expected_market_count=brand_discovery_settings.market_prompt_count,
        expected_brand_relevant_count=(
            brand_discovery_settings.brand_relevant_prompt_count
        ),
    )
    if not result.errors:
        return list(result.accepted)
    fallback_result = validate_portfolio(
        fallback_prompts,
        brand_terms=[brand_name],
        competitor_terms=competitor_terms,
        primary_market=primary_market,
        context_terms=context_terms,
        expected_market_count=brand_discovery_settings.market_prompt_count,
        expected_brand_relevant_count=(
            brand_discovery_settings.brand_relevant_prompt_count
        ),
    )
    if fallback_result.errors:
        raise RuntimeError(
            "Config-owned onboarding fallback failed validation: "
            + ", ".join(fallback_result.errors)
        )
    return list(fallback_result.accepted)
