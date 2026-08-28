"""Deterministic buyer-query slot planning and archetype validation.

Code owns the plan: which topic, which buyer stage, which intent, which surface
form, and how many. The model owns only the wording.

The line this module has to hold is between those two. v1 put it in the wrong
place -- it handed the model literal sentence frames (``Use the exact form
"What is [topic]?"``) and enforced them with prefix matchers, which left no
wording for the model to own at all and produced portfolios that were four
templates rotating over topic names. Every check below therefore asks whether a
query does its archetype's JOB; none of them look at how it opens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.analysis.normalization import normalize_alias
from app.core.config.prompts import (
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_CORE,
    TOPICAL_BINDING_STOPWORDS,
)
from app.core.config.visibility_prompt_vocabulary import (
    ACQUISITION_WORDS,
    COMPARISON_WORDS,
    MIN_CONSTRAINT_TOKENS,
    PRICE_WORDS,
    PROCEDURAL_WORDS,
    PROVIDER_NOUNS,
    SELECTION_WORDS,
)
from app.core.config.visibility_prompts import (
    ARCHETYPES_BY_KEY,
    BRAND_DIAGNOSTIC_ARCHETYPES,
    BUYER_STAGE_CONSIDERATION,
    BUYER_STAGE_DECISION,
    COMPARISON_ARCHETYPES,
    CORE_ARCHETYPES,
    LEGACY_INTENT_ARCHETYPES,
    QUERY_FORMS,
    QueryArchetype,
)
from app.domain.prompts.normalization import prompt_text_hash
from app.domain.prompts.portfolio import contains_tracked_name

# Stages whose queries an assistant is expected to answer by naming a business.
# Awareness and implementation queries are answered with explanation, so the
# provider-seeking check would reject perfectly good ones ("How do I remove
# stains from delicate fabrics without damaging them").
_COMMERCIAL_STAGES = frozenset({BUYER_STAGE_CONSIDERATION, BUYER_STAGE_DECISION})

_BUSINESS_SEEKING_WORDS = (
    PROVIDER_NOUNS | SELECTION_WORDS | ACQUISITION_WORDS | PRICE_WORDS
)

# Two archetypes are defined by NOT naming their category: a solve query
# states a situation ("AC not cooling, who can repair it today") and an
# implementation query asks about the thing already owned ("How do I remove
# stains from delicate fabrics"). Requiring a topic token from those would
# reject them for doing exactly the job the archetype asks for. Off-domain
# text is still caught by project-level topical binding before any insert.
_BINDING_EXEMPT_ARCHETYPES = frozenset({"awareness_solve", "implementation_implement"})

# The one signal per archetype that is genuinely semantic rather than
# syntactic. An archetype absent here is judged on the shared rules alone.
_ARCHETYPE_SIGNALS: dict[str, frozenset[str]] = {
    "decision_buy": PRICE_WORDS | ACQUISITION_WORDS,
    "consideration_compare": COMPARISON_WORDS,
    "implementation_implement": PROCEDURAL_WORDS,
    "brand_consideration_compare": COMPARISON_WORDS,
}


@dataclass(frozen=True, slots=True)
class PromptSlot:
    """One code-owned model task. Only ``text`` comes back from the model."""

    slot_id: str
    topic_id: str | None
    topic_name: str
    topic_description: str
    archetype: str
    buyer_stage: str
    prompt_intent: str
    intent: str
    cohort: str
    form: str
    qualifiers: tuple[str, ...] = ()
    brand_name: str = ""
    competitor_names: tuple[str, ...] = ()

    def as_model_input(self) -> dict[str, object]:
        """The slot as the model sees it: a job and a form, never a template."""
        archetype = ARCHETYPES_BY_KEY[self.archetype]
        payload: dict[str, object] = {
            "slot_id": self.slot_id,
            "topic": self.topic_name,
            "topic_description": self.topic_description,
            "archetype": self.archetype,
            "buyer_stage": self.buyer_stage,
            "intent": self.prompt_intent,
            "job": archetype.job,
            "form": self.form,
            "example": archetype.example,
        }
        if self.qualifiers:
            payload["words_this_business_supports"] = list(self.qualifiers)
        if self.brand_name:
            payload["brand"] = self.brand_name
        if self.competitor_names:
            payload["competitors"] = list(self.competitor_names)
        return payload


@dataclass(frozen=True, slots=True)
class PlannedPrompt:
    slot_id: str
    topic_id: str | None
    text: str
    intent: str
    buyer_stage: str
    prompt_intent: str
    cohort: str
    archetype: str


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


def _weighted_recipe(
    archetypes: tuple[QueryArchetype, ...],
) -> tuple[QueryArchetype, ...]:
    """Expand weights into a fair-share order, heavier archetypes spread out.

    Appending the extra copies at the end looked equivalent and was not: the
    planner walks the recipe by ``(topic + round)``, so for any plan shorter
    than the full recipe the tail is never reached and the archetype weighted
    highest became the RAREST in the portfolio -- the exact opposite of the
    intent. Placing each copy at ``(occurrence + 0.5) / weight`` interleaves
    them, so a recommendation slot appears early and often at any plan size.
    """
    if not archetypes:
        return ()
    spread = [
        ((occurrence + 0.5) / archetype.weight, order, archetype)
        for order, archetype in enumerate(archetypes)
        for occurrence in range(archetype.weight)
    ]
    return tuple(
        archetype for _, _, archetype in sorted(spread, key=lambda row: row[:2])
    )


def _core_recipe(intents: tuple[str, ...]) -> tuple[QueryArchetype, ...]:
    """The organic recipe, narrowed when the caller named legacy intents.

    The archetype -- never the request -- owns the intent stamped on the row.
    Asking for ``comparison`` selects the comparison archetype; it does not
    relabel a recommendation slot as one.
    """
    if not intents:
        return _weighted_recipe(CORE_ARCHETYPES)
    selected = {
        key for intent in intents for key in LEGACY_INTENT_ARCHETYPES.get(intent, ())
    }
    return _weighted_recipe(
        tuple(archetype for archetype in CORE_ARCHETYPES if archetype.key in selected)
    )


def _named_recipe(cohort: str) -> tuple[QueryArchetype, ...]:
    return _weighted_recipe(
        BRAND_DIAGNOSTIC_ARCHETYPES
        if cohort == PROMPT_COHORT_BRAND_DIAGNOSTIC
        else COMPARISON_ARCHETYPES
    )


def build_prompt_slots(
    *,
    topics: list[Any],
    count: int,
    cohort: str,
    intents: tuple[str, ...] = (),
    brand_name: str = "",
    competitor_names: tuple[str, ...] = (),
    qualifiers: tuple[str, ...] = (),
    unbound_brand_diagnostic: bool = False,
) -> list[PromptSlot]:
    """Plan exact topic/archetype/form slots, topic-first and stage-balanced."""
    if count <= 0 or not topics:
        return []
    recipe = (
        _core_recipe(intents) if cohort == PROMPT_COHORT_CORE else _named_recipe(cohort)
    )
    if not recipe:
        return []
    topic_rows = [_topic_fields(topic) for topic in topics]
    # One pass over topics x recipe covers every pairing once. Beyond that the
    # planner keeps going in further cycles, each shifted onto a different
    # surface form, rather than silently returning fewer prompts than asked
    # for -- which is what a hard `min(count, topics * recipe)` cap did.
    pairings = len(topic_rows) * len(recipe)
    limit = min(count, pairings * len(QUERY_FORMS))
    # Start each topic at a well-separated point in the recipe. Offsetting by
    # one meant a portfolio with several topics never advanced far enough to
    # reach the recipe's tail, so implementation and awareness slots -- the
    # ones that make a portfolio span the funnel -- went unplanned entirely.
    stride = max(1, len(recipe) // len(topic_rows))
    slots: list[PromptSlot] = []
    for index in range(limit):
        topic_index = index % len(topic_rows)
        round_index = index // len(topic_rows)
        cycle = index // pairings
        archetype = recipe[(round_index + topic_index * stride) % len(recipe)]
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
                archetype=archetype.key,
                buyer_stage=archetype.stage,
                prompt_intent=archetype.intent,
                intent=archetype.legacy_intent,
                cohort=cohort,
                form=QUERY_FORMS[(index + cycle) % len(QUERY_FORMS)],
                qualifiers=qualifiers,
                brand_name=brand_name,
                competitor_names=competitor_names,
            )
        )
    return slots


def _singular(token: str) -> str:
    """Crude plural fold, so "homeware" matches the topic "Homewares".

    Topic names are written as categories and buyers type singulars (and the
    reverse), so exact token equality dropped good prompts for a spelling the
    model had no way to guess. Only a trailing "s" is folded: anything cleverer
    would need a stemmer per language, and this runs on every generated row.
    """
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _tokens(value: str) -> set[str]:
    return {
        _singular(token)
        for token in normalize_alias(value).split()
        if len(token) >= 3 and token not in TOPICAL_BINDING_STOPWORDS
    }


def _topic_is_bound(text: str, slot: PromptSlot) -> bool:
    expected = _tokens(f"{slot.topic_name} {slot.topic_description}")
    return bool(expected and expected & _tokens(text))


def _carries_constraint(text: str, slot: PromptSlot) -> bool:
    """Whether the query says anything beyond restating its own topic.

    This is what separates a real buyer question from a topic name wrapped in a
    question mark: "What is womenswear including plus size?" carries one
    non-topic word, "Looking for cheap kids school clothes before term starts"
    carries several.
    """
    topic = _tokens(f"{slot.topic_name} {slot.topic_description}")
    return len(_tokens(text) - topic) >= MIN_CONSTRAINT_TOKENS


def _answerable_by_business(text: str) -> bool:
    """Whether an assistant could answer this by naming a business.

    Required only of consideration- and decision-stage queries: those are the
    ones whose answers a brand can appear in, and therefore the only ones worth
    measuring visibility against.
    """
    return bool(set(normalize_alias(text).split()) & _BUSINESS_SEEKING_WORDS)


def _has_archetype_signal(text: str, archetype: str) -> bool:
    signal = _ARCHETYPE_SIGNALS.get(archetype)
    if signal is None:
        return True
    return bool(set(normalize_alias(text).split()) & signal)


def _identity_is_valid(text: str, slot: PromptSlot) -> bool:
    """Brand-cohort identity, checked here so a slot cannot be answered generically."""
    if slot.cohort == PROMPT_COHORT_CORE:
        return True
    if not contains_tracked_name(text, [slot.brand_name]):
        return False
    if slot.archetype == "brand_consideration_compare":
        return contains_tracked_name(text, slot.competitor_names)
    return True


def _archetype_is_satisfied(text: str, slot: PromptSlot) -> bool:
    # Named-brand cohorts are bound by identity instead: they must carry the
    # tracked brand (and, for a comparison, a competitor), which is a stronger
    # constraint than a topic token and one a brand query naturally satisfies.
    binds_topic = (
        slot.cohort == PROMPT_COHORT_CORE
        and slot.topic_id is not None
        and slot.archetype not in _BINDING_EXEMPT_ARCHETYPES
    )
    if binds_topic and not _topic_is_bound(text, slot):
        return False
    if not _carries_constraint(text, slot):
        return False
    if not _has_archetype_signal(text, slot.archetype):
        return False
    if slot.buyer_stage in _COMMERCIAL_STAGES and not _answerable_by_business(text):
        return False
    return _identity_is_valid(text, slot)


def resolve_planned_prompts(
    rows: list[tuple[str, str]], slots: list[PromptSlot]
) -> tuple[list[PlannedPrompt], int]:
    """Resolve model rows through exact slot and archetype-job gates."""
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
            or not _archetype_is_satisfied(text, slot)
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
                buyer_stage=slot.buyer_stage,
                prompt_intent=slot.prompt_intent,
                cohort=slot.cohort,
                archetype=slot.archetype,
            )
        )
    return accepted, dropped
