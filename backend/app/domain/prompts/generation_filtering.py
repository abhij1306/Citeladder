"""Cohort filtering for generated prompt suggestions.

Thin by design. The cross-prompt rules live in one place --
``domain/prompts/portfolio_validation.py`` -- and this module's job is only to
build that validator from a project's brand context and feed the parsed
suggestions through it.

It used to reimplement those rules, and the copy had drifted: it never expanded
a brand's short forms, never capped market mentions per topic, and used a
different near-duplicate threshold. A portfolio generated from the "Generate
prompts" button was therefore judged more loosely than the same project's
onboarding portfolio, which is how prompts that all ended "in Australia" and
organic prompts naming the tracked brand reached a customer.
"""

from __future__ import annotations

from typing import Any

from app.core.config.prompts import PROMPT_GROUNDING_BUSINESS_CONTEXT_FIELDS
from app.core.config.visibility_prompt_vocabulary import PRICE_WORDS, SELECTION_WORDS
from app.core.config.visibility_prompts import (
    brand_cohort_system_prompt,
    prompt_system_prompt,
)
from app.domain.prompts.generation_contract import SuggestedPrompt, SuggestedTopic
from app.domain.prompts.portfolio import contains_tracked_name
from app.domain.prompts.portfolio_validation import (
    PortfolioValidator,
    brand_terms,
    market_terms,
    positioning_shingles,
)
from app.domain.prompts.style import words


def _competitor_terms(brand_context: dict[str, Any]) -> list[str]:
    return [
        str(name)
        for competitor in brand_context.get("competitors", [])
        for name in [competitor.get("name", ""), *competitor.get("aliases", [])]
        if str(name)
    ]


def _category_vocabulary(brand_context: dict[str, Any]) -> list[str]:
    """The business's own category words, which are never brand tokens.

    Same escape hatch onboarding uses: a token the confirmed category uses is
    category language first, so "Red Dress" does not ban "dress" and empty its
    own organic cohort.
    """
    context = brand_context.get("business_context") or {}
    values: list[str] = []
    for field in PROMPT_GROUNDING_BUSINESS_CONTEXT_FIELDS:
        value = context.get(field)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value)
    return values


def build_validator(
    suggestions_topic_ids: frozenset[str], brand_context: dict[str, Any]
) -> PortfolioValidator:
    """The same validator onboarding builds, from an existing project's context."""
    knowledge = brand_context.get("knowledge_base") or {}
    context = brand_context.get("business_context") or {}
    return PortfolioValidator(
        topic_ids=suggestions_topic_ids,
        brand_terms=brand_terms(
            str(brand_context.get("brand_name") or ""),
            [str(alias) for alias in brand_context.get("brand_aliases") or []],
            _category_vocabulary(brand_context),
        ),
        competitor_terms=_competitor_terms(brand_context),
        positioning=positioning_shingles(
            [
                str(knowledge.get(field) or "")
                for field in ("description", "positioning", "target_audience")
            ]
        ),
        market_words=market_terms(
            str(brand_context.get("country_code") or ""),
            [str(area) for area in context.get("service_areas") or []],
        ),
    )


def _commerce_product_names(
    brand_context: dict[str, Any], *, category: str | None = None
) -> list[str]:
    products = brand_context.get("commerce_products", [])
    category_identity = str(category or "").strip().casefold()
    names = [
        str(product.get("name") or "")
        for product in products
        if not category_identity
        or str(product.get("category") or "").strip().casefold() == category_identity
    ]
    return sorted(names, key=lambda name: len(name.casefold()), reverse=True)


