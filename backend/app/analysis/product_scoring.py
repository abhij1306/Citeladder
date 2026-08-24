"""Deterministic product-visibility scoring (no LLM — invariant 9).

Sibling analyzer pass to ``analysis/scoring.py`` (brand level): scores product
mentions, rank-in-list, and price accuracy over the same persisted answer
text. Pure functions only — no I/O, no ORM, no provider. Every knob comes
from ``app/core/config/products.py`` (invariant 1); matching reuses
``analysis/normalization.py`` (imported, not copied — invariant 2).

Matching semantics: each catalog entry's match-alias set is name + SKU +
aliases + variant names/SKUs (folded by ``from_project``). Alias containment
runs on the normalized text (``normalize_alias`` — SKU punctuation survives
as tokens); rank/price extraction runs on the ORIGINAL answer text (list
structure and ``$`` markers are destroyed by normalization), located via a
token-tolerant regex for the same aliases.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from app.analysis.normalization import (
    domain_matches,
    first_alias_offset,
    normalize_alias,
    normalize_domain,
)
from app.core.config.commerce import (
    MERCHANT_DOMAINS,
    MERCHANT_KIND_BRAND_SITE,
    MERCHANT_KIND_OTHER,
    PRICE_RELATION_HIGHER,
    PRICE_RELATION_LOWER,
    PRICE_RELATION_MATCH,
    PRODUCT_ATTRIBUTE_WINDOW_CHARS,
    AttributeDimension,
)
from app.core.config.products import (
    PRICE_CURRENCY_PATTERNS,
    PRODUCT_PRICE_TOLERANCE_ABS,
    PRODUCT_PRICE_TOLERANCE_PCT,
    PRODUCT_PRICE_WINDOW_CHARS,
)
from app.domain.analytics.sanitize import sanitize_referral_url

if TYPE_CHECKING:
    from app.analysis.product_scoring_aggregation import (
        aggregate_product_run,
        score_product_execution,
    )


# --------------------------------------------------------------------------
# Config entries
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ProductEntry:
    id: str
    sku: str
    name: str
    # Full match-alias set (name + sku + aliases + variants), folded at
    # config-build time.
    aliases: tuple[str, ...]
    price: float | None
    currency: str
    # Frozen attribute bag (audit-frozen at creation — invariant 9). The
    # category-keyed attribute dimensions read it, never the live catalog.
    attributes: dict[str, Any]
    # Casefolded ``attributes["category"]``; selects the dimension tuple.
    category: str
    url: str = ""


def _as_price(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _match_aliases(*parts: Any) -> tuple[str, ...]:
    """Fold name/sku/aliases/variant tokens into one deduped match-alias set."""
    seen: set[str] = set()
    aliases: list[str] = []
    for part in parts:
        for value in part if isinstance(part, (list, tuple)) else [part]:
            text = str(value or "").strip()
            if text and text not in seen:
                seen.add(text)
                aliases.append(text)
    return tuple(aliases)


def _owned_product_aliases(item: dict[str, Any]) -> tuple[str, ...]:
    """Combine an owned product's frozen identity and variant aliases."""
    variants = [
        variant for variant in (item.get("variants") or []) if isinstance(variant, dict)
    ]
    return _match_aliases(
        item.get("name"),
        item.get("sku"),
        item.get("aliases") or [],
        [variant.get("name") for variant in variants],
        [variant.get("sku") for variant in variants],
    )


def _owned_product_entry(item: dict[str, Any]) -> ProductEntry:
    """Build one owned-product matcher from the frozen audit catalog."""
    attributes = dict(item.get("attributes") or {})
    return ProductEntry(
        id=str(item.get("id") or ""),
        sku=str(item.get("sku") or ""),
        name=str(item.get("name") or ""),
        aliases=_owned_product_aliases(item),
        price=_as_price(item.get("price")),
        currency=str(item.get("currency") or "").strip().upper(),
        attributes=attributes,
        category=str(attributes.get("category") or "").strip().casefold(),
        url=str(item.get("url") or ""),
    )


