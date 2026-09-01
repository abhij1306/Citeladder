"""Deterministic product and category readiness composites."""

from __future__ import annotations

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_rule_types import CompositeContract


def _count(value: object) -> int:
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 0


def _present(value: object) -> str:
    return RULE_OUTCOME_SATISFIED if bool(value) else RULE_OUTCOME_MISSING


def _product_signals(facts: dict) -> tuple[dict, dict, dict]:
    entity = (facts.get("entity") or {}).get("product") or {}
    schema = (facts.get("structured_data") or {}).get("product") or {}
    commerce = facts.get("commerce") or {}
    return entity, schema, commerce


def _availability(schema: dict, commerce: dict) -> list[str]:
    values = [str(value) for value in schema.get("availability") or () if value]
    visible = str(commerce.get("visible_availability") or "").strip()
    if visible:
        values.append(visible)
    return list(dict.fromkeys(values))


def check_product_answer_facts(
    facts: dict, *, contract: CompositeContract
) -> tuple[str, dict]:
    """Score required PDP facts and a trait-gated variants atom."""
    entity, schema, commerce = _product_signals(facts)
    headings = facts.get("headings") or {}
    identity = bool(headings.get("h1_texts") or schema.get("name"))
    offer = bool(entity.get("has_primary_price") or schema.get("price"))
    availability = _availability(schema, commerce)
    variants = bool(entity.get("has_variant_control") or schema.get("variants"))
    traits = facts.get("page_traits") or ()
    atoms = [
        contract.atom_detail(
            "identity", satisfied=identity, evidence=identity, page_traits=traits
        ),
        contract.atom_detail(
            "offer", satisfied=offer, evidence=offer, page_traits=traits
        ),
        contract.atom_detail(
            "availability",
            satisfied=bool(availability),
            evidence=availability[:8],
            page_traits=traits,
        ),
        contract.atom_detail(
            "variants",
            satisfied=variants,
            evidence=variants,
            page_traits=traits,
        ),
    ]
    return contract.outcome_for(atoms), {
        "atoms": atoms,
        "threshold": contract.threshold,
    }


def check_offer_freshness_signal(facts: dict) -> tuple[str, dict]:
    """Require dated, currency-qualified Offer evidence before claiming current."""
    entity, schema, commerce = _product_signals(facts)
    offer = bool(
        entity.get("has_primary_price")
        or schema.get("price")
        or commerce.get("visible_price")
    )
    currency = [str(value) for value in schema.get("price_currency") or () if value]
    timestamp, timestamp_source = _offer_freshness_timestamp(facts, schema)
    evidence = {
        "offer": offer,
        "currency": list(dict.fromkeys(currency))[:8],
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
    }
    if not offer:
        return RULE_OUTCOME_MISSING, {**evidence, "reason": "offer_state_missing"}
    if not currency:
        return RULE_OUTCOME_MISSING, {
            **evidence,
            "reason": "offer_currency_missing",
        }
    if not timestamp:
        return RULE_OUTCOME_MISSING, {
            **evidence,
            "reason": "freshness_signal_missing",
        }
    return RULE_OUTCOME_SATISFIED, evidence


def check_product_evidence_facts(facts: dict) -> tuple[str, dict]:
    """Require a stable visible or machine-readable product identifier."""
    entity, schema, _commerce = _product_signals(facts)
    identifiers = [
        *(schema.get("sku") or ()),
        *(schema.get("gtin") or ()),
        *(schema.get("mpn") or ()),
    ]
    visible_marker = bool(entity.get("has_sku_marker"))
    return _present(identifiers or visible_marker), {
        "identifiers": [str(value) for value in identifiers[:12]],
        "visible_identifier_marker": visible_marker,
    }


def check_product_brand_identity(facts: dict) -> tuple[str, dict]:
    """Require a product-owned brand or manufacturer identity."""
    _entity, schema, _commerce = _product_signals(facts)
    brands = [str(value) for value in schema.get("brand") or () if value]
    return _present(brands), {"brands": brands[:8]}


def _listing_signals(facts: dict) -> tuple[bool, int]:
    headings = facts.get("headings") or {}
    entity = (facts.get("entity") or {}).get("listing") or {}
    commerce = facts.get("commerce") or {}
    purpose = bool(headings.get("h1_texts"))
    item_count = max(
        _count(entity.get("distinct_card_list_targets")),
        len(commerce.get("product_cards") or ()),
    )
    return purpose, item_count


def check_listing_answer_set(
    facts: dict, *, contract: CompositeContract
) -> tuple[str, dict]:
    """Require both a collection purpose and a crawlable item set."""
    purpose, item_count = _listing_signals(facts)
    traits = facts.get("page_traits") or ()
    atoms = [
        contract.atom_detail(
            "collection_purpose",
            satisfied=purpose,
            evidence=purpose,
            page_traits=traits,
        ),
        contract.atom_detail(
            "item_set",
            satisfied=bool(item_count),
            evidence=item_count,
            page_traits=traits,
        ),
    ]
    return contract.outcome_for(atoms), {
        "atoms": atoms,
        "threshold": contract.threshold,
    }


def check_assortment_freshness_signal(facts: dict) -> tuple[str, dict]:
    """Require a dated assortment observation; item count is not freshness."""
    timestamp, timestamp_source = _freshness_timestamp(facts)
    if not timestamp:
        return RULE_OUTCOME_MISSING, {
            "reason": "freshness_signal_missing",
            "timestamp": "",
            "timestamp_source": "",
        }
    return RULE_OUTCOME_SATISFIED, {
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
    }


def _freshness_timestamp(facts: dict) -> tuple[str, str]:
    dates = facts.get("dates") or {}
    for key in ("modified", "published"):
        timestamp = str(dates.get(key) or "").strip()
        if timestamp:
            return timestamp[:128], key
    return "", ""


def _offer_freshness_timestamp(facts: dict, schema: dict) -> tuple[str, str]:
    validity = next(
        (
            str(value).strip()
            for value in schema.get("price_valid_until") or ()
            if value
        ),
        "",
    )
    if validity:
        return validity[:128], "offer_price_valid_until"
    return _freshness_timestamp(facts)


def check_listing_item_facts(facts: dict) -> tuple[str, dict]:
    """Require crawlable category items with bounded labels and targets."""
    cards = (facts.get("commerce") or {}).get("product_cards") or ()
    complete = list(filter(None, map(_listing_item_fact, cards)))
    listing = (facts.get("entity") or {}).get("listing") or {}
    entity_count = _count(listing.get("distinct_card_list_targets"))
    item_count = max(len(complete), entity_count)
    return _present(item_count), {
        "item_fact_count": item_count,
        "items": complete[:12],
    }


def _listing_item_fact(card: dict) -> dict | None:
    """Normalize one complete crawlable listing card for persisted evidence."""
    title = str(card.get("title") or "")
    url = str(card.get("url") or "")
    if not title.strip() or not url.strip():
        return None
    return {"title": title[:256], "url": url[:512]}
