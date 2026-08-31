"""Deterministic applicability evidence for page currency checks."""

from __future__ import annotations

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from app.core.config.site_health_measurement import (
    FRESHNESS_IDENTITY_PATTERN,
    FRESHNESS_PURPOSE_PATTERN,
    FRESHNESS_ROUTE_SEGMENTS,
)

_IDENTITY_RE = re.compile(FRESHNESS_IDENTITY_PATTERN, re.IGNORECASE)
_PURPOSE_RE = re.compile(FRESHNESS_PURPOSE_PATTERN, re.IGNORECASE)


def _route_segments(final_url: str) -> set[str]:
    try:
        path = urlsplit(final_url).path
    except ValueError:
        return set()
    return {segment.casefold() for segment in path.split("/") if segment}


def _identity_text(title: str, headings: Mapping[str, object]) -> str:
    values = [title]
    for key in ("h1_texts", "h2_texts"):
        raw = headings.get(key)
        if isinstance(raw, list):
            values.extend(str(value) for value in raw)
    return " ".join(values)


def freshness_context_facts(
    *, final_url: str, title: str, headings: Mapping[str, object]
) -> dict[str, object]:
    """Return bounded context that can require freshness without using a date."""
    reasons: list[str] = []
    if _route_segments(final_url) & FRESHNESS_ROUTE_SEGMENTS:
        reasons.append("changelog_or_news_route")
    identity = _identity_text(title, headings)
    if _IDENTITY_RE.search(identity):
        reasons.append("explicit_year_or_version_identity")
    if _PURPOSE_RE.search(identity):
        reasons.append("time_bound_purpose_identity")
    return {"required": bool(reasons), "reasons": reasons}
