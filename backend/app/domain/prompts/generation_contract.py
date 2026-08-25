"""Strict topic-ID prompt generation contract."""

from __future__ import annotations

import json
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.connectors.web_evidence.brand_evidence import evidence_block_lines
from app.core.config.projects import PROMPT_INTENTS
from app.domain.projects.knowledge_base import serialize_brand_knowledge_context
from app.domain.prompts.normalization import prompt_text_hash


class GenerationOutputError(RuntimeError):
    """The generation provider returned no usable suggestions."""


class SuggestedPrompt(BaseModel):
    text: str = Field(min_length=1)
    intent: str = ""


class SuggestedTopic(BaseModel):
    topic_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    prompts: list[SuggestedPrompt] = Field(default_factory=list)


class GeneratedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: uuid.UUID
    text: str = Field(min_length=1)
    intent: str = ""


class GenerationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompts: list[GeneratedPrompt] = Field(default_factory=list)


def _topic_keyed_rows(
    key: object,
    rows: object,
    *,
    allowed_topic_ids: set[str],
    fallback_intents: tuple[str, ...],
) -> list[dict[str, str]] | None:
    try:
        topic_id = str(uuid.UUID(str(key)))
    except ValueError:
        return None
    if topic_id not in allowed_topic_ids or not isinstance(rows, list):
        return None
    if not all(isinstance(text, str) and text.strip() for text in rows):
        return None
    if fallback_intents and len(rows) != len(fallback_intents):
        return None
    return [
        {
            "topic_id": topic_id,
            "text": text,
            "intent": fallback_intents[index] if fallback_intents else "",
        }
        for index, text in enumerate(rows)
    ]


def _normalize_topic_keyed_output(
    value: object,
    *,
    allowed_topic_ids: set[str],
    fallback_intents: tuple[str, ...],
) -> object:
    """Normalize the bounded topic-map shape returned by some JSON-only hosts."""
    if not isinstance(value, dict):
        return value
    topic_keys = [key for key in value if key != "prompts"]
    if not topic_keys:
        return value
    prompts = value.get("prompts", [])
    if not isinstance(prompts, list):
        return value

    normalized = list(prompts)
    for key in topic_keys:
        rows = _topic_keyed_rows(
            key,
            value[key],
            allowed_topic_ids=allowed_topic_ids,
            fallback_intents=fallback_intents,
        )
        if rows is None:
            return value
        normalized.extend(rows)
    return {"prompts": normalized}


def parse_generation_output(
    raw: str,
    *,
    allowed_topics: list[dict[str, str]],
    fallback_intents: tuple[str, ...] = (),
) -> tuple[list[SuggestedTopic], int]:
    topics = {str(topic["id"]): topic["name"] for topic in allowed_topics}
    try:
        payload = _normalize_topic_keyed_output(
            json.loads(raw),
            allowed_topic_ids=set(topics),
            fallback_intents=fallback_intents,
        )
        output = GenerationOutput.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GenerationOutputError(f"Unparseable agent output: {exc}") from exc

    grouped: dict[str, list[SuggestedPrompt]] = {}
    seen_hashes: set[str] = set()
    duplicate_count = 0
    for prompt in output.prompts:
        topic_id = str(prompt.topic_id)
        text = prompt.text.strip()
        if topic_id not in topics or not text:
            continue
        text_hash = prompt_text_hash(text)
        if text_hash in seen_hashes:
            duplicate_count += 1
            continue
        seen_hashes.add(text_hash)
        intent = prompt.intent.strip().casefold()
        grouped.setdefault(topic_id, []).append(
            SuggestedPrompt(
                text=text,
                intent=intent if intent in PROMPT_INTENTS else "",
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
    return suggestions, duplicate_count


def build_generation_user_message(
    *,
    brand_context: dict[str, Any],
    topics: list[dict[str, str]],
    existing_prompts: list[str],
    count: int,
    intents: list[str],
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
        "Canonical topics (copy one id exactly for every prompt): "
        + json.dumps(topics, ensure_ascii=False, separators=(",", ":")),
    ]
    if intents:
        lines.append("Restrict prompt intents to: " + ", ".join(intents))
    commerce_products = list(brand_context.get("commerce_products") or [])
    if commerce_products:
        lines.append(
            "Uploaded catalog products (use only products whose category matches the "
            "target topic): "
            + json.dumps(commerce_products, ensure_ascii=False, separators=(",", ":"))
        )
    lines.append(f"Generate exactly {count} prompts in total.")
    if existing_prompts:
        lines.append(
            "Existing prompts (do NOT duplicate any of these):\n- "
            + "\n- ".join(existing_prompts)
        )
    return "\n".join(lines)
