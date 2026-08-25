import json
import uuid
from types import SimpleNamespace

import pytest

from app.domain.prompts.generation import (
    _deterministic_commerce_suggestions,
    _validate_generation_payload,
)
from app.domain.prompts.generation_contract import (
    SuggestedPrompt,
    SuggestedTopic,
    parse_generation_output,
)
from app.domain.prompts.generation_errors import GenerationValidationError
from app.domain.prompts.generation_filtering import filter_for_cohort


def test_deterministic_commerce_generation_asks_about_purchase_platforms() -> None:
    topic_id = uuid.uuid4()
    suggestions = _deterministic_commerce_suggestions(
        [{"id": str(topic_id), "name": "Headphones", "description": ""}],
    )

    assert suggestions == [
        SuggestedTopic(
            topic_id=topic_id,
            name="Headphones",
            prompts=[
                SuggestedPrompt(
                    text="Where can I buy headphones online?",
                    intent="discovery",
                ),
                SuggestedPrompt(
                    text=(
                        "Which online store or marketplace is best for buying "
                        "headphones?"
                    ),
                    intent="comparison",
                ),
            ],
        )
    ]


def test_deterministic_commerce_generation_does_not_need_product_names() -> None:
    topic_id = uuid.uuid4()
    suggestions = _deterministic_commerce_suggestions(
        [{"id": str(topic_id), "name": "Laptops", "description": ""}],
    )

    assert suggestions[0].prompts[1] == SuggestedPrompt(
        text="Which online store or marketplace is best for buying laptops?",
        intent="comparison",
    )


def test_commerce_prompt_filter_keeps_generic_platform_prompts() -> None:
    category = SuggestedTopic(
        topic_id=uuid.uuid4(),
        name="Smartphones",
        prompts=[
            SuggestedPrompt(
                text="Where can I buy smartphones online",
                intent="discovery",
            ),
            SuggestedPrompt(
                text="Which online marketplace is best for buying smartphones",
                intent="comparison",
            ),
            SuggestedPrompt(
                text="Is Apple iPhone 16 the best smartphone this year",
                intent="discovery",
            ),
        ],
    )
    context = {
        "commerce_products": [
            {"name": "Apple iPhone 16", "category": "Smartphones"},
            {"name": "Samsung Galaxy S25", "category": "Smartphones"},
        ]
    }

    filtered = filter_for_cohort([category], "commerce", context)

    assert [prompt.intent for prompt in filtered[0].prompts] == [
        "discovery",
        "comparison",
    ]


def test_commerce_topic_keyed_output_reaches_the_existing_content_filter() -> None:
    topic_id = uuid.uuid4()
    raw = json.dumps(
        {
            str(topic_id): [
                ("Where can I buy wireless headphones online with reliable delivery"),
                "Which online store is best for buying wireless headphones",
            ]
        }
    )
    suggestions, _ = parse_generation_output(
        raw,
        allowed_topics=[{"id": str(topic_id), "name": "Headphones"}],
        fallback_intents=("discovery", "comparison"),
    )
    context = {
        "commerce_products": [
            {"name": "Sony WH-1000XM6", "category": "Headphones"},
            {"name": "Bose QuietComfort Ultra", "category": "Headphones"},
        ]
    }

    filtered = filter_for_cohort(suggestions, "commerce", context)

    assert [prompt.intent for prompt in filtered[0].prompts] == [
        "discovery",
        "comparison",
    ]


def test_commerce_discovery_rejects_product_named_from_another_category() -> None:
    category = SuggestedTopic(
        topic_id=uuid.uuid4(),
        name="Smartphones",
        prompts=[
            SuggestedPrompt(
                text="Which trail shoes compare with Alpine Runner 2",
                intent="discovery",
            )
        ],
    )
    context = {
        "commerce_products": [
            {"name": "Phone One", "category": "Smartphones"},
            {"name": "Alpine Runner 2", "category": "Footwear"},
        ]
    }

    assert filter_for_cohort([category], "commerce", context) == []


def _generation_fixture(*, products, topic_name="Smartphones"):
    topic = SimpleNamespace(id=uuid.uuid4(), name=topic_name)
    project = SimpleNamespace(topics=[topic], products=products)
    prompt_set = SimpleNamespace(project=project)
    payload = SimpleNamespace(
        count=2,
        intents=["discovery", "comparison"],
        cohort="commerce",
        topic_id=topic.id,
    )
    return prompt_set, payload


def test_commerce_generation_ignores_uncategorized_products_outside_target() -> None:
    prompt_set, payload = _generation_fixture(
        products=[
            SimpleNamespace(sku="PHONE-1", attributes={"category": "smartphones"}),
            SimpleNamespace(sku="OTHER-1", attributes={}),
        ]
    )

    assert _validate_generation_payload(prompt_set, payload).name == "Smartphones"


def test_commerce_generation_caps_missing_skus_for_empty_target_category() -> None:
    prompt_set, payload = _generation_fixture(
        products=[
            SimpleNamespace(sku=f"SKU-{index:02}", attributes={}) for index in range(12)
        ]
    )

    with pytest.raises(GenerationValidationError) as caught:
        _validate_generation_payload(prompt_set, payload)

    message = str(caught.value)
    assert "SKU-09" in message
    assert "SKU-10" not in message
    assert "(+2 more)" in message
