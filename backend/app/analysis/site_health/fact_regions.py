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
from app.core.config import site_health_acquisition as _acquisition
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
    """Return the strongest structural primary-content candidate.

    Invalid documents often contain several ``<main>`` elements for drawers,
    search overlays, navigation panels, and the actual document. Select the
    visible candidate with the most page-content evidence instead of trusting
    document order. ``<body>`` remains the fallback when no main/article
    candidate survives.
    """
    try:
        candidates = root.xpath("//main | //*[@role='main'] | //article")
    except DOM_ERRORS as exc:
        dom_failure("primary_region", exc)
        candidates = []
    eligible: list[tuple[Any, str]] = []
    for candidate in candidates[: _config.REGION_MAX_PRIMARY_CANDIDATES]:
        if not region_node_is_visible(candidate):
            continue
        eligible.append((candidate, _primary_candidate_source(candidate)))
    if len(eligible) == 1:
        node, source = eligible[0]
        return node, source
    if eligible:
        ranked = [
            (_primary_candidate_rank(candidate, source), candidate, source)
            for candidate, source in eligible
        ]
        _rank, node, source = max(ranked, key=lambda item: item[0])
        return node, source
    try:
        bodies = root.xpath("//body")
    except DOM_ERRORS as exc:
        dom_failure("primary_region", exc)
        bodies = []
    return (bodies[0], _SOURCE_BODY) if bodies else (root, _SOURCE_ROOT)


def _primary_candidate_source(node: Any) -> str:
    try:
        tag = str(getattr(node, "tag", "") or "").lower()
        role = str(node.get("role") or "").strip().lower()
    except DOM_ERRORS as exc:
        dom_failure("_primary_candidate_source", exc)
        return _SOURCE_ARTICLE
    return _SOURCE_MAIN if tag == "main" or role == "main" else _SOURCE_ARTICLE


def _primary_candidate_rank(node: Any, source: str) -> tuple[int, int, int, int]:
    """Bounded content rank; source priority breaks otherwise equal candidates."""
    heading_count = 0
    try:
        headings = node.xpath(".//h1 | .//h2 | .//h3 | .//h4 | .//h5 | .//h6")
    except DOM_ERRORS as exc:
        dom_failure("_primary_candidate_rank", exc)
        headings = []
    for heading in headings[: _config.REGION_MAX_PRIMARY_CANDIDATES]:
        if region_node_is_visible(heading):
            heading_count += 1
    text_chars = 0
    for part in visible_region_text_nodes(node):
        text_chars += len(str(part).strip())
        if text_chars >= _config.REGION_PRIMARY_RANK_TEXT_CHARS:
            text_chars = _config.REGION_PRIMARY_RANK_TEXT_CHARS
            break
    return (
        int(heading_count > 0),
        heading_count,
        text_chars,
        int(source == _SOURCE_MAIN),
    )


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


def region_text(node: Any, *, excluded_container_ids: set[int] | None = None) -> str:
    """Visible text of ``node`` with every excluded subtree left out.

    This is what ``commerce_facts`` must read instead of the whole tree: an
    inline script body is not visible content, and treating it as such is why
    every page of a real store reported a visible price of ``$1``.
    """
    collected: list[str] = []
    size = 0
    for part in visible_region_text_nodes(node):
        if excluded_container_ids and not node_outside_containers(
            part, excluded_container_ids
        ):
            continue
        chunk = str(part).strip()
        if not chunk:
            continue
        collected.append(chunk)
        size += len(chunk) + 1
        if size >= _config.REGION_MAX_TEXT_CHARS:
            break
    return " ".join(collected)


def primary_region_text(root: Any, *, exclude_card_lists: bool = False) -> str:
    """Visible text of the page's primary region (convenience wrapper)."""
    node, _source = primary_region(root)
    containers = card_list_containers(node) if exclude_card_lists else []
    return region_text(node, excluded_container_ids={id(item) for item in containers})


