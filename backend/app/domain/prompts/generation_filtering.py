"""Deterministic cohort and style filters for generated prompt suggestions."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from app.core.config.prompts import PROMPT_NEAR_DUPLICATE_SIMILARITY
from app.core.config.visibility_prompts import (
    VISIBILITY_MAX_SHARED_OPENINGS,
    VISIBILITY_PROMPT_MAX_WORDS,
    VISIBILITY_PROMPT_MIN_WORDS,
    brand_cohort_system_prompt,
    prompt_system_prompt,
)
from app.domain.prompts.generation_contract import SuggestedPrompt, SuggestedTopic
from app.domain.prompts.portfolio import contains_tracked_name, prompt_identity_is_valid
from app.domain.prompts.style import (
    opening_key,
    positioning_shingles,
    repeats_positioning,
    starts_with_template,
    words,
)


def _identity_terms(brand_context: dict[str, Any]) -> tuple[list[str], list[str]]:
    brand_names = [
        brand_context.get("brand_name", ""),
        *brand_context.get("brand_aliases", []),
    ]
    competitor_names = [
        name
        for competitor in brand_context.get("competitors", [])
        for name in [competitor.get("name", ""), *competitor.get("aliases", [])]
    ]
    return (
        [str(name) for name in brand_names],
        [str(name) for name in competitor_names],
    )


def _positioning_shingles(brand_context: dict[str, Any]) -> frozenset[str]:
    knowledge = brand_context.get("knowledge_base") or {}
    return positioning_shingles(
        [
            str(knowledge.get(field) or "")
            for field in ("description", "positioning", "target_audience")
        ]
    )


def _style_is_valid(
    prompt: SuggestedPrompt,
    normalized: str,
    accepted: list[str],
    *,
    positioning: frozenset[str],
    openings: dict[str, int],
) -> bool:
    if not (
        VISIBILITY_PROMPT_MIN_WORDS
        <= len(words(prompt.text))
        <= VISIBILITY_PROMPT_MAX_WORDS
    ):
        return False
    if starts_with_template(prompt.text) or repeats_positioning(
        prompt.text, positioning
    ):
        return False
    if any(
        SequenceMatcher(None, normalized, previous).ratio()
        >= PROMPT_NEAR_DUPLICATE_SIMILARITY
        for previous in accepted
    ):
        return False
    opening = opening_key(prompt.text)
    if openings.get(opening, 0) >= VISIBILITY_MAX_SHARED_OPENINGS:
        return False
    openings[opening] = openings.get(opening, 0) + 1
    return True


def _identity_is_valid(
    prompt: SuggestedPrompt,
    *,
    cohort: str,
    brand_terms: list[str],
    competitor_terms: list[str],
) -> bool:
    return bool(prompt.intent) and prompt_identity_is_valid(
        text=prompt.text,
        cohort=cohort,
        intent=prompt.intent,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
    )


def _filter_commerce_prompts(
    suggestions: list[SuggestedTopic], brand_context: dict[str, Any]
) -> list[SuggestedTopic]:
    """Keep one generic buyer-destination question for each Commerce intent."""
    all_names = _commerce_product_names(brand_context)
    filtered: list[SuggestedTopic] = []
    for topic in suggestions:
        chosen: dict[str, SuggestedPrompt] = {}
        for prompt in topic.prompts:
            intent = prompt.intent
            if (
                intent in {"discovery", "comparison"}
                and intent not in chosen
                and not contains_tracked_name(prompt.text, all_names)
            ):
                chosen[intent] = prompt
        prompts = [
            chosen[intent] for intent in ("discovery", "comparison") if intent in chosen
        ]
        if prompts:
            filtered.append(
                SuggestedTopic(
                    topic_id=topic.topic_id, name=topic.name, prompts=prompts
                )
            )
    return filtered


def _prompt_is_valid(
    prompt: SuggestedPrompt,
    *,
    cohort: str,
    normalized: str,
    accepted: list[str],
    positioning: frozenset[str],
    openings: dict[str, int],
    brand_terms: list[str],
    competitor_terms: list[str],
) -> bool:
    return _identity_is_valid(
        prompt,
        cohort=cohort,
        brand_terms=brand_terms,
        competitor_terms=competitor_terms,
    ) and _style_is_valid(
        prompt,
        normalized,
        accepted,
        positioning=positioning,
        openings=openings,
    )


def _commerce_product_names(brand_context: dict[str, Any]) -> list[str]:
    products = brand_context.get("commerce_products", [])
    return [str(product.get("name") or "") for product in products]


def _drop_invalid_prompts(
    suggestions: list[SuggestedTopic],
    brand_context: dict[str, Any],
    *,
    cohort: str,
) -> list[SuggestedTopic]:
    """Apply identity, buyer-style, opening, and duplicate rules."""
    accepted: list[str] = []
    openings: dict[str, int] = {}
    positioning = _positioning_shingles(brand_context)
    brand_terms, competitor_terms = _identity_terms(brand_context)
    topics: list[SuggestedTopic] = []
    for topic in suggestions:
        rows: list[SuggestedPrompt] = []
        for prompt in topic.prompts:
            normalized = " ".join(prompt.text.casefold().split())
            if not _prompt_is_valid(
                prompt,
                cohort=cohort,
                normalized=normalized,
                accepted=accepted,
                positioning=positioning,
                openings=openings,
                brand_terms=brand_terms,
                competitor_terms=competitor_terms,
            ):
                continue
            accepted.append(normalized)
            rows.append(prompt)
        if rows:
            topics.append(
                SuggestedTopic(topic_id=topic.topic_id, name=topic.name, prompts=rows)
            )
    return topics


def _drop_invalid_core_prompts(
    suggestions: list[SuggestedTopic], brand_context: dict[str, Any]
) -> list[SuggestedTopic]:
    return _drop_invalid_prompts(suggestions, brand_context, cohort="core")


def filter_for_cohort(
    suggestions: list[SuggestedTopic], cohort: str, brand_context: dict[str, Any]
) -> list[SuggestedTopic]:
    if cohort == "commerce":
        return _filter_commerce_prompts(suggestions, brand_context)
    return _drop_invalid_prompts(suggestions, brand_context, cohort=cohort)


def business_model(brand_context: dict[str, Any]) -> str:
    context = brand_context.get("business_context") or {}
    return str(context.get("business_model") or "")


def generation_system_prompt(cohort: str, brand_context: dict[str, Any]) -> str:
    model = business_model(brand_context)
    if cohort == "core":
        return prompt_system_prompt(model)
    return brand_cohort_system_prompt(model, cohort)
