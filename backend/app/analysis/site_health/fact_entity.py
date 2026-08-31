"""Primary-entity signals scoped to the page's own content region.

What makes a page a product page is its **own** buy box, not the prices in a
"You May Also Like" strip; what makes it a listing is its **own** grid, not the
63 category links every page of the site carries in its navigation. So every
signal here is read from :mod:`fact_regions`' primary region and, for the
product signals, from outside every repeated card list in it.

These are observations, not verdicts. This module never names a page kind --
it reports which structures are present, and
:mod:`app.analysis.site_health.page_kinds` decides what that means.
"""

from __future__ import annotations

import re
from typing import Any, Final

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.analysis.site_health.dom import node_text as _text
from app.analysis.site_health.fact_regions import (
    bounded_container_name,
    bounded_structural_relation,
    card_list_containers,
    element_region,
    node_outside_containers,
    primary_region,
    region_node_is_visible,
    visible_region_text_nodes,
)
from app.core.config import site_health_acquisition as _acquisition
from app.core.config import site_health_taxonomy as _config

_PRICE_RE: Final = re.compile(_config.PAGE_KIND_PRICE_PATTERN, re.IGNORECASE)
_RESULT_COUNT_RE: Final = re.compile(_config.RESULT_COUNT_PATTERN, re.IGNORECASE)

_HOURS_XPATH: Final = (
    ".//*[@itemprop='openingHours']|.//*[@itemprop='openingHoursSpecification']"
)

_CHROME_REGIONS: Final[frozenset[str]] = frozenset(
    {
        _config.PAGE_REGION_NAV,
        _config.PAGE_REGION_HEADER,
        _config.PAGE_REGION_FOOTER,
        _config.PAGE_REGION_ASIDE,
    }
)

#: Attributes read when matching a control against a bounded token vocabulary.
_CONTROL_ATTRIBUTES: Final[tuple[str, ...]] = (
    "name",
    "id",
    "class",
    "aria-label",
    "data-testid",
    "value",
)

_RESULT_ATTRIBUTE_TOKENS: Final[frozenset[str]] = frozenset(
    {"count", "matches", "result", "results"}
)
_PAGINATION_TOKENS: Final[frozenset[str]] = frozenset(
    {"pager", "pagination", "next-page", "previous-page"}
)
_EMPTY_STATE_TOKENS: Final[frozenset[str]] = frozenset(
    {"empty-state", "no-results", "nothing-found"}
)
_RECOMMENDATION_TOKENS: Final[frozenset[str]] = frozenset(
    {"more-like", "recommend", "related", "suggested", "you-may-also"}
)
_MAX_COLLECTION_AFFORDANCES: Final = _config.CARD_SHAPE_MAX_CHILDREN


def empty_entity_signals() -> dict[str, Any]:
    """The zero value, used for non-HTML responses and failed reads."""
    return {
        "region": {"source": "", "card_list_count": 0},
        "product": {
            "has_primary_price": False,
            "has_product_detail_heading": False,
            "has_purchase_control": False,
            "has_variant_control": False,
            "has_sku_marker": False,
        },
        "listing": {
            "largest_card_list_size": 0,
            "distinct_card_list_targets": 0,
            "has_result_count": False,
            "has_sort_control": False,
            "has_filter_control": False,
            "has_facet_control": False,
            "has_pagination": False,
            "has_empty_state": False,
            "collection_evidence": {
                "container": {
                    "tag": "",
                    "label": "",
                    "item_count": 0,
                    "distinct_targets": 0,
                },
                "affordances": [],
            },
        },
        "location": {
            "address_entity_count": 0,
            "has_phone": False,
            "has_hours": False,
        },
    }


def safe_entity_signals(root: Any) -> dict[str, Any]:
    """Entity facts for one document, or the zero value when the read fails.

    Call this before body-text extraction mutates non-rendered subtrees.
    The fail-open contract belongs to this module rather than to its caller:
    a page whose structure could not be read has no entity evidence, which is
    exactly what the zero value says.
    """
    try:
        return extract_entity_signals(root)
    except DOM_ERRORS as exc:
        dom_failure("safe_entity_signals", exc)
        return empty_entity_signals()


