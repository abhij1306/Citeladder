# Structured-data (JSON-LD / microdata) parse + validation (Task 5; widened in
# v2 P2 / sh-extractor-2).
#
# Pure, deterministic, hardened helpers that turn the raw structured-data blocks
# an HTML page carries into bounded, normalized fact dicts and validate each
# recognized schema.org type against the config-owned maps. No I/O, no ORM.
#
# Recognition (P2): a block is recorded when its ``@type`` is in the config
# ``STRUCTURED_DATA_RECOGNIZED_TYPES`` set — the v1
# ``STRUCTURED_DATA_REQUIRED_PROPERTIES`` types UNION every type named by
# ``PAGE_KIND_EXPECTED_SCHEMA``. The v1 map keeps owning the back-compat
# ``required``/``present``/``missing``/``valid`` fields (types outside it
# validate with ``required=()``, ``valid=True``; the per-type expectation
# rules own required/recommended validation for them, spec §5.2).
#
# Enrichment (P2): each recognized JSON-LD block also carries bounded,
# pre-extracted fields the page-type schema checks read — ``name``, ``author``,
# ``date_published``, ``date_modified``, ``same_as``, and ``props_present``
# (the config ``SCHEMA_PROPERTY_PATHS`` set present on the object, incl.
# dotted one-level paths like ``offers.price``).
#
# Hardening: JSON-LD is parsed with the stdlib ``json`` loader (no XML external
# entity surface); microdata is walked over an already-parsed lxml tree. Any
# malformed block is skipped (never raises) so a hostile page yields partial
# facts, never a crash (subplan Persistence contract).
from __future__ import annotations

import json
from typing import Any

from app.core.config import site_health_acquisition as site_health_config
from app.core.config.site_health_page_profiles import (
    PRODUCT_FACT_MAX_VALUE_CHARS,
    PRODUCT_FACT_MAX_VALUES,
    PRODUCT_NESTED_VALUE_KEYS,
    PRODUCT_RECOGNIZED_SCHEMA_TYPES,
    PRODUCT_SCHEMA_PROPERTY_PATHS,
)
from app.core.config.site_health_rules import (
    STRUCTURED_DATA_RECOGNIZED_TYPES,
    STRUCTURED_DATA_REQUIRED_PROPERTIES,
)
from app.core.config.site_health_taxonomy import (
    SCHEMA_PROPERTY_PATHS,
)

# Absolute ceiling on how deep we descend into a JSON-LD object graph so a
# deeply-nested (or self-referential) payload can never blow the stack.
_MAX_JSONLD_DEPTH = site_health_config.SITE_HEALTH_MAX_JSONLD_DEPTH

# Bounded enrichment fields (compatibility aliases for existing tests).
_MAX_NAME_CHARS = site_health_config.SITE_HEALTH_MAX_NAME_CHARS
_MAX_AUTHOR_CHARS = site_health_config.SITE_HEALTH_MAX_AUTHOR_CHARS
_MAX_DATE_CHARS = site_health_config.SITE_HEALTH_MAX_DATE_CHARS
_MAX_SAME_AS_ENTRIES = site_health_config.SITE_HEALTH_MAX_SAME_AS_ENTRIES
_MAX_SAME_AS_CHARS = site_health_config.SITE_HEALTH_MAX_SAME_AS_CHARS


def _clean_type(value: Any) -> str:
    """Normalize a schema.org ``@type`` token to its bare type name.

    Accepts ``"Article"`` or ``"http://schema.org/Article"`` and returns
    ``""`` for values that are not scalar type tokens.
    """
    if not isinstance(value, str):
        return ""
    token = value.strip()
    if not token:
        return ""
    # Strip a schema.org URL prefix / trailing slash so "schema.org/Article"
    # and "Article" collapse to the same recognized type.
    token = token.rstrip("/")
    if "/" in token:
        token = token.rsplit("/", 1)[-1]
    if "#" in token:
        token = token.rsplit("#", 1)[-1]
    return token


