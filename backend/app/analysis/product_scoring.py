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
import uuid
from dataclasses import dataclass, field
from typing import Any, cast

from app.analysis.normalization import (
    domain_matches,
    first_alias_offset,
    normalize_alias,
    normalize_domain,
)
from app.core.config.commerce import (
    ATTRIBUTE_DIMENSIONS,
    CO_PLACEMENT_MAX_PAIRS,
    MERCHANT_DOMAINS,
    MERCHANT_KIND_BRAND_SITE,
    MERCHANT_KIND_OTHER,
    PRICE_RELATION_HIGHER,
    PRICE_RELATION_LOWER,
    PRICE_RELATION_MATCH,
    PRICE_RELATION_MISMATCH,
    PRODUCT_ATTRIBUTE_WINDOW_CHARS,
    PRODUCT_WIN_REQUIRES_ENUMERATION,
    AttributeDimension,
)
from app.core.config.products import (
    PRICE_CURRENCY_PATTERNS,
    PRODUCT_PRICE_TOLERANCE_ABS,
    PRODUCT_PRICE_TOLERANCE_PCT,
    PRODUCT_PRICE_WINDOW_CHARS,
    PRODUCT_RANK_BUCKET_UNRANKED,
    PRODUCT_RANK_BUCKETS,
)
from app.domain.analytics.sanitize import sanitize_referral_url


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


@dataclass(frozen=True)
class CompetitorProductEntry:
    id: str
    competitor: str
    name: str
    aliases: tuple[str, ...]
    price: float | None
    currency: str
    # Competitor products have no attribute bag (M1 model) -> DEFAULT dims.
    category: str = ""


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


