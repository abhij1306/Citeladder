"""The exemplars and the validators must agree.

This is the regression guard for the failure that made this rewrite necessary.
The previous contract shipped GOOD exemplars like "I want to buy cheap baby
clothes in bulk" while enforcing ``text.startswith("what is ")`` -- so every
example the model was shown would have been rejected by the code judging it.
The model got two contradictory signals and produced the templated register the
exemplars existed to prevent.

Nothing detected that, because instruction and enforcement were only ever tested
apart. Here they are tested against each other: every GOOD exemplar must survive
the exact gates its own slot would face, and every BAD one must not.
"""

from __future__ import annotations

from collections import Counter

import pytest

from app.core.config.visibility_prompts import (
    ARCHETYPES_BY_KEY,
    BUYER_STAGES,
    CORE_ARCHETYPES,
    EXEMPLAR_ARCHETYPES,
    PROMPT_EXEMPLARS,
    PROMPT_INTENT_VOCABULARY,
    VISIBILITY_PROMPT_MAX_WORDS,
    VISIBILITY_PROMPT_MIN_WORDS,
    prompt_system_prompt,
)
from app.domain.prompts.query_patterns import (
    PromptSlot,
    _archetype_is_satisfied,
    build_prompt_slots,
)
from app.domain.prompts.style import starts_with_template, words

# Real generated prompts for a value clothing retailer, from a competing AEO
# product. This is the register CiteLadder is aiming at, so it is pinned as a
# golden set: if a change to the gates would reject these, the gates are wrong.
TARGET_REGISTER = [
    ("I want to buy cheap baby clothes in bulk", "decision_buy", "Baby Clothing"),
    (
        "Best affordable plus size clothing stores Australia online",
        "consideration_recommend",
        "Plus Size Clothing",
    ),
    (
        "Looking for cheap kids school clothes before term starts",
        "consideration_recommend",
        "Kids Clothing",
    ),
    (
        "Where to buy affordable winter clothes for the whole family",
        "decision_buy",
        "Winter Clothing",
    ),
    (
        "I want budget friendly homewares for my new apartment",
        "consideration_recommend",
        "Homewares",
    ),
    (
        "Where to find cheap maternity clothes Australia online stores",
        "decision_buy",
        "Maternity Clothing",
    ),
    (
        "Affordable home decor and furniture stores Australia online",
        "consideration_recommend",
        "Home Decor",
    ),
    (
        "Best value homeware stores for kitchen and bathroom items",
        "consideration_recommend",
        "Homewares",
    ),
    (
        "Best value clothing retailers compared for Australian shoppers",
        "consideration_compare",
        "Clothing",
    ),
    (
        "How do I remove stains from delicate fabrics without damaging them",
        "implementation_implement",
        "Clothing Care",
    ),
]


def _slot(archetype_key: str, topic: str) -> PromptSlot:
    archetype = ARCHETYPES_BY_KEY[archetype_key]
    return PromptSlot(
        slot_id="q1",
        topic_id="topic-1",
        topic_name=topic,
        topic_description="",
        archetype=archetype.key,
        buyer_stage=archetype.stage,
        prompt_intent=archetype.intent,
        intent=archetype.legacy_intent,
        cohort="core",
        form="question",
    )


def _passes_every_gate(text: str, slot: PromptSlot) -> bool:
    """Both halves of the contract: the archetype job and the shared style gate."""
    if starts_with_template(text):
        return False
    if (
        not VISIBILITY_PROMPT_MIN_WORDS
        <= len(words(text))
        <= VISIBILITY_PROMPT_MAX_WORDS
    ):
        return False
    return _archetype_is_satisfied(text, slot)


def _good_exemplars() -> list[str]:
    return [
        line.strip().removeprefix("GOOD").strip()
        for block in dict.fromkeys(PROMPT_EXEMPLARS.values())
        for line in block.splitlines()
        if line.strip().startswith("GOOD")
    ]


