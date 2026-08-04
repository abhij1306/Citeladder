# Deterministic input normalization for projects + prompts (B3).
#
# ``_normalize_prompts`` / ``_normalize_benchmark_mode`` helpers. Validation of the
# enum *values* happens in the Pydantic schemas; these helpers normalize the
# free-text fields (trim, casefold intent, drop unknown intents) so what lands
# in the database is canonical regardless of how it was entered.
from __future__ import annotations

from typing import Any

from app.core.config.projects import (
    BENCHMARK_MODES,
    DEFAULT_BENCHMARK_MODE,
    PROMPT_INTENTS,
)


def normalize_intent(value: Any) -> str:
    """Casefold + trim an intent; drop it if it is not a known intent.

    An empty / unknown intent normalizes to ``""`` ("unspecified"), matching
    the reference behaviour.
    """
    intent = str(value or "").strip().lower()
    if intent and intent not in PROMPT_INTENTS:
        return ""
    return intent


def normalize_benchmark_mode(value: Any) -> str:
    """Trim + casefold a benchmark mode; empty -> default; unknown -> error."""
    mode = str(value or "").strip().lower()
    if not mode:
        return DEFAULT_BENCHMARK_MODE
    if mode not in BENCHMARK_MODES:
        raise ValueError(f"Unsupported benchmark_mode: {mode}")
    return mode


def normalize_prompt_rows(
    prompts: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize a list of raw prompt dicts (text/theme/intent...).

    Drops rows with empty text, trims text/theme, casefolds+validates intent,
    and preserves the ``branded``/``enabled``/``origin``/``generation_evidence``
    fields when present. Mirrors the reference ``_normalize_prompts`` while
    carrying the extra columns CiteLadder's dedicated prompt resource adds.
    """
    normalized: list[dict[str, Any]] = []
    for prompt in prompts or []:
        text = str(prompt.get("text") or "").strip()
        if not text:
            continue
        row: dict[str, Any] = {
            "text": text,
            "theme": str(prompt.get("theme") or "").strip(),
            "intent": normalize_intent(prompt.get("intent")),
        }
        if "branded" in prompt:
            row["branded"] = bool(prompt.get("branded"))
        if "enabled" in prompt:
            row["enabled"] = bool(prompt.get("enabled"))
        if prompt.get("origin"):
            row["origin"] = str(prompt.get("origin"))
        if prompt.get("generation_evidence") is not None:
            row["generation_evidence"] = prompt.get("generation_evidence")
        normalized.append(row)
    return normalized


def clean_profile_products(values: list[str] | None) -> list[str]:
    """Trim, drop blanks, and de-duplicate case-insensitively (first wins).

    Lives here rather than in ``domain/projects/brand_profile`` so both the
    profile module and ``domain/projects/service`` can use it: the latter seeds
    a BrandProfile at project creation, and importing it from ``brand_profile``
    (which imports ``service``) would be a circular import.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = value.strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            cleaned.append(item)
    return cleaned