def extract_entity_signals(root: Any) -> dict[str, Any]:
    """Bounded primary-entity structure facts for one parsed document."""
    facts = empty_entity_signals()
    region, source = primary_region(root)
    # Held for the whole call: lxml element proxies stay identity-stable only
    # while a reference to them is alive, and the outside-card-list test below
    # compares node identity.
    containers = card_list_containers(region)
    container_ids = {id(node) for node in containers}
    facts["region"] = {"source": source, "card_list_count": len(containers)}
    facts["product"] = _product_signals(region, container_ids)
    facts["listing"] = _listing_signals(region, _listing_containers(region, containers))
    facts["location"] = _location_signals(region)
    return facts


def _product_signals(region: Any, container_ids: set[int]) -> dict[str, Any]:
    return {
        "has_primary_price": _has_price_outside_cards(region, container_ids),
        "has_product_detail_heading": _has_product_detail_heading(
            region, container_ids
        ),
        "has_purchase_control": _has_purchase_control(region, container_ids),
        "has_variant_control": _has_variant_control(region, container_ids),
        "has_sku_marker": _has_sku_marker(region, container_ids),
    }


def _has_product_detail_heading(region: Any, container_ids: set[int]) -> bool:
    for node in _find(region, ".//h2"):
        if not node_outside_containers(node, container_ids):
            continue
        normalized = " ".join(re.findall(r"[a-z0-9]+", _text(node).lower()))
        if normalized in _config.PRODUCT_DETAIL_HEADING_PHRASES:
            return True
    return False


def _listing_containers(region: Any, repeated: list[Any]) -> list[Any]:
    """Repeated containers plus explicit list/grid owners for empty-state binding."""
    containers = [
        item
        for item in repeated
        if not _inside_collection_excluded_region(item, region)
    ]
    known = {id(item) for item in repeated}
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("_listing_containers", exc)
        return containers
    for scanned, node in enumerate(walker, start=1):
        if scanned > _config.REGION_MAX_CONTAINERS_SCANNED:
            break
        if (
            id(node) in known
            or _inside_collection_excluded_region(node, region)
            or not _is_explicit_list_container(node)
        ):
            continue
        known.add(id(node))
        containers.append(node)
    return containers


def _is_explicit_list_container(node: Any) -> bool:
    try:
        tag = str(getattr(node, "tag", "") or "").lower()
        role = str(node.get("role") or "").strip().casefold()
        identity = " ".join(
            str(node.get(name) or "") for name in ("id", "class", "aria-label")
        ).casefold()
    except DOM_ERRORS as exc:
        dom_failure("_is_explicit_list_container", exc)
        return False
    if role in {"feed", "grid", "list", "listbox"}:
        return True
    if tag not in {"div", "ol", "section", "ul"}:
        return False
    tokens = set(re.findall(r"[a-z0-9]+", identity))
    return bool(tokens & {"catalog", "grid", "items", "list", "products", "results"})


def _listing_signals(region: Any, containers: list[Any]) -> dict[str, Any]:
    affordance_nodes = _collection_affordance_nodes(region)
    observations = [
        _collection_observation(item, affordance_nodes) for item in containers
    ]
    largest = max(
        observations,
        key=lambda item: (
            int(item["container"]["item_count"]),
            int(item["container"]["distinct_targets"]),
        ),
        default=None,
    )
    evidence_candidates = [
        item for item in observations if not item.pop("_is_recommendation", False)
    ]
    selected = max(
        evidence_candidates,
        key=lambda item: (
            int(item["container"]["item_count"]),
            len(item["affordances"]),
            int(item["container"]["distinct_targets"]),
        ),
        default=None,
    )
    evidence = selected or empty_entity_signals()["listing"]["collection_evidence"]
    affordance_classes = {
        str(item.get("class") or "") for item in evidence["affordances"]
    }
    largest_container = largest["container"] if largest is not None else {}
    return {
        "largest_card_list_size": int(largest_container.get("item_count", 0)),
        "distinct_card_list_targets": int(largest_container.get("distinct_targets", 0)),
        "has_result_count": "result_count" in affordance_classes,
        "has_sort_control": "sort" in affordance_classes,
        "has_filter_control": bool({"filter", "facet"} & affordance_classes),
        "has_facet_control": "facet" in affordance_classes,
        "has_pagination": "pagination" in affordance_classes,
        "has_empty_state": "empty_state" in affordance_classes,
        "collection_evidence": evidence,
    }


