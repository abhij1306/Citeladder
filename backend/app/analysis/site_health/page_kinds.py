# Deterministic page-type classification.
#
# ``classify(final_url, facts)`` assigns every analyzed page a config-owned
# ``page_kind`` with a confidence LABEL and bounded, explainable evidence.
# PURE: no I/O, no ORM, no LLM — the same inputs always yield the same type
# (invariant 9), and every pattern table and vocabulary is read from
# ``app.core.config.site_health_taxonomy`` (invariant 1).
#
# EVIDENCE TIERS, not accumulated weights. The classifier takes the highest
# tier that produced evidence and stops:
#
#   Tier A  structural   the page's own primary entity — one Product node with
#                        an Offer, or a buy box outside every repeated card
#                        list; a listing grid with result/sort/filter controls;
#                        a single address entity
#   Tier B  route        the semantic URL segment nearest the root
#   Tier C  semantic     question headings, a byline + date, the page's own
#                        stated purpose in its title/H1/slug, schema types
#
# A score summed across signals let several weak agreeing signals outrank one
# decisive observation, and it produced a "confidence" of 1.3 on a page it
# classified from a signal worth 0.8 — because the sum included the signals
# that DISAGREED. Tiers make the deciding fact nameable: ``classified_by`` is
# always the one signal that chose the type.
#
# DELIBERATE SEMANTICS: structured data sits in the weakest tier. The markup is
# the page's *claim* about itself; letting the claim decide the type would make
# the type-expected-schema rules circular.
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from app.analysis.site_health.content_heuristics import content_heuristic
from app.core.config import site_health_acquisition as _acquisition
from app.core.config import site_health_contracts as _contracts
from app.core.config import site_health_taxonomy as _config
from app.core.config.site_health_page_profiles import (
    CLASSIFICATION_MAX_ALTERNATIVES,
    CLASSIFICATION_OTHER_REASON_CONFLICT,
    CLASSIFICATION_OTHER_REASON_NO_SIGNALS,
    CLASSIFICATION_OTHER_REASON_SCHEMA_ONLY,
)

# Bounded per-input caps so a hostile URL/body can never bloat the evidence
# or the classification work (same bounding convention as parser.py).
_MAX_PATH_CHARS = _acquisition.SITE_HEALTH_MAX_PATH_CHARS
_MAX_SIGNAL_DETAIL_CHARS = _acquisition.SITE_HEALTH_MAX_SIGNAL_DETAIL_CHARS
# Compiled once from the config tables (deterministic; the tables are frozen
# config, so compilation at import is exact).
_PATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (page_kind, re.compile(pattern))
    for page_kind, pattern in _config.PAGE_KIND_PATH_PATTERNS
)

#: Signal precedence WITHIN a tier. Reaching two signals in one tier is a
#: genuine disagreement, recorded as a conflict; this table decides it.
_TIER_SIGNAL_ORDER: tuple[str, ...] = (
    _config.PAGE_KIND_SIGNAL_PRIMARY_PRODUCT,
    _config.PAGE_KIND_SIGNAL_PRIMARY_LISTING,
    _config.PAGE_KIND_SIGNAL_PRIMARY_LOCATION,
    _config.PAGE_KIND_SIGNAL_ROOT_PATH,
    _config.PAGE_KIND_SIGNAL_PATH_PATTERN,
    _config.PAGE_KIND_SIGNAL_CONTENT_HEURISTIC,
    _config.PAGE_KIND_SIGNAL_SEMANTIC_TITLE,
    _config.PAGE_KIND_SIGNAL_STRUCTURED_DATA,
)


@dataclass(frozen=True)
class PageKindAssessment:
    """The bounded, deterministic result of classifying one page.

    ``page_kind`` is a config ``PAGE_KINDS`` member (falling back to
    ``other``); ``confidence`` is a LABEL (``high``/``medium``/``low``/
    ``unknown``) derived from the deciding tier, never a decimal that invites
    a reader to treat it as a calibrated probability; ``signals`` is the
    bounded matched-signal evidence; ``classified_by`` is the one signal that
    chose the type (``none`` when nothing matched); ``schema_suggested_type``
    is what structured data alone would have suggested, recorded so a
    content-vs-schema disagreement stays explainable.
    """

    page_kind: str
    confidence: str
    tier: str
    signals: tuple[dict[str, Any], ...]
    classifier_version: str
    classified_by: str
    schema_suggested_type: str | None
    alternatives: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, Any], ...]
    other_reason: str | None

    def to_evidence(self) -> dict[str, Any]:
        """Bounded, JSON-safe evidence dict persisted into the facts dict."""
        return {
            "classifier_version": self.classifier_version,
            "classified_by": self.classified_by,
            "schema_suggested_type": self.schema_suggested_type,
            "confidence": self.confidence,
            "tier": self.tier,
            "signals": [dict(signal) for signal in self.signals],
            "alternatives": [dict(item) for item in self.alternatives],
            "conflicts": [dict(item) for item in self.conflicts],
            "other_reason": self.other_reason,
        }


