"""Bounded content and citability signals extracted from parsed HTML."""

from __future__ import annotations

import re
from typing import Any, Final
from urllib.parse import urlsplit

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.analysis.site_health.dom import node_text as _text
from app.analysis.site_health.fact_regions import (
    card_list_containers,
    node_outside_containers,
    primary_region,
    region_node_is_visible,
)
from app.core.config import site_health_acquisition as config
from app.core.config import site_health_taxonomy as taxonomy
from app.core.config.site_health_rules import ANSWER_FIRST_MAX_HOPS

_PAGE_METADATA_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "author",
        "badge",
        "breadcrumb",
        "byline",
        "date",
        "eyebrow",
        "kicker",
        "metadata",
        "published",
        "tag",
        "timestamp",
    }
)
_NEXT_ACTION_RE: Final = re.compile(
    r"\b(?:apply|book|buy|contact|get started|join|register|request|"
    r"schedule|sign up|start|subscribe|talk to|try)\b",
    re.IGNORECASE,
)
_PROVIDER_RE: Final = re.compile(
    r"^(?P<provider>(?:we|[A-Z][A-Za-z0-9&'.-]*"
    r"(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,5}))\s+"
    r"(?P<verb>provides?|offers?|delivers?|builds?|manages?|"
    r"helps?|enables?|specializes\s+in)\s+",
)
_OFFER_CAPABILITY_RE: Final = re.compile(
    r"\b(?:provides?|offers?|delivers?|builds?|manages?|specializes\s+in)\s+"
    r"(?P<capability>[^.,;]{3,160}?)(?=\s+(?:for|so|that|to)\b|[.,;]|$)",
    re.IGNORECASE,
)
_AUDIENCE_OUTCOME_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bfor\s+(?P<value>[^.,;]{3,160})", re.IGNORECASE),
    re.compile(
        r"\b(?:helps?|enables?|lets?)\s+(?P<value>[^.,;]{3,160})",
        re.IGNORECASE,
    ),
    re.compile(r"\bso\s+(?P<value>[^.,;]{3,160})", re.IGNORECASE),
)


def empty_page_owned_content_facts() -> dict[str, Any]:
    """Stable zero shape for absent, unreadable, or non-rendered content."""
    return {
        "editorial_lead": "",
        "direct_answer": "",
        "entity_proposition": {
            "identity": "",
            "proposition": "",
            "provider": "",
            "named_capability": "",
            "audience_or_outcome": "",
            "next_action": "",
        },
        "primary_heading_outline": [],
    }


def page_owned_content_facts(root: Any) -> dict[str, Any]:
    """Extract bounded facts spoken by the primary content, not page chrome."""
    facts = empty_page_owned_content_facts()
    try:
        region, _source = primary_region(root)
        containers = card_list_containers(region)
        container_ids = {id(item) for item in containers}
        outline = _primary_heading_outline(region, container_ids)
        lead = _editorial_lead(region, container_ids)
        direct = _direct_answer(region, container_ids)
        facts["primary_heading_outline"] = outline
        facts["editorial_lead"] = lead
        facts["direct_answer"] = direct
        facts["entity_proposition"] = _entity_proposition(
            region,
            container_ids,
            outline=outline,
            proposition=lead,
        )
    except DOM_ERRORS as exc:
        dom_failure("page_owned_content_facts", exc)
    return facts


def _primary_heading_outline(
    region: Any, container_ids: set[int]
) -> list[dict[str, Any]]:
    outline: list[dict[str, Any]] = []
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("_primary_heading_outline", exc)
        return outline
    for node in walker:
        tag = str(getattr(node, "tag", "") or "").lower()
        if tag not in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            continue
        if not _page_owned_node(node, region, container_ids):
            continue
        text = " ".join(_text(node).split())[: config.SITE_HEALTH_MAX_HEADING_CHARS]
        if not text:
            continue
        outline.append({"level": int(tag[1]), "text": text})
        if len(outline) >= config.SITE_HEALTH_MAX_HEADINGS_KEPT:
            break
    return outline


def _editorial_lead(region: Any, container_ids: set[int]) -> str:
    seen_identity = False
    scanned = 0
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("_editorial_lead", exc)
        return ""
    for node in walker:
        scanned += 1
        if scanned > taxonomy.REGION_MAX_CONTAINERS_SCANNED:
            break
        tag = str(getattr(node, "tag", "") or "").lower()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and _page_owned_node(
            node, region, container_ids
        ):
            if seen_identity:
                return ""
            seen_identity = tag in {"h1", "h2"}
            continue
        candidate = _editorial_lead_candidate(
            node, region, container_ids, seen_identity=seen_identity
        )
        if candidate:
            return candidate
    return ""