def _clean_types(value: Any) -> tuple[str, ...]:
    """Normalize every unique type declared by one schema object.

    Multi-typed JSON-LD is valid. Keeping only the first token could discard a
    recognized ``Product`` or ``Article`` merely because an unfamiliar type
    appeared before it in the array.
    """
    values = value if isinstance(value, list) else [value]
    cleaned_types: list[str] = []
    for item in values:
        cleaned = _clean_type(item)
        if cleaned and cleaned not in cleaned_types:
            cleaned_types.append(cleaned)
    return tuple(cleaned_types)


def _iter_jsonld_objects(node: Any, depth: int = 0):
    """Yield every dict node in a JSON-LD payload (bounded recursion).

    Descends into ``@graph`` arrays and nested lists/dicts up to
    ``_MAX_JSONLD_DEPTH`` so a nested Organization inside a WebPage is still
    discovered, while a pathological payload can never recurse without bound.
    """
    if depth > _MAX_JSONLD_DEPTH:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _iter_jsonld_objects(value, depth + 1)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                yield from _iter_jsonld_objects(item, depth + 1)


def _present_properties(obj: dict, required: tuple[str, ...]) -> list[str]:
    """Return the required properties actually present + non-empty on ``obj``."""
    present: list[str] = []
    for prop in required:
        if prop in obj and obj[prop] not in (None, "", [], {}):
            present.append(prop)
    return present


def _path_value(obj: Any, path: str) -> Any:
    """Resolve a (possibly dotted, one-level) property path on a JSON-LD object.

    A list at any level collapses to its first dict entry (schema.org
    properties like ``offers`` are commonly single-object or single-item
    lists). Returns ``None`` when any segment is absent.
    """
    current = obj
    for segment in path.split("."):
        if isinstance(current, list):
            current = next((item for item in current if isinstance(item, dict)), None)
        if not isinstance(current, dict):
            return None
        current = current.get(segment)
        if current is None:
            return None
    return current


def _props_present(obj: dict) -> list[str]:
    """Sorted config ``SCHEMA_PROPERTY_PATHS`` present + non-empty on ``obj``."""
    present: list[str] = []
    for path in sorted(SCHEMA_PROPERTY_PATHS | PRODUCT_SCHEMA_PROPERTY_PATHS):
        value = _path_value(obj, path)
        if value is not None and value not in ("", [], {}):
            present.append(path)
    return present