def _normalized_path(final_url: str) -> str:
    """Lowercase path with trailing slashes stripped ("" for the root).

    Bounded and guarded: an unparseable URL yields "" (the root form), which
    is itself a deterministic classification input.
    """
    try:
        path = urlsplit(final_url or "").path or ""
    except ValueError:
        return ""
    path = path[:_MAX_PATH_CHARS].lower()
    while path.endswith("/"):
        path = path[:-1]
    return path


def _is_absolute_http_url(final_url: str) -> bool:
    """Whether a URL is an absolute http(s) URL with a real host.

    Classification reasons about a page's PATH, which only means something
    once we know which document the path belongs to. Anything else contributes
    no signals rather than defaulting to the root.
    """
    try:
        parts = urlsplit(str(final_url or ""))
    # Same guard as ``_normalized_path``: the two call ``urlsplit`` on the same
    # input, so a narrower scope here would let a malformed URL raise out of one
    # while the other quietly returned a value for it.
    except Exception:  # noqa: BLE001
        return False
    # ``hostname``, not ``netloc``: ``http://user@/products`` carries a non-empty
    # netloc with no host at all, and deriving path signals from it would attach
    # findings to a URL that names no document.
    return parts.scheme.lower() in {"http", "https"} and bool(parts.hostname)


def _signal(signal: str, page_kind: str, detail: str) -> dict[str, Any]:
    """One bounded matched-signal record, tagged with its evidence tier."""
    return {
        "signal": signal,
        "page_kind": page_kind,
        # ``.get`` with the weakest tier as default: a signal constant added
        # without a tier should contribute the least, not raise KeyError and
        # fail the whole classification of an otherwise analyzable page.
        "tier": _config.PAGE_KIND_SIGNAL_TIERS.get(
            signal, _config.PAGE_KIND_TIER_SEMANTIC
        ),
        "detail": detail[:_MAX_SIGNAL_DETAIL_CHARS],
    }


def is_question_heading(text: str) -> bool:
    """Question-form heading: ends with "?" or starts with a question word.

    Public since sh-extractor-2: the parser's ``question_heading_ratio`` fact
    and the FAQ content heuristic share this one definition.
    """
    normalized = " ".join(str(text or "").split()).lower()
    if not normalized:
        return False
    if normalized.endswith("?"):
        return True
    first_word = normalized.split(" ", 1)[0].strip("¿?¡!.,:;\"'")
    return first_word in _config.PAGE_KIND_QUESTION_WORDS


def _mapping(value: Any) -> dict[str, Any]:
    """A nested fact as a mapping, or ``{}`` when it is the wrong shape.

    The facts dict normally comes from our own extractor, but it is also read
    back from persisted JSON written by an older extractor version. A field
    that is not a mapping must contribute NO signals rather than raise: the
    classifier's contract is that partial facts simply match fewer signals.
    """
    return value if isinstance(value, dict) else {}


def _str_sequence(value: Any) -> list[str]:
    """A nested fact as a list of strings, or ``[]`` when wrongly shaped.

    A bare string is deliberately NOT treated as a one-item sequence: iterating
    it would yield characters and fabricate signals from nothing.
    """
    if isinstance(value, list | tuple):
        return [str(item) for item in value]
    return []


def _schema_suggestion(facts: dict) -> tuple[str | None, str | None]:
    """(suggested page_kind, matched schema type) or (None, None).

    Uses the explicit config order (most specific to most general), rather
    than alphabetical ordering, when a JSON-LD object declares multiple types.
    """
    structured = _mapping(facts.get("structured_data"))
    types = set(_str_sequence(structured.get("types")))
    for schema_type, page_kind in _config.PAGE_KIND_SCHEMA_TYPE_MAP.items():
        if schema_type in types:
            return page_kind, schema_type
    return None, None


def classify(final_url: str, facts: dict) -> PageKindAssessment:
    """Classify one page into the config taxonomy (pure, deterministic).

    Collects every tier's evidence, then resolves by taking the highest tier
    that produced any. Never raises on malformed facts: partial facts simply
    match fewer signals, and no evidence at all is an explicit ``other``.
    """
    mapped = _mapping(facts)
    matched, schema_page_kind = _classification_signals(final_url, mapped)
    winner = _winning_signal(matched)
    return _assessment(matched, winner, schema_page_kind)


