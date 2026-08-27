"""Product/Offer completeness and visible-schema parity checks."""

from __future__ import annotations

import re

from app.analysis.site_health.schema_rules import matches_by_tokens
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_page_profiles import (
    PRODUCT_AVAILABILITY_VISIBLE_TERMS,
    PRODUCT_NEGATIVE_AVAILABILITY_KEYS,
    PRODUCT_PARITY_FIELDS,
    PRODUCT_PARITY_NORMALIZATION_PATTERN,
    PRODUCT_PARITY_SCHEMA_FACT_KEYS,
    PRODUCT_SCHEMA_URI_SEPARATOR,
)


def _pass_fail(condition: bool) -> str:
    return RULE_OUTCOME_PASS if condition else RULE_OUTCOME_FAIL


def _product_block(facts: dict) -> dict | None:
    """The bounded Product fact, only when Product markup is actually present."""
    product = (facts.get("structured_data") or {}).get("product") or {}
    return product if int(product.get("schema_product_count", 0) or 0) else None


def check_product_offer_details(facts: dict) -> tuple[str, dict]:
    """Validate Product/Offer completeness without inferring optional claims."""
    product = _product_block(facts)
    if product is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_product_schema"}
    offer_declared = _product_offer_declared(facts)
    missing = _missing_product_offer_fields(product, offer_declared=offer_declared)
    return _pass_fail(not missing), _product_offer_evidence(
        product, offer_declared=offer_declared, missing=missing
    )


def _product_offer_declared(facts: dict) -> bool:
    blocks = (facts.get("structured_data") or {}).get("blocks") or []
    return any(
        block.get("type") == "Product"
        and "offers" in (block.get("props_present") or [])
        for block in blocks
    )


def _missing_product_offer_fields(product: dict, *, offer_declared: bool) -> list[str]:
    missing: list[str] = []
    if not (product.get("sku") or product.get("gtin") or product.get("mpn")):
        missing.append("identifier")
    if not product.get("brand"):
        missing.append("brand")
    if offer_declared:
        for field, key in (
            ("price", "price"),
            ("priceCurrency", "price_currency"),
            ("availability", "availability"),
        ):
            if not product.get(key):
                missing.append(f"offers.{field}")
    return missing


def _product_offer_evidence(
    product: dict, *, offer_declared: bool, missing: list[str]
) -> dict:
    return {
        "schema_product_count": product["schema_product_count"],
        "offer_declared": offer_declared,
        "missing": missing,
        "sku": product.get("sku") or [],
        "gtin": product.get("gtin") or [],
        "brand": product.get("brand") or [],
        "price": product.get("price") or [],
        "price_currency": product.get("price_currency") or [],
        "availability": product.get("availability") or [],
        "variants": product.get("variants") or [],
        "ratings": product.get("ratings") or [],
        "shipping": bool(product.get("shipping")),
        "returns": bool(product.get("returns")),
    }


def _parity_text(facts: dict) -> str:
    headings = facts.get("headings") or {}
    return " ".join(
        [str(facts.get("title") or "")]
        + [str(value) for value in (headings.get("h1_texts") or [])]
        + [str((facts.get("body") or {}).get("text") or "")]
    ).lower()


def _parity_field_check(
    parity_field: str, values: list, facts: dict, visible: str
) -> dict[str, object] | None:
    """Check whether the page shows any declared value for one field."""
    matched: list[str] = []
    unmatched: list[str] = []
    for value in values:
        result = _parity_match(parity_field, str(value), facts, visible)
        if result is None:
            continue
        (matched if result else unmatched).append(str(value)[:256])
    if not matched and not unmatched:
        return None
    return {
        "field": parity_field,
        "schema_value": (matched or unmatched)[0],
        "declared_count": len(matched) + len(unmatched),
        "visible_match": bool(matched),
    }


def _parity_match(
    parity_field: str, value: str, facts: dict, visible: str
) -> bool | None:
    normalized = re.sub(PRODUCT_PARITY_NORMALIZATION_PATTERN, "", value.lower())
    if not normalized:
        return None
    if parity_field == "name":
        return matches_by_tokens(value, _visible_name_text(facts))
    if parity_field == "availability":
        return _availability_visible(normalized, visible)
    comparable = re.sub(
        PRODUCT_PARITY_NORMALIZATION_PATTERN,
        "",
        value.rsplit(PRODUCT_SCHEMA_URI_SEPARATOR, 1)[-1].lower(),
    )
    return _normalized_field_visible(normalized, visible) or _normalized_field_visible(
        comparable, visible
    )


def _normalized_field_visible(normalized: str, visible: str) -> bool:
    """Match a complete normalized value across complete visible tokens."""
    target = re.sub(PRODUCT_PARITY_NORMALIZATION_PATTERN, "", normalized.lower())
    if not target:
        return False
    tokens = re.findall(r"[a-z0-9]+", visible.lower())
    for start in range(len(tokens)):
        candidate = ""
        for token in tokens[start:]:
            candidate += token
            if candidate == target:
                return True
            if len(candidate) >= len(target):
                break
    return False


def _visible_name_text(facts: dict) -> str:
    headings = facts.get("headings") or {}
    return " ".join(
        [str(facts.get("title") or "")]
        + [str(value) for value in (headings.get("h1_texts") or [])]
    )


def _availability_visible(normalized: str, visible: str) -> bool:
    """Match a schema availability enum after checking negative states first."""
    key = normalized.rsplit("schemaorg", 1)[-1]
    negative_matches = {
        enum_key: any(
            _normalized_field_visible(term, visible)
            for term in PRODUCT_AVAILABILITY_VISIBLE_TERMS[enum_key]
        )
        for enum_key in PRODUCT_NEGATIVE_AVAILABILITY_KEYS
    }
    if any(negative_matches.values()):
        return any(
            key.endswith(enum_key) and matched
            for enum_key, matched in negative_matches.items()
        )
    for enum_key, terms in PRODUCT_AVAILABILITY_VISIBLE_TERMS.items():
        if key.endswith(enum_key):
            return any(_normalized_field_visible(term, visible) for term in terms)
    return _normalized_field_visible(key, visible)


def check_product_visible_schema_parity(facts: dict) -> tuple[str, dict]:
    """Compare only populated Product claims with persisted visible facts."""
    product = _product_block(facts)
    if product is None:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_product_schema"}
    visible = _parity_text(facts)
    checks: list[dict[str, object]] = []
    for parity_field in PRODUCT_PARITY_FIELDS:
        values = (
            product.get("name") or []
            if parity_field == "name"
            else product.get(PRODUCT_PARITY_SCHEMA_FACT_KEYS[parity_field]) or []
        )
        check = _parity_field_check(parity_field, values, facts, visible)
        if check is not None:
            checks.append(check)
    if not checks:
        return RULE_OUTCOME_NOT_APPLICABLE, {"reason": "no_comparable_product_claims"}
    mismatches = [check for check in checks if not check["visible_match"]]
    return _pass_fail(not mismatches), {
        "checked_claim_count": len(checks),
        "mismatch_count": len(mismatches),
        "checks": checks,
    }