def _filter_commerce_prompts(
    suggestions: list[SuggestedTopic], brand_context: dict[str, Any]
) -> list[SuggestedTopic]:
    """Keep named buyer questions; unnamed category prompts are not measurable."""
    filtered: list[SuggestedTopic] = []
    for topic in suggestions:
        all_names = _commerce_product_names(brand_context, category=topic.name)
        chosen: dict[tuple[str, str], SuggestedPrompt] = {}
        for prompt in topic.prompts:
            intent = prompt.intent
            matched_name = next(
                (
                    name
                    for name in all_names
                    if contains_tracked_name(prompt.text, [name])
                ),
                None,
            )
            if intent in {"discovery", "comparison"} and matched_name:
                chosen.setdefault((matched_name.casefold(), intent), prompt)
        prompts = list(chosen.values())
        if prompts:
            filtered.append(
                SuggestedTopic(
                    topic_id=topic.topic_id, name=topic.name, prompts=prompts
                )
            )
    return filtered


def _drop_invalid_prompts(
    suggestions: list[SuggestedTopic],
    *,
    cohort: str,
    validator: PortfolioValidator,
) -> list[SuggestedTopic]:
    """Offer every suggestion to the run's validator, keeping what it admits."""
    topics: list[SuggestedTopic] = []
    for topic in suggestions:
        rows = [
            prompt
            for prompt in topic.prompts
            if not validator.offer(
                {
                    "slot_id": prompt.slot_id,
                    "topic_id": str(topic.topic_id),
                    "text": prompt.text,
                    "intent": prompt.intent,
                    "buyer_stage": prompt.buyer_stage,
                    "prompt_intent": prompt.prompt_intent,
                    "archetype": prompt.archetype,
                },
                cohort=cohort,
            )
        ]
        if rows:
            topics.append(
                SuggestedTopic(topic_id=topic.topic_id, name=topic.name, prompts=rows)
            )
    return topics


def filter_for_cohort(
    suggestions: list[SuggestedTopic],
    cohort: str,
    brand_context: dict[str, Any],
    *,
    validator: PortfolioValidator | None = None,
) -> list[SuggestedTopic]:
    """Admit suggestions for one cohort.

    ``validator`` is owned by the caller so the portfolio-wide rules -- opening
    diversity, near-duplicates, the per-topic market cap -- accumulate across
    every model call in one run. Batches are one topic wide, so a per-batch
    validator only ever compared a topic against itself.
    """
    if cohort == "commerce":
        return _filter_commerce_prompts(suggestions, brand_context)
    if validator is None:
        validator = build_validator(
            frozenset(str(topic.topic_id) for topic in suggestions), brand_context
        )
    return _drop_invalid_prompts(suggestions, cohort=cohort, validator=validator)


# Commercial qualifiers a prompt may reach for. Offered to the model, never
# required: "cheap", "affordable" and "best value" run through every good
# best&less query because value IS that brand's positioning, and inventing the
# same words for a premium brand would be a fabricated constraint.
_QUALIFIER_VOCABULARY = SELECTION_WORDS | PRICE_WORDS


def supported_qualifiers(brand_context: dict[str, Any]) -> tuple[str, ...]:
    """Qualifier words the brand's own confirmed copy and demand data use.

    Grounding, not decoration: only words already present in the positioning,
    description, audience or observed demand clusters are offered, so the model
    cannot justify "affordable" for a business that never claims it.
    """
    knowledge = brand_context.get("knowledge_base") or {}
    sources = [
        str(knowledge.get(field) or "")
        for field in ("description", "positioning", "target_audience")
    ]
    sources += [
        str(signal.get("topic") or "")
        for signal in brand_context.get("demand_signals") or []
    ]
    found = {token for source in sources for token in words(source)}
    return tuple(sorted(found & _QUALIFIER_VOCABULARY))


def business_model(brand_context: dict[str, Any]) -> str:
    context = brand_context.get("business_context") or {}
    return str(context.get("business_model") or "")


def generation_system_prompt(cohort: str, brand_context: dict[str, Any]) -> str:
    model = business_model(brand_context)
    if cohort == "core":
        return prompt_system_prompt(model)
    return brand_cohort_system_prompt(model, cohort)