def _editorial_lead_candidate(
    node: Any,
    region: Any,
    container_ids: set[int],
    *,
    seen_identity: bool,
) -> str:
    tag = str(getattr(node, "tag", "") or "").lower()
    if tag != "p" or not seen_identity:
        return ""
    if not _page_owned_node(node, region, container_ids) or _is_metadata_or_cta(node):
        return ""
    text = " ".join(_text(node).split())
    if len(text.split()) < 5:
        return ""
    return text[: config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS]


def _direct_answer(region: Any, container_ids: set[int]) -> str:
    try:
        headings = region.xpath(".//h1 | .//h2 | .//h3 | .//dt")
    except DOM_ERRORS as exc:
        dom_failure("_direct_answer", exc)
        return ""
    accepted = 0
    for heading in headings:
        if not _page_owned_node(heading, region, container_ids):
            continue
        accepted += 1
        if accepted > config.SITE_HEALTH_MAX_HEADINGS_KEPT:
            break
        heading_text = " ".join(_text(heading).split())
        if not _is_answer_heading(heading_text):
            continue
        answer = _associated_answer(region, heading, container_ids)
        if answer:
            return answer[: config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS]
    return ""


def _is_answer_heading(text: str) -> bool:
    normalized = " ".join(text.casefold().split())
    if not normalized:
        return False
    if normalized.endswith("?"):
        return True
    first = normalized.split(" ", 1)[0].strip("¿?¡!.,:;\"'")
    return (
        first in taxonomy.PAGE_KIND_QUESTION_WORDS
        or normalized.startswith("definition ")
        or normalized.startswith("definition of ")
        or normalized.startswith("meaning of ")
        or normalized.startswith("define ")
    )


def _associated_answer(region: Any, heading: Any, container_ids: set[int]) -> str:
    sibling_answer = _answer_from_siblings(region, heading, container_ids)
    if sibling_answer:
        return sibling_answer
    return _answer_from_document_order(region, heading, container_ids)


def _answer_from_siblings(region: Any, heading: Any, container_ids: set[int]) -> str:
    try:
        siblings = heading.itersiblings()
    except DOM_ERRORS as exc:
        dom_failure("_associated_answer", exc)
        return ""
    for hops, sibling in enumerate(siblings, start=1):
        if hops > ANSWER_FIRST_MAX_HOPS or _is_answer_boundary(sibling):
            break
        candidate = _answer_candidate(sibling, region, container_ids)
        if candidate:
            return candidate
    return ""


def _answer_from_document_order(
    region: Any, heading: Any, container_ids: set[int]
) -> str:
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("_associated_answer", exc)
        return ""
    seen_heading = False
    hops = 0
    for node in walker:
        if node is heading:
            seen_heading = True
            continue
        if not seen_heading:
            continue
        hops += 1
        if hops > ANSWER_FIRST_MAX_HOPS or _is_answer_boundary(node):
            break
        candidate = _answer_candidate(node, region, container_ids)
        if candidate:
            return candidate
    return ""


def _is_answer_boundary(node: Any) -> bool:
    return str(getattr(node, "tag", "") or "").lower() in {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "dt",
    }


def _answer_candidate(node: Any, region: Any, container_ids: set[int]) -> str:
    tag = str(getattr(node, "tag", "") or "").lower()
    if tag not in {"p", "dd"} or not _page_owned_node(node, region, container_ids):
        return ""
    if _is_metadata_or_cta(node):
        return ""
    return " ".join(_text(node).split())


def _entity_proposition(
    region: Any,
    container_ids: set[int],
    *,
    outline: list[dict[str, Any]],
    proposition: str,
) -> dict[str, str]:
    identity = next(
        (
            str(item["text"])
            for item in outline
            if item.get("level") == 1 and item.get("text")
        ),
        "",
    )
    provider = _provider_identity(identity, proposition)
    capability = _named_capability(identity, provider, proposition)
    audience_or_outcome = _audience_or_outcome(f"{identity}. {proposition}")
    next_action = _next_action_path(region, container_ids)
    return {
        "identity": identity[: config.SITE_HEALTH_MAX_HEADING_CHARS],
        "proposition": proposition[: config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS],
        "provider": provider[: config.SITE_HEALTH_MAX_HEADING_CHARS],
        "named_capability": capability[: config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS],
        "audience_or_outcome": audience_or_outcome[
            : config.SITE_HEALTH_MAX_FIRST_ANSWER_CHARS
        ],
        "next_action": next_action[: config.SITE_HEALTH_MAX_URL_CHARS],
    }


