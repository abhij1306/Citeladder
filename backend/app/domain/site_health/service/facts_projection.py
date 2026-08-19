"""Pure normalized-facts projection for the page-detail contract."""

from __future__ import annotations


def _robots_directives(facts: dict) -> list[str]:
    robots = facts.get("robots") or {}
    return [name for name in ("noindex", "nofollow") if robots.get(name)]


def _link_counts(facts: dict) -> tuple[int, int]:
    anchors = (facts.get("links") or {}).get("anchors") or []
    internal = sum(1 for anchor in anchors if anchor.get("is_internal"))
    return internal, len(anchors) - internal


def _heading_count(facts: dict) -> int:
    counts = (facts.get("headings") or {}).get("counts") or {}
    return sum(int(value or 0) for value in counts.values())


def _groups(
    facts: dict | None,
) -> tuple[dict, dict, dict, dict, int, int]:
    facts = facts or {}
    headings = facts.get("headings") or {}
    images = facts.get("images") or {}
    body = facts.get("body") or {}
    structured = facts.get("structured_data") or {}
    internal, external = _link_counts(facts)
    return headings, images, body, structured, internal, external


def project_page_facts(facts: dict | None) -> dict:
    """Project bounded persisted facts into the stable detail shape."""
    facts = facts or {}
    headings, images, body, structured, internal, external = _groups(facts)
    return {
        "title": facts.get("title") or None,
        "meta_description": facts.get("meta_description") or None,
        "canonical_url": facts.get("canonical_url") or None,
        "robots_directives": _robots_directives(facts),
        "h1_count": int(headings.get("h1_count", 0) or 0),
        "heading_count": _heading_count(facts),
        "image_count": int(images.get("count", 0) or 0),
        "image_missing_alt_count": int(images.get("missing_alt", 0) or 0),
        "word_count": int(body.get("word_count", 0) or 0),
        "internal_link_count": int(internal),
        "external_link_count": external,
        "structured_data_types": list(structured.get("types") or []),
    }