@dataclass(frozen=True)
class ProductScoringConfig:
    products: tuple[ProductEntry, ...] = field(default_factory=tuple)
    competitor_products: tuple[CompetitorProductEntry, ...] = field(
        default_factory=tuple
    )
    # Frozen owned domains (from the planner's ``project_scoring_identity``):
    # merchant classification reads this audit-frozen copy, never live
    # ``OwnedDomain`` rows (invariant 9).
    owned_domains: tuple[str, ...] = field(default_factory=tuple)
    price_tolerance_pct: float = PRODUCT_PRICE_TOLERANCE_PCT
    price_tolerance_abs: float = PRODUCT_PRICE_TOLERANCE_ABS

    @classmethod
    def from_project(cls, config: dict[str, Any]) -> ProductScoringConfig:
        """Build from the audit's FROZEN catalog dict (never live config).

        Reads the ``products`` / ``competitor_products`` keys the planner
        froze via ``project_product_identity`` plus the ``owned_domains``
        key frozen via ``project_scoring_identity`` (mirrors
        ``ScoringConfig.from_project``).
        """
        products = []
        for item in config.get("products") or []:
            variants = [v for v in (item.get("variants") or []) if isinstance(v, dict)]
            attributes = dict(item.get("attributes") or {})
            products.append(
                ProductEntry(
                    id=str(item.get("id") or ""),
                    sku=str(item.get("sku") or ""),
                    name=str(item.get("name") or ""),
                    aliases=_match_aliases(
                        item.get("name"),
                        item.get("sku"),
                        item.get("aliases") or [],
                        [v.get("name") for v in variants],
                        [v.get("sku") for v in variants],
                    ),
                    price=_as_price(item.get("price")),
                    currency=str(item.get("currency") or "").strip().upper(),
                    attributes=attributes,
                    category=str(attributes.get("category") or "").strip().casefold(),
                )
            )
        competitor_products = []
        for item in config.get("competitor_products") or []:
            competitor_products.append(
                CompetitorProductEntry(
                    id=str(item.get("id") or ""),
                    competitor=str(item.get("competitor_name") or ""),
                    name=str(item.get("name") or ""),
                    aliases=_match_aliases(item.get("name"), item.get("aliases") or []),
                    price=_as_price(item.get("price")),
                    currency=str(item.get("currency") or "").strip().upper(),
                )
            )
        return cls(
            products=tuple(products),
            competitor_products=tuple(competitor_products),
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
    entry: ProductEntry | CompetitorProductEntry,
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
    entry: ProductEntry | CompetitorProductEntry,
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


def _rank_in_block(
    block: list[tuple[int, str]], match_offset: int, family: str
) -> int | None:
    """1-based ordinal of the block item whose span contains the offset."""
    if family == "table":
        # Skip separator rows, and the header row ONLY when a separator marks
        # one. A headerless or single-row pipe table has no header to drop —
        # stripping its first row unconditionally would leave nothing to rank
        # and report a genuine mention as unranked.
        has_header = any(_is_table_separator(line) for _, line in block)
        data_rows = [row for row in block if not _is_table_separator(row[1])]
        if has_header:
            data_rows = data_rows[1:]
        for ordinal, (start, line) in enumerate(data_rows, start=1):
            end = start + len(line)
            if start <= match_offset < end:
                return ordinal
        return None

    ordinal = 0
    item_start: int | None = None
    for index, (start, line) in enumerate(block):
        is_marker = (
            _NUMBERED_RE.match(line) if family == "numbered" else _BULLET_RE.match(line)
        )
        if is_marker:
            ordinal += 1
            item_start = start
        # An item's span runs to the next marker (or the block end).
        next_start = block[index + 1][0] if index + 1 < len(block) else None
        if item_start is not None and match_offset >= item_start:
            if next_start is None or match_offset < next_start:
                return ordinal
    return None


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

    # Group lines into contiguous same-family blocks. A numbered block
    # restarts when the explicit number does not increase (a new list).
    blocks: list[tuple[str, list[tuple[int, str]]]] = []
    current_family = ""
    current: list[tuple[int, str]] = []
    last_number = 0
    for start, line in lines:
        numbered = _NUMBERED_RE.match(line)
        family = ""
        if _TABLE_ROW_RE.match(line):
            family = "table"
        elif numbered:
            family = "numbered"
            if current_family == "numbered" and int(numbered.group(1)) <= last_number:
                family = "numbered_restart"
            last_number = int(numbered.group(1))
        elif _BULLET_RE.match(line):
            family = "bullet"
        elif line.strip() and current and current_family in {"numbered", "bullet"}:
            # Continuation line of the current list item.
            family = current_family

        if family == "numbered_restart" or (family != current_family and current):
            blocks.append((current_family, current))
            current = []
            current_family = ""
        if family:
            current_family = "numbered" if family == "numbered_restart" else family
            current.append((start, line))
    if current:
        blocks.append((current_family, current))

    for family, block in blocks:
        block_start = block[0][0]
        block_end = block[-1][0] + len(block[-1][1])
        if block_start <= match_offset < block_end:
            return _rank_in_block(block, match_offset, family)
    return None


# --------------------------------------------------------------------------
# Per-execution scoring + run aggregation
# --------------------------------------------------------------------------
def _entry_signals(
    *,
    entry: ProductEntry | CompetitorProductEntry,
    answer_text: str,
    normalized_answer: str,
    config: ProductScoringConfig,
) -> dict[str, Any]:
    first_offset = _first_offset(entry.aliases, normalized_answer)
    mentioned = first_offset is not None
    signals: dict[str, Any] = {
        "mentioned": mentioned,
        "first_offset": first_offset,
        "rank_position": None,
        "price_text": "",
        "price_value": None,
        "price_currency": "",
        "price_matches_catalog": None,
        "price_relation": None,
        "attribute_mentions": [],
        "merchant_mentions": [],
    }
    if not mentioned:
        return signals
    original_offset = _original_text_offset(entry.aliases, answer_text)
    if original_offset is None:
        return signals
    signals["rank_position"] = detect_product_rank(answer_text, original_offset)
    prices = extract_price_mentions(answer_text, original_offset)
    if prices:
        first = prices[0]
        signals["price_text"] = first["text"][:64]
        signals["price_value"] = first["value"]
        signals["price_currency"] = first["currency"]
        signals["price_matches_catalog"] = price_matches_catalog(
            first["value"],
            first["currency"],
            entry,
            tolerance_pct=config.price_tolerance_pct,
            tolerance_abs=config.price_tolerance_abs,
        )
        signals["price_relation"] = price_relation(
            first["value"],
            first["currency"],
            entry,
            tolerance_pct=config.price_tolerance_pct,
            tolerance_abs=config.price_tolerance_abs,
        )
    # Attribute dimensions: DEFAULT always, plus the frozen category's tuple
    # (unknown/empty category -> DEFAULT only). Competitor entries carry no
    # attribute bag, so they evaluate DEFAULT dimensions too.
    dimensions = ATTRIBUTE_DIMENSIONS["DEFAULT"] + ATTRIBUTE_DIMENSIONS.get(
        entry.category, ()
    )
    signals["attribute_mentions"] = extract_attribute_mentions(
        answer_text, original_offset, dimensions
    )
    merchant_mentions: list[dict[str, Any]] = []
    for destination in extract_destination_urls(answer_text, original_offset):
        classification = classify_destination(
            destination["url"], owned_domains=config.owned_domains
        )
        merchant_mentions.append(
            {
                **classification,
                "destination_url": destination["url"],
                # Reuse the first same-line price extraction as optional
                # merchant price evidence.
                "price_text": signals["price_text"],
                "price_value": signals["price_value"],
                "price_currency": signals["price_currency"],
            }
        )
    signals["merchant_mentions"] = merchant_mentions
    return signals


def score_product_execution(
    *, answer_text: str, config: ProductScoringConfig
) -> dict[str, Any]:
    """Per-execution deterministic product score.

    For every catalog entry (own + competitor): mention flag + first offset
    (normalized coordinates, mirroring the brand scorer), rank-in-list, the
    first windowed price mention, and catalog-price accuracy; plus headline
    counts. Applies the WHOLE frozen catalog to every response (mirrors
    ``_competitor_signals`` applying the full competitor registry).
    """
    normalized_answer = normalize_alias(answer_text)
    products = [
        {
            "product_id": entry.id,
            **_entry_signals(
                entry=entry,
                answer_text=answer_text,
                normalized_answer=normalized_answer,
                config=config,
            ),
        }
        for entry in config.products
    ]
    competitor_products = [
        {
            "competitor_product_id": entry.id,
            **_entry_signals(
                entry=entry,
                answer_text=answer_text,
                normalized_answer=normalized_answer,
                config=config,
            ),
        }
        for entry in config.competitor_products
    ]
    all_signals = products + competitor_products
    return {
        "products": products,
        "competitor_products": competitor_products,
        "own_product_mention_count": sum(1 for p in products if p["mentioned"]),
        "competitor_product_mention_count": sum(
            1 for p in competitor_products if p["mentioned"]
        ),
        # Entries (own + competitor) whose extracted price matched the catalog.
        "products_with_price_match": sum(
            1 for p in all_signals if p["price_matches_catalog"] is True
        ),
        # Deterministic co-placement input: mentioned entry ids in catalog
        # order (own ids first, then competitor ids).
        "mentioned_entry_ids": [
            *[p["product_id"] for p in products if p["mentioned"]],
            *[
                c["competitor_product_id"]
                for c in competitor_products
                if c["mentioned"]
            ],
        ],
    }


def _rank_bucket(rank: int) -> str:
    for label, minimum, maximum in PRODUCT_RANK_BUCKETS:
        if rank >= minimum and (maximum is None or rank <= maximum):
            return label
    return PRODUCT_RANK_BUCKET_UNRANKED


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _mentioned_id_sets(scores: list[dict[str, Any]]) -> list[set[str]]:
    """Per-execution mentioned entry-id sets (co-placement input).

    v2 score dicts carry ``mentioned_entry_ids``; legacy v1 dicts fall back
    to the mentioned flags in their own/competitor sections (mixed-version
    aggregation).
    """
    id_sets: list[set[str]] = []
    for score in scores:
        ids = score.get("mentioned_entry_ids")
        if ids is None:
            ids = [
                str(signals.get("product_id") or "")
                for signals in score.get("products") or []
                if signals.get("mentioned")
            ] + [
                str(signals.get("competitor_product_id") or "")
                for signals in score.get("competitor_products") or []
                if signals.get("mentioned")
            ]
        id_sets.append({str(value) for value in ids})
    return id_sets


def _price_relation_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Relation tallies over one entry's persisted mention rows.

    v2 rows count their persisted ``price_relation`` string. Legacy rows
    (relation absent/null) fall back to the ``price_matches_catalog``
    boolean: True -> ``match``, False -> ``mismatch`` (no direction is ever
    inferred for v1 data). Unverifiable rows (both null) are not counted.
    """
    counts = {
        PRICE_RELATION_MATCH: 0,
        PRICE_RELATION_HIGHER: 0,
        PRICE_RELATION_LOWER: 0,
        PRICE_RELATION_MISMATCH: 0,
    }
    for row in rows:
        relation = row.get("price_relation")
        if relation is None:
            legacy = row.get("price_matches_catalog")
            if legacy is True:
                relation = PRICE_RELATION_MATCH
            elif legacy is False:
                relation = PRICE_RELATION_MISMATCH
        if relation in counts:
            counts[relation] += 1
    return counts


def _attribute_dimension_frequency(
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """``{group: {dimension: count}}`` over persisted attribute mentions.

    Both key levels are sorted so serialization is stable; an entry with no
    observations gets ``{}``.
    """
    frequency: dict[str, dict[str, int]] = {}
    for row in rows:
        for item in row.get("attribute_mentions") or []:
            group = str(item.get("group") or "")
            dimension = str(item.get("dimension") or "")
            if not group or not dimension:
                continue
            group_counts = frequency.setdefault(group, {})
            group_counts[dimension] = group_counts.get(dimension, 0) + 1
    return {
        group: {
            dimension: group_counts[dimension] for dimension in sorted(group_counts)
        }
        for group, group_counts in sorted(frequency.items())
    }


def _buyer_destination_mix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """``{"total", "by_kind", "by_domain"}`` over persisted destinations.

    ``total`` counts every destination observation; ``by_kind`` sorts by
    (-count, merchant_kind) and ``by_domain`` by (-count, merchant_domain,
    merchant_name, merchant_kind).
    """
    total = 0
    kind_counts: dict[str, int] = {}
    domain_counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        for item in row.get("merchant_mentions") or []:
            total += 1
            kind = str(item.get("merchant_kind") or "")
            domain = str(item.get("merchant_domain") or "")
            name = str(item.get("merchant_name") or "")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
            key = (domain, name, kind)
            domain_counts[key] = domain_counts.get(key, 0) + 1
    return {
        "total": total,
        "by_kind": [
            {"merchant_kind": kind, "count": count}
            for kind, count in sorted(
                kind_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
        ],
        "by_domain": [
            {
                "merchant_domain": domain,
                "merchant_name": name,
                "merchant_kind": kind,
                "count": count,
            }
            for (domain, name, kind), count in sorted(
                domain_counts.items(),
                key=lambda kv: (-kv[1], kv[0][0], kv[0][1], kv[0][2]),
            )
        ],
    }


def _competitor_co_placement(
    entry_id: str,
    mentioned_sets: list[set[str]],
    competitor_identity: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    """Competitor products co-mentioned with ``entry_id`` (self excluded).

    Sorted by (-count, casefolded competitor name, casefolded product name,
    str(competitor_product_id or "")); capped at ``CO_PLACEMENT_MAX_PAIRS``
    with ``truncated`` recording whether pairs were omitted (always
    present, including false).
    """
    pair_counts: dict[str, int] = {}
    for id_set in mentioned_sets:
        if entry_id not in id_set:
            continue
        for other_id in id_set:
            if other_id == entry_id or other_id not in competitor_identity:
                continue
            pair_counts[other_id] = pair_counts.get(other_id, 0) + 1
    items: list[dict[str, Any]] = []
    for other_id, count in pair_counts.items():
        competitor_name, product_name = competitor_identity[other_id]
        try:
            competitor_product_id: str | None = str(uuid.UUID(other_id))
        except ValueError:
            competitor_product_id = None
        items.append(
            {
                "competitor_product_id": competitor_product_id,
                "competitor_name": competitor_name,
                "product_name": product_name,
                "count": count,
            }
        )
    items.sort(
        key=lambda item: (
            -item["count"],
            item["competitor_name"].casefold(),
            item["product_name"].casefold(),
            item["competitor_product_id"] or "",
        )
    )
    return {
        "items": items[:CO_PLACEMENT_MAX_PAIRS],
        "truncated": len(items) > CO_PLACEMENT_MAX_PAIRS,
    }


def _product_entries(config: ProductScoringConfig) -> list[tuple[str, str]]:
    """Return every configured entry with the score section that owns it."""
    return [(entry.id, "products") for entry in config.products] + [
        (entry.id, "competitor_products") for entry in config.competitor_products
    ]


def _product_mentions(
    scores: list[dict[str, Any]], entries: list[tuple[str, str]]
) -> dict[str, list[dict[str, Any]]]:
    """Collect only positive mention signals for each configured entry."""
    id_key = {
        "products": "product_id",
        "competitor_products": "competitor_product_id",
    }
    mentions: dict[str, list[dict[str, Any]]] = {
        entry_id: [] for entry_id, _ in entries
    }
    for score in scores:
        for section, key in id_key.items():
            for signals in score.get(section) or []:
                entry_id = str(signals.get(key) or "")
                if entry_id in mentions and signals.get("mentioned"):
                    mentions[entry_id].append(signals)
    return mentions


def _rank_metrics(rows: list[dict[str, Any]]) -> tuple[list[Any], dict[str, int]]:
    """Compute rank values and the complete deterministic bucket distribution."""
    ranks = [
        row["rank_position"] for row in rows if row.get("rank_position") is not None
    ]
    distribution = {label: 0 for label, _, _ in PRODUCT_RANK_BUCKETS}
    for rank in ranks:
        distribution[_rank_bucket(rank)] += 1
    distribution[PRODUCT_RANK_BUCKET_UNRANKED] = len(rows) - len(ranks)
    return ranks, distribution


def _price_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute price-verification counts and accuracy/mismatch rates."""
    price_mentions = [row for row in rows if row.get("price_value") is not None]
    verifiable = [
        row for row in price_mentions if row.get("price_matches_catalog") is not None
    ]
    matches = [row for row in verifiable if row["price_matches_catalog"] is True]
    relation_counts = _price_relation_counts(rows)
    verifiable_relations = sum(relation_counts.values())
    mismatches = sum(
        relation_counts[relation]
        for relation in (
            PRICE_RELATION_HIGHER,
            PRICE_RELATION_LOWER,
            PRICE_RELATION_MISMATCH,
        )
    )
    return {
        "price_mention_count": len(price_mentions),
        "price_match_count": len(matches),
        "price_accuracy_rate": (
            _rate(len(matches), len(verifiable)) if verifiable else None
        ),
        "price_relation_counts": relation_counts,
        "price_mismatch_rate": (
            round(mismatches / verifiable_relations, 4)
            if verifiable_relations
            else None
        ),
    }


def _win_rate(rows: list[dict[str, Any]]) -> float | None:
    """Compute the configured rank-one win rate without treating omissions as losses."""
    denominator_rows = (
        [row for row in rows if row.get("rank_position") is not None]
        if PRODUCT_WIN_REQUIRES_ENUMERATION
        else rows
    )
    wins = sum(1 for row in denominator_rows if row.get("rank_position") == 1)
    return round(wins / len(denominator_rows), 4) if denominator_rows else None


def _product_aggregate(
    *,
    entry_id: str,
    section: str,
    rows: list[dict[str, Any]],
    total_mentions: int,
    mentioned_sets: list[set[str]],
    competitor_identity: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    """Build one catalog entry's aggregate while preserving every null distinction."""
    ranks, distribution = _rank_metrics(rows)
    aggregate = {
        "kind": "product" if section == "products" else "competitor_product",
        "mention_count": len(rows),
        "sov_share": _rate(len(rows), total_mentions),
        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "rank_distribution": distribution,
        "win_rate": _win_rate(rows),
        "attribute_dimension_frequency": _attribute_dimension_frequency(rows),
        "buyer_destination_mix": _buyer_destination_mix(rows),
        "competitor_co_placement": _competitor_co_placement(
            entry_id, mentioned_sets, competitor_identity
        ),
    }
    aggregate.update(_price_metrics(rows))
    return aggregate


def aggregate_product_run(
    scores: list[dict[str, Any]], config: ProductScoringConfig
) -> dict[str, dict[str, Any]]:
    """Aggregate per-execution product scores into per-entry metrics.

    Pure function of the PERSISTED score dicts (invariant 7). Returns
    ``{entry_id: aggregate}`` for every catalog entry (zero-filled when
    unmentioned). SOV share = the entry's mention count over the total
    product + competitor-product mention volume (mirrors the brand SOV).
    Per-engine breakdowns are computed by the caller grouping executions by
    engine and re-calling this (mirrors ``aggregate_run``).
    """
    entries = _product_entries(config)
    mentions = _product_mentions(scores, entries)
    total_mentions = sum(len(rows) for rows in mentions.values())
    mentioned_sets = _mentioned_id_sets(scores)
    competitor_identity = {
        entry.id: (entry.competitor, entry.name) for entry in config.competitor_products
    }
    return {
        entry_id: _product_aggregate(
            entry_id=entry_id,
            section=section,
            rows=mentions[entry_id],
            total_mentions=total_mentions,
            mentioned_sets=mentioned_sets,
            competitor_identity=competitor_identity,
        )
        for entry_id, section in entries
    }
