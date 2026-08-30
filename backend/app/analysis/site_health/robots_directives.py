"""Bounded robots meta and response-header directive extraction."""

from __future__ import annotations

from typing import Any

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.core.config.site_health_search_rules import SEARCH_ROBOTS_HEADER_AGENTS

_COLON_DIRECTIVES = frozenset(
    {"max-snippet", "max-image-preview", "max-video-preview", "unavailable_after"}
)


def _tokens(value: str) -> set[str]:
    return {token.strip().lower() for token in value.split(",") if token.strip()}


def _header_tokens(value: str) -> set[str]:
    directives: set[str] = set()
    applicable_scope = True
    for token in (item.strip().lower() for item in value.split(",")):
        if not token:
            continue
        prefix, separator, payload = token.partition(":")
        if separator and prefix not in _COLON_DIRECTIVES:
            applicable_scope = prefix in SEARCH_ROBOTS_HEADER_AGENTS
            if applicable_scope and payload.strip():
                directives.add(payload.strip())
            continue
        if applicable_scope:
            directives.add(token)
    return directives


def _max_snippet(tokens: set[str]) -> int | None:
    values: list[int] = []
    for token in tokens:
        if not token.startswith("max-snippet:"):
            continue
        try:
            values.append(int(token.partition(":")[2].strip()))
        except ValueError:
            continue
    bounded = [value for value in values if value >= 0]
    if bounded:
        return min(bounded)
    return -1 if -1 in values else None


def _projection(tokens: set[str]) -> dict[str, Any]:
    return {
        "noindex": "noindex" in tokens or "none" in tokens,
        "nofollow": "nofollow" in tokens or "none" in tokens,
        "nosnippet": "nosnippet" in tokens,
        "max_snippet": _max_snippet(tokens),
        "directives": sorted(tokens)[:32],
    }


def extract_robots_directives(root: Any) -> dict[str, Any]:
    """Read general/search robots meta without collapsing snippet controls."""
    try:
        nodes = root.xpath(
            "//meta[translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='robots' or "
            "translate(@name,"
            "'ABCDEFGHIJKLMNOPQRSTUVWXYZ',"
            "'abcdefghijklmnopqrstuvwxyz')='googlebot']"
        )
    except DOM_ERRORS as exc:
        dom_failure("extract_robots_directives", exc)
        nodes = []
    tokens: set[str] = set()
    for node in nodes:
        tokens.update(_tokens(str(node.get("content") or "")))
    return _projection(tokens)


def merge_x_robots_tag(robots: dict[str, Any], header_value: str) -> dict[str, Any]:
    """Merge the persisted allowlisted X-Robots-Tag into meta observations."""
    header_tokens = _header_tokens(header_value)
    merged = _projection(set(robots.get("directives") or ()) | header_tokens)
    header = _projection(header_tokens)
    for key in ("noindex", "nofollow", "nosnippet"):
        merged[key] = bool(robots.get(key)) or header[key]
    snippet_values = [
        value
        for value in (robots.get("max_snippet"), header["max_snippet"])
        if isinstance(value, int)
    ]
    bounded = [value for value in snippet_values if value >= 0]
    merged["max_snippet"] = (
        min(bounded) if bounded else (-1 if -1 in snippet_values else None)
    )
    return merged
