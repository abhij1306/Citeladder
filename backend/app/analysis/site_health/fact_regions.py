"""Structural page regions and primary-entity signals.

Every content-derived Site Health signal used to read the WHOLE document, and
that single choice produced most of the classifier's false evidence:

* ``commerce.visible_price`` was ``"$1"`` on every crawled page of a real
  store, taken from a JavaScript regex replacement string in an inline
  ``<script>`` that no visitor ever sees;
* every page of that store carried ~63 navigation links to category pages and
  ~5 footer links to products, so any whole-page link count described the
  template, not the page;
* a "You May Also Like" carousel on a returns-policy page carries prices and
  buy buttons that belong to other pages entirely.

This module owns the fix. It selects one **primary region** using structure
alone -- ``<main>``, else ``<article>``, else ``<body>`` minus the chrome
landmarks and the non-rendered subtrees -- and it tags **repeated card lists**:
any container holding several structurally similar linked children. A
recommendation carousel, a product grid and a related-posts strip are the same
shape, so one structural test covers all three without naming any of them and
without a vocabulary that would eventually delete legitimate content.

Nothing here decides what a page IS. It reports what is present and where.
Nothing is removed from the caller's tree: regions are expressed as XPath
exclusions so later extractors still see the document they expect.
"""

from __future__ import annotations

from typing import Any, Final

from app.analysis.site_health.dom import DOM_ERRORS, dom_failure
from app.core.config import site_health_taxonomy as _config

# One XPath predicate naming every excluded ancestor. Built from config so the
# excluded set stays config-owned (invariant 1) and identical for text reads,
# element reads and the per-anchor region label.
_EXCLUDED_PREDICATE: Final = " or ".join(
    [f"ancestor-or-self::{tag}" for tag in _config.REGION_EXCLUDED_TAGS]
    + [f"ancestor-or-self::*[@role={role!r}]" for role in _config.REGION_EXCLUDED_ROLES]
)

#: Landmark tag -> region label, checked innermost-first when labelling a node.
_REGION_BY_TAG: Final[dict[str, str]] = {
    "nav": _config.PAGE_REGION_NAV,
    "header": _config.PAGE_REGION_HEADER,
    "footer": _config.PAGE_REGION_FOOTER,
    "aside": _config.PAGE_REGION_ASIDE,
    "main": _config.PAGE_REGION_MAIN,
    "article": _config.PAGE_REGION_MAIN,
}

_REGION_BY_ROLE: Final[dict[str, str]] = {
    "navigation": _config.PAGE_REGION_NAV,
    "banner": _config.PAGE_REGION_HEADER,
    "contentinfo": _config.PAGE_REGION_FOOTER,
    "complementary": _config.PAGE_REGION_ASIDE,
    "main": _config.PAGE_REGION_MAIN,
}

_SOURCE_MAIN: Final = "main"
_SOURCE_ARTICLE: Final = "article"
_SOURCE_BODY: Final = "body_minus_chrome"
_SOURCE_ROOT: Final = "root"


def primary_region(root: Any) -> tuple[Any, str]:
    """Return ``(region_node, source_label)`` for the page's primary content.

    Structure only: the first ``<main>`` / ``[role=main]``, else the first
    ``<article>``, else ``<body>``. The chrome landmarks are not removed here;
    they are excluded at read time by :data:`_EXCLUDED_PREDICATE`, so the
    caller's tree is never mutated and later extractors are unaffected.
    """
    for expression, source in (
        ("//main | //*[@role='main']", _SOURCE_MAIN),
        ("//article", _SOURCE_ARTICLE),
        ("//body", _SOURCE_BODY),
    ):
        try:
            found = root.xpath(expression)
        except DOM_ERRORS as exc:
            dom_failure("primary_region", exc)
            continue
        if found:
            return found[0], source
    return root, _SOURCE_ROOT


def visible_region_text_nodes(node: Any) -> list[Any]:
    """Text nodes in ``node`` that the region contract considers visible."""
    try:
        return list(node.xpath(f".//text()[not({_EXCLUDED_PREDICATE})]"))
    except DOM_ERRORS as exc:
        dom_failure("visible_region_text_nodes", exc)
        return []