def _location_signals(region: Any) -> dict[str, Any]:
    return {
        "address_entity_count": len(
            _find(region, ".//address | .//*[@itemprop='address']")
        ),
        "has_phone": bool(_find(region, ".//a[starts-with(@href, 'tel:')]")),
        "has_hours": bool(_find(region, _HOURS_XPATH)),
    }


def _find(node: Any, expression: str) -> list[Any]:
    """Elements matching ``expression`` that are not inside page chrome."""
    try:
        found = list(node.xpath(expression))
    except DOM_ERRORS as exc:
        dom_failure("fact_entity._find", exc)
        return []
    return [
        item
        for item in found
        if region_node_is_visible(item) and element_region(item) not in _CHROME_REGIONS
    ]


def _has_price_outside_cards(region: Any, container_ids: set[int]) -> bool:
    """A visible price that belongs to this page, not to a card in a list."""
    scanned = 0
    for text_node in visible_region_text_nodes(region):
        scanned += 1
        if scanned > _config.REGION_MAX_CONTAINERS_SCANNED:
            break
        chunk = str(text_node).strip()
        if not chunk or not _PRICE_RE.search(chunk):
            continue
        parent = _parent_of(text_node)
        if parent is None:
            continue
        if element_region(parent) in _CHROME_REGIONS:
            continue
        if node_outside_containers(parent, container_ids):
            return True
    return False


def _parent_of(text_node: Any) -> Any:
    try:
        return text_node.getparent()
    except DOM_ERRORS as exc:
        dom_failure("_parent_of", exc)
        return None


def _has_purchase_control(region: Any, container_ids: set[int]) -> bool:
    """A form posting to a cart endpoint, or a labelled purchase button.

    The cart-marker vocabulary is the one already used by the content
    heuristic; the change is that it is read from CONTROLS in this page's own
    region rather than from anywhere in the body text, which is what let a
    recommendation carousel speak for the page.
    """
    for form in _find(region, ".//form[@action]"):
        action = (form.get("action") or "").strip().lower()
        if not node_outside_containers(form, container_ids):
            continue
        if any(token in action for token in _config.CART_FORM_ACTION_TOKENS):
            return True
    return _has_purchase_button(region, container_ids)


def _has_purchase_button(region: Any, container_ids: set[int]) -> bool:
    for control in _find(region, ".//button | .//input[@type='submit'] | .//a[@href]"):
        if not node_outside_containers(control, container_ids):
            continue
        blob = f"{_attr_blob(control)} {_text(control).lower()}"
        if any(marker in blob for marker in _config.PAGE_KIND_CART_MARKERS):
            return True
    return False


def _has_variant_control(region: Any, container_ids: set[int]) -> bool:
    """A size/colour chooser: one multi-option select, or grouped radios.

    A listing page's "Sort by" dropdown is also a multi-option select, so the
    sort/filter vocabulary is excluded here -- otherwise every category page
    would report a variant control and corroborate a product reading of
    itself.
    """
    for select in _find(region, ".//select"):
        if not node_outside_containers(select, container_ids):
            continue
        if _matches_tokens(select, _config.SORT_CONTROL_TOKENS):
            continue
        if _matches_tokens(select, _config.FILTER_CONTROL_TOKENS):
            continue
        if len(_find(select, ".//option")) >= _config.VARIANT_MIN_OPTIONS:
            return True
    names: dict[str, int] = {}
    for radio in _find(region, ".//input[@type='radio']"):
        if not node_outside_containers(radio, container_ids):
            continue
        name = (radio.get("name") or "").strip().lower()
        if name:
            names[name] = names.get(name, 0) + 1
    return any(count >= _config.VARIANT_MIN_OPTIONS for count in names.values())


def _has_sku_marker(region: Any, container_ids: set[int]) -> bool:
    for node in _find(region, ".//*[@itemprop='sku'] | .//*[@data-sku] | .//*[@id]"):
        if not node_outside_containers(node, container_ids):
            continue
        if _sku_attribute(node):
            return True
    return False


