"""Commerce-specific validation for prompt generation requests."""

from __future__ import annotations

from typing import Any

from app.core.config.prompts import COMMERCE_VALIDATION_SKU_PREVIEW_LIMIT
from app.domain.prompts.generation_errors import GenerationValidationError
from app.models.prompt import PromptSet, Topic


def _missing_category_message(prompt_set: PromptSet, target_topic: Topic) -> str:
    missing = sorted(
        product.sku
        for product in prompt_set.project.products
        if not str((product.attributes or {}).get("category") or "").strip()
    )
    shown = missing[:COMMERCE_VALIDATION_SKU_PREVIEW_LIMIT]
    remaining = len(missing) - len(shown)
    suffix = f" (+{remaining} more)" if remaining else ""
    guidance = (
        "Add a category for these SKUs: " + ", ".join(shown) + suffix
        if shown
        else "Update the catalog category or target topic."
    )
    return (
        f"No uploaded products belong to target category {target_topic.name!r}. "
        + guidance
    )


def validate_commerce_payload(
    prompt_set: PromptSet, payload: Any, target_topic: Topic | None
) -> None:
    if payload.count != 2 or set(payload.intents) != {"discovery", "comparison"}:
        raise GenerationValidationError(
            "Commerce generation requires exactly two prompts: discovery and comparison"
        )
    if target_topic is None:
        raise GenerationValidationError(
            "Commerce generation must target one catalog category topic"
        )
    target_category = target_topic.name.strip().casefold()
    has_category_product = any(
        str((product.attributes or {}).get("category") or "").strip().casefold()
        == target_category
        for product in prompt_set.project.products
    )
    if not has_category_product:
        raise GenerationValidationError(
            _missing_category_message(prompt_set, target_topic)
        )
