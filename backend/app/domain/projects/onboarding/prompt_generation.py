"""Hybrid industry-library and model-personalized prompt generation."""

from __future__ import annotations

import re

from app.core.config.brand_discovery import (
    MARKET_CONTEXT_TERMS,
    brand_discovery_settings,
)
from app.domain.projects.onboarding.industry_library import load_industry_library
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_DIAGNOSTIC,
    MARKET_VISIBILITY,
    PromptQualityResult,
    validate_portfolio,
)

_INTENTS = ("discovery", "service", "comparison", "purchase", "local")


def _localized_question(template: str, values: dict[str, str]) -> str:
    question = _ensure_use_case(template.format(**values), values["use_case"])
    return _ensure_market(question, values["market_code"])


def _ensure_use_case(question: str, use_case: str) -> str:
    if use_case.casefold() in question.casefold():
        return question
    return question.removesuffix("?") + f" for {use_case}?"


def _ensure_market(question: str, market: str) -> str:
    terms = MARKET_CONTEXT_TERMS.get(market, (market,))
    if any(
        re.search(rf"\b{re.escape(term)}\b", question, re.IGNORECASE) for term in terms
    ):
        return question
    return question.removesuffix("?") + f" in {terms[0]}?"


def fallback_portfolio(
    *,
    brand_name: str,
    primary_market: str,
    industry: str,
    industry_context: dict,
    products_services: list[str],
    target_audience: str,
) -> list[dict]:
    """Build a complete editable portfolio when application-model research fails."""
    categories, audience, uses = _fallback_context(
        industry, industry_context, products_services, target_audience
    )

    market_templates = list(industry_context.get("archetypes") or [])
    diagnostic_templates = list(
        load_industry_library().get("brand_diagnostic_archetypes") or []
    )
    market_count = brand_discovery_settings.market_prompt_count
    diagnostic_count = brand_discovery_settings.diagnostic_prompt_count
    topics = list(industry_context.get("topics") or [industry])
    market = [
        {
            "text": _localized_question(
                template,
                _fallback_values(
                    index, brand_name, primary_market, categories, audience, uses
                ),
            ),
            "theme": str(topics[index % len(topics)]),
            "intent": _INTENTS[index % len(_INTENTS)],
            "cohort": MARKET_VISIBILITY,
        }
        for index in range(market_count)
        for template in [market_templates[index % len(market_templates)]]
    ]
    diagnostic = [
        {
            "text": _localized_question(
                template,
                _fallback_values(
                    index, brand_name, primary_market, categories, audience, uses
                ),
            ),
            "theme": str(topics[index % len(topics)]),
            "intent": _INTENTS[index % len(_INTENTS)],
            "cohort": BRAND_DIAGNOSTIC,
        }
        for index in range(diagnostic_count)
        for template in [diagnostic_templates[index % len(diagnostic_templates)]]
    ]
    return [*market, *diagnostic]


def _fallback_values(index, brand, market, categories, audience, uses):
    return {
        "brand": brand,
        "market": MARKET_CONTEXT_TERMS.get(market, (market,))[0],
        "market_code": market,
        "category": categories[index % len(categories)],
        "audience": audience,
        "use_case": uses[index % len(uses)],
    }


def _fallback_context(industry, industry_context, products_services, target_audience):
    categories = [str(item).strip() for item in products_services if str(item).strip()]
    if not categories:
        categories = [
            industry.casefold() if industry != "General" else "products and services"
        ]
    audiences = list(industry_context.get("customer_types") or [])
    uses = _values_or_default(industry_context.get("use_cases"), "their needs")
    audience = target_audience.strip() or (audiences[0] if audiences else "buyers")
    return categories, audience, uses


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
) -> tuple[list[dict], list[str]]:
    localized_model_prompts = [
        {
            **prompt,
            "text": _ensure_market(str(prompt.get("text", "")), primary_market),
        }
        for prompt in model_prompts
    ]
    result: PromptQualityResult = validate_portfolio(
        localized_model_prompts,
        brand_terms=[brand_name],
        competitor_terms=competitor_terms,
        primary_market=primary_market,
        context_terms=context_terms,
        expected_market_count=brand_discovery_settings.market_prompt_count,
        expected_diagnostic_count=brand_discovery_settings.diagnostic_prompt_count,
    )
    if not result.errors:
        return list(result.accepted), []
    fallback_result = validate_portfolio(
        fallback_prompts,
        brand_terms=[brand_name],
        competitor_terms=competitor_terms,
        primary_market=primary_market,
        context_terms=context_terms,
        expected_market_count=brand_discovery_settings.market_prompt_count,
        expected_diagnostic_count=brand_discovery_settings.diagnostic_prompt_count,
    )
    if fallback_result.errors:
        raise RuntimeError(
            "Config-owned onboarding fallback failed validation: "
            + ", ".join(fallback_result.errors)
        )
    return list(fallback_result.accepted), ["research_degraded"]