@dataclass(frozen=True)
class ProductScoringConfig:
    products: tuple[ProductEntry, ...] = field(default_factory=tuple)
    # Frozen owned domains (from the planner's ``project_scoring_identity``):
    # merchant classification reads this audit-frozen copy, never live
    # ``OwnedDomain`` rows (invariant 9).
    owned_domains: tuple[str, ...] = field(default_factory=tuple)
    price_tolerance_pct: float = PRODUCT_PRICE_TOLERANCE_PCT
    price_tolerance_abs: float = PRODUCT_PRICE_TOLERANCE_ABS

    @classmethod
    def from_project(cls, config: dict[str, Any]) -> ProductScoringConfig:
        """Build from the audit's FROZEN catalog dict (never live config).

        Reads the ``products`` key the planner
        froze via ``project_product_identity`` plus the ``owned_domains``
        key frozen via ``project_scoring_identity`` (mirrors
        ``ScoringConfig.from_project``).
        """
        return cls(
            products=tuple(
                _owned_product_entry(item) for item in config.get("products") or []
            ),
            owned_domains=tuple(
                str(domain) for domain in (config.get("owned_domains") or [])
            ),
        )


# --------------------------------------------------------------------------
# Alias matching (normalized haystack — mirrors the brand scorer)
# --------------------------------------------------------------------------
def _first_offset(aliases: tuple[str, ...], normalized_haystack: str) -> int | None:
    offsets = [
        offset
        for alias in aliases
        if (offset := first_alias_offset(normalize_alias(alias), normalized_haystack))
        is not None
    ]
    return min(offsets) if offsets else None


def _original_text_offset(aliases: tuple[str, ...], text: str) -> int | None:
    """Locate the earliest alias occurrence in the ORIGINAL text.

    Normalized offsets do not map back to the original string (normalization
    collapses whitespace/punctuation), so rank/price extraction re-locates the
    mention with a token-tolerant regex: alias tokens joined by arbitrary
    non-word runs, case-insensitive. Returns None when no alias maps back
    (e.g. NFKC-folded characters) — rank/price then stay absent, keeping the
    pass deterministic.
    """
    starts: list[int] = []
    for alias in aliases:
        tokens = normalize_alias(alias).split()
        if not tokens:
            continue
        pattern = r"(?<!\w)" + r"[^\w]+".join(re.escape(t) for t in tokens) + r"(?!\w)"
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match is not None:
            starts.append(match.start())
    return min(starts) if starts else None


