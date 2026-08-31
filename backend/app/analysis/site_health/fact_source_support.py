"""Bounded source relationships observed inside primary page content."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlsplit

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.analysis.site_health.dom import node_text as _text
from app.analysis.site_health.fact_regions import (
    card_list_containers,
    node_outside_containers,
    primary_region,
    region_node_is_visible,
)
from app.connectors.web_evidence.url_policy import registrable_domain
from app.core.config import site_health_acquisition as acquisition_config
from app.core.config import site_health_taxonomy as taxonomy_config
from app.core.config.site_health_measurement import (
    SOURCE_SUPPORT_ATTRIBUTION_PATTERN,
    SOURCE_SUPPORT_CITATION_MARKER_PATTERN,
    SOURCE_SUPPORT_MAX_ITEMS,
    SOURCE_SUPPORT_SECTION_HEADINGS,
)

_ATTRIBUTION_RE = re.compile(SOURCE_SUPPORT_ATTRIBUTION_PATTERN, re.IGNORECASE)
_CITATION_RE = re.compile(SOURCE_SUPPORT_CITATION_MARKER_PATTERN, re.IGNORECASE)
_SOURCE_ERRORS = (*DOM_ERRORS, ValueError)
_HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})


def empty_source_support_facts() -> dict[str, Any]:
    return {
        "primary_content_available": False,
        "research_sensitive": False,
        "context_reasons": [],
        "attached_sources": [],
        "ambiguous_source_count": 0,
        "invalid_source_count": 0,
    }


def extract_source_support_facts(root: Any, *, final_url: str) -> dict[str, Any]:
    """Inspect source links once without inferring whether they prove a claim."""
    facts = empty_source_support_facts()
    try:
        region, _source = primary_region(root)
        container_ids = {id(item) for item in card_list_containers(region)}
        facts["primary_content_available"] = True
        base_host = urlsplit(final_url).hostname or ""
        _scan_source_nodes(
            region.iter(),
            region=region,
            container_ids=container_ids,
            final_url=final_url,
            base_host=base_host,
            facts=facts,
        )
    except _SOURCE_ERRORS as exc:
        dom_failure("extract_source_support_facts", exc)
        return empty_source_support_facts()
    facts["research_sensitive"] = bool(facts["context_reasons"])
    return facts


def _scan_source_nodes(
    walker: Any,
    *,
    region: Any,
    container_ids: set[int],
    final_url: str,
    base_host: str,
    facts: dict[str, Any],
) -> None:
    section = ""
    section_level = 0
    for scanned, node in enumerate(walker, start=1):
        if scanned > taxonomy_config.REGION_MAX_CONTAINERS_SCANNED:
            break
        if not isinstance(getattr(node, "tag", None), str):
            continue
        tag = str(node.tag).lower()
        if tag in _HEADING_TAGS and _page_owned(node, region, container_ids):
            section, section_level = _next_section(node, section, section_level)
            if section and section not in facts["context_reasons"]:
                facts["context_reasons"].append(section)
            continue
        if tag != "a" or not _page_owned(node, region, container_ids):
            continue
        _record_anchor(
            node,
            section=section,
            final_url=final_url,
            base_host=base_host,
            facts=facts,
        )


def _next_section(node: Any, current: str, current_level: int) -> tuple[str, int]:
    tag = str(node.tag).lower()
    level = int(tag[1])
    heading = " ".join(_text(node).casefold().split()).strip(":")
    if heading in SOURCE_SUPPORT_SECTION_HEADINGS:
        relationship = (
            "methodology_section" if heading == "methodology" else "references_section"
        )
        return relationship, level
    if current and level <= current_level:
        return "", 0
    return current, current_level


def _record_anchor(
    node: Any,
    *,
    section: str,
    final_url: str,
    base_host: str,
    facts: dict[str, Any],
) -> None:
    href = str(node.get("href") or "").strip()
    absolute = urljoin(final_url, href)
    host = _external_host(absolute, base_host=base_host)
    if not host:
        if section and href.startswith(("http://", "https://")):
            facts["invalid_source_count"] += 1
        return
    relationship = section or _local_relationship(node)
    if not relationship:
        facts["ambiguous_source_count"] += 1
        return
    sources = facts["attached_sources"]
    if len(sources) >= SOURCE_SUPPORT_MAX_ITEMS:
        return
    source_name = " ".join(_text(node).split()) or host
    item = {
        "url": absolute[: acquisition_config.SITE_HEALTH_MAX_URL_CHARS],
        "domain": host[: acquisition_config.SITE_HEALTH_MAX_DOMAIN_CHARS],
        "source_name": source_name[: acquisition_config.SITE_HEALTH_MAX_NAME_CHARS],
        "relationship": relationship,
    }
    if item not in sources:
        sources.append(item)


def _external_host(url: str, *, base_host: str) -> str:
    try:
        parts = urlsplit(url)
        hostname = parts.hostname
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not hostname:
        return ""
    host = hostname.casefold().rstrip(".")
    base = base_host.casefold().rstrip(".")
    if host == base:
        return ""
    if base and registrable_domain(host) == registrable_domain(base):
        return ""
    return host


def _local_relationship(node: Any) -> str:
    parent_text = _parent_text(node)
    own_text = " ".join(_text(node).split())
    if _CITATION_RE.search(f"{own_text} {parent_text}"):
        return "citation_marker"
    if _ATTRIBUTION_RE.search(parent_text):
        return "nearby_attribution"
    return ""


def _parent_text(node: Any) -> str:
    parent = node.getparent()
    if parent is None:
        return ""
    return " ".join(_text(parent).split())[
        : acquisition_config.SITE_HEALTH_MAX_META_CHARS
    ]


def _page_owned(node: Any, region: Any, container_ids: set[int]) -> bool:
    if not node_outside_containers(node, container_ids) or not region_node_is_visible(
        node
    ):
        return False
    current = node
    for _depth in range(taxonomy_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is region:
            return True
        tag = str(getattr(current, "tag", "") or "").lower()
        role = str(current.get("role") or "").strip().casefold()
        if tag in {"aside", "footer", "nav"} or role in {
            "complementary",
            "contentinfo",
            "navigation",
        }:
            return False
        current = current.getparent()
        if current is None:
            return False
    return False
