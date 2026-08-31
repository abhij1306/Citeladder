"""Bounded author and publication-date extraction from declared and visible facts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.analysis.site_health.content_heuristics import (
    visible_author_name,
    visible_byline,
    visible_date,
)
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


@dataclass(slots=True)
class _VisibleAuthorshipEvidence:
    """Visible attribution accumulated while scanning the primary region."""

    author: str = ""
    profile_url: str = ""
    published: str = ""

    def observe(self, node: Any) -> None:
        tokens = _attribute_tokens(node)
        text = _visible_node_text(node)
        tag = str(getattr(node, "tag", "") or "").lower()
        author_tokens = tokens & authorship_config.VISIBLE_AUTHOR_NODE_TOKENS
        heading_candidate = tag in {"h1", "h2", "h3"}
        if not self.author and (author_tokens or heading_candidate):
            self.author = _visible_author_candidate(
                text, tag=tag, has_author_tokens=bool(author_tokens)
            )
            self.profile_url = _visible_profile_url(node) if self.author else ""
        if not self.published and (
            node.tag == "time" or tokens & authorship_config.VISIBLE_DATE_NODE_TOKENS
        ):
            self.published = visible_date(text)


def _visible_author_candidate(text: str, *, tag: str, has_author_tokens: bool) -> str:
    if byline := visible_byline(text):
        return byline
    if has_author_tokens:
        return visible_author_name(text)
    if (
        tag in {"h2", "h3"}
        and text.casefold() not in authorship_config.VISIBLE_AUTHOR_HEADING_EXCLUSIONS
    ):
        return visible_author_name(text)
    return ""


def _visible_node_text(node: Any) -> str:
    """Preserve boundaries between inline descendants such as ``<br>``."""
    try:
        return " ".join(" ".join(str(part) for part in node.itertext()).split())
    except DOM_ERRORS as exc:
        dom_failure("_visible_node_text", exc)
        return node_text(node)


def _visible_values(root: Any) -> tuple[str, str, str]:
    """Targeted visible byline/date evidence from the primary content region."""
    region, _source = primary_region(root)
    evidence = _VisibleAuthorshipEvidence()
    try:
        for scanned, node in enumerate(region.iter(), start=1):
            if scanned > taxonomy_config.REGION_MAX_CONTAINERS_SCANNED:
                break
            if not region_node_is_visible(node):
                continue
            evidence.observe(node)
            if evidence.author and evidence.published:
                break
    except DOM_ERRORS as exc:
        dom_failure("_visible_values", exc)
    return evidence.author, evidence.profile_url, evidence.published


def _visible_profile_url(node: Any) -> str:
    try:
        links = [node] if node.tag == "a" else node.xpath(".//a[@href]")
        href = next(
            (str(link.get("href") or "").strip() for link in links if link.get("href")),
            "",
        )
    except DOM_ERRORS as exc:
        dom_failure("_visible_profile_url", exc)
        return ""
    return href[: acquisition_config.SITE_HEALTH_MAX_URL_CHARS]


def _declared_author(
    structured_author: str, meta_author: str, article_author: str
) -> tuple[str, str]:
    for value, source in (
        (structured_author, "structured_data"),
        (meta_author, "meta_author"),
        (article_author, "article_meta"),
    ):
        if cleaned := value.strip():
            return cleaned, source
    return "", ""


def author_and_dates(
    root: Any,
    structured_data: dict[str, Any],
    article_meta: dict[str, str],
    *,
    meta_author: str,
) -> tuple[str, dict[str, str], dict[str, str]]:
    """Resolve declared values first, then bounded visible fallbacks."""
    structured_author, published, modified = _structured_values(structured_data)
    visible_author, profile_url, visible_published = _visible_values(root)
    declared_author, declared_source = _declared_author(
        structured_author,
        meta_author,
        (article_meta.get("article:author") or ""),
    )
    author = declared_author or visible_author
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
            "visible_profile_url": profile_url,
            "visible_date": visible_published[
                : acquisition_config.SITE_HEALTH_MAX_DATE_CHARS
            ],
            "declared_author": declared_author[
                : acquisition_config.SITE_HEALTH_MAX_AUTHOR_CHARS
            ],
            "declared_author_source": declared_source,
        },
    )
