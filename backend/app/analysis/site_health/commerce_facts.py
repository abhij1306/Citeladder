"""Generic bounded Commerce facts extracted from an already-safe HTML tree."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.parse import urljoin

from app.analysis.site_health.fact_regions import primary_region_text

_PRICE = re.compile(
    r"(?:[$£€₹]|AUD|USD|CAD|NZD|GBP|EUR|INR)\s*\d[\d,.]*(?:\.\d{1,2})?",
    re.IGNORECASE,
)
_PRICE_CONTEXT_CHARS = 48
_PRODUCT_TOKENS = ("product-card", "product_card", "productgrid", "product-tile")
_CATEGORY_TOKENS = ("subcategory", "category-card", "department", "collection-card")


def _ancestor_tokens(node: Any) -> str:
    values: list[str] = []
    current = node
    for _ in range(4):
        if current is None:
            break
        values.extend(
            str(current.get(key) or "").casefold()
            for key in ("class", "id", "role", "data-testid")
        )
        current = current.getparent()
    return " ".join(values)


def _breadcrumbs(
    root: Any, *, final_url: str, text_of: Callable[[Any], str]
) -> tuple[list[str], list[dict[str, str]]]:
    xpath = (
        "//*[contains(translate(@class,'BREADCRUMB','breadcrumb'),'breadcrumb') "
        "or @aria-label='breadcrumb' or @aria-label='Breadcrumb']"
    )
    values: list[str] = []
    links: list[dict[str, str]] = []
    for node in root.xpath(xpath)[:4]:
        for item in node.xpath(".//a|.//li|.//span"):
            cleaned = text_of(item).strip()[:255]
            if cleaned and cleaned not in values:
                values.append(cleaned)
            href = str(item.get("href") or "").strip()
            if href:
                row = {
                    "url": urljoin(final_url, href)[:2048],
                    "title": cleaned,
                }
                _append_unique(links, row, limit=16)
            if len(values) >= 16:
                return values, links
    return values, links


def _cards(
    root: Any, *, final_url: str, text_of: Callable[[Any], str]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    products: list[dict[str, str]] = []
    categories: list[dict[str, str]] = []
    for anchor in root.iter("a"):
        href = (anchor.get("href") or "").strip()
        label = text_of(anchor).strip()
        if not href or not label:
            continue
        row = {"url": urljoin(final_url, href)[:2048], "title": label[:512]}
        tokens = _ancestor_tokens(anchor)
        if any(token in tokens for token in _PRODUCT_TOKENS):
            _append_unique(products, row, limit=200)
        elif any(token in tokens for token in _CATEGORY_TOKENS):
            _append_unique(categories, row, limit=100)
    return products, categories


def _append_unique(
    rows: list[dict[str, str]], row: dict[str, str], *, limit: int
) -> None:
    if row not in rows and len(rows) < limit:
        rows.append(row)


def extract_commerce_facts(
    root: Any, *, final_url: str, text_of: Callable[[Any], str]
) -> dict[str, Any]:
    """Return structural taxonomy/card facts without assigning a page kind."""
    breadcrumbs, breadcrumb_links = _breadcrumbs(
        root, final_url=final_url, text_of=text_of
    )
    product_cards, category_links = _cards(root, final_url=final_url, text_of=text_of)
    # The page's own visible text, not the whole tree: ``text_of(root)`` also
    # reads inline <script> bodies, and a JavaScript regex replacement string
    # made every crawled page of a real store report a visible price of "$1".
    page_text = primary_region_text(root, exclude_card_lists=True)
    match = _PRICE.search(page_text)
    return {
        "breadcrumbs": breadcrumbs,
        "breadcrumb_links": breadcrumb_links,
        "product_cards": product_cards,
        "category_links": category_links,
        "category_role": (
            "leaf" if product_cards else "hub" if category_links else "unknown"
        ),
        "visible_price": match.group(0)[:64] if match else "",
        # The words AROUND the price decide whether it is a price at all.
        # Only the bare match was carried forward, so the projector's
        # "from"/"over"/"up to" guard was checking a string that could not
        # contain them, and a "Free shipping over $100" banner became the
        # product's price on every page that had no real one.
        "visible_price_context": _price_context(page_text, match),
    }


def _price_context(text: str, match: re.Match[str] | None) -> str:
    if match is None:
        return ""
    start = max(0, match.start() - _PRICE_CONTEXT_CHARS)
    return " ".join(text[start : match.end() + _PRICE_CONTEXT_CHARS].split())
