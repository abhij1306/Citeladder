"""Unit contracts for topic-ID-only prompt generation."""

from __future__ import annotations

import json
import time
import uuid

import pytest
from pydantic import ValidationError

from app.core.config.prompts import PromptGenerationSettings
from app.domain.prompts.generation import (
    GenerationOutputError,
    SuggestedPrompt,
    SuggestedTopic,
    _cap_suggestions_to_count,
    _drop_cross_batch_duplicates,
    build_generation_user_message,
    parse_generation_output,
)
from app.domain.prompts.normalization import normalize_prompt_text, prompt_text_hash
from app.domain.prompts.query_patterns import build_prompt_slots
from tests.fixtures.archetype_text import satisfies_slot, slot_text

TOPIC_ID = uuid.uuid4()
SECOND_TOPIC_ID = uuid.uuid4()
ALLOWED_TOPICS = [
    {"id": str(TOPIC_ID), "name": "Footwear", "description": "Shoes"},
    {"id": str(SECOND_TOPIC_ID), "name": "Activewear", "description": "Sportswear"},
]
BRAND_CONTEXT = {
    "brand_name": "Acme Corp",
    "brand_aliases": ["Acme"],
    "competitors": [{"name": "Globex"}],
    "country_code": "AU",
    "language_code": "en-AU",
    "knowledge_base": {"description": "Australian footwear retailer."},
}
SLOTS = build_prompt_slots(topics=ALLOWED_TOPICS, count=4, cohort="core")


def test_normalization_and_hash_are_stable() -> None:
    assert normalize_prompt_text("  Best   Running Shoes!? ") == "best running shoes"
    assert prompt_text_hash("Best Shoes?") == prompt_text_hash("best  shoes")


def test_normalization_remains_linear() -> None:
    payload = "\t" * 200_000 + "x"
    started = time.perf_counter()
    normalize_prompt_text(payload)
    assert time.perf_counter() - started < 1.0


def test_parse_resolves_short_slots_to_code_owned_stage_and_intent() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {"slot_id": "q1", "text": "Best footwear stores for wide feet"},
                {
                    "slot_id": "q2",
                    "text": "Cheap activewear wears out after marathon training",
                },
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, slots=SLOTS)

    assert dropped == 0
    assert [(topic.topic_id, topic.name) for topic in topics] == [
        (TOPIC_ID, "Footwear"),
        (SECOND_TOPIC_ID, "Activewear"),
    ]
    # Stage and intent come from the plan, never from the returned text.
    assert topics[0].prompts[0].buyer_stage == "consideration"
    assert topics[0].prompts[0].prompt_intent == "recommend"
    assert topics[0].prompts[0].intent == "purchase"
    assert topics[1].prompts[0].buyer_stage == "awareness"
    assert topics[1].prompts[0].prompt_intent == "solve"


def test_slot_plan_rotates_archetypes_and_forms_while_covering_topics() -> None:
    # Topic-first: every topic is covered before any repeats. The two topics
    # start at opposite ends of the recipe, so a small plan still spans stages
    # instead of asking each topic the same kind of question.
    assert [(slot.topic_id, slot.archetype) for slot in SLOTS] == [
        (str(TOPIC_ID), "consideration_recommend"),
        (str(SECOND_TOPIC_ID), "awareness_solve"),
        (str(TOPIC_ID), "decision_buy"),
        (str(SECOND_TOPIC_ID), "awareness_learn"),
    ]
    # Adjacent slots never share a surface form, which is what stops a batch
    # coming back as one sentence frame repeated across topics.
    forms = [slot.form for slot in SLOTS]
    assert all(first != second for first, second in zip(forms, forms[1:], strict=False))


def test_parse_drops_unknown_duplicate_and_off_job_slots() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {"slot_id": "unknown", "text": "Best footwear stores for wide feet"},
                {"slot_id": "q1", "text": "Best footwear stores for wide feet"},
                {"slot_id": "q1", "text": "Best footwear shops for wide feet"},
                # Does not do its job: no constraint beyond the topic name.
                {"slot_id": "q2", "text": "What is activewear?"},
                # "Where" alone is not a buying signal. This is educational,
                # so it cannot inherit q3's decision/buy provenance.
                {
                    "slot_id": "q3",
                    "text": "Where can I learn about footwear energy ratings",
                },
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, slots=SLOTS)

    assert dropped == 4
    assert len(topics) == 1
    assert topics[0].topic_id == TOPIC_ID


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"topics": []}',
        '{"prompts": []}',
        json.dumps(
            {
                "prompts": [
                    {
                        "slot_id": "q1",
                        "text": "best walking shoes",
                        "theme": "model invented topic",
                    }
                ]
            }
        ),
    ],
)
def test_parse_rejects_malformed_or_empty_output(raw: str) -> None:
    with pytest.raises(GenerationOutputError):
        parse_generation_output(raw, slots=SLOTS)