def _assessment(
    matched: list[dict[str, Any]],
    winner: dict[str, Any] | None,
    schema_page_kind: str | None,
) -> PageKindAssessment:
    winner_type = str(winner["page_kind"]) if winner is not None else None
    tier = (
        str(winner["tier"]) if winner is not None else _config.PAGE_KIND_TIER_SEMANTIC
    )
    return PageKindAssessment(
        page_kind=winner_type or _config.PAGE_KIND_OTHER,
        confidence=_confidence(matched, winner, tier),
        tier=tier if winner is not None else "",
        signals=tuple(matched),
        classifier_version=_contracts.CLASSIFIER_VERSION,
        classified_by=(
            str(winner["signal"])
            if winner is not None
            else _config.PAGE_KIND_SIGNAL_NONE
        ),
        schema_suggested_type=schema_page_kind,
        alternatives=_alternatives(matched, winner_type=winner_type),
        conflicts=_conflicts(matched, winner_type=winner_type),
        other_reason=_other_reason(matched, winner),
    )


def _other_reason(
    matched: list[dict[str, Any]], winner: dict[str, Any] | None
) -> str | None:
    if winner is not None:
        return None
    independent = [
        signal
        for signal in matched
        if signal["signal"] != _config.PAGE_KIND_SIGNAL_STRUCTURED_DATA
    ]
    if independent:
        return CLASSIFICATION_OTHER_REASON_CONFLICT
    if matched:
        return CLASSIFICATION_OTHER_REASON_SCHEMA_ONLY
    return CLASSIFICATION_OTHER_REASON_NO_SIGNALS


def _confidence(
    matched: list[dict[str, Any]],
    winner: dict[str, Any] | None,
    tier: str,
) -> str:
    if winner is None:
        return _config.PAGE_KIND_CONFIDENCE_UNKNOWN
    has_conflict = any(signal["page_kind"] != winner["page_kind"] for signal in matched)
    if tier == _config.PAGE_KIND_TIER_STRUCTURAL and has_conflict:
        return _config.PAGE_KIND_CONFIDENCE_MEDIUM
    return _config.PAGE_KIND_TIER_CONFIDENCE[tier]


def _alternatives(
    matched: list[dict[str, Any]], *, winner_type: str | None
) -> tuple[dict[str, Any], ...]:
    """Non-winning candidate types with the tier that proposed them.

    Aggregating by kind makes the runner-up explainable without changing the
    tier-based winner policy.
    """
    candidates: dict[str, dict[str, Any]] = {}
    for signal in matched:
        page_kind = str(signal["page_kind"])
        if page_kind == winner_type:
            continue
        entry = candidates.setdefault(
            page_kind,
            {"page_kind": page_kind, "tier": str(signal["tier"]), "signals": []},
        )
        entry["signals"].append(str(signal["signal"]))
    ordered = sorted(
        candidates.values(),
        key=lambda item: (
            _config.PAGE_KIND_TIERS.index(item["tier"]),
            item["page_kind"],
        ),
    )[:CLASSIFICATION_MAX_ALTERNATIVES]
    return tuple(dict(item) for item in ordered)


def _conflicts(
    matched: list[dict[str, Any]], *, winner_type: str | None
) -> tuple[dict[str, Any], ...]:
    """Record only material disagreements between classification signals."""
    if winner_type is None:
        return ()
    conflicts = [
        {
            "winner_page_kind": winner_type,
            "conflicting_page_kind": str(signal["page_kind"]),
            "signal": str(signal["signal"]),
            "tier": str(signal["tier"]),
            "detail": str(signal["detail"]),
        }
        for signal in matched
        if str(signal["page_kind"]) != winner_type
    ]
    return tuple(conflicts[:CLASSIFICATION_MAX_ALTERNATIVES])


