# Reading the list of things a business offers, from its own site.
#
# Almost every business publishes that list. Only its name changes: a retailer
# calls it departments, a SaaS calls it products, a law firm calls it
# capabilities, a hospital calls it specialties, a college calls it courses.
# The structure is identical everywhere -- same-origin links, shallow paths,
# noun-phrase labels -- so one harvest serves every business model and nothing
# here encodes any industry's actual categories.
#
# This exists because topic selection used to invent topics from prose. Asked
# to describe a marketplace in five topics with no list to work from, a model
# can only abstract, and it returned "Online Retail", "Ecommerce Marketplace"
# and "Online General Merchandise" -- one topic restated five times. Handed the
# published list instead, the same model returns Air Conditioners, Men's
# Footwear and Mobile Phones Under 25000.
#
# Selection is ranking, never document-order truncation. Document order is not
# importance order: one hospital homepage led with its entire investor
# relations and board tree, which would fill the whole budget before a single
# clinical link appeared.
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.connectors.web_evidence.brand_evidence import BrandEvidencePage
from app.core.config.brand_evidence import (
    BRAND_EVIDENCE_DETAIL_PATH_PATTERN,
    BRAND_EVIDENCE_EDITORIAL_LINK_TERMS,
    BRAND_EVIDENCE_JUNK_LABEL_TERMS,
    BRAND_EVIDENCE_LOCALE_LABELS,
    BRAND_EVIDENCE_MAX_NODES_PER_LABEL_FAMILY,
    BRAND_EVIDENCE_MAX_NODES_PER_PAGE,
    BRAND_EVIDENCE_MAX_NODES_PER_PREFIX,
    BRAND_EVIDENCE_MAX_OFFERING_NODES,
    BRAND_EVIDENCE_MIN_OFFERING_NODES,
    BRAND_EVIDENCE_NAVIGATION_VERBS,
    BRAND_EVIDENCE_OFFERING_HUB_TERMS,
    BRAND_EVIDENCE_OFFERING_LABEL_MAX_WORDS,
    BRAND_EVIDENCE_OFFERING_LABEL_MIN_CHARS,
    BRAND_EVIDENCE_OFFERING_MAX_PATH_DEPTH,
    BRAND_EVIDENCE_PERSON_LABEL_PATTERN,
    BRAND_EVIDENCE_UTILITY_LINK_TERMS,
)

_DETAIL_PATH = re.compile(BRAND_EVIDENCE_DETAIL_PATH_PATTERN, re.IGNORECASE)
_PERSON_LABEL = re.compile(BRAND_EVIDENCE_PERSON_LABEL_PATTERN, re.IGNORECASE)
_TOKEN = re.compile(r"[a-z0-9]+")
# A locale prefix carries no meaning about what a link offers. Skipping it in
# the prefix key stops a fully localized site (every path under /in/ or /en-gb/)
# collapsing into a single bucket, which capped Stripe's whole product list at
# eight links.
_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$", re.IGNORECASE)
_EXCLUDED_TERMS = (
    BRAND_EVIDENCE_UTILITY_LINK_TERMS | BRAND_EVIDENCE_EDITORIAL_LINK_TERMS
)


@dataclass(frozen=True, slots=True)
class OfferingNode:
    """One published offering, as the site itself labels it."""

    ref: str
    label: str
    path: str


@dataclass(frozen=True, slots=True)
class OfferingHarvest:
    """What the site publishes about what it offers."""

    nodes: tuple[OfferingNode, ...] = ()

    @property
    def is_ready(self) -> bool:
        """Whether there is a usable published list.

        Below the floor the caller must tell topic selection the harvest is
        empty so it works from page text and is allowed to return fewer
        topics -- or none. A law firm that renders its practice areas
        client-side genuinely cannot be read, and saying so is the correct
        outcome.
        """
        return len(self.nodes) >= BRAND_EVIDENCE_MIN_OFFERING_NODES

    def serialize(self) -> list[dict[str, str]]:
        return [
            {"ref": node.ref, "label": node.label, "path": node.path}
            for node in self.nodes
        ]


@dataclass(frozen=True, slots=True)
class _Candidate:
    label: str
    path: str
    page_index: int
    order: int
    is_hub: bool

    @property
    def rank(self) -> tuple[int, int, int]:
        # Hub paths first, then the page the link came from, then its position
        # on that page. Every term is deterministic, so the same site always
        # harvests the same list.
        return (0 if self.is_hub else 1, self.page_index, self.order)