def test_user_message_contains_only_canonical_topic_ids() -> None:
    message = build_generation_user_message(
        brand_context=BRAND_CONTEXT,
        slots=SLOTS,
        existing_prompts=["existing prompt"],
    )

    assert "q1" in message
    assert "Buyer-query slots" in message
    assert "Return exactly 4 prompts" in message
    assert "create a topic" not in message.casefold()


def test_cap_preserves_topic_ids_and_model_order() -> None:
    suggestions = [
        SuggestedTopic(
            topic_id=TOPIC_ID,
            name="Footwear",
            prompts=[SuggestedPrompt(text=f"prompt {index}") for index in range(3)],
        ),
        SuggestedTopic(
            topic_id=SECOND_TOPIC_ID,
            name="Activewear",
            prompts=[SuggestedPrompt(text="prompt 4")],
        ),
    ]

    capped = _cap_suggestions_to_count(suggestions, 2)

    assert len(capped) == 1
    assert capped[0].topic_id == TOPIC_ID
    assert [prompt.text for prompt in capped[0].prompts] == ["prompt 0", "prompt 1"]


def test_cross_batch_duplicates_are_removed_and_counted_for_every_cohort() -> None:
    existing = [
        SuggestedTopic(
            topic_id=TOPIC_ID,
            name="Footwear",
            prompts=[SuggestedPrompt(text="Acme Corp vs Globex for walking shoes")],
        )
    ]
    incoming = [
        SuggestedTopic(
            topic_id=SECOND_TOPIC_ID,
            name="Activewear",
            prompts=[
                SuggestedPrompt(text="Acme Corp vs Globex for walking shoes?"),
                SuggestedPrompt(text="Acme Corp vs Globex for running clothes"),
            ],
        )
    ]

    retained, dropped = _drop_cross_batch_duplicates(existing, incoming)

    assert dropped == 1
    assert [prompt.text for prompt in retained[0].prompts] == [
        "Acme Corp vs Globex for running clothes"
    ]


def test_generation_settings_keep_bounded_batches() -> None:
    settings = PromptGenerationSettings(
        generation_max_count=100,
        generation_model_batch_size=20,
        generation_existing_prompt_context_limit=0,
    )
    assert settings.max_count == 100
    assert settings.model_batch_size == 20
    assert settings.existing_prompt_context_limit == 0


def test_negative_existing_context_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        PromptGenerationSettings(generation_existing_prompt_context_limit=-1)


def test_manual_generation_applies_the_same_buyer_style_gate() -> None:
    """The "Generate prompts" button must not reintroduce the survey register."""
    from app.domain.prompts.generation_contract import SuggestedPrompt, SuggestedTopic
    from app.domain.prompts.generation_filtering import filter_for_cohort

    topic_id = uuid.uuid4()
    brand_context = {
        "brand_name": "Acme",
        "brand_aliases": [],
        "competitors": [],
        "knowledge_base": {
            "positioning": "Acme serves families seeking affordable everyday footwear"
        },
        "business_context": {"business_model": "retail"},
    }
    candidates = [
        "What are my best options for kids shoes?",
        "which retailer serves families seeking affordable everyday footwear",
        "cheap shoes",
        "I need school shoes for a 6 year old before term starts",
        "best running shoes for flat feet",
        "best running shoes for wide toes",
        "best running shoes for high arches",
    ]
    result = filter_for_cohort(
        [
            SuggestedTopic(
                topic_id=topic_id,
                name="Kids Shoes",
                prompts=[
                    SuggestedPrompt(text=text, intent="discovery")
                    for text in candidates
                ],
            )
        ],
        "core",
        brand_context,
    )
    kept = [prompt.text for topic in result for prompt in topic.prompts]
    assert "What are my best options for kids shoes?" not in kept  # template frame
    # Unbranded, so it clears the tracked-name gate and is dropped by the
    # positioning-paste rule it exists to cover.
    assert not any("families seeking affordable" in text for text in kept)
    assert "cheap shoes" not in kept  # too short to carry a real need
    assert "I need school shoes for a 6 year old before term starts" in kept
    # At most two prompts may share an opening, so the third "best running
    # shoes" variant is dropped.
    assert sum(text.startswith("best running shoes") for text in kept) == 2


