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
        {
            "commerce_products": [
                {"name": "Sony WH-1000XM6", "sku": "XM6", "category": "Headphones"}
            ]
        },
    )

    assert suggestions == [
        SuggestedTopic(
            topic_id=topic_id,
            name="Headphones",
            prompts=[
                SuggestedPrompt(
                    text="Where can I buy Sony WH-1000XM6 online?",
                    intent="discovery",
                ),
                SuggestedPrompt(
                    text=(
                        "What are the best alternatives to Sony WH-1000XM6 in "
                        "headphones?"
                    ),
                    intent="comparison",
                ),
            ],
        )
    ]


def test_deterministic_commerce_generation_names_every_product() -> None:
    topic_id = uuid.uuid4()
    suggestions = _deterministic_commerce_suggestions(
        [{"id": str(topic_id), "name": "Laptops", "description": ""}],
        {
            "commerce_products": [
                {"name": "Acer Aspire 3", "sku": "A3", "category": "Laptops"},
                {"name": "MacBook Air M4", "sku": "MBA", "category": "laptops"},
            ]
        },
    )

    assert len(suggestions[0].prompts) == 4
    for product_name in ("Acer Aspire 3", "MacBook Air M4"):
        named = [
            prompt for prompt in suggestions[0].prompts if product_name in prompt.text
        ]
        assert {prompt.intent for prompt in named} == {"discovery", "comparison"}


def test_commerce_prompt_filter_rejects_unnamed_category_prompts() -> None:
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
                text="Where can I buy Apple iPhone 16 online",
                intent="discovery",
            ),
            SuggestedPrompt(
                text="What are the best alternatives to Apple iPhone 16",
                intent="comparison",
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

    assert [prompt.text for prompt in filtered[0].prompts] == [
        "Where can I buy Apple iPhone 16 online",
        "What are the best alternatives to Apple iPhone 16",
    ]
    assert [prompt.intent for prompt in filtered[0].prompts] == [
        "discovery",
        "comparison",
    ]


def test_commerce_topic_keyed_output_reaches_the_existing_content_filter() -> None:
    topic_id = uuid.uuid4()
    raw = json.dumps(
        {
            str(topic_id): [
                ("Where can I buy Sony WH-1000XM6 online with reliable delivery"),
                "What are the best alternatives to Sony WH-1000XM6",
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


def test_commerce_prompt_filter_prefers_the_longest_matching_product_name() -> None:
    category = SuggestedTopic(
        topic_id=uuid.uuid4(),
        name="Smartphones",
        prompts=[
            SuggestedPrompt(
                text="Where can I buy Phone Pro online",
                intent="discovery",
            ),
            SuggestedPrompt(
                text="Where can I buy Phone online",
                intent="discovery",
            ),
        ],
    )
    context = {
        "commerce_products": [
            {"name": "Phone", "category": "Smartphones"},
            {"name": "Phone Pro", "category": "Smartphones"},
        ]
    }

    filtered = filter_for_cohort([category], "commerce", context)

    assert filtered[0].prompts == category.prompts


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
