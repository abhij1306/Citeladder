"""Versioned, deterministic industry context for degraded onboarding."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_LIBRARY_PATH = Path(__file__).with_name("industry_library.json")


@lru_cache(maxsize=1)
def load_industry_library() -> dict[str, Any]:
    return json.loads(_LIBRARY_PATH.read_text(encoding="utf-8"))


def industry_names() -> list[str]:
    return list(load_industry_library()["industries"])


def subindustries_by_industry() -> dict[str, list[str]]:
    return {
        name: list(context.get("subindustries") or [])
        for name, context in load_industry_library()["industries"].items()
    }


def industry_context(industry: str) -> tuple[str, dict[str, Any]]:
    library = load_industry_library()
    industries = library["industries"]
    selected = str(industry or "").strip()
    if selected not in industries:
        selected = "General"
    return selected, dict(industries[selected])


def library_version() -> str:
    return str(load_industry_library()["version"])