def test_named_manual_generation_keeps_identity_and_style_rules() -> None:
    from app.domain.prompts.generation_contract import SuggestedPrompt, SuggestedTopic
    from app.domain.prompts.generation_filtering import filter_for_cohort

    topic_id = uuid.uuid4()
    brand_context = {
        "brand_name": "Acme",
        "brand_aliases": [],
        "competitors": [{"name": "Rival", "aliases": []}],
        "knowledge_base": {},
    }

    def filtered(cohort: str, prompts: list[SuggestedPrompt]) -> list[str]:
        result = filter_for_cohort(
            [SuggestedTopic(topic_id=topic_id, name="Shoes", prompts=prompts)],
            cohort,
            brand_context,
        )
        return [prompt.text for topic in result for prompt in topic.prompts]

    comparisons = filtered(
        "comparison",
        [
            SuggestedPrompt(
                text="What are my best options for Acme versus Rival?",
                intent="comparison",
            ),
            SuggestedPrompt(
                text="Acme or Rival for school shoes this year", intent="comparison"
            ),
            SuggestedPrompt(
                text=" ".join(["Acme", "Rival", *(["shoes"] * 16)]),
                intent="comparison",
            ),
        ],
    )
    assert comparisons == ["Acme or Rival for school shoes this year"]

    diagnostics = filtered(
        "brand_diagnostic",
        [
            SuggestedPrompt(
                text="Is Acme reliable for school shoes in India",
                intent="discovery",
            )
        ],
    )
    assert diagnostics == ["Is Acme reliable for school shoes in India"]


def test_one_topic_no_longer_caps_the_plan_at_one_slot_per_archetype() -> None:
    """A request larger than topics x recipe is planned, not silently truncated.

    ``min(count, topics * recipe)`` meant a single selected topic returned four
    prompts however many were asked for, with no error to say so. Extra cycles
    reuse a pairing only with a different surface form.
    """
    topics = [{"id": "t1", "name": "Running Shoes", "description": "Trainers"}]

    assert len(build_prompt_slots(topics=topics, count=20, cohort="core")) == 20

    slots = build_prompt_slots(topics=topics, count=12, cohort="core")
    assert {slot.form for slot in slots} == {
        "question",
        "first_person",
        "search_phrase",
    }


def test_repeated_pairing_advances_form_for_one_topic_brand_diagnostic() -> None:
    slots = build_prompt_slots(
        topics=[{"id": "t1", "name": "Running Shoes", "description": "Trainers"}],
        count=3,
        cohort="brand_diagnostic",
        brand_name="Acme",
    )

    assert slots[0].archetype == slots[2].archetype
    assert [slot.form for slot in slots] == [
        "question",
        "first_person",
        "search_phrase",
    ]


def test_fixture_renderer_honors_each_planned_surface_form() -> None:
    slots = build_prompt_slots(
        topics=[{"id": "t1", "name": "Running Shoes", "description": "Trainers"}],
        count=3,
        cohort="core",
    )

    for index, slot in enumerate(slots):
        payload = slot.as_model_input()
        text = slot_text(payload, index)
        assert satisfies_slot(payload, text)


def test_narrowing_intents_stamps_the_archetype_intent_not_the_request() -> None:
    """Asking for ``comparison`` selects the comparison job, it does not relabel.

    The previous planner stamped the REQUESTED intent onto whatever slot it
    produced, so a ``comparison`` request on the core cohort returned a
    recommendation slot wearing a comparison label.
    """
    topics = [{"id": "t1", "name": "Running Shoes", "description": "Trainers"}]
    slots = build_prompt_slots(
        topics=topics, count=3, cohort="core", intents=("comparison",)
    )

    assert {slot.archetype for slot in slots} == {"consideration_compare"}
    assert slots[0].intent == "comparison"
    assert slots[0].prompt_intent == "compare"