# --------------------------------------------------------------------------
# Shared original-text window (price/attribute/destination extraction)
# --------------------------------------------------------------------------
def _line_clipped_window(text: str, offset: int, window: int) -> tuple[int, str]:
    """Centered character window around ``offset`` clipped to its own line.

    Returns the original-text absolute segment start plus the segment. A
    list item's evidence (price, attributes, links) sits on the same line,
    so clipping keeps a neighbouring item's evidence from being
    misattributed. All context extraction locates mentions via
    ``_original_text_offset`` and scans the segment this returns.
    """
    start = max(0, offset - window // 2)
    end = min(len(text), offset + window // 2)
    line_start = text.rfind("\n", 0, offset) + 1
    line_end = text.find("\n", offset)
    if line_end == -1:
        line_end = len(text)
    start = max(start, line_start)
    end = min(end, line_end)
    return start, text[start:end]


# --------------------------------------------------------------------------
# Price extraction (config-driven currency patterns)
# --------------------------------------------------------------------------
_NUMBER = r"(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"


def _compiled_currency_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    patterns: list[tuple[str, re.Pattern[str]]] = []
    for currency, markers in PRICE_CURRENCY_PATTERNS.items():
        escaped = sorted((re.escape(m) for m in markers), key=len, reverse=True)
        # Symbol/code BEFORE the amount ("$2,499.00", "USD 49.99").
        prefix = re.compile(
            r"(?<![\w$€£])(?:" + "|".join(escaped) + r")\s?" + _NUMBER,
            flags=re.IGNORECASE,
        )
        patterns.append((currency, prefix))
        # ISO code AFTER the amount ("2,499.00 USD"). The widened lookbehind
        # keeps comma-decimal fragments ("1.149,00 EUR") from matching.
        suffix = re.compile(
            r"(?<![\w.,\d])" + _NUMBER + r"\s?(?:" + re.escape(currency) + r")\b",
            flags=re.IGNORECASE,
        )
        patterns.append((currency, suffix))
    return tuple(patterns)


_CURRENCY_PATTERNS = _compiled_currency_patterns()


def _to_amount(raw: str) -> float | None:
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def extract_price_mentions(
    text: str, offset: int, window: int = PRODUCT_PRICE_WINDOW_CHARS
) -> list[dict[str, Any]]:
    """Extract price mentions in a character window around ``offset``.

    Config-driven (``PRICE_CURRENCY_PATTERNS``): a number only counts as a
    price when a known currency marker is present, so every mention carries a
    resolved ISO currency. Overlapping matches (e.g. prefix vs suffix forms)
    are de-duped keeping the earliest/longest. Results are position-ordered;
    each item: ``{"text", "value", "currency", "offset"}`` with ``offset`` in
    original-text coordinates.
    """
    if not text:
        return []
    start, segment = _line_clipped_window(text, offset, window)

    matches: list[dict[str, Any]] = []
    for currency, pattern in _CURRENCY_PATTERNS:
        for match in pattern.finditer(segment):
            value = _to_amount(match.group("amount"))
            if value is None:
                continue
            matches.append(
                {
                    "text": match.group(0),
                    "value": value,
                    "currency": currency,
                    "offset": start + match.start(),
                    "_end": start + match.end(),
                }
            )
    # Earliest first, longest match wins ties; drop overlapping duplicates.
    matches.sort(key=lambda m: (m["offset"], -(m["_end"] - m["offset"])))
    accepted: list[dict[str, Any]] = []
    for candidate in matches:
        if any(
            candidate["offset"] < kept["_end"] and kept["offset"] < candidate["_end"]
            for kept in accepted
        ):
            continue
        accepted.append(candidate)
    for item in accepted:
        del item["_end"]
    return accepted


def price_matches_catalog(
    mentioned_value: float,
    mentioned_currency: str,
    entry: ProductEntry,
    *,
    tolerance_pct: float = PRODUCT_PRICE_TOLERANCE_PCT,
    tolerance_abs: float = PRODUCT_PRICE_TOLERANCE_ABS,
) -> bool | None:
    """Whether a mentioned price matches the catalog price within tolerance.

    Returns None (not verifiable) when the catalog has no price or the
    currencies conflict; else compares within
    ``max(catalog * pct, abs floor)``.
    """
    if entry.price is None:
        return None
    if (
        mentioned_currency
        and entry.currency
        and mentioned_currency.strip().upper() != entry.currency.strip().upper()
    ):
        return None
    tolerance = max(entry.price * tolerance_pct, tolerance_abs)
    return abs(mentioned_value - entry.price) <= tolerance + 1e-9


def price_relation(
    mentioned_value: float,
    mentioned_currency: str,
    entry: ProductEntry,
    *,
    tolerance_pct: float = PRODUCT_PRICE_TOLERANCE_PCT,
    tolerance_abs: float = PRODUCT_PRICE_TOLERANCE_ABS,
) -> str | None:
    """Direction of a mentioned price vs the catalog price.

    Returns None exactly where ``price_matches_catalog`` is unverifiable
    (absent catalog price, or both currencies present and unequal),
    ``match`` when its tolerance comparison holds, else ``higher``/``lower``
    against the catalog price. The legacy ``price_matches_catalog`` boolean
    keeps being written beside this for compatibility.
    """
    matches = price_matches_catalog(
        mentioned_value,
        mentioned_currency,
        entry,
        tolerance_pct=tolerance_pct,
        tolerance_abs=tolerance_abs,
    )
    if matches is None:
        return None
    if matches:
        return PRICE_RELATION_MATCH
    catalog_price = cast(float, entry.price)
    if mentioned_value > catalog_price:
        return PRICE_RELATION_HIGHER
    return PRICE_RELATION_LOWER


# --------------------------------------------------------------------------
# Attribute extraction (config-owned dimension phrases; frequency only)
# --------------------------------------------------------------------------
def _phrase_pattern(phrase: str) -> re.Pattern[str] | None:
    """Token-tolerant whole-phrase regex (mirrors ``_original_text_offset``)."""
    tokens = normalize_alias(phrase).split()
    if not tokens:
        return None
    pattern = r"(?<!\w)" + r"[^\w]+".join(re.escape(t) for t in tokens) + r"(?!\w)"
    return re.compile(pattern, flags=re.IGNORECASE)


def extract_attribute_mentions(
    text: str,
    offset: int,
    dimensions: tuple[AttributeDimension, ...],
    window: int = PRODUCT_ATTRIBUTE_WINDOW_CHARS,
) -> list[dict[str, Any]]:
    """Phrase-matched attribute mentions in the mention's line-clipped window.

    Casefolded whole-phrase matching against the ORIGINAL text segment.
    Each item: ``{"dimension", "group", "text", "offset"}`` with the exact
    matched substring and its original-text absolute offset, deduped by
    (dimension, group, offset) and position-ordered. Frequency has no
    valence (invariant 9).
    """
    if not text or not dimensions:
        return []
    start, segment = _line_clipped_window(text, offset, window)
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for dimension in dimensions:
        for phrase in dimension.phrases:
            pattern = _phrase_pattern(phrase)
            if pattern is None:
                continue
            for match in pattern.finditer(segment):
                absolute = start + match.start()
                key = (dimension.key, dimension.group, absolute)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "dimension": dimension.key,
                        "group": dimension.group,
                        "text": match.group(0),
                        "offset": absolute,
                    }
                )
    found.sort(key=lambda item: (item["offset"], item["dimension"], item["group"]))
    return found


