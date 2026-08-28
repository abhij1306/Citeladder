"""Render slot text that satisfies its archetype, for fake generation agents.

Test fakes previously rendered one string per sentence frame ("What is {topic}?",
"Best {topic} for ..."). Those frames are gone: an archetype names a job, so a
fake has to produce something that DOES the job. Every renderer below carries a
per-slot marker inside its first three words, because opening diversity is now
enforced across a whole run and a fixed opener would be dropped after two uses.
"""

from __future__ import annotations

import json

from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_CORE,
)
from app.core.config.visibility_prompts import ARCHETYPES_BY_KEY
from app.domain.prompts.query_patterns import PromptSlot, _archetype_is_satisfied

# Two varying words per slot, not one. The shared validator rejects near
# duplicates at 0.88 similarity, and templates that differ only by a marker
# scored above that -- so a fake filling seven slots silently lost one and the
# test read as an off-by-one in the planner.
_FLAVOURS = (
    "winter",
    "summer",
    "school",
    "weekend",
    "wedding",
    "travel",
    "budget",
    "outdoor",
    "toddler",
    "evening",
    "camping",
    "commuting",
)
_AUDIENCES = (
    "families",
    "students",
    "commuters",
    "toddlers",
    "teenagers",
    "runners",
    "travellers",
    "parents",
    "nurses",
    "cyclists",
    "gardeners",
    "hikers",
)

_RENDERERS = {
    "consideration_recommend": (
        "Best {marker} {flavour} {topic} stores for {audience}"
    ),
    "decision_buy": "Where {marker} {audience} buy cheap {flavour} {topic}",
    "consideration_compare": (
        "{marker} {topic} retailers compared for {flavour} {audience}"
    ),
    "decision_validate": "Is {marker} {flavour} {topic} worth buying for {audience}",
    "awareness_solve": ("{marker} {audience} outgrew their {flavour} {topic} already"),
    "awareness_learn": (
        "Do {marker} {topic} outlast cheaper {flavour} pairs for {audience}"
    ),
    "implementation_implement": (
        "{marker} care guide for washing {flavour} {topic} for {audience}"
    ),
    "brand_awareness_learn": (
        "Does {marker} {brand} still sell {flavour} basics for {audience}"
    ),
    "brand_decision_validate": (
        "Is {marker} {brand} good for {flavour} shopping by {audience}"
    ),
    "brand_consideration_compare": (
        "{marker} {brand} versus {competitor} for {flavour} {topic}"
    ),
}


def _offset(index: object) -> int:
    """A stable small integer for either an int index or a labelled one."""
    if isinstance(index, int):
        return index
    return sum(ord(char) for char in str(index))


def slot_text(slot: dict[str, object], index: object) -> str:
    """Valid text for one planned slot, unique in wording and in opening."""
    competitors = list(slot.get("competitors") or [])
    return _RENDERERS[str(slot["archetype"])].format(
        marker=f"run{index}",
        flavour=_FLAVOURS[_offset(index) % len(_FLAVOURS)],
        audience=_AUDIENCES[(_offset(index) * 5 + 3) % len(_AUDIENCES)],
        topic=str(slot.get("topic") or "footwear"),
        brand=str(slot.get("brand") or "Brand"),
        competitor=str(competitors[0]) if competitors else "Competitor",
    )


def _cohort(archetype_key: str) -> str:
    if archetype_key == "brand_consideration_compare":
        return PROMPT_COHORT_COMPARISON
    if archetype_key.startswith("brand_"):
        return PROMPT_COHORT_BRAND_DIAGNOSTIC
    return PROMPT_COHORT_CORE


def slot_from_payload(slot: dict[str, object]) -> PromptSlot:
    """Rebuild the planned slot a fake agent was handed, for validation."""
    archetype = ARCHETYPES_BY_KEY[str(slot["archetype"])]
    return PromptSlot(
        slot_id=str(slot["slot_id"]),
        topic_id="topic-1",
        topic_name=str(slot.get("topic") or ""),
        topic_description=str(slot.get("topic_description") or ""),
        archetype=archetype.key,
        buyer_stage=archetype.stage,
        prompt_intent=archetype.intent,
        intent=archetype.legacy_intent,
        cohort=_cohort(archetype.key),
        form=str(slot.get("form") or "question"),
        brand_name=str(slot.get("brand") or ""),
        competitor_names=tuple(str(name) for name in (slot.get("competitors") or [])),
    )


def satisfies_slot(slot: dict[str, object], text: str) -> bool:
    """Whether text would survive the real archetype gates for this slot."""
    return bool(text) and _archetype_is_satisfied(text, slot_from_payload(slot))


SLOT_MARKER = "Buyer-query slots (return one row per slot): "


def slots_from_user_message(user: str) -> list[dict]:
    """The planned slots a fake agent was handed.

    Both generation paths now send the same user message, so both fakes read it
    the same way instead of one parsing a bespoke JSON payload.
    """
    line = next(line for line in user.splitlines() if line.startswith(SLOT_MARKER))
    return json.loads(line.removeprefix(SLOT_MARKER))


def response_for(user: str) -> str:
    """A valid structured response filling every slot in the message."""
    return json.dumps(
        {
            "prompts": [
                {"slot_id": slot["slot_id"], "text": slot_text(slot, index)}
                for index, slot in enumerate(slots_from_user_message(user))
            ]
        }
    )
