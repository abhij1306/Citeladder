"""Taxonomy-grounding helpers for generated prompt topics."""

from __future__ import annotations

import re

from app.core.config.prompts import TOPIC_TITLE_MINOR_WORDS
from app.domain.prompts.generation_contract import SuggestedTopic
from app.models.project import Project
from app.models.prompt import Topic

_TOPIC_TOKEN = re.compile(r"[a-z0-9]+")


def _title_case_topic(value: str) -> str:
    words = " ".join(value.strip().rstrip(".?!").split()).split()
    titled: list[str] = []
    for index, word in enumerate(words):
        lowered = word.casefold()
        if index > 0 and lowered in TOPIC_TITLE_MINOR_WORDS:
            titled.append(lowered)
        elif word.isupper() and len(word) > 1:
            titled.append(word)
        else:
            titled.append(word[:1].upper() + word[1:].lower())
    return " ".join(titled)


def _product_service_topic_names(project: Project) -> list[str]:
    brand = project.brand
    profile = brand.profile if brand is not None else None
    values = profile.products_services if profile is not None else []
    names: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        name = _title_case_topic(str(value))
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            names.append(name)
    return names


def _topic_tokens(value: str) -> set[str]:
    return set(_TOPIC_TOKEN.findall(value.casefold()))


def _best_matching_name(tokens: set[str], candidates: list[str]) -> str | None:
    matches = [
        (len(tokens & _topic_tokens(name)), -index, name)
        for index, name in enumerate(candidates)
    ]
    score, _index, name = max(matches, default=(0, 0, ""))
    return name if score > 0 else None


def _canonical_topic_name(
    suggestion: SuggestedTopic,
    *,
    existing: dict[str, str],
    products_by_key: dict[str, str],
    products: list[str],
) -> str | None:
    key = suggestion.name.strip().casefold()
    canonical = existing.get(key) or products_by_key.get(key)
    if canonical is not None:
        return canonical
    tokens = _topic_tokens(
        " ".join([suggestion.name, *(prompt.text for prompt in suggestion.prompts)])
    )
    return _best_matching_name(tokens, products) or _best_matching_name(
        tokens, list(existing.values())
    )


def ground_suggestion_topics(
    suggestions: list[SuggestedTopic],
    *,
    project: Project,
    target_topic: Topic | None,
) -> list[SuggestedTopic]:
    """Bind model labels to persisted or confirmed product taxonomy."""
    if target_topic is not None:
        return [
            SuggestedTopic(name=target_topic.name, prompts=topic.prompts)
            for topic in suggestions
        ]

    existing = {topic.name.casefold(): topic.name for topic in project.topics}
    products = _product_service_topic_names(project)
    products_by_key = {name.casefold(): name for name in products}
    return [
        SuggestedTopic(name=canonical, prompts=suggestion.prompts)
        for suggestion in suggestions
        if (
            canonical := _canonical_topic_name(
                suggestion,
                existing=existing,
                products_by_key=products_by_key,
                products=products,
            )
        )
    ]
