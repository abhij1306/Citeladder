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


def test_parse_resolves_short_slots_to_code_owned_topic_and_intent() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {"slot_id": "q1", "text": "What is footwear?"},
                {"slot_id": "q2", "text": "Best activewear for running"},
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, slots=SLOTS)

    assert dropped == 0
    assert [(topic.topic_id, topic.name) for topic in topics] == [
        (TOPIC_ID, "Footwear"),
        (SECOND_TOPIC_ID, "Activewear"),
    ]
    assert topics[0].prompts[0].intent == "discovery"
    assert topics[0].prompts[0].pattern == "what_is"
    assert topics[1].prompts[0].intent == "purchase"


def test_slot_plan_rotates_patterns_while_covering_topics() -> None:
    assert [(slot.topic_id, slot.pattern) for slot in SLOTS] == [
        (str(TOPIC_ID), "what_is"),
        (str(SECOND_TOPIC_ID), "best_for"),
        (str(TOPIC_ID), "best_for"),
        (str(SECOND_TOPIC_ID), "how_to"),
    ]


def test_parse_drops_unknown_duplicate_and_wrong_shape_slots() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {"slot_id": "unknown", "text": "What is footwear?"},
                {"slot_id": "q1", "text": "What is footwear?"},
                {"slot_id": "q1", "text": "What is footwear exactly?"},
                {"slot_id": "q2", "text": "comfortable gym clothes"},
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, slots=SLOTS)

    assert dropped == 3
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
    from app.domain.prompts.generation_filtering import _drop_invalid_core_prompts

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
    result = _drop_invalid_core_prompts(
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