def node_outside_containers(node: Any, container_ids: set[int]) -> bool:
    """Whether ``node`` sits outside every identified repeated container."""
    if not container_ids:
        return True
    current = node
    for _depth in range(_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is None:
            return True
        if id(current) in container_ids:
            return False
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("node_outside_containers", exc)
            return True
    return True


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
    return any(
        sum(
            count
            for other, count in counts.items()
            if _card_shapes_compatible(shape, other)
        )
        >= _config.CARD_LIST_MIN_ITEMS
        for shape in counts
    )


def _card_shapes_compatible(
    left: tuple[str, tuple[str, ...]], right: tuple[str, tuple[str, ...]]
) -> bool:
    """Match repeated wrappers while tolerating optional direct-child markup."""
    if left[0] != right[0]:
        return False
    left_children = set(left[1])
    right_children = set(right[1])
    return left_children <= right_children or right_children <= left_children


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


def bounded_container_name(container: Any) -> dict[str, str]:
    """Return a bounded, serializable name for a collection container.

    The name intentionally omits IDs, classes, and selectors.  A semantic
    label plus the element tag is enough to explain which observed collection
    an affordance was bound to without persisting DOM implementation details.
    """
    tag = getattr(container, "tag", "")
    normalized_tag = str(tag).lower() if isinstance(tag, str) else ""
    label = _container_label(container)
    return {
        "tag": normalized_tag[:32],
        "label": label[: _acquisition.SITE_HEALTH_MAX_HEADING_CHARS],
    }


def bounded_structural_relation(node: Any, container: Any) -> str:
    """Name the bounded structural relation between an affordance and collection."""
    if _has_ancestor(node, container):
        return "contained"
    if _has_ancestor(container, node):
        return "contains"
    if _targets_container(node, container):
        return "targets"
    if _labels_container(node, container):
        return "labelled"
    if _adjacent_branches(node, container):
        return "adjacent"
    return ""


def _has_ancestor(node: Any, ancestor: Any) -> bool:
    current = node
    for _depth in range(_config.REGION_MAX_ANCESTOR_DEPTH):
        if current is ancestor:
            return True
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("_has_ancestor", exc)
            return False
        if current is None:
            return False
    return False


def _targets_container(node: Any, container: Any) -> bool:
    try:
        container_id = str(container.get("id") or "").strip()
        if not container_id:
            return False
        references = " ".join(
            str(node.get(name) or "")
            for name in ("aria-controls", "aria-owns", "for", "href")
        )
    except DOM_ERRORS as exc:
        dom_failure("_targets_container", exc)
        return False
    tokens = {token.lstrip("#") for token in references.split()}
    return container_id in tokens


def _labels_container(node: Any, container: Any) -> bool:
    try:
        node_id = str(node.get("id") or "").strip()
        labelled_by = str(container.get("aria-labelledby") or "").split()
        described_by = str(container.get("aria-describedby") or "").split()
        node_label = " ".join(
            str(node.get(name) or "") for name in ("aria-label", "title", "name")
        ).casefold()
    except DOM_ERRORS as exc:
        dom_failure("_labels_container", exc)
        return False
    if node_id and node_id in {*labelled_by, *described_by}:
        return True
    label = _container_label(container).casefold()
    return bool(label and len(label) >= 3 and label in node_label)


def _adjacent_branches(node: Any, container: Any) -> bool:
    left = _bounded_ancestors(node)
    right = _bounded_ancestors(container)
    for left_node in left:
        try:
            parent = left_node.getparent()
        except DOM_ERRORS as exc:
            dom_failure("_adjacent_branches", exc)
            return False
        if parent is None:
            continue
        for right_node in right:
            try:
                if right_node.getparent() is not parent:
                    continue
                siblings = list(parent)
                if abs(siblings.index(left_node) - siblings.index(right_node)) == 1:
                    return True
            except DOM_ERRORS as exc:
                dom_failure("_adjacent_branches", exc)
                return False
    return False


def _bounded_ancestors(node: Any) -> list[Any]:
    ancestors: list[Any] = []
    current = node
    for _depth in range(3):
        if current is None:
            break
        ancestors.append(current)
        try:
            current = current.getparent()
        except DOM_ERRORS as exc:
            dom_failure("_bounded_ancestors", exc)
            break
    return ancestors


def _container_label(container: Any) -> str:
    try:
        explicit = " ".join(str(container.get("aria-label") or "").split())
        if explicit:
            return explicit
        for heading in container.xpath(".//h1 | .//h2 | .//h3"):
            text = " ".join(str(heading.text_content() or "").split())
            if text:
                return text
        for sibling in container.itersiblings(preceding=True):
            if getattr(sibling, "tag", None) not in ("h1", "h2", "h3"):
                continue
            return " ".join(str(sibling.text_content() or "").split())
    except DOM_ERRORS as exc:
        dom_failure("_container_label", exc)
    return ""
