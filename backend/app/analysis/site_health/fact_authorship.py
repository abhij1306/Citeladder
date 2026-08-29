"""Bounded author and publication-date extraction from declared and visible facts."""

from __future__ import annotations

import re
from typing import Any

from app.analysis.site_health.content_heuristics import visible_byline, visible_date
from app.analysis.site_health.dom import DOM_ERRORS, dom_failure, node_text
from app.analysis.site_health.fact_regions import primary_region, region_node_is_visible
from app.core.config import site_health_acquisition as acquisition_config
from app.core.config import site_health_authorship as authorship_config
from app.core.config import site_health_taxonomy as taxonomy_config


def _structured_values(structured_data: dict[str, Any]) -> tuple[str, str, str]:
    author = ""
    published = ""
    modified = ""
    for block in structured_data.get("blocks") or []:
        author = author or str(block.get("author") or "").strip()
        published = published or str(block.get("date_published") or "").strip()
        modified = modified or str(block.get("date_modified") or "").strip()
    return author, published, modified


def _first_declared_time(root: Any) -> str:
    try:
        for node in root.xpath("//time[@datetime]"):
            if candidate := (node.get("datetime") or "").strip():
                return candidate
    except DOM_ERRORS as exc:
        dom_failure("_first_declared_time", exc)
    return ""


def _attribute_tokens(node: Any) -> set[str]:
    values = " ".join(
        str(node.get(name) or "") for name in ("class", "id", "itemprop", "rel")
    )
    return {token for token in re.split(r"[^a-z0-9]+", values.casefold()) if token}


def _visible_values(root: Any) -> tuple[str, str]:
    """Targeted visible byline/date evidence from the primary content region."""
    region, _source = primary_region(root)
    author = ""
    published = ""
    try:
        for scanned, node in enumerate(region.iter(), start=1):
            if scanned > taxonomy_config.REGION_MAX_CONTAINERS_SCANNED:
                break
            if not region_node_is_visible(node):
                continue
            tokens = _attribute_tokens(node)
            text = node_text(node)
            if not author and tokens & authorship_config.VISIBLE_AUTHOR_NODE_TOKENS:
                author = visible_byline(text)
            if not published and (
                node.tag == "time"
                or tokens & authorship_config.VISIBLE_DATE_NODE_TOKENS
            ):
                published = visible_date(text)
            if author and published:
                break
    except DOM_ERRORS as exc:
        dom_failure("_visible_values", exc)
    return author, published


def author_and_dates(
    root: Any,
    structured_data: dict[str, Any],
    article_meta: dict[str, str],
    *,
    meta_author: str,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Resolve declared values first, then bounded visible fallbacks."""
    author, published, modified = _structured_values(structured_data)
    visible_author, visible_published = _visible_values(root)
    author = (
        author
        or meta_author.strip()
        or (article_meta.get("article:author") or "").strip()
        or visible_author
    )
    published = (
        published
        or (article_meta.get("article:published_time") or "").strip()
        or _first_declared_time(root)
        or visible_published
    )
    modified = modified or (article_meta.get("article:modified_time") or "").strip()
    return (
        author[: acquisition_config.SITE_HEALTH_MAX_AUTHOR_CHARS],
        {
            "published": published[: acquisition_config.SITE_HEALTH_MAX_DATE_CHARS],
            "modified": modified[: acquisition_config.SITE_HEALTH_MAX_DATE_CHARS],
        },
        {
            "visible_byline": visible_author[
                : acquisition_config.SITE_HEALTH_MAX_AUTHOR_CHARS
            ],
            "visible_date": visible_published[
                : acquisition_config.SITE_HEALTH_MAX_DATE_CHARS
            ],
        },
    )
