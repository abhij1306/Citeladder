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


def _render_search(template: str, values: dict[str, str]) -> str:
    """Render one complete search without bolting extra clauses onto it."""
    rendered = " ".join(template.format(**values).split())
    rendered = re.sub(r"\b(\w+)\s+\1\b", r"\1", rendered, flags=re.IGNORECASE)
    # A slot value that ended in its own sentence punctuation used to collide
    # with the template's ("...trusted delivery.?"). Keep the template's mark.
    return re.sub(r"[.!?]+(?=[.!?])", "", rendered)


def _mid_sentence(value: str) -> str:
    """Lower-case a slot value that is only sentence-cased, not a proper noun.

    Verified offerings and topics arrive title/sentence-cased ("Consumer
    electronics", "Online retail marketplace") and were dropped verbatim into
    the middle of a question. Acronyms and real proper nouns ("SaaS", "iPhone",
    "NDIS") keep their casing because their first word is not plain
    capitalised-then-lowercase.
    """
    text = value.strip()
    first = text.split(" ", 1)[0]
    if not first[:1].isupper() or not first[1:].islower():
        return text
    return text[:1].lower() + text[1:]


def _trimmed_phrase(value: str) -> str:
    """Collapse whitespace and drop a slot value's own trailing punctuation."""
    return " ".join(str(value).split()).rstrip(".!?,;:")


def _slot_phrase(value: str) -> str:
    """Normalize a CATEGORY-style slot value for mid-sentence interpolation.

    Only for values drawn from the curated topic / verified-offering lists,
    which are sentence-cased labels. Free prose (the reviewed target audience)
    uses ``_trimmed_phrase`` instead — lower-casing it would wreck proper
    adjectives like "Indian households".
    """
    return _mid_sentence(_trimmed_phrase(value))


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
            template["text"],
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
        # The template owns its intent. Cycling a fixed intent tuple by loop
        # position produced labels that contradicted the wording (a "which
        # stores can I trust" search tagged `local`) and made every downstream
        # intent filter meaningless.
        "intent": template["intent"],
        "cohort": cohort,
    }


def _fallback_values(index, market, categories, uses, persona, price_tier):
    return {
        "market": MARKET_CONTEXT_TERMS.get(market, (market,))[0],
        "category": _slot_phrase(categories[index % len(categories)]),
        "use_case": _slot_phrase(uses[index % len(uses)]),
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
    # The reviewed audience is free text ending in its own punctuation; it is
    # interpolated mid-question, so it has to be trimmed and lower-cased first.
    reviewed_audience = _trimmed_phrase(target_audience)
    persona = (
        f"my needs as {reviewed_audience}"
        if reviewed_audience
        else _trimmed_phrase(industry_context.get("buyer_persona") or "my needs")
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
    banned_patterns: list[re.Pattern[str]] | None = None,
) -> list[dict]:
    """Prefer the model's portfolio; fall back to templates; never raise.

    This used to raise ``RuntimeError`` when the deterministic fallback failed
    its own gate, which is not a theoretical path: running the real pipeline
    over eleven well-known brands crashed on two of them, because a discovered
    offering happened to contain a competitor's name. That exception propagated
    out of ``complete_discovery``, so the user could not create the project at
    all.

    A partial portfolio is always better than a failed onboarding, so the worst
    case now degrades to the largest surviving set and lets the caller warn.
    """

    def _run(candidates: list[dict], *, ban_templates: bool) -> PromptQualityResult:
        return validate_portfolio(
            candidates,
            brand_terms=[brand_name],
            competitor_terms=competitor_terms,
            primary_market=primary_market,
            context_terms=context_terms,
            banned_patterns=banned_patterns if ban_templates else None,
        )

    # The template ban applies to the model's reply only. Applying it to the
    # fallback would make that path reject itself -- these prompts *are* the
    # templates, and a degraded portfolio is still better than none.
    result = _run(model_prompts, ban_templates=True)
    if _is_usable(result):
        return list(result.accepted)
    fallback_result = _run(fallback_prompts, ban_templates=False)
    if not fallback_result.errors:
        return list(fallback_result.accepted)
    best = max((result.accepted, fallback_result.accepted), key=len)
    return list(best)


def _is_usable(result: PromptQualityResult) -> bool:
    """Keep the model's portfolio unless something is wrong with it *as a set*.

    Per-prompt rejections are the gate doing its job, not a reason to throw the
    portfolio away: discarding twelve good model-written prompts because a
    thirteenth was a duplicate silently handed the whole portfolio back to the
    templates, and the eval caught it as `template_tell` snapping back to 1.0.
    Only portfolio-level faults -- too few prompts, no grounding, no intent
    spread -- justify falling back.
    """
    portfolio_errors = [
        error for error in result.errors if not error.startswith("prompt[")
    ]
    return bool(result.accepted) and not portfolio_errors