def _sku_attribute(node: Any) -> bool:
    try:
        keys = [str(key).strip().lower() for key in node.keys()]
        itemprop = (node.get("itemprop") or "").strip().lower()
    except DOM_ERRORS as exc:
        dom_failure("_sku_attribute", exc)
        return False
    if itemprop == "sku":
        return True
    return any(key in _config.SKU_ATTRIBUTE_TOKENS for key in keys)


def _collection_observation(
    container: Any, affordance_nodes: list[Any]
) -> dict[str, Any]:
    item_count, distinct_targets = _card_list_observation(container)
    name = bounded_container_name(container)
    descriptor: dict[str, Any] = {
        **name,
        "item_count": item_count,
        "distinct_targets": distinct_targets,
    }
    affordances: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for node in affordance_nodes:
        affordance_class = _affordance_class(node)
        if not affordance_class:
            continue
        relation = bounded_structural_relation(node, container)
        if not relation:
            continue
        key = (affordance_class, relation)
        if key in seen:
            continue
        seen.add(key)
        affordances.append(
            {
                "class": affordance_class,
                "relation": relation,
                "text": _bounded_evidence_text(node),
            }
        )
        if len(affordances) >= _MAX_COLLECTION_AFFORDANCES:
            break
    return {
        "container": descriptor,
        "affordances": affordances,
        "_is_recommendation": _is_recommendation_container(container, name),
    }


def _collection_affordance_nodes(region: Any) -> list[Any]:
    found: list[Any] = []
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("_collection_affordance_nodes", exc)
        return found
    for scanned, node in enumerate(walker, start=1):
        if scanned > _config.REGION_MAX_CONTAINERS_SCANNED:
            break
        if not isinstance(getattr(node, "tag", None), str):
            continue
        if _inside_collection_excluded_region(
            node, region, allow_pagination_navigation=True
        ):
            continue
        if _could_be_affordance(node):
            found.append(node)
    return found


