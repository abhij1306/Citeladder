"""Deterministic buyer-query slot planning and pattern validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analysis.normalization import normalize_alias
from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_CORE,
    TOPICAL_BINDING_STOPWORDS,
)
from app.core.config.visibility_prompts import (
    BUYER_QUERY_BEST_FOR,
    BUYER_QUERY_BRAND_COMPARISON,
    BUYER_QUERY_BRAND_FIT,
    BUYER_QUERY_BRAND_OVERVIEW,
    BUYER_QUERY_BRAND_PATTERNS,
    BUYER_QUERY_CORE_PATTERNS,
    BUYER_QUERY_HOW_TO,
    BUYER_QUERY_INTENT_PATTERNS,
    BUYER_QUERY_PATTERN_INSTRUCTIONS,
    BUYER_QUERY_PATTERN_INTENTS,
    BUYER_QUERY_PRICING,
    BUYER_QUERY_WHAT_IS,
)
from app.domain.prompts.normalization import prompt_text_hash
from app.domain.prompts.portfolio import contains_tracked_name


@dataclass(frozen=True, slots=True)
class PromptSlot:
    """One code-owned model task. Only ``text`` comes back from the model."""

    slot_id: str
    topic_id: str | None
    topic_name: str
    topic_description: str
    pattern: str
    intent: str
    cohort: str
    brand_name: str = ""
    competitor_names: tuple[str, ...] = ()

    def as_model_input(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "topic": self.topic_name,
            "topic_description": self.topic_description,
            "pattern": self.pattern,
            "pattern_instruction": BUYER_QUERY_PATTERN_INSTRUCTIONS[self.pattern],
            "brand": self.brand_name,
            "competitors": list(self.competitor_names),
        }


@dataclass(frozen=True, slots=True)
class PlannedPrompt:
    slot_id: str
    topic_id: str | None
    text: str
    intent: str
    cohort: str
    pattern: str


def _topic_fields(topic: Any) -> tuple[str, str, str]:
    if isinstance(topic, dict):
        return (
            str(topic.get("id") or topic.get("topic_id") or ""),
            str(topic.get("name") or ""),
            str(topic.get("description") or ""),
        )
    return (
        str(getattr(topic, "id", None) or getattr(topic, "topic_id", "")),
        str(getattr(topic, "name", "")),
        str(getattr(topic, "description", "") or ""),
    )


def _explicit_recipe(intents: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    recipe: list[tuple[str, str]] = []
    for intent in intents:
        for pattern in BUYER_QUERY_INTENT_PATTERNS.get(intent, ()):
            recipe.append((pattern, intent))
    return tuple(recipe)


def _core_recipe(intents: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    if intents:
        return _explicit_recipe(intents)
    return tuple(
        (pattern, BUYER_QUERY_PATTERN_INTENTS[pattern])
        for pattern in BUYER_QUERY_CORE_PATTERNS
    )


def _named_recipe(cohort: str) -> tuple[tuple[str, str], ...]:
    patterns = (
        BUYER_QUERY_BRAND_PATTERNS
        if cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC
        else (BUYER_QUERY_BRAND_COMPARISON,)
    )
    return tuple(
        (pattern, BUYER_QUERY_PATTERN_INTENTS[pattern]) for pattern in patterns
    )


def build_prompt_slots(
    *,
    topics: list[Any],
    count: int,
    cohort: str,
    intents: tuple[str, ...] = (),
    brand_name: str = "",
    competitor_names: tuple[str, ...] = (),
    unbound_brand_diagnostic: bool = False,
) -> list[PromptSlot]:
    """Plan exact topic/pattern slots with topic-first, pattern-balanced order."""
    if count <= 0 or not topics:
        return []
    recipe = (
        _core_recipe(intents) if cohort == PROMPT_COHORT_CORE else _named_recipe(cohort)
    )
    if not recipe:
        return []
    topic_rows = [_topic_fields(topic) for topic in topics]
    slots: list[PromptSlot] = []
    limit = min(count, len(topic_rows) * len(recipe))
    for index in range(limit):
        topic_index = index % len(topic_rows)
        round_index = index // len(topic_rows)
        pattern, intent = recipe[(topic_index + round_index) % len(recipe)]
        topic_id, name, description = topic_rows[topic_index]
        slots.append(
            PromptSlot(
                slot_id=f"q{index + 1}",
                topic_id=(
                    None
                    if cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC
                    and unbound_brand_diagnostic
                    else topic_id
                ),
                topic_name=name,
                topic_description=description,
                pattern=pattern,
                intent=intent,
                cohort=cohort,
                brand_name=brand_name,
                competitor_names=competitor_names,
            )
        )
    return slots


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in normalize_alias(value).split()
        if len(token) >= 3 and token not in TOPICAL_BINDING_STOPWORDS
    }


def _topic_is_bound(text: str, slot: PromptSlot) -> bool:
    expected = _tokens(f"{slot.topic_name} {slot.topic_description}")
    return bool(expected and expected & _tokens(text))


def _what_is_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return normalized.startswith("what is ") and _topic_is_bound(text, slot)


def _best_for_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return (
        normalized.startswith("best ")
        and " for " in f" {normalized} "
        and _topic_is_bound(text, slot)
    )


def _how_to_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return normalized.startswith("how to ") and _topic_is_bound(text, slot)


def _pricing_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    pricing = {"price", "prices", "pricing", "cost", "costs"}
    return bool(pricing & set(normalized.split())) and _topic_is_bound(text, slot)


def _brand_overview_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return normalized.startswith("what is ") and contains_tracked_name(
        text, [slot.brand_name]
    )


def _brand_fit_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return (
        normalized.startswith("is ")
        and " good for " in f" {normalized} "
        and contains_tracked_name(text, [slot.brand_name])
    )


def _brand_comparison_valid(text: str, slot: PromptSlot, normalized: str) -> bool:
    return (
        bool({"vs", "versus"} & set(normalized.split()))
        and contains_tracked_name(text, [slot.brand_name])
        and contains_tracked_name(text, slot.competitor_names)
    )


_PATTERN_VALIDATORS = {
    BUYER_QUERY_WHAT_IS: _what_is_valid,
    BUYER_QUERY_BEST_FOR: _best_for_valid,
    BUYER_QUERY_HOW_TO: _how_to_valid,
    BUYER_QUERY_PRICING: _pricing_valid,
    BUYER_QUERY_BRAND_OVERVIEW: _brand_overview_valid,
    BUYER_QUERY_BRAND_FIT: _brand_fit_valid,
    BUYER_QUERY_BRAND_COMPARISON: _brand_comparison_valid,
}


def _pattern_shape_is_valid(text: str, slot: PromptSlot) -> bool:
    normalized = normalize_alias(text)
    validator = _PATTERN_VALIDATORS.get(slot.pattern)
    return bool(validator and validator(text, slot, normalized))


def resolve_planned_prompts(
    rows: list[tuple[str, str]], slots: list[PromptSlot]
) -> tuple[list[PlannedPrompt], int]:
    """Resolve model rows through exact slot and pattern gates."""
    slots_by_id = {slot.slot_id: slot for slot in slots}
    accepted: list[PlannedPrompt] = []
    seen_slots: set[str] = set()
    seen_text: set[str] = set()
    dropped = 0
    for slot_id, raw_text in rows:
        slot = slots_by_id.get(slot_id)
        text = " ".join(raw_text.split())
        text_key = prompt_text_hash(text)
        if (
            slot is None
            or slot_id in seen_slots
            or text_key in seen_text
            or not _pattern_shape_is_valid(text, slot)
        ):
            dropped += 1
            continue
        seen_slots.add(slot_id)
        seen_text.add(text_key)
        accepted.append(
            PlannedPrompt(
                slot_id=slot_id,
                topic_id=slot.topic_id,
                text=text,
                intent=slot.intent,
                cohort=slot.cohort,
                pattern=slot.pattern,
            )
        )
    return accepted, dropped
