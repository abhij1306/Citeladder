"""Run-level aggregation for deterministic product scoring."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, cast

from app.analysis.normalization import normalize_alias
from app.analysis.product_scoring import (
    CompetitorProductEntry,
    ProductEntry,
    ProductScoringConfig,
    _first_offset,
    _original_text_offset,
    classify_destination,
    detect_product_rank,
    extract_attribute_mentions,
    extract_destination_urls,
    extract_price_mentions,
    price_matches_catalog,
    price_relation,
)
from app.core.config.commerce import (
    ATTRIBUTE_DIMENSIONS,
    CO_PLACEMENT_MAX_PAIRS,
    PRICE_RELATION_HIGHER,
    PRICE_RELATION_LOWER,
    PRICE_RELATION_MATCH,
    PRICE_RELATION_MISMATCH,
    PRODUCT_WIN_REQUIRES_ENUMERATION,
)
from app.core.config.products import (
    PRODUCT_RANK_BUCKET_UNRANKED,
    PRODUCT_RANK_BUCKETS,
)


# Per-execution scoring + run aggregation
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


def _scored_entries(
    *,
    entries: Sequence[ProductEntry | CompetitorProductEntry],
    id_key: str,
    answer_text: str,
    normalized_answer: str,
    config: ProductScoringConfig,
) -> list[dict[str, Any]]:
    return [
        {
            id_key: entry.id,
            **_entry_signals(
                entry=entry,
                answer_text=answer_text,
                normalized_answer=normalized_answer,
                config=config,
            ),
        }
        for entry in entries
    ]


def _execution_summary(
    products: list[dict[str, Any]], competitor_products: list[dict[str, Any]]
) -> dict[str, Any]:
    all_signals = products + competitor_products
    return {
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


def score_product_execution(
    *, answer_text: str, config: ProductScoringConfig
) -> dict[str, Any]:
    """Per-execution deterministic product score for the frozen catalog."""
    normalized_answer = normalize_alias(answer_text)
    products = _scored_entries(
        entries=config.products,
        id_key="product_id",
        answer_text=answer_text,
        normalized_answer=normalized_answer,
        config=config,
    )
    competitor_products = _scored_entries(
        entries=config.competitor_products,
        id_key="competitor_product_id",
        answer_text=answer_text,
        normalized_answer=normalized_answer,
        config=config,
    )
    return {
        "products": products,
        "competitor_products": competitor_products,
        **_execution_summary(products, competitor_products),
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


def _rank_metrics(rows: list[dict[str, Any]]) -> tuple[list[int], dict[str, int]]:
    """Compute rank values and the complete deterministic bucket distribution."""
    ranks: list[int] = [
        cast(int, row["rank_position"])
        for row in rows
        if row.get("rank_position") is not None
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