# --------------------------------------------------------------------------
# Buyer-destination extraction (absolute URLs + markdown-link targets)
# --------------------------------------------------------------------------
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((https?://[^)\s]+)\)", flags=re.IGNORECASE)
_ABSOLUTE_URL_RE = re.compile(r"https?://[^\s<>()\[\]\"']+", flags=re.IGNORECASE)
# Bare URLs in prose are usually followed by sentence punctuation or a
# closing bracket; those characters are never part of the destination.
_URL_TRAILING_PUNCT = ".,;:!?)]}'\"*»”’"


def extract_destination_urls(
    text: str, offset: int, window: int = PRODUCT_ATTRIBUTE_WINDOW_CHARS
) -> list[dict[str, Any]]:
    """Absolute http(s) URLs and markdown-link targets in the window.

    Every candidate is sanitized with ``sanitize_referral_url`` (fragment,
    credentials, and non-allowlisted query params dropped) BEFORE being
    returned, deduped by the sanitized URL, and position-ordered. Each
    item: ``{"url", "offset"}`` with the offset in original-text
    coordinates.
    """
    if not text:
        return []
    start, segment = _line_clipped_window(text, offset, window)
    candidates: list[tuple[int, str]] = []
    for match in _MARKDOWN_LINK_RE.finditer(segment):
        candidates.append((start + match.start(1), match.group(1)))
    for match in _ABSOLUTE_URL_RE.finditer(segment):
        candidates.append(
            (start + match.start(), match.group(0).rstrip(_URL_TRAILING_PUNCT))
        )
    candidates.sort(key=lambda item: item[0])
    seen: set[str] = set()
    destinations: list[dict[str, Any]] = []
    for absolute, raw in candidates:
        sanitized = sanitize_referral_url(raw)
        if not sanitized or sanitized in seen:
            continue
        seen.add(sanitized)
        destinations.append({"url": sanitized, "offset": absolute})
    return destinations


def classify_destination(url: str, *, owned_domains: tuple[str, ...]) -> dict[str, str]:
    """Classify a sanitized destination URL into its merchant identity.

    Order: any frozen ``owned_domains`` match -> ``brand_site`` with the
    normalized host as the name; any ``MERCHANT_DOMAINS`` key match -> the
    configured display name and kind; otherwise -> ``other`` with the
    normalized host as the name. All matching is suffix-safe
    (``domain_matches``): ``notamazon.com`` stays ``other`` while a
    subdomain of ``amazon.com`` is the Amazon marketplace.
    ``merchant_domain`` is always the normalized host.
    """
    host = normalize_domain(url)
    for owned in owned_domains:
        if domain_matches(host, owned):
            return {
                "merchant_name": host,
                "merchant_domain": host,
                "merchant_kind": MERCHANT_KIND_BRAND_SITE,
            }
    for domain, (merchant_name, merchant_kind) in MERCHANT_DOMAINS.items():
        if domain_matches(host, domain):
            return {
                "merchant_name": merchant_name,
                "merchant_domain": host,
                "merchant_kind": merchant_kind,
            }
    return {
        "merchant_name": host,
        "merchant_domain": host,
        "merchant_kind": MERCHANT_KIND_OTHER,
    }


# --------------------------------------------------------------------------
# Rank-in-list detection (enumerated blocks: numbered, bullets, tables)
# --------------------------------------------------------------------------
_NUMBERED_RE = re.compile(r"^\s*(\d{1,3})[.)]\s+\S")
_BULLET_RE = re.compile(r"^\s*[-*•]\s+\S")
_TABLE_ROW_RE = re.compile(r"^\s*\|")
_TABLE_SEPARATOR_CELL_RE = re.compile(r"^:?-{3,}:?$")


def _line_spans(text: str) -> list[tuple[int, str]]:
    """(absolute start offset, line) pairs covering ``text``."""
    spans: list[tuple[int, str]] = []
    position = 0
    for line in text.split("\n"):
        spans.append((position, line))
        position += len(line) + 1
    return spans


def _is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return any(cells) and all(
        _TABLE_SEPARATOR_CELL_RE.match(cell) for cell in cells if cell
    )


def _table_rank(block: list[tuple[int, str]], match_offset: int) -> int | None:
    has_header = any(_is_table_separator(line) for _, line in block)
    data_rows = [row for row in block if not _is_table_separator(row[1])]
    if has_header:
        data_rows = data_rows[1:]
    for ordinal, (start, line) in enumerate(data_rows, start=1):
        if start <= match_offset < start + len(line):
            return ordinal
    return None


def _list_rank(
    block: list[tuple[int, str]], match_offset: int, family: str
) -> int | None:
    ordinal = 0
    item_start: int | None = None
    for index, (start, line) in enumerate(block):
        marker = (
            _NUMBERED_RE.match(line) if family == "numbered" else _BULLET_RE.match(line)
        )
        if marker:
            ordinal += 1
            item_start = start
        next_start = block[index + 1][0] if index + 1 < len(block) else None
        if item_start is not None and match_offset >= item_start:
            if next_start is None or match_offset < next_start:
                return ordinal
    return None


def _rank_in_block(
    block: list[tuple[int, str]], match_offset: int, family: str
) -> int | None:
    """1-based ordinal of the block item whose span contains the offset."""
    if family == "table":
        return _table_rank(block, match_offset)
    return _list_rank(block, match_offset, family)


def _rank_line_family(
    line: str,
    *,
    current_family: str,
    current: list[tuple[int, str]],
    last_number: int,
) -> tuple[str, int]:
    numbered = _NUMBERED_RE.match(line)
    if _TABLE_ROW_RE.match(line):
        return "table", last_number
    if numbered:
        number = int(numbered.group(1))
        if current_family == "numbered" and number <= last_number:
            return "numbered_restart", number
        return "numbered", number
    if _BULLET_RE.match(line):
        return "bullet", last_number
    if line.strip() and current and current_family in {"numbered", "bullet"}:
        return current_family, last_number
    return "", last_number


def _rank_blocks(
    lines: list[tuple[int, str]],
) -> list[tuple[str, list[tuple[int, str]]]]:
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    current_family = ""
    current: list[tuple[int, str]] = []
    last_number = 0
    for start, line in lines:
        family, last_number = _rank_line_family(
            line,
            current_family=current_family,
            current=current,
            last_number=last_number,
        )

        if family == "numbered_restart" or (family != current_family and current):
            blocks.append((current_family, current))
            current = []
            current_family = ""
        if family:
            current_family = "numbered" if family == "numbered_restart" else family
            current.append((start, line))
    if current:
        blocks.append((current_family, current))
    return blocks


def detect_product_rank(answer_text: str, match_offset: int) -> int | None:
    """1-based rank of the enumerated item containing ``match_offset``.

    Parses contiguous enumerated blocks — ``1.``/``1)`` numbered lines,
    ``-``/``*``/``•`` bullets, and markdown table rows — and returns the
    ordinal of the item containing the offset. Returns None when the mention
    is not part of an enumeration (prose, headings, ...).
    """
    if not answer_text or match_offset < 0:
        return None
    lines = _line_spans(answer_text)

    for family, block in _rank_blocks(lines):
        block_start = block[0][0]
        block_end = block[-1][0] + len(block[-1][1])
        if block_start <= match_offset < block_end:
            return _rank_in_block(block, match_offset, family)
    return None


__all__ = ["aggregate_product_run", "score_product_execution"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from app.analysis import product_scoring_aggregation

        return getattr(product_scoring_aggregation, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
