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


def test_normalization_and_hash_are_stable() -> None:
    assert normalize_prompt_text("  Best   Running Shoes!? ") == "best running shoes"
    assert prompt_text_hash("Best Shoes?") == prompt_text_hash("best  shoes")


def test_normalization_remains_linear() -> None:
    payload = "\t" * 200_000 + "x"
    started = time.perf_counter()
    normalize_prompt_text(payload)
    assert time.perf_counter() - started < 1.0


def test_parse_groups_prompts_by_supplied_topic_id() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {
                    "topic_id": str(TOPIC_ID),
                    "text": "best shoes for walking",
                    "intent": "Discovery",
                },
                {
                    "topic_id": str(SECOND_TOPIC_ID),
                    "text": "comfortable gym clothes",
                    "intent": "purchase",
                },
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, allowed_topics=ALLOWED_TOPICS)

    assert dropped == 0
    assert [(topic.topic_id, topic.name) for topic in topics] == [
        (TOPIC_ID, "Footwear"),
        (SECOND_TOPIC_ID, "Activewear"),
    ]
    assert topics[0].prompts[0].intent == "discovery"


def test_parse_drops_unknown_topic_ids_and_duplicates() -> None:
    raw = json.dumps(
        {
            "prompts": [
                {
                    "topic_id": str(uuid.uuid4()),
                    "text": "unsupported topic",
                    "intent": "discovery",
                },
                {
                    "topic_id": str(TOPIC_ID),
                    "text": "best walking shoes",
                    "intent": "discovery",
                },
                {
                    "topic_id": str(SECOND_TOPIC_ID),
                    "text": "BEST  WALKING SHOES?",
                    "intent": "discovery",
                },
            ]
        }
    )

    topics, dropped = parse_generation_output(raw, allowed_topics=ALLOWED_TOPICS)

    assert dropped == 1
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
                        "topic_id": str(TOPIC_ID),
                        "text": "best walking shoes",
                        "intent": "discovery",
                        "theme": "model invented topic",
                    }
                ]
            }
        ),
    ],
)
def test_parse_rejects_malformed_or_empty_output(raw: str) -> None:
    with pytest.raises(GenerationOutputError):
        parse_generation_output(raw, allowed_topics=ALLOWED_TOPICS)


def test_user_message_contains_only_canonical_topic_ids() -> None:
    message = build_generation_user_message(
        brand_context=BRAND_CONTEXT,
        topics=ALLOWED_TOPICS,
        existing_prompts=["existing prompt"],
        count=4,
        intents=["discovery"],
    )

    assert str(TOPIC_ID) in message
    assert "Canonical topics" in message
    assert "Generate exactly 4 prompts" in message
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
