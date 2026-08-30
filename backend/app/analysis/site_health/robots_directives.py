"""Bounded robots meta and response-header directive extraction."""

from __future__ import annotations

from typing import Any

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure


def _tokens(value: str) -> set[str]:
    return {token.strip().lower() for token in value.split(",") if token.strip()}


def _max_snippet(tokens: set[str]) -> int | None:
    for token in tokens:
        if not token.startswith("max-snippet:"):
            continue
        try:
            return int(token.partition(":")[2].strip())
        except ValueError:
            return None
    return None


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
    combined = set(robots.get("directives") or ()) | _tokens(header_value)
    return _projection(combined)