def _provider_identity(identity: str, proposition: str) -> str:
    match = _PROVIDER_RE.match(proposition.strip())
    if match is None:
        return ""
    provider = match.group("provider").strip()
    return identity if provider.casefold() == "we" else provider


def _named_capability(identity: str, provider: str, proposition: str) -> str:
    match = _OFFER_CAPABILITY_RE.search(proposition)
    if match is not None:
        return " ".join(match.group("capability").split())
    normalized_identity = " ".join(identity.split())
    if provider and normalized_identity.casefold() != provider.casefold():
        words = normalized_identity.split()
        if len(words) >= 2:
            return normalized_identity
    return ""


def _audience_or_outcome(text: str) -> str:
    for pattern in _AUDIENCE_OUTCOME_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return " ".join(match.group("value").split())
    return ""


def _next_action_path(region: Any, container_ids: set[int]) -> str:
    for node in _next_action_nodes(region, container_ids):
        path = _next_action_candidate(node)
        if path:
            return path
    return ""


def _next_action_nodes(region: Any, container_ids: set[int]) -> list[Any]:
    nodes: list[Any] = []
    try:
        walker = region.iter()
        for scanned, node in enumerate(walker, start=1):
            if scanned > taxonomy.REGION_MAX_CONTAINERS_SCANNED:
                break
            tag = str(getattr(node, "tag", "") or "").lower()
            if tag not in {"a", "form"}:
                continue
            if not _page_owned_node(node, region, container_ids):
                continue
            nodes.append(node)
            if len(nodes) >= config.SITE_HEALTH_MAX_CTA_TEXTS * 4:
                break
    except DOM_ERRORS as exc:
        dom_failure("_next_action_path", exc)
    return nodes


def _next_action_candidate(node: Any) -> str:
    text = " ".join(_text(node).split())
    if not (_NEXT_ACTION_RE.search(text) or _is_cta_anchor(node)):
        return ""
    href = str(node.get("href") or node.get("action") or "").strip()
    if not href or href.startswith("#"):
        return ""
    return _bounded_action_path(href)


def _bounded_action_path(href: str) -> str:
    try:
        parts = urlsplit(href)
    except ValueError:
        return ""
    if parts.scheme in {"mailto", "tel"}:
        return f"{parts.scheme}:"
    return parts.path or ""


def _page_owned_node(node: Any, region: Any, container_ids: set[int]) -> bool:
    if not node_outside_containers(node, container_ids) or not region_node_is_visible(
        node
    ):
        return False
    current = node
    for _depth in range(taxonomy.REGION_MAX_ANCESTOR_DEPTH):
        if current is region:
            return True
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("_page_owned_node", exc)
            return False
        if current is None:
            return False
    return False


def _is_metadata_or_cta(node: Any) -> bool:
    text = " ".join(_text(node).split())
    if not text or _is_metadata_copy(text):
        return True
    if _has_explicit_cta_marker(node) or _has_metadata_ancestor(node):
        return True
    return _has_short_cta_descendant(node, text)


def _has_explicit_cta_marker(node: Any) -> bool:
    attributes, _parent = _metadata_node_state(node)
    if attributes is None:
        return True
    tokens = set(re.findall(r"[a-z0-9]+", attributes.casefold()))
    return bool(tokens & config.CTA_BUTTON_ROLE_TOKENS)


def _is_metadata_copy(text: str) -> bool:
    normalized = text.casefold()
    if normalized.startswith("by "):
        name = text[3:].strip()
        return 2 <= len(name) <= 60 and not any(
            character.isdigit() or character in ".,;" for character in name
        )
    if normalized.startswith(("published ", "updated ")):
        return True
    return re.fullmatch(r"\w+\s+\d{1,2},\s+\d{4}", text) is not None


def _has_metadata_ancestor(node: Any) -> bool:
    current = node
    for _depth in range(4):
        attributes, parent = _metadata_node_state(current)
        if attributes is None:
            return True
        tokens = set(re.findall(r"[a-z0-9]+", attributes.casefold()))
        if tokens & _PAGE_METADATA_TOKENS:
            return True
        current = parent
        if current is None:
            break
    return False


