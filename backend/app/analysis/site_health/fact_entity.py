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
    card_list_containers,
    element_region,
    node_outside_containers,
    primary_region,
    region_node_is_visible,
    region_text,
    visible_region_text_nodes,
)
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
    facts["listing"] = _listing_signals(region, containers)
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


def _listing_signals(region: Any, containers: list[Any]) -> dict[str, Any]:
    largest, distinct = _largest_card_list(containers)
    text = region_text(region)
    return {
        "largest_card_list_size": largest,
        "distinct_card_list_targets": distinct,
        "has_result_count": bool(_RESULT_COUNT_RE.search(text)),
        "has_sort_control": _has_control(region, _config.SORT_CONTROL_TOKENS),
        "has_filter_control": _has_control(region, _config.FILTER_CONTROL_TOKENS),
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


def _has_control(region: Any, tokens: frozenset[str]) -> bool:
    """A sort/filter affordance somewhere in the page's own region."""
    return any(
        _matches_tokens(control, tokens)
        for control in _find(region, ".//select | .//button | .//fieldset | .//form")
    )


def _matches_tokens(node: Any, tokens: frozenset[str]) -> bool:
    """Whether a control's identifying attributes name one of ``tokens``."""
    blob = _attr_blob(node)
    return any(token in blob for token in tokens)


def _attr_blob(node: Any) -> str:
    """Lowercase concatenation of the attributes a control is identified by."""
    try:
        values = [str(node.get(name) or "") for name in _CONTROL_ATTRIBUTES]
    except DOM_ERRORS as exc:
        dom_failure("_attr_blob", exc)
        return ""
    return " ".join(values).lower()


def _largest_card_list(containers: list[Any]) -> tuple[int, int]:
    """``(largest item count, distinct link targets)`` across card lists."""
    largest = 0
    targets: set[str] = set()
    for container in containers:
        items = 0
        try:
            children = list(container)
        except DOM_ERRORS as exc:
            dom_failure("_largest_card_list", exc)
            continue
        for child in children:
            if not isinstance(getattr(child, "tag", None), str):
                continue
            hrefs = _hrefs(child)
            if not hrefs:
                continue
            items += 1
            targets.update(hrefs)
        largest = max(largest, items)
    return largest, len(targets)


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