def _bad_exemplars() -> list[str]:
    return [
        line.strip().removeprefix("BAD").strip()
        for block in dict.fromkeys(PROMPT_EXEMPLARS.values())
        for line in block.splitlines()
        if line.strip().startswith("BAD")
    ]


@pytest.mark.parametrize("text", _good_exemplars())
def test_every_good_exemplar_survives_its_own_validators(text: str) -> None:
    archetype_key, topic = EXEMPLAR_ARCHETYPES[text]
    assert _passes_every_gate(text, _slot(archetype_key, topic))


@pytest.mark.parametrize("text", _bad_exemplars())
def test_every_bad_exemplar_is_rejected(text: str) -> None:
    # A BAD exemplar is rejected whatever archetype it is offered against: it is
    # the sentence-frame register, not a mismatch of job.
    assert not any(
        _passes_every_gate(text, _slot(archetype.key, "Baby Clothing"))
        for archetype in CORE_ARCHETYPES
    )


def test_every_good_exemplar_is_mapped_to_an_archetype() -> None:
    assert set(_good_exemplars()) == set(EXEMPLAR_ARCHETYPES)


@pytest.mark.parametrize(("text", "archetype_key", "topic"), TARGET_REGISTER)
def test_target_register_is_accepted(text: str, archetype_key: str, topic: str) -> None:
    assert _passes_every_gate(text, _slot(archetype_key, topic))


def test_the_frames_that_caused_the_regression_are_rejected() -> None:
    """The exact output that shipped to a customer, and why each one fails.

    "What is womenswear including plus size?" restates its topic and asks
    nothing an assistant answers by naming a retailer -- which is what a
    definitional slot always produces, and why there is no longer one.
    """
    rejected = [
        ("What is womenswear including plus size?", "Womenswear including plus size"),
        ("What is schoolwear and how does it work in Australia?", "Schoolwear"),
    ]
    for text, topic in rejected:
        assert not any(
            _passes_every_gate(text, _slot(archetype.key, topic))
            for archetype in CORE_ARCHETYPES
        )


def test_planned_slots_cover_every_buyer_stage() -> None:
    """One topic's full recipe spans the funnel, weighted toward buying."""
    topics = [{"id": "t1", "name": "Kids Clothing", "description": ""}]
    slots = build_prompt_slots(topics=topics, count=10, cohort="core")

    assert {slot.buyer_stage for slot in slots} == set(BUYER_STAGES)
    assert {slot.prompt_intent for slot in slots} <= set(PROMPT_INTENT_VOCABULARY)
    stages = Counter(slot.buyer_stage for slot in slots)
    # Commercially shaped, not evenly split: the stages an assistant answers by
    # naming a business outnumber the ones it answers with an explanation.
    assert (
        stages["consideration"] + stages["decision"]
        > stages["awareness"] + stages["implementation"]
    )


def test_several_topics_still_reach_the_tail_of_the_recipe() -> None:
    """A multi-topic portfolio spans the funnel too.

    Advancing one recipe step per round meant four topics over four rounds only
    ever saw the first seven entries, so no portfolio with several topics ever
    contained an implementation prompt.
    """
    topics = [
        {"id": f"t{index}", "name": name, "description": ""}
        for index, name in enumerate(
            ["Kids Clothing", "Womenswear", "Homewares", "School Uniforms"]
        )
    ]
    slots = build_prompt_slots(topics=topics, count=16, cohort="core")

    assert {slot.buyer_stage for slot in slots} == set(BUYER_STAGES)


def test_system_prompt_states_the_jobs_without_dictating_a_frame() -> None:
    instruction = prompt_system_prompt("retail")

    assert "exact form" not in instruction
    assert "Vary the opening." in instruction
    # The instruction the model reads must offer the same forms the planner
    # stamps onto slots, or a slot can carry a form nothing explains.
    for form in ("question", "first_person", "search_phrase"):
        assert form in instruction