def _first_string(value: Any) -> str:
    """First non-empty plain string in a scalar/dict/list JSON-LD value."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return _first_string(value.get("name"))
    if isinstance(value, list):
        for item in value:
            text = _first_string(item)
            if text:
                return text
    return ""


def _enrichment(obj: dict) -> dict[str, Any]:
    """The bounded P2 enrichment fields for one recognized JSON-LD object."""
    name = _first_string(obj.get("name")) or _first_string(obj.get("headline"))
    author = _first_string(obj.get("author"))
    date_published = _first_string(obj.get("datePublished"))
    date_modified = _first_string(obj.get("dateModified"))
    same_as_raw = obj.get("sameAs")
    if isinstance(same_as_raw, str):
        same_as_raw = [same_as_raw]
    same_as: list[str] = []
    if isinstance(same_as_raw, list):
        for entry in same_as_raw[:_MAX_SAME_AS_ENTRIES]:
            if isinstance(entry, str) and entry.strip():
                same_as.append(entry.strip()[:_MAX_SAME_AS_CHARS])
    return {
        "name": name[:_MAX_NAME_CHARS],
        "author": author[:_MAX_AUTHOR_CHARS],
        "date_published": date_published[:_MAX_DATE_CHARS],
        "date_modified": date_modified[:_MAX_DATE_CHARS],
        "same_as": same_as,
        "props_present": _props_present(obj),
        "description": _first_string(obj.get("description"))[:_MAX_NAME_CHARS],
        "url": _first_string(obj.get("url"))[:_MAX_SAME_AS_CHARS],
        "category": _first_string(obj.get("category"))[:_MAX_NAME_CHARS],
        "product": _product_enrichment(obj),
    }


def _values(value: Any) -> list[str]:
    """Bound a JSON-LD value into stable scalar evidence strings."""
    values: list[str] = []
    if isinstance(value, list):
        for item in value:
            values.extend(_values(item))
    elif isinstance(value, dict):
        for key in PRODUCT_NESTED_VALUE_KEYS:
            text = _first_string(value.get(key))
            if text:
                values.append(text)
    elif value not in (None, ""):
        values.append(str(value).strip())
    unique = dict.fromkeys(v[:PRODUCT_FACT_MAX_VALUE_CHARS] for v in values if v)
    return list(unique)[:PRODUCT_FACT_MAX_VALUES]


def _product_enrichment(obj: dict) -> dict[str, Any]:
    """Extract Product/Offer claims without retaining raw JSON-LD.

    The output is observational: optional fields are empty when absent rather
    than inferred.  This lets downstream rules distinguish a missing claim
    from a visible/schema disagreement.
    """
    offer = _path_value(obj, "offers")
    if isinstance(offer, list):
        offer = next((item for item in offer if isinstance(item, dict)), {})
    if not isinstance(offer, dict):
        offer = {}
    return {
        "sku": _values(obj.get("sku")),
        "gtin": _values(
            [obj.get(key) for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14")]
        ),
        "brand": _values(obj.get("brand")),
        "mpn": _values(obj.get("mpn")),
        "price": _values(offer.get("price") if offer else obj.get("price")),
        "price_currency": _values(
            offer.get("priceCurrency") if offer else obj.get("priceCurrency")
        ),
        "availability": _values(
            offer.get("availability") if offer else obj.get("availability")
        ),
        "variants": _values(obj.get("hasVariant")) + _values(obj.get("isVariantOf")),
        "ratings": _values(obj.get("aggregateRating")) + _values(obj.get("review")),
        "shipping": bool(offer.get("shippingDetails")),
        "returns": bool(offer.get("hasMerchantReturnPolicy")),
    }


def _validate_objects(obj: dict) -> tuple[dict, ...]:
    """Validate every recognized type declared by one JSON-LD object.

    Returns one bounded fact dict per recognized type (``type`` +
    required/present/missing property lists + a ``valid`` flag + enrichment),
    or an empty tuple when the object carries no recognized ``@type``.
    """
    recognized = STRUCTURED_DATA_RECOGNIZED_TYPES | PRODUCT_RECOGNIZED_SCHEMA_TYPES
    facts: list[dict] = []
    for schema_type in _clean_types(obj.get("@type")):
        if schema_type not in recognized:
            continue
        # v1 back-compat: only the v1 map's types carry a required-property
        # contract; newly recognized types validate with an empty contract.
        required = STRUCTURED_DATA_REQUIRED_PROPERTIES.get(schema_type, ())
        present = _present_properties(obj, required)
        missing = [prop for prop in required if prop not in present]
        facts.append(
            {
                "type": schema_type,
                "syntax": "json-ld",
                "required": list(required),
                "present": present,
                "missing": missing,
                "valid": not missing,
                **_enrichment(obj),
            }
        )
    return tuple(facts)


def parse_jsonld_blocks(raw_blocks: list[str], *, max_blocks: int) -> list[dict]:
    """Parse + validate a bounded list of raw JSON-LD script bodies.

    Each element of ``raw_blocks`` is the text of one
    ``<script type="application/ld+json">``. Malformed JSON is skipped. Returns
    one bounded fact dict per recognized schema.org object across all blocks,
    capped at ``max_blocks`` (invariant 9: deterministic + bounded).
    """
    facts: list[dict] = []
    for body in raw_blocks:
        if len(facts) >= max_blocks:
            break
        text = (body or "").strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError, RecursionError):
            # Malformed/pathologically-nested JSON-LD: skip this block, keep
            # the rest (partial facts). A deeply nested block can raise
            # RecursionError inside json.loads() itself, before
            # _iter_jsonld_objects()'s own depth cap ever runs.
            continue
        for obj in _iter_jsonld_objects(parsed):
            if len(facts) >= max_blocks:
                break
            for fact in _validate_objects(obj):
                if len(facts) >= max_blocks:
                    break
                facts.append(fact)
    return facts


def validate_microdata_types(itemtypes: list[str], *, max_blocks: int) -> list[dict]:
    """Turn bounded microdata ``itemtype`` URLs into recognized-type facts.

    Microdata property extraction is intentionally shallow (the AEO rules only
    need "is a recognized schema.org type present"); we record each recognized
    ``itemtype`` as a fact with an empty present/missing breakdown (properties
    are attribute-scattered in microdata and not required for the current
    rule set). Bounded by ``max_blocks``.
    """
    facts: list[dict] = []
    for raw in itemtypes:
        if len(facts) >= max_blocks:
            break
        # A valid `itemtype` attribute may list multiple space-separated
        # schema.org URLs; passing the whole attribute to `_clean_type()`
        # would discard every recognized type in a multi-value attribute.
        for candidate in str(raw or "").split():
            if len(facts) >= max_blocks:
                break
            schema_type = _clean_type(candidate)
            if not schema_type or schema_type not in (
                STRUCTURED_DATA_RECOGNIZED_TYPES | PRODUCT_RECOGNIZED_SCHEMA_TYPES
            ):
                continue
            # v1 back-compat: microdata property extraction stays shallow, so
            # v1-map types record their full required list as missing/invalid;
            # newly recognized types carry an empty contract (valid=True).
            required = STRUCTURED_DATA_REQUIRED_PROPERTIES.get(schema_type, ())
            facts.append(
                {
                    "type": schema_type,
                    "syntax": "microdata",
                    "required": list(required),
                    "present": [],
                    "missing": list(required),
                    "valid": not required,
                    "name": "",
                    "author": "",
                    "date_published": "",
                    "date_modified": "",
                    "same_as": [],
                    "props_present": [],
                    "product": {},
                }
            )
    return facts


def product_facts(blocks: list[dict]) -> dict[str, Any]:
    """Merge the preferred Product observations into one deterministic fact.

    ``schema_product_count`` intentionally counts this same preferred set, not
    every nested variant node visited by JSON-LD traversal. That is the stable
    rule-evidence contract; the helper extraction does not change its meaning.
    """
    product_blocks = _preferred_product_blocks(blocks)
    values = _empty_product_values()
    shipping = False
    returns = False
    for block in product_blocks:
        block_shipping, block_returns = _merge_product_values(values, block)
        shipping = shipping or block_shipping
        returns = returns or block_returns
    return {
        "schema_product_count": len(product_blocks),
        **values,
        "shipping": shipping,
        "returns": returns,
    }


def _preferred_product_blocks(blocks: list[dict]) -> list[dict]:
    all_product_blocks = [block for block in blocks if block.get("type") == "Product"]
    # JSON-LD traversal also sees nested variant Products. Prefer Product
    # nodes with identity/offer evidence; only fall back to all Product nodes
    # when a minimal product schema carries none of those fields.
    return [
        block
        for block in all_product_blocks
        if any(
            (block.get("product") or {}).get(key)
            for key in ("sku", "gtin", "mpn", "brand", "price")
        )
        or "offers" in (block.get("props_present") or [])
    ] or all_product_blocks


def _empty_product_values() -> dict[str, list[str]]:
    return {
        key: []
        for key in (
            "name",
            "sku",
            "gtin",
            "brand",
            "mpn",
            "price",
            "price_currency",
            "availability",
            "variants",
            "ratings",
            "description",
            "url",
            "category",
        )
    }


def _merge_product_values(
    values: dict[str, list[str]], block: dict
) -> tuple[bool, bool]:
    product = {
        "name": [str(block.get("name") or "")],
        "description": [str(block.get("description") or "")],
        "url": [str(block.get("url") or "")],
        "category": [str(block.get("category") or "")],
        **(block.get("product") or {}),
    }
    for key, target in values.items():
        for value in product.get(key) or []:
            if value and value not in target and len(target) < PRODUCT_FACT_MAX_VALUES:
                target.append(str(value)[:PRODUCT_FACT_MAX_VALUE_CHARS])
    return bool(product.get("shipping")), bool(product.get("returns"))
