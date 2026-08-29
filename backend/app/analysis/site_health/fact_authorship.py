"""Bounded author and publication-date extraction from declared and visible facts."""

from __future__ import annotations

from typing import Any

from app.analysis.site_health.content_heuristics import visible_byline, visible_date
from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.core.config import site_health_acquisition as config
from app.core.config.site_health_taxonomy import PAGE_KIND_ARTICLE_SCAN_CHARS


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


def author_and_dates(
    root: Any,
    structured_data: dict[str, Any],
    article_meta: dict[str, str],
    *,
    meta_author: str,
    body_text: str,
) -> tuple[str, dict[str, str]]:
    """Resolve declared values first, then bounded visible fallbacks."""
    author, published, modified = _structured_values(structured_data)
    prefix = str(body_text or "")[:PAGE_KIND_ARTICLE_SCAN_CHARS]
    author = (
        author
        or meta_author.strip()
        or (article_meta.get("article:author") or "").strip()
        or visible_byline(prefix)
    )
    published = (
        published
        or (article_meta.get("article:published_time") or "").strip()
        or _first_declared_time(root)
        or visible_date(prefix)
    )
    modified = modified or (article_meta.get("article:modified_time") or "").strip()
    return (
        author[: config.SITE_HEALTH_MAX_AUTHOR_CHARS],
        {
            "published": published[: config.SITE_HEALTH_MAX_DATE_CHARS],
            "modified": modified[: config.SITE_HEALTH_MAX_DATE_CHARS],
        },
    )