def _winning_signal(matched: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The single signal that decides the type: highest tier, then priority."""
    # Structured data remains evidence and a schema suggestion, but cannot
    # self-certify the page kind whose schema contract will then be validated.
    eligible = [
        signal
        for signal in matched
        if signal["signal"] != _config.PAGE_KIND_SIGNAL_STRUCTURED_DATA
    ]
    if not eligible:
        return None
    best_tier = min(
        _config.PAGE_KIND_TIERS.index(str(signal["tier"])) for signal in eligible
    )
    top_tier = [
        signal
        for signal in eligible
        if _config.PAGE_KIND_TIERS.index(str(signal["tier"])) == best_tier
    ]
    if len({str(signal["page_kind"]) for signal in top_tier}) > 1:
        return None
    return min(
        top_tier,
        key=lambda signal: (
            _config.PAGE_KIND_TIERS.index(str(signal["tier"])),
            _TIER_SIGNAL_ORDER.index(str(signal["signal"])),
        ),
    )


def _classification_signals(
    final_url: str, facts: dict
) -> tuple[list[dict[str, Any]], str | None]:
    matched: list[dict[str, Any]] = []
    # A missing or malformed URL has no path to reason about. Falling through
    # to ``_normalized_path`` yields "" for all of them, which IS a homepage
    # equivalent — so ``classify("", {})`` and ``classify("http://", {})`` both
    # used to report a confident homepage for a page we never located.
    if not _is_absolute_http_url(final_url):
        return matched, None
    path = _normalized_path(final_url)

    # The root path is an exact fact about the URL, not a heuristic: a
    # homepage stays a homepage even when it also renders a product grid.
    if path in _config.HOMEPAGE_PATH_EQUIVALENTS:
        matched.append(
            _signal(
                _config.PAGE_KIND_SIGNAL_ROOT_PATH,
                _config.PAGE_KIND_HOMEPAGE,
                path or "/",
            )
        )
        return matched, _schema_suggestion(facts)[0]

    route_signals = _route_signals(path)
    matched.extend(_structural_signals(facts, route_signals))
    matched.extend(route_signals)
    matched.extend(_semantic_signals(path, facts))
    schema_page_kind, _schema_type = _schema_suggestion(facts)
    return matched, schema_page_kind


def _structural_signals(
    facts: dict, route_signals: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Tier A — what the page's own primary content region contains."""
    entity = _mapping(facts.get("entity"))
    signals: list[dict[str, Any]] = []
    product_detail = _product_evidence(facts, _mapping(entity.get("product")))
    if product_detail:
        signals.append(
            _signal(
                _config.PAGE_KIND_SIGNAL_PRIMARY_PRODUCT,
                _config.PAGE_KIND_PRODUCT,
                product_detail,
            )
        )
    listing_detail = _listing_evidence(_mapping(entity.get("listing")))
    if listing_detail:
        signals.append(
            _signal(
                _config.PAGE_KIND_SIGNAL_PRIMARY_LISTING,
                _config.PAGE_KIND_CATEGORY,
                listing_detail,
            )
        )
    has_local_route = any(
        signal["page_kind"] == _config.PAGE_KIND_LOCAL for signal in route_signals
    )
    location_detail = _location_evidence(
        _mapping(entity.get("location")), has_local_route=has_local_route
    )
    if location_detail:
        signals.append(
            _signal(
                _config.PAGE_KIND_SIGNAL_PRIMARY_LOCATION,
                _config.PAGE_KIND_LOCAL,
                location_detail,
            )
        )
    return signals


def _product_evidence(facts: dict, product: dict) -> str:
    """Decisive product evidence, or "" when the page has not shown any.

    A real buy box in the page's own region needs a corroborator. A product
    without an active purchase control can instead use a primary-region price
    plus an explicit product-detail heading. Both routes stay scoped outside
    every repeated card list, which stops a recommendation carousel on a
    returns-policy page from speaking for that page.
    """
    if not product.get("has_primary_price"):
        return ""
    if not product.get("has_purchase_control"):
        return (
            "primary_price+product_heading"
            if product.get("has_product_detail_heading")
            else ""
        )
    corroborated = (
        product.get("has_variant_control")
        or product.get("has_sku_marker")
        or _og_type(facts) == "product"
        or _single_product_schema(facts)
    )
    return "primary_buy_box" if corroborated else ""


def _single_product_schema(facts: dict) -> bool:
    """Exactly one top-level Product node, carrying offer evidence."""
    structured = _mapping(facts.get("structured_data"))
    blocks = structured.get("blocks")
    if not isinstance(blocks, list):
        return False
    products = [
        block
        for block in blocks
        if isinstance(block, dict) and str(block.get("type") or "") == "Product"
    ]
    if len(products) != 1:
        return False
    has_offer = "Offer" in set(_str_sequence(structured.get("types")))
    return has_offer or bool(_mapping(structured.get("product")).get("price"))


def _listing_evidence(listing: dict) -> str:
    """Decisive listing evidence: a real grid PLUS a listing affordance.

    The grid size alone is not enough — a related-products strip is also a
    grid. Requiring a result count, a sort control or a filter control is what
    separates a page that IS a listing from a page that merely contains one.

    An ``ItemList``/``CollectionPage`` node used to count as a fourth
    affordance, and it was the wrong test: ``structured_data.types`` is the set
    of schema types found ANYWHERE on the page, not the type of the node
    wrapping the grid. Every blog post carrying a related-posts strip and a
    site-wide ``ItemList`` therefore satisfied it, the structural tier won, and
    the route tier's ``article`` verdict was discarded as a conflict — one site
    classified 87 pages ``category`` against 9 ``article``, and a SaaS crawl
    minted a shelf per blog post. A page-wide schema type is exactly the "page's
    own claim about itself" this module places in the WEAKEST tier; it must not
    decide the strongest one. It still reaches ``structured_data``, which is
    where a claim belongs.
    """
    size = listing.get("largest_card_list_size")
    if not isinstance(size, int) or size < _config.LISTING_MIN_CARD_ITEMS:
        return ""
    affordances = [
        name
        for name, present in (
            ("result_count", listing.get("has_result_count")),
            ("sort_control", listing.get("has_sort_control")),
            ("filter_control", listing.get("has_filter_control")),
        )
        if present
    ]
    if not affordances:
        return ""
    return f"grid:{size} {'+'.join(affordances)}"


def _location_evidence(location: dict, *, has_local_route: bool) -> str:
    """One address under a local route; a store finder listing many is not local."""
    if not has_local_route:
        return ""
    count = location.get("address_entity_count")
    if count != 1:
        return ""
    if not (location.get("has_phone") or location.get("has_hours")):
        return ""
    return "single_address_entity"


def _route_signals(path: str) -> list[dict[str, Any]]:
    """Tier B — the semantic URL segment nearest the root.

    Config order is the deterministic tie-breaker when two patterns identify
    the same segment. This preserves ``/blog/products/...`` as article while
    still finding nested families such as ``/resources/guides/...``.
    """
    path_matches: list[tuple[int, int, str, re.Pattern[str]]] = []
    for priority, (page_kind, pattern) in enumerate(_PATH_PATTERNS):
        match = pattern.match(path)
        if match is not None:
            path_matches.append((match.start(1), priority, page_kind, pattern))
    if not path_matches:
        return []
    _position, _priority, page_kind, pattern = min(path_matches)
    return [_signal(_config.PAGE_KIND_SIGNAL_PATH_PATTERN, page_kind, pattern.pattern)]


def _semantic_signals(path: str, facts: dict) -> list[dict[str, Any]]:
    """Tier C — weak evidence, used only when nothing stronger spoke."""
    signals: list[dict[str, Any]] = []
    heuristic = content_heuristic(facts)
    if heuristic is not None:
        signals.append(
            _signal(
                str(heuristic["signal"]),
                str(heuristic["page_kind"]),
                str(heuristic["detail"]),
            )
        )
    title_kind, phrase = _title_suggestion(path, facts)
    if title_kind is not None:
        signals.append(
            _signal(_config.PAGE_KIND_SIGNAL_SEMANTIC_TITLE, title_kind, phrase)
        )
    schema_page_kind, schema_type = _schema_suggestion(facts)
    if schema_page_kind is not None:
        signals.append(
            _signal(
                _config.PAGE_KIND_SIGNAL_STRUCTURED_DATA,
                schema_page_kind,
                schema_type or "",
            )
        )
    return signals


def _title_suggestion(path: str, facts: dict) -> tuple[str | None, str]:
    """The page's own stated purpose, from its title, H1 and final slug.

    Longest phrase wins so ``shipping policy`` is read as a policy rather than
    as a shipping service; config order breaks ties between equal-length
    phrases. This is the weakest signal in the classifier and only ever fires
    where the alternative is ``other``.
    """
    haystack = _semantic_haystack(path, facts)
    if not haystack:
        return None, ""
    best: tuple[int, int, str, str] | None = None
    for index, (page_kind, phrase) in enumerate(_config.PAGE_KIND_TITLE_KEYWORDS):
        if f" {phrase} " not in f" {haystack} ":
            continue
        candidate = (-len(phrase), index, page_kind, phrase)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None, ""
    return best[2], best[3]


def _semantic_haystack(path: str, facts: dict) -> str:
    """Normalized title + H1 + final path segment, lowercased."""
    headings = _mapping(facts.get("headings"))
    parts = [str(facts.get("title") or "")]
    parts.extend(_str_sequence(headings.get("h1_texts"))[:1])
    slug = path.rsplit("/", 1)[-1] if path else ""
    parts.append(slug.replace("-", " ").replace("_", " "))
    joined = " ".join(part for part in parts if part).lower()
    return " ".join(re.findall(r"[a-z0-9]+", joined))


def _og_type(facts: dict) -> str:
    return str(_mapping(facts.get("open_graph")).get("og:type") or "").strip().lower()
