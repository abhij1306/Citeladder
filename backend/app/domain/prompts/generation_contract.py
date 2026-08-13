"""Strict model-output parsing and request construction for prompt generation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

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
    name: str = Field(min_length=1, max_length=255)
    prompts: list[SuggestedPrompt] = Field(default_factory=list)


class GenerationOutput(BaseModel):
    topics: list[SuggestedTopic] = Field(default_factory=list)


def parse_generation_output(raw: str) -> tuple[list[SuggestedTopic], int]:
    try:
        output = GenerationOutput.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GenerationOutputError(f"Unparseable agent output: {exc}") from exc

    seen_hashes: set[str] = set()
    duplicate_count = 0
    topics: list[SuggestedTopic] = []
    for topic in output.topics:
        prompts: list[SuggestedPrompt] = []
        for prompt in topic.prompts:
            text = prompt.text.strip()
            text_hash = prompt_text_hash(text)
            if not text or text_hash in seen_hashes:
                duplicate_count += bool(text)
                continue
            seen_hashes.add(text_hash)
            intent = prompt.intent.strip().casefold()
            prompts.append(
                SuggestedPrompt(
                    text=text,
                    intent=intent if intent in PROMPT_INTENTS else "",
                )
            )
        if topic.name.strip() and prompts:
            topics.append(SuggestedTopic(name=topic.name.strip(), prompts=prompts))
    if not topics:
        raise GenerationOutputError("Agent output contained no usable prompts")
    return topics, duplicate_count


def build_generation_user_message(
    *,
    brand_context: dict[str, Any],
    existing_topics: list[dict[str, str]],
    existing_prompts: list[str],
    count: int,
    intents: list[str],
    target_topic: str = "",
    target_topic_description: str = "",
) -> str:
    competitors = [item["name"] for item in brand_context.get("competitors", [])]
    lines = [
        serialize_brand_knowledge_context(dict(brand_context.get("knowledge_base", {})))
    ]
    lines += evidence_block_lines(
        brand_context.get("website_evidence", ""),
        "Ground every prompt in the <brand_website_evidence> page content "
        "above: it is what this brand actually sells and to whom. Do NOT "
        "infer the brand's market or products from its name.",
    )
    lines += [
        f"Brand: {brand_context.get('brand_name', '')}",
        f"Brand aliases: {', '.join(brand_context.get('brand_aliases', [])) or 'none'}",
        f"Competitors: {', '.join(competitors) or 'none'}",
        f"Market country: {brand_context.get('country_code') or 'unspecified'}",
        f"Language: {brand_context.get('language_code') or 'unspecified'}",
    ]
    if target_topic:
        lines.append(
            f"Generate prompts ONLY for this topic (use it verbatim): {target_topic}"
        )
        if target_topic_description:
            lines.append(f"Target topic description: {target_topic_description}")
    elif existing_topics:
        serialized = json.dumps(
            existing_topics, ensure_ascii=False, separators=(",", ":")
        )
        lines.append(
            "Existing topics (reuse the exact name field when applicable): "
            + serialized
        )
    if intents:
        lines.append("Restrict prompt intents to: " + ", ".join(intents))
    lines.append(f"Generate exactly {count} prompts in total across topics.")
    if existing_prompts:
        lines.append(
            "Existing prompts (do NOT duplicate any of these):\n- "
            + "\n- ".join(existing_prompts)
        )
    return "\n".join(lines)