def _inside_collection_excluded_region(
    node: Any,
    region: Any,
    *,
    allow_pagination_navigation: bool = False,
) -> bool:
    current = node
    for _depth in range(_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is region:
            return False
        state = _collection_ancestor_state(current)
        if state is None:
            return True
        current_node = current
        tag, role, current = state
        if _collection_ancestor_is_excluded(tag, role):
            if allow_pagination_navigation and _is_pagination_navigation(
                current_node, tag, role
            ):
                continue
            return True
        if current is None:
            return True
    return True


def _is_pagination_navigation(node: Any, tag: str, role: str) -> bool:
    if tag != "nav" and role != "navigation":
        return False
    return _is_pagination(node, _attr_blob(node))


def _collection_ancestor_state(node: Any) -> tuple[str, str, Any] | None:
    try:
        tag = str(getattr(node, "tag", "") or "").lower()
        role = str(node.get("role") or "").strip().lower()
        return tag, role, node.getparent()
    except DOM_ERRORS as exc:
        dom_failure("_inside_collection_excluded_region", exc)
        return None


def _collection_ancestor_is_excluded(tag: str, role: str) -> bool:
    return tag in {"aside", "footer", "header", "nav"} or role in {
        "banner",
        "complementary",
        "contentinfo",
        "navigation",
    }


def _could_be_affordance(node: Any) -> bool:
    tag = str(getattr(node, "tag", "") or "").lower()
    if tag in {
        "a",
        "button",
        "fieldset",
        "form",
        "nav",
        "output",
        "p",
        "select",
        "span",
        "strong",
    }:
        return True
    blob = _attr_blob(node)
    return bool(
        _has_blob_token(blob, _RESULT_ATTRIBUTE_TOKENS)
        or _has_blob_token(blob, _PAGINATION_TOKENS)
        or _has_blob_token(blob, _EMPTY_STATE_TOKENS)
    )


def _affordance_class(node: Any) -> str:
    blob = _attr_blob(node)
    if _is_result_count(node, blob):
        return "result_count"
    if _matches_tokens(node, _config.SORT_CONTROL_TOKENS):
        return "sort"
    if _matches_tokens(node, _config.FILTER_CONTROL_TOKENS):
        return "facet" if "facet" in _normalized_tokens(blob) else "filter"
    if _is_pagination(node, blob):
        return "pagination"
    if _is_empty_state(node, blob):
        return "empty_state"
    return ""


def _is_result_count(node: Any, blob: str) -> bool:
    text = " ".join(_text(node).split())
    if not text or _RESULT_COUNT_RE.search(text) is None:
        return False
    try:
        semantic = (
            str(getattr(node, "tag", "") or "").lower() == "output"
            or str(node.get("role") or "").strip().lower() == "status"
            or node.get("aria-live") is not None
            or _has_blob_token(blob, _RESULT_ATTRIBUTE_TOKENS)
        )
    except DOM_ERRORS as exc:
        dom_failure("_is_result_count", exc)
        return False
    return semantic


def _is_pagination(node: Any, blob: str) -> bool:
    try:
        rel = _normalized_tokens(str(node.get("rel") or ""))
        tag = str(getattr(node, "tag", "") or "").lower()
        aria_label = str(node.get("aria-label") or "").casefold()
    except DOM_ERRORS as exc:
        dom_failure("_is_pagination", exc)
        return False
    return (
        bool({"next", "prev", "previous"} & rel)
        or _has_blob_token(blob, _PAGINATION_TOKENS)
        or (tag == "nav" and "pagination" in aria_label)
    )


def _is_empty_state(node: Any, blob: str) -> bool:
    text = " ".join(_text(node).casefold().split())
    return _has_blob_token(blob, _EMPTY_STATE_TOKENS) or bool(
        re.fullmatch(
            r"(?:0\s+(?:results?|items?|products?)|"
            r"no\s+(?:results?|items?|products?)"
            r"(?:\s+(?:found|available))?|nothing\s+found)[.!]?",
            text,
        )
    )


def _matches_tokens(node: Any, tokens: frozenset[str]) -> bool:
    """Whether a control's identifying attributes name one of ``tokens``."""
    return bool(_normalized_tokens(_attr_blob(node)) & tokens)


def _has_blob_token(blob: str, tokens: frozenset[str]) -> bool:
    normalized = _normalized_tokens(blob)
    return bool(
        normalized & tokens or any(token in blob for token in tokens if "-" in token)
    )


def _normalized_tokens(value: str) -> set[str]:
    normalized = value.casefold()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    tokens.update(re.findall(r"[a-z0-9]+-[a-z0-9]+", normalized))
    return tokens


def _attr_blob(node: Any) -> str:
    """Lowercase concatenation of bounded identifying attributes."""
    try:
        values = [str(node.get(name) or "") for name in _CONTROL_ATTRIBUTES]
    except DOM_ERRORS as exc:
        dom_failure("_attr_blob", exc)
        return ""
    return " ".join(values).lower()[: _acquisition.SITE_HEALTH_MAX_META_CHARS]


def _bounded_evidence_text(node: Any) -> str:
    text = " ".join(
        str(item).strip()
        for item in visible_region_text_nodes(node)
        if str(item).strip()
    )
    return " ".join(text.split())[: _acquisition.SITE_HEALTH_MAX_CTA_TEXT_CHARS]


def _is_recommendation_container(container: Any, name: dict[str, str]) -> bool:
    label = str(name.get("label") or "").casefold()
    blob = _attr_blob(container)
    normalized = f"{label} {blob}".replace(" ", "-")
    return any(token in normalized for token in _RECOMMENDATION_TOKENS)


def _card_list_observation(container: Any) -> tuple[int, int]:
    """Item and distinct-target observations for one repeated container."""
    items = 0
    targets: set[str] = set()
    try:
        children = list(container)
    except DOM_ERRORS as exc:
        dom_failure("_card_list_observation", exc)
        return 0, 0
    for child in children:
        if not isinstance(getattr(child, "tag", None), str):
            continue
        hrefs = _hrefs(child)
        if not hrefs:
            continue
        items += 1
        targets.update(hrefs)
    return items, len(targets)


def _hrefs(node: Any) -> list[str]:
    try:
        return [
            href
            for anchor in node.iter("a")
            if (href := (anchor.get("href") or "").strip())
        ]
    except DOM_ERRORS as exc:
        dom_failure("_hrefs", exc)
        return []