def _metadata_node_state(node: Any) -> tuple[str | None, Any]:
    try:
        attributes = " ".join(
            str(node.get(name) or "")
            for name in ("class", "id", "itemprop", "rel", "role")
        )
        return attributes, node.getparent()
    except DOM_ERRORS as exc:
        dom_failure("_is_metadata_or_cta", exc)
        return None, None


def _has_short_cta_descendant(node: Any, text: str) -> bool:
    try:
        links = list(node.xpath(".//a | .//button | .//input[@type='submit']"))
    except DOM_ERRORS as exc:
        dom_failure("_is_metadata_or_cta", exc)
        return True
    if not links or len(text.split()) > 12:
        return False
    return any(_NEXT_ACTION_RE.search(_text(item)) for item in links)


def _is_cta_anchor(node: Any) -> bool:
    role = str(node.get("role") or "").strip().casefold()
    if role == "button":
        return True
    classes = str(node.get("class") or "").casefold()
    return bool(
        classes and set(re.split(r"[\s_-]+", classes)) & config.CTA_BUTTON_ROLE_TOKENS
    )


def _append_unique(values: list[str], seen: set[str], value: str, limit: int) -> None:
    cleaned = " ".join(str(value or "").split())[:limit]
    if cleaned and cleaned.casefold() not in seen:
        seen.add(cleaned.casefold())
        values.append(cleaned)


def _cta_value(node: Any) -> str:
    tag = str(node.tag).lower()
    if tag == "button":
        return _text(node)
    if tag == "input" and str(node.get("type") or "").strip().casefold() in {
        "submit",
        "button",
    }:
        return str(node.get("value") or "")
    return _text(node) if tag == "a" and _is_cta_anchor(node) else ""


def cta_texts(root: Any) -> list[str]:
    texts: list[str] = []
    seen: set[str] = set()

    try:
        for node in root.iter("button", "a", "input"):
            if len(texts) >= config.SITE_HEALTH_MAX_CTA_TEXTS:
                break
            _append_unique(
                texts,
                seen,
                _cta_value(node),
                config.SITE_HEALTH_MAX_CTA_TEXT_CHARS,
            )
    except DOM_ERRORS as exc:
        dom_failure("cta_texts", exc)
    return texts[: config.SITE_HEALTH_MAX_CTA_TEXTS]


def form_fields(root: Any) -> list[str]:
    fields: list[str] = []
    seen: set[str] = set()
    try:
        labels_by_for: dict[str, str] = {}
        for label in root.iter("label"):
            if not region_node_is_visible(label):
                continue
            target = str(label.get("for") or "").strip()
            if target and target not in labels_by_for:
                labels_by_for[target] = _text(label)
        for node in root.iter("input", "select", "textarea"):
            if len(fields) >= config.SITE_HEALTH_MAX_FORM_FIELDS:
                break
            if not region_node_is_visible(node):
                continue
            if _ignored_field(node):
                continue
            candidate = _field_candidate(node, labels_by_for)
            _append_unique(
                fields, seen, candidate, config.SITE_HEALTH_MAX_FORM_FIELD_CHARS
            )
    except DOM_ERRORS as exc:
        dom_failure("form_fields", exc)
    return fields[: config.SITE_HEALTH_MAX_FORM_FIELDS]


def _ignored_field(node: Any) -> bool:
    return str(node.get("type") or "").strip().casefold() in {
        "hidden",
        "submit",
        "button",
        "reset",
        "image",
    }


def _field_candidate(node: Any, labels_by_for: dict[str, str]) -> str:
    return (
        labels_by_for.get(str(node.get("id") or "").strip(), "")
        or node.get("aria-label")
        or node.get("placeholder")
        or node.get("name")
        or ""
    )


def ordered_list_steps(root: Any) -> int:
    """Longest primary-content ordered list outside repeated card grids."""
    try:
        region, _source = primary_region(root)
        excluded = {id(item) for item in card_list_containers(region)}
        return max(
            (
                len(ordered.xpath("./li"))
                for ordered in region.xpath(".//ol")
                if region_node_is_visible(ordered)
                and not any(
                    id(ancestor) in excluded for ancestor in ordered.iterancestors()
                )
            ),
            default=0,
        )
    except DOM_ERRORS as exc:
        dom_failure("ordered_list_steps", exc)
        return 0
