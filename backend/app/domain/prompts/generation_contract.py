"""Strict topic-ID prompt generation contract."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.web_evidence.brand_evidence import evidence_block_lines
from app.core.config.prompts import prompt_generation_settings
from app.domain.projects.knowledge_base import serialize_brand_knowledge_context
from app.domain.prompts.query_patterns import (
    PlannedPrompt,
    PromptSlot,
    resolve_planned_prompts,
)


class GenerationOutputError(RuntimeError):
    """The generation provider returned no usable suggestions."""


class SuggestedPrompt(BaseModel):
    text: str = Field(min_length=1)
    intent: str = ""
    pattern: str = ""
    slot_id: str = ""


class SuggestedTopic(BaseModel):
    topic_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    prompts: list[SuggestedPrompt] = Field(default_factory=list)


class GeneratedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot_id: str = Field(min_length=1, max_length=16)
    text: str = Field(min_length=1)


class GenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompts: list[GeneratedPrompt] = Field(default_factory=list)


def generation_model_call_budget(count: int) -> int:
    """Return the maximum provider calls one bounded generation may make."""
    batch_size = min(prompt_generation_settings.model_batch_size, count)
    return (count + batch_size - 1) // batch_size + 1


def parse_generation_output(
    raw: str,
    *,
    slots: list[PromptSlot],
) -> tuple[list[SuggestedTopic], int]:
    topics = {
        str(slot.topic_id): slot.topic_name
        for slot in slots
        if slot.topic_id is not None
    }
    try:
        payload = json.loads(raw)
        output = GenerationOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GenerationOutputError(f"Unparseable agent output: {exc}") from exc

    grouped: dict[str, list[SuggestedPrompt]] = {}
    planned, dropped = resolve_planned_prompts(
        [(prompt.slot_id, prompt.text) for prompt in output.prompts], slots
    )
    for prompt in planned:
        topic_id = str(prompt.topic_id)
        if topic_id not in topics:
            dropped += 1
            continue
        grouped.setdefault(topic_id, []).append(
            SuggestedPrompt(
                text=prompt.text,
                intent=prompt.intent,
                pattern=prompt.pattern,
                slot_id=prompt.slot_id,
            )
        )
    suggestions = [
        SuggestedTopic(
            topic_id=uuid.UUID(topic_id), name=topics[topic_id], prompts=prompts
        )
        for topic_id, prompts in grouped.items()
    ]
    if not suggestions:
        raise GenerationOutputError("Agent output contained no usable prompts")
    return suggestions, dropped


def parse_planned_output(
    raw: str, *, slots: list[PromptSlot]
) -> tuple[list[PlannedPrompt], int]:
    """Parse the shared slot contract for onboarding's portfolio validator."""
    try:
        output = GenerationOutput.model_validate_json(raw)
    except ValidationError as exc:
        raise GenerationOutputError(f"Unparseable agent output: {exc}") from exc
    planned, dropped = resolve_planned_prompts(
        [(prompt.slot_id, prompt.text) for prompt in output.prompts], slots
    )
    if not planned:
        raise GenerationOutputError("Agent output contained no usable prompts")
    return planned, dropped


def build_generation_user_message(
    *,
    brand_context: dict[str, Any],
    slots: list[PromptSlot],
    existing_prompts: list[str],
) -> str:
    competitors = [item["name"] for item in brand_context.get("competitors", [])]
    lines = [
        serialize_brand_knowledge_context(dict(brand_context.get("knowledge_base", {})))
    ]
    lines += evidence_block_lines(
        brand_context.get("website_evidence", ""),
        "Use the website evidence only to ground prompt wording. The canonical "
        "topics below are the complete allowed taxonomy.",
    )
    lines += [
        f"Brand: {brand_context.get('brand_name', '')}",
        f"Brand aliases: {', '.join(brand_context.get('brand_aliases', [])) or 'none'}",
        f"Competitors: {', '.join(competitors) or 'none'}",
        f"Market country: {brand_context.get('country_code') or 'unspecified'}",
        f"Language: {brand_context.get('language_code') or 'unspecified'}",
        "Buyer-query slots (return one row per slot): "
        + json.dumps(
            [slot.as_model_input() for slot in slots],
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    ]
    commerce_products = list(brand_context.get("commerce_products") or [])
    if commerce_products:
        lines.append(
            "Uploaded catalog products (use only products whose category matches the "
            "target topic): "
            + json.dumps(commerce_products, ensure_ascii=False, separators=(",", ":"))
        )
    lines.append(f"Return exactly {len(slots)} prompts in total.")
    if existing_prompts:
        lines.append(
            "Existing prompts (do NOT duplicate any of these):\n- "
            + "\n- ".join(existing_prompts)
        )
    return "\n".join(lines)