def _path_of(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path or "/"
    return f"{path}?{parts.query}" if parts.query else path


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def _terms(label: str, path: str) -> set[str]:
    return set(_TOKEN.findall(f"{label} {path}".casefold()))


def _is_shapely(label: str, path: str) -> bool:
    """Whether a link looks like an offering rather than a control or a page."""
    if len(label) < BRAND_EVIDENCE_OFFERING_LABEL_MIN_CHARS:
        return False
    if len(label.split()) > BRAND_EVIDENCE_OFFERING_LABEL_MAX_WORDS:
        return False
    if label.replace(" ", "").isdigit():
        return False
    low = label.casefold()
    if low in BRAND_EVIDENCE_NAVIGATION_VERBS or low in BRAND_EVIDENCE_LOCALE_LABELS:
        return False
    if set(_TOKEN.findall(low)) & BRAND_EVIDENCE_JUNK_LABEL_TERMS:
        return False
    if _PERSON_LABEL.match(label):
        return False
    segments = _segments(path)
    return bool(segments) and len(segments) <= BRAND_EVIDENCE_OFFERING_MAX_PATH_DEPTH


def _brand_key(brand_terms: list[str]) -> list[str]:
    return [
        " ".join(_TOKEN.findall(term.casefold()))
        for term in brand_terms
        if term.strip()
    ]


def _collect(pages: tuple[BrandEvidencePage, ...]) -> list[tuple[int, int, str, str]]:
    """Flatten every fetched page's links into one ordered candidate list."""
    rows: list[tuple[int, int, str, str]] = []
    for page_index, page in enumerate(pages):
        for order, link in enumerate(page.navigation_links):
            label = " ".join(link.label.split())
            if label:
                rows.append((page_index, order, label, _path_of(link.url)))
    return rows


def _candidates(
    pages: tuple[BrandEvidencePage, ...], *, brand_terms: list[str]
) -> list[_Candidate]:
    rows = _collect(pages)
    brand_keys = _brand_key(brand_terms)
    seen: set[str] = set()
    candidates: list[_Candidate] = []
    for page_index, order, label, path in rows:
        key = f"{label.casefold()}|{path.casefold()}"
        if key in seen:
            continue
        normalized_label = f" {' '.join(_TOKEN.findall(label.casefold()))} "
        if any(brand and f" {brand} " in normalized_label for brand in brand_keys):
            continue
        if _DETAIL_PATH.search(path):
            continue
        if _terms(label, path) & _EXCLUDED_TERMS:
            continue
        if not _is_shapely(label, path):
            continue
        seen.add(key)
        candidates.append(
            _Candidate(
                label=label,
                path=path,
                page_index=page_index,
                order=order,
                is_hub=bool(_terms("", path) & BRAND_EVIDENCE_OFFERING_HUB_TERMS),
            )
        )
    return candidates


def _prefix_key(path: str) -> str:
    """The first meaningful path segment, ignoring any locale prefix."""
    segments = [
        segment for segment in _segments(path) if not _LOCALE_SEGMENT.match(segment)
    ]
    return segments[0].casefold() if segments else ""


def _within_prefix_budget(candidates: list[_Candidate]) -> list[_Candidate]:
    """Cap links per site section and per source page, in rank order.

    Both caps exist because one part of a site can otherwise supply every
    candidate: an investor-relations tree crowded out a hospital's clinical
    navigation, and a single city index or brand sitemap buried a retailer's
    real rail under hundreds of equally well-formed links.
    """
    per_prefix: dict[str, int] = {}
    per_page: dict[int, int] = {}
    kept: list[_Candidate] = []
    for candidate in candidates:
        prefix = _prefix_key(candidate.path)
        if per_prefix.get(prefix, 0) >= BRAND_EVIDENCE_MAX_NODES_PER_PREFIX:
            continue
        if per_page.get(candidate.page_index, 0) >= BRAND_EVIDENCE_MAX_NODES_PER_PAGE:
            continue
        per_prefix[prefix] = per_prefix.get(prefix, 0) + 1
        per_page[candidate.page_index] = per_page.get(candidate.page_index, 0) + 1
        kept.append(candidate)
    return kept


def _within_family_budget(candidates: list[_Candidate]) -> list[_Candidate]:
    """Keep a few labels per template family, not one per location.

    "Ambulance in Chennai" and "Ambulance in Delhi" are one offering listed
    twice; "Hapur, India" and "Kheri, India" are a city index. Both are keyed
    by the tokens they share -- the leading pair and the trailing pair -- so a
    store locator cannot flood the budget while a genuinely varied rail passes
    untouched.
    """
    used: dict[str, int] = {}
    kept: list[_Candidate] = []
    for candidate in candidates:
        # Drop one-character tokens first. "Men's Shoes" and "Women's Shoes"
        # both tokenize with a bare "s", which made their trailing key "s
        # shoes" and merged two real departments into one family.
        tokens = [
            token
            for token in _TOKEN.findall(candidate.label.casefold())
            if len(token) > 1
        ]
        if len(tokens) < 2:
            kept.append(candidate)
            continue
        families = (" ".join(tokens[:2]), " ".join(tokens[-2:]))
        if any(
            used.get(family, 0) >= BRAND_EVIDENCE_MAX_NODES_PER_LABEL_FAMILY
            for family in families
        ):
            continue
        for family in families:
            used[family] = used.get(family, 0) + 1
        kept.append(candidate)
    return kept


def _deduplicated(candidates: list[_Candidate]) -> list[_Candidate]:
    """Drop labels with the same singular-normalized token set.

    Not character similarity. "mens shoes" and "womens shoes" score 0.93, so a
    ratio high enough to collapse "Air Conditioner"/"Air Conditioners" also
    collapsed two real departments -- the same trap the topic-distinctness rule
    fell into. Token identity separates them exactly and needs no threshold.
    """
    kept: list[_Candidate] = []
    seen: set[frozenset[str]] = set()
    for candidate in candidates:
        key = frozenset(
            token[:-1] if len(token) > 3 and token.endswith("s") else token
            for token in _TOKEN.findall(candidate.label.casefold())
            if len(token) > 1
        )
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(candidate)
    return kept


def harvest_offerings(
    pages: tuple[BrandEvidencePage, ...], *, brand_terms: list[str]
) -> OfferingHarvest:
    """Read the site's published offering list from pages already fetched.

    Never fetches. Never raises. An unreadable or offering-free site yields an
    empty harvest, which the caller reports rather than fills in.
    """
    candidates = _candidates(pages, brand_terms=brand_terms)
    candidates.sort(key=lambda candidate: candidate.rank)
    selected = _deduplicated(_within_family_budget(_within_prefix_budget(candidates)))[
        :BRAND_EVIDENCE_MAX_OFFERING_NODES
    ]
    return OfferingHarvest(
        nodes=tuple(
            OfferingNode(ref=f"nav-{index}", label=item.label, path=item.path)
            for index, item in enumerate(selected, start=1)
        )
    )