def region_node_is_visible(node: Any) -> bool:
    """Whether ``node`` is outside every region-excluded subtree."""
    current = node
    for _depth in range(_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is None:
            return True
        try:
            tag = current.tag
            role = (current.get("role") or "").strip().lower()
        except DOM_ERRORS as exc:
            dom_failure("region_node_is_visible", exc)
            return False
        if isinstance(tag, str) and tag in _config.REGION_EXCLUDED_TAGS:
            return False
        if role in _config.REGION_EXCLUDED_ROLES:
            return False
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("region_node_is_visible", exc)
            return False
    return True


def region_text(node: Any) -> str:
    """Visible text of ``node`` with every excluded subtree left out.

    This is what ``commerce_facts`` must read instead of the whole tree: an
    inline script body is not visible content, and treating it as such is why
    every page of a real store reported a visible price of ``$1``.
    """
    collected: list[str] = []
    size = 0
    for part in visible_region_text_nodes(node):
        chunk = str(part).strip()
        if not chunk:
            continue
        collected.append(chunk)
        size += len(chunk) + 1
        if size >= _config.REGION_MAX_TEXT_CHARS:
            break
    return " ".join(collected)


def primary_region_text(root: Any) -> str:
    """Visible text of the page's primary region (convenience wrapper)."""
    node, _source = primary_region(root)
    return region_text(node)


def element_region(node: Any) -> str:
    """Label one element with the landmark region it sits in.

    Walking the ancestor chain is how chrome is identified in this codebase:
    the DOM already says which links are navigation, so nothing downstream has
    to infer boilerplate from how often a link repeats across a crawl.
    """
    current = node
    for _depth in range(_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is None:
            break
        region = _region_of(current)
        if region is not None:
            return region
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("element_region", exc)
            return _config.PAGE_REGION_OTHER
    return _config.PAGE_REGION_OTHER


def _region_of(node: Any) -> str | None:
    """Region label for one node from its own tag/role, or ``None``."""
    try:
        tag = node.tag
        role = (node.get("role") or "").strip().lower()
    except DOM_ERRORS as exc:
        dom_failure("_region_of", exc)
        return None
    if role in _REGION_BY_ROLE:
        return _REGION_BY_ROLE[role]
    if isinstance(tag, str) and tag in _REGION_BY_TAG:
        return _REGION_BY_TAG[tag]
    return None


def card_list_containers(region: Any) -> list[Any]:
    """Containers holding several structurally similar linked children.

    Structural definition only: at least ``CARD_LIST_MIN_ITEMS`` direct
    children that share a tag and each contain a link. That covers product
    grids, recommendation carousels and related-post strips identically, which
    is the point -- the page's own primary entity is never one item of a
    repeated list.
    """
    containers: list[Any] = []
    scanned = 0
    try:
        walker = region.iter()
    except DOM_ERRORS as exc:
        dom_failure("card_list_containers", exc)
        return containers
    for candidate in walker:
        scanned += 1
        if scanned > _config.REGION_MAX_CONTAINERS_SCANNED:
            break
        if _is_card_list(candidate):
            containers.append(candidate)
    return containers


def _is_card_list(candidate: Any) -> bool:
    """Whether one container's direct children form a repeated card list."""
    counts: dict[tuple[str, tuple[str, ...]], int] = {}
    try:
        children = list(candidate)
    except DOM_ERRORS as exc:
        dom_failure("_is_card_list", exc)
        return False
    for child in children:
        signature = _card_shape(child)
        if signature is None:
            continue
        if not _contains_link(child):
            continue
        counts[signature] = counts.get(signature, 0) + 1
    return any(count >= _config.CARD_LIST_MIN_ITEMS for count in counts.values())


def _card_shape(node: Any) -> tuple[str, tuple[str, ...]] | None:
    """Bounded direct-child signature used to group structurally similar cards."""
    tag = getattr(node, "tag", None)
    if not isinstance(tag, str):
        return None
    try:
        children = tuple(
            child_tag
            for child in list(node)[: _config.CARD_SHAPE_MAX_CHILDREN]
            if isinstance((child_tag := getattr(child, "tag", None)), str)
        )
    except DOM_ERRORS as exc:
        dom_failure("_card_shape", exc)
        return None
    return tag, children


def _contains_link(node: Any) -> bool:
    try:
        return next(node.iter("a"), None) is not None
    except DOM_ERRORS as exc:
        dom_failure("_contains_link", exc)
        return False
