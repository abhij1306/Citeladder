# A1 attribution projection + ``attribution_snapshot`` executor (WS-B Task 1).
#
# Rebuilds the Commerce attribution snapshot for one (project, window) from
# PERSISTED evidence only — the latest-``resync_seq``
# ``IntegrationMetricRow`` rows of the three GA4 ecommerce datasets
# (``ATTRIBUTION_CONSUMED_DATASETS``) plus the property currency persisted
# on the ecommerce import-artifact payloads (``currency_code``). NO provider
# I/O anywhere (invariant 7) and NO LLM (invariant 9): every number is a
# deterministic fold of persisted rows.
#
# FORMULAS (all folds documented so a reader can reproduce every number):
#   - Latest revision: per metric-row identity ``(property_ref, provider,
#     dataset, date, dimension_key)`` only the highest ``resync_seq`` row
#     folds in (stale revisions are never evidence). The executor's SQL
#     applies the same rule (``metric_row_not_superseded``); the pure
#     projection re-applies it inside so a stale row can never leak in.
#   - Currency partitions: every fold is keyed by the ISO currency persisted
#     on the row's source artifact (``metadata.currencyCode`` of the GA4
#     ``runReport`` response — the ONLY currency source for A1, AC3). Unlike
#     currencies are NEVER converted or summed together (no FX-rate source
#     exists). Rows whose currency is unknown never fold into a measured
#     partition; a window with ONLY unknown-currency rows serves the
#     defensive ``no_data`` partition with null metrics (unreachable in
#     practice: the ecommerce datasets are new, so every ecommerce artifact
#     carries the stamped currency).
#   - totals (per partition, over the source/medium ecommerce rows):
#     ``revenue`` = Σ purchaseRevenue, ``orders`` = Σ transactions,
#     ``sessions`` = Σ sessions; ``average_order_value`` = revenue / orders
#     (NULL when orders = 0), ``conversion_rate`` = orders / sessions (NULL
#     when sessions = 0) — null denominators stay null, never a fabricated
#     rate. Money folds round to 2 decimals and rates to 4 (the
#     ``_RATE_DECIMALS`` convention) so re-runs serialize identically.
#   - by_ai_source (per partition, over the SAME source/medium rows): the
#     session source/medium pair is classified through the deterministic
#     referral classifier (``classify_referral_signals`` with
#     ``utm_source``/``utm_medium`` — the source/medium dims ARE the UTM
#     signals); an unmatched pair lands in ``other`` (the schema-valid
#     bucket — never a guessed source). ALL groups, ``other`` included, are
#     listed (revenue accounting reconciles to the totals), ordered revenue
#     desc then ai_source asc, with the same per-group metric formulas.
#   - by_product (per partition, over the ITEM rows): the primary item
#     report groups by itemId and classifies its session source/medium
#     (``ai_source`` as above, ``source_label`` = "source / medium"); the
#     fallback channel-group report groups by (itemId, channel group) with
#     ``ai_source = None`` and ``source_label`` = the channel-group name
#     (reduced granularity — never guessed into an AI source). ``orders`` =
#     Σ itemsPurchased, ``revenue`` = Σ itemRevenue; itemId resolves to
#     ``Product.sku`` (unresolved → ``product_id = None``), ``name`` = sku.
#   - source_granularity: ``default_channel_group`` (+ reduced_granularity)
#     when fallback item rows are present, else ``session_source_medium``.
#   - State: a partition with any A1 rows is ``available``; a built window
#     with NO A1 rows serves one ``no_data`` method row with null metrics
#     and empty sections (empty method sections, never fabricated rates).
#
# A2 (``order_referrer``) is OUT OF SCOPE in Task 1: the ``a2``, ``delta``,
# and ``unattributed`` sections persist empty and the statistical namespace
# persists ``not_offered`` with empty allocations (never a fabricated
# estimate). ``coverage_rate`` is null (A1 coverage is undefined here).
#
# Idempotent: recomputing from the same persisted rows rewrites the SAME
# snapshot rows in place via ``INSERT ... ON CONFLICT (project_id,
# window_start, window_end, granularity) DO UPDATE`` (the
# ``domain/analytics/ai_referrals_snapshot.py`` precedent). Provenance (invariant 4):
# ``source_metric_row_ids`` = the folded row ids (sorted strings, so
# re-runs serialize identically); analyzer/formula versions stamp the
# config/attribution.py constants. Cooperative cancel is honored at every
# metric-row batch boundary (invariant 9) — the write phase is one
# transaction, so a cancelled run leaves no partial projection behind.
from __future__ import annotations

import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config.analytics import (
    AI_SOURCE_OTHER,
)
from app.core.config.attribution import (
    ATTRIBUTION_DATA_STATE_AVAILABLE,
    ATTRIBUTION_DATA_STATE_NO_DATA,
    ATTRIBUTION_DELTA_STATE_COMPARABLE,
    ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE,
    ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE,
    ATTRIBUTION_METHOD_GA4_PLATFORM,
    ATTRIBUTION_METHOD_ORDER_REFERRER,
    ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC,
    ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL,
    ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
    ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    DIMENSION_KEY_SEPARATOR,
    INTEGRATION_DATASET_TEMPLATES,
)
from app.domain.analytics.classification import classify_referral_signals
from app.domain.traffic.projection import metric_count
from app.models.attribution import AttributionLink
from app.models.commerce import OrderFact
from app.models.integrations import IntegrationMetricRow

# Bounded work per read batch: each batch is one cooperative-cancel boundary
# (the WRITE phase is a single transaction). Module constant (not config) —
# the same precedent as A6's ``_CLASSIFY_BATCH_SIZE``; tests monkeypatch it
# down to 1 to exercise the boundary per row.
_METRIC_ROW_BATCH_SIZE = 1000

# Rounding conventions (the run-level aggregate precedent): money folds to
# 2 decimals, rates to 4 — re-runs serialize identically (invariant 9).
_MONEY_DECIMALS = 2
_RATE_DECIMALS = 4


@dataclass(frozen=True)
class A1Projection:
    """The granularity-independent A1 fold, ready to persist.

    ``metrics`` is the exact persisted + served document (deterministic a1
    sections + the permanently ``not_offered`` statistical namespace);
    ``source_metric_row_ids`` are the folded evidence ids (sorted string
    UUIDs, so re-runs serialize identically).
    """

    metrics: dict[str, Any]
    source_metric_row_ids: list[str]


@dataclass(frozen=True)
class CombinedProjection:
    metrics: dict[str, Any]
    source_metric_row_ids: list[str]
    source_order_fact_ids: list[str]
    source_link_ids: list[str]


# --- Pure helpers --------------------------------------------------------------


def _source_revenue_sort_key(row: Mapping[str, Any]) -> tuple[float, str]:
    """Stable source ordering without inferred heterogeneous-dict indexing."""
    metrics = row.get("metrics")
    revenue = metrics.get("revenue", 0) if isinstance(metrics, Mapping) else 0
    return (-float(revenue or 0), str(row.get("ai_source") or ""))


def _metric_money(metrics: Mapping[str, Any] | None, key: str) -> float:
    """An additive money measure: a missing/non-numeric key counts as 0."""
    value = (metrics or {}).get(key)
    return float(value) if isinstance(value, (int, float)) else 0.0


def _metric_set(
    *,
    currency: str | None,
    revenue: float | None,
    orders: int | None,
    sessions: int | None,
) -> dict[str, Any]:
    """One attributionMetricSet: rates null when their denominator is 0."""
    average_order_value = (
        round(revenue / orders, _MONEY_DECIMALS)
        if revenue is not None and orders
        else None
    )
    conversion_rate = (
        round(orders / sessions, _RATE_DECIMALS)
        if orders is not None and sessions
        else None
    )
    return {
        "currency": currency,
        "revenue": revenue,
        "orders": orders,
        "average_order_value": average_order_value,
        "sessions": sessions,
        "conversion_rate": conversion_rate,
    }


def _null_metric_set(currency: str | None) -> dict[str, Any]:
    """The metric set of an unavailable method row: every value null."""
    return _metric_set(currency=currency, revenue=None, orders=None, sessions=None)


def _dimension_values(row: IntegrationMetricRow) -> list[str] | None:
    """Peel a row's dimension values (date excluded) from its ``dimension_key``.

    The key packs the template's declared dims in order (date trailing);
    the dataset template pins the arity, so a key that does not split into
    exactly the declared count is malformed — dropped, never guessed.
    """
    template = INTEGRATION_DATASET_TEMPLATES.get(row.dataset)
    if template is None:
        return None
    parts = row.dimension_key.split(DIMENSION_KEY_SEPARATOR)
    if len(parts) != len(template.dimensions):
        return None
    return parts[:-1]  # the trailing value is the date dimension


def _classify_source_medium(source: str, medium: str) -> str:
    """The deterministic AI source for a session source/medium pair.

    GA4 session source/medium ARE the UTM signals, classified through the
    ONE deterministic rule table; an unmatched pair is ``other`` — never a
    guessed source (invariant 9).
    """
    match = classify_referral_signals(utm_source=source, utm_medium=medium)
    return match.ai_source if match is not None else AI_SOURCE_OTHER


def _select_latest(
    rows: Sequence[IntegrationMetricRow],
) -> list[IntegrationMetricRow]:
    """Keep the latest ``resync_seq`` row per metric-row identity.

    The identity is ``(property_ref, provider, dataset, date,
    dimension_key)`` (the ``uq_integration_metric_row_identity`` columns);
    a row superseded by a later re-sync is stale evidence and never folds
    in. The result is sorted deterministically so float aggregation is
    order-independent (invariant 9).
    """
    latest: dict[tuple[str, str, str, date, str], IntegrationMetricRow] = {}
    for row in rows:
        identity = (
            row.property_ref,
            row.provider,
            row.dataset,
            row.date,
            row.dimension_key,
        )
        current = latest.get(identity)
        if current is None or row.resync_seq > current.resync_seq:
            latest[identity] = row
    return sorted(latest.values(), key=lambda row: (row.date, str(row.id)))


def _rows_by_currency(
    rows: Sequence[IntegrationMetricRow], currencies: Mapping[uuid.UUID, str]
) -> dict[str | None, list[IntegrationMetricRow]]:
    """Partition the latest rows by their persisted artifact currency."""
    by_currency: dict[str | None, list[IntegrationMetricRow]] = {}
    for row in _select_latest(rows):
        by_currency.setdefault(currencies.get(row.source_artifact_id), []).append(row)
    return by_currency


def _a1_dataset_rows(
    partition: Sequence[IntegrationMetricRow], dataset: str
) -> list[IntegrationMetricRow]:
    """Keep well-formed rows for one A1 dataset within a currency partition."""
    return [
        row
        for row in partition
        if row.dataset == dataset and _dimension_values(row) is not None
    ]


def _a1_totals(rows: Sequence[IntegrationMetricRow], currency: str) -> dict[str, Any]:
    """Compute source/medium A1 totals for one currency."""
    return _metric_set(
        currency=currency,
        revenue=round(
            sum(_metric_money(row.metrics, "purchaseRevenue") for row in rows),
            _MONEY_DECIMALS,
        ),
        orders=sum(metric_count(row.metrics, "transactions") for row in rows),
        sessions=sum(metric_count(row.metrics, "sessions") for row in rows),
    )


def _by_ai_source(
    rows: Sequence[IntegrationMetricRow], currency: str
) -> list[dict[str, Any]]:
    """Aggregate source/medium ecommerce rows by deterministic AI source."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        source, medium = _dimension_values(row) or ("", "")
        ai_source = _classify_source_medium(source, medium)
        group = groups.setdefault(
            ai_source, {"revenue": 0.0, "orders": 0, "sessions": 0}
        )
        group["revenue"] += _metric_money(row.metrics, "purchaseRevenue")
        group["orders"] += metric_count(row.metrics, "transactions")
        group["sessions"] += metric_count(row.metrics, "sessions")
    result = [
        {
            "ai_source": ai_source,
            "currency": currency,
            "metrics": _metric_set(
                currency=currency,
                revenue=round(group["revenue"], _MONEY_DECIMALS),
                orders=group["orders"],
                sessions=group["sessions"],
            ),
        }
        for ai_source, group in groups.items()
    ]
    result.sort(key=_source_revenue_sort_key)
    return result


def _add_product_group(
    groups: dict[tuple[str, str | None], dict[str, Any]],
    *,
    sku: str,
    ai_source: str | None,
    source_label: str,
    row: IntegrationMetricRow,
) -> None:
    """Accumulate one item-report row into its product/source group."""
    group = groups.setdefault(
        (sku, ai_source), {"revenue": 0.0, "orders": 0, "source_labels": set()}
    )
    group["source_labels"].add(source_label)
    group["revenue"] += _metric_money(row.metrics, "itemRevenue")
    group["orders"] += metric_count(row.metrics, "itemsPurchased")


def _by_product(
    primary_rows: Sequence[IntegrationMetricRow],
    fallback_rows: Sequence[IntegrationMetricRow],
    products_by_sku: Mapping[str, uuid.UUID],
    currency: str,
) -> list[dict[str, Any]]:
    """Aggregate primary and reduced-granularity item reports by product."""
    groups: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in primary_rows:
        sku, source, medium = _dimension_values(row) or ("", "", "")
        _add_product_group(
            groups,
            sku=sku,
            ai_source=_classify_source_medium(source, medium),
            source_label=f"{source} / {medium}",
            row=row,
        )
    for row in fallback_rows:
        sku, channel_group = _dimension_values(row) or ("", "")
        _add_product_group(
            groups,
            sku=sku,
            ai_source=None,
            source_label=channel_group,
            row=row,
        )
    result = [
        {
            "product_id": (
                str(product_id) if (product_id := products_by_sku.get(sku)) else None
            ),
            "sku": sku,
            "name": sku,
            "ai_source": ai_source,
            "source_label": "; ".join(sorted(group["source_labels"])),
            "currency": currency,
            "revenue": round(group["revenue"], _MONEY_DECIMALS),
            "orders": group["orders"],
        }
        for (sku, ai_source), group in groups.items()
    ]
    result.sort(
        key=lambda entry: (-entry["revenue"], entry["sku"], entry["ai_source"] or "~")
    )
    return result


def _available_a1_row(
    partition: Sequence[IntegrationMetricRow],
    products_by_sku: Mapping[str, uuid.UUID],
    currency: str,
) -> tuple[dict[str, Any], list[IntegrationMetricRow]]:
    """Build one available A1 method row and return its folded evidence."""
    source_medium_rows = _a1_dataset_rows(
        partition, DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY
    )
    primary_rows = _a1_dataset_rows(partition, DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY)
    fallback_rows = _a1_dataset_rows(partition, DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY)
    reduced = bool(fallback_rows)
    return (
        {
            "method": ATTRIBUTION_METHOD_GA4_PLATFORM,
            "state": ATTRIBUTION_DATA_STATE_AVAILABLE,
            "source_granularity": (
                ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP
                if reduced
                else ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM
            ),
            "reduced_granularity": reduced,
            "currency": currency,
            "coverage_rate": None,
            "totals": _a1_totals(source_medium_rows, currency),
            "by_ai_source": _by_ai_source(source_medium_rows, currency),
            "by_product": _by_product(
                primary_rows, fallback_rows, products_by_sku, currency
            ),
        },
        source_medium_rows + primary_rows + fallback_rows,
    )


def _no_data_a1_row() -> dict[str, Any]:
    """The one defensive A1 row for an evidence-free window."""
    return {
        "method": ATTRIBUTION_METHOD_GA4_PLATFORM,
        "state": ATTRIBUTION_DATA_STATE_NO_DATA,
        "source_granularity": None,
        "reduced_granularity": False,
        "currency": None,
        "coverage_rate": None,
        "totals": _null_metric_set(None),
        "by_ai_source": [],
        "by_product": [],
    }


def build_a1_projection(
    rows: Sequence[IntegrationMetricRow],
    products_by_sku: Mapping[str, uuid.UUID],
    *,
    currency_by_artifact_id: Mapping[uuid.UUID, str] | None = None,
) -> A1Projection:
    """Fold the window's ecommerce metric rows into the A1 metrics document.

    PURE: no DB, no network, no clock — the same inputs always yield
    byte-identical metrics and provenance (invariants 7 + 9).
    ``currency_by_artifact_id`` threads the artifact-payload currency
    (``metadata.currencyCode``) through to each row; a row without a known
    currency lands in the defensive unknown-currency partition.
    """
    by_currency = _rows_by_currency(rows, currency_by_artifact_id or {})
    a1_rows: list[dict[str, Any]] = []
    folded_ids: list[str] = []
    for currency in sorted(code for code in by_currency if code is not None):
        a1_row, folded_rows = _available_a1_row(
            by_currency[currency], products_by_sku, currency
        )
        a1_rows.append(a1_row)
        folded_ids.extend(str(row.id) for row in folded_rows)

    if not a1_rows:
        # A built window with NO A1 evidence (or only unknown-currency
        # rows — the defensive partition): one no_data method row with null
        # metrics and empty sections, never fabricated rates or zeros.
        a1_rows.append(_no_data_a1_row())

    return A1Projection(
        metrics={
            ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC: {
                "a1": a1_rows,
                # A2/delta/unattributed land with the Shopify order facts —
                # empty sections in this scope, never fabricated zeros.
                "a2": [],
                "delta": [],
                "unattributed": [],
            },
            ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL: {
                "state": ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED,
                "sample_size": None,
                "allocations": [],
            },
        },
        source_metric_row_ids=sorted(folded_ids),
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, _RATE_DECIMALS) if denominator else None


def _has_attribution_evidence(order: OrderFact) -> bool:
    keys = order.attribution_keys or {}
    return any(keys.get(key) for key in ("referrer_url", "utm_source", "utm_medium"))


def _accumulate_line_item_revenue(
    product_groups: dict[tuple[str | None, str, str], dict[str, Any]],
    order: OrderFact,
    ai_source: str,
) -> None:
    """Roll one order's line items into ``product_groups`` for ``ai_source``.

    Skips non-mapping or unpriceable items silently — partial data must not
    poison the projection. Validation happens BEFORE the group is touched so a
    bad item cannot leave a phantom ``orders`` entry behind.
    """
    for item in order.line_items or []:
        if not isinstance(item, Mapping):
            continue
        sku = str(item.get("sku") or "")
        product_id = item.get("product_id")
        try:
            price = float(item.get("unit_price") or 0)
            quantity = int(item.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(price):
            continue
        group = product_groups.setdefault(
            (str(product_id) if product_id else None, sku, ai_source),
            {"orders": set(), "revenue": 0.0},
        )
        group["orders"].add(order.id)
        group["revenue"] += price * quantity


def _aggregate_a2_for_currency(
    currency: str,
    currency_orders: Sequence[OrderFact],
    link_by_order: Mapping[uuid.UUID, AttributionLink],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the A2 method row and unattributed summary for one currency."""
    linked = [order for order in currency_orders if order.id in link_by_order]
    unlinked = [order for order in currency_orders if order.id not in link_by_order]
    coverage_rate = _ratio(
        sum(_has_attribution_evidence(order) for order in currency_orders),
        len(currency_orders),
    )
    unattributed = {
        "currency": currency,
        "orders": len(unlinked),
        "order_share": _ratio(len(unlinked), len(currency_orders)),
        "revenue": round(
            sum(float(order.total_amount) for order in unlinked), _MONEY_DECIMALS
        ),
    }
    if not linked:
        return (
            {
                "method": ATTRIBUTION_METHOD_ORDER_REFERRER,
                "state": ATTRIBUTION_DATA_STATE_NO_DATA,
                "source_granularity": None,
                "reduced_granularity": False,
                "currency": currency,
                "coverage_rate": coverage_rate,
                "totals": _null_metric_set(currency),
                "by_ai_source": [],
                "by_product": [],
            },
            unattributed,
        )

    source_groups: dict[str, dict[str, Any]] = {}
    product_groups: dict[tuple[str | None, str, str], dict[str, Any]] = {}
    for order in linked:
        link = link_by_order[order.id]
        ai_source = str((link.evidence_refs or {}).get("ai_source") or AI_SOURCE_OTHER)
        source_group = source_groups.setdefault(
            ai_source, {"orders": 0, "revenue": 0.0}
        )
        source_group["orders"] += 1
        source_group["revenue"] += float(link.revenue_amount)
        _accumulate_line_item_revenue(product_groups, order, ai_source)

    by_ai_source = [
        {
            "ai_source": ai_source,
            "currency": currency,
            "metrics": _metric_set(
                currency=currency,
                revenue=round(group["revenue"], _MONEY_DECIMALS),
                orders=group["orders"],
                sessions=None,
            ),
        }
        for ai_source, group in source_groups.items()
    ]
    by_ai_source.sort(key=_source_revenue_sort_key)
    by_product = [
        {
            "product_id": product_id,
            "sku": sku,
            "name": sku,
            "ai_source": ai_source,
            "source_label": ai_source,
            "currency": currency,
            "revenue": round(group["revenue"], _MONEY_DECIMALS),
            "orders": len(group["orders"]),
        }
        for (product_id, sku, ai_source), group in product_groups.items()
    ]
    by_product.sort(key=lambda row: (-row["revenue"], row["sku"], row["ai_source"]))
    total_revenue = round(
        sum(float(link_by_order[order.id].revenue_amount) for order in linked),
        _MONEY_DECIMALS,
    )
    return (
        {
            "method": ATTRIBUTION_METHOD_ORDER_REFERRER,
            "state": ATTRIBUTION_DATA_STATE_AVAILABLE,
            "source_granularity": None,
            "reduced_granularity": False,
            "currency": currency,
            "coverage_rate": coverage_rate,
            "totals": _metric_set(
                currency=currency,
                revenue=total_revenue,
                orders=len(linked),
                sessions=None,
            ),
            "by_ai_source": by_ai_source,
            "by_product": by_product,
        },
        unattributed,
    )


def _build_delta_rows(
    a1_rows: Sequence[dict[str, Any]],
    a2_rows: Sequence[dict[str, Any]],
    currencies: Sequence[str],
) -> list[dict[str, Any]]:
    """Join available A1/A2 currency partitions without cross-currency math."""
    a1_available = {
        row["currency"]: row
        for row in a1_rows
        if row["state"] == ATTRIBUTION_DATA_STATE_AVAILABLE and row["currency"]
    }
    a2_available = {
        row["currency"]: row
        for row in a2_rows
        if row["state"] == ATTRIBUTION_DATA_STATE_AVAILABLE
    }
    rows: list[dict[str, Any]] = []
    for currency in sorted(set(a1_available) | set(currencies)):
        left = a1_available.get(currency)
        right = a2_available.get(currency)
        if left is None or right is None:
            rows.append(
                {
                    "currency": currency,
                    "state": (
                        ATTRIBUTION_DELTA_STATE_CURRENCY_UNAVAILABLE
                        if a1_available and a2_available
                        else ATTRIBUTION_DELTA_STATE_METHOD_UNAVAILABLE
                    ),
                    "revenue": None,
                    "orders": None,
                    "average_order_value": None,
                    "conversion_rate": None,
                }
            )
            continue
        left_totals, right_totals = left["totals"], right["totals"]
        left_aov = left_totals["average_order_value"]
        right_aov = right_totals["average_order_value"]
        rows.append(
            {
                "currency": currency,
                "state": ATTRIBUTION_DELTA_STATE_COMPARABLE,
                "revenue": round(
                    left_totals["revenue"] - right_totals["revenue"],
                    _MONEY_DECIMALS,
                ),
                "orders": left_totals["orders"] - right_totals["orders"],
                "average_order_value": (
                    round(left_aov - right_aov, _MONEY_DECIMALS)
                    if left_aov is not None and right_aov is not None
                    else None
                ),
                "conversion_rate": None,
            }
        )
    return rows


def build_combined_projection(
    a1: A1Projection,
    orders: Sequence[OrderFact],
    links: Sequence[AttributionLink],
    *,
    window_start: date,
    window_end: date,
) -> CombinedProjection:
    """Add A2, coverage, unattributed, and currency-safe deltas to A1."""
    metrics = {
        ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC: dict(
            a1.metrics[ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC]
        ),
        ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL: dict(
            a1.metrics[ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL]
        ),
    }
    deterministic = metrics[ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC]
    link_by_order = {link.order_fact_id: link for link in links}
    orders_by_currency: dict[str, list[OrderFact]] = {}
    for order in orders:
        if len(order.currency or "") == 3:
            orders_by_currency.setdefault(order.currency, []).append(order)

    currency_rows = [
        _aggregate_a2_for_currency(currency, currency_orders, link_by_order)
        for currency, currency_orders in sorted(orders_by_currency.items())
    ]
    a2_rows = [row for row, _unattributed in currency_rows]
    unattributed_rows = [row for _a2, row in currency_rows]

    deterministic["a2"] = a2_rows
    deterministic["unattributed"] = unattributed_rows
    evidence_order_count = sum(_has_attribution_evidence(order) for order in orders)
    deterministic["coverage"] = {
        "total_latest_orders": len(orders),
        "orders_with_evidence": evidence_order_count,
        "linked_ai_orders": len(link_by_order),
        "unattributed_orders": len(orders) - len(link_by_order),
        "evidence_coverage_rate": _ratio(evidence_order_count, len(orders)),
        "attributed_share": _ratio(len(link_by_order), len(orders)),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    deterministic["delta"] = _build_delta_rows(
        deterministic["a1"], a2_rows, list(orders_by_currency)
    )
    return CombinedProjection(
        metrics=metrics,
        source_metric_row_ids=a1.source_metric_row_ids,
        source_order_fact_ids=sorted(str(order.id) for order in orders),
        source_link_ids=sorted(str(link.id) for link in links),
    )


from app.domain.attribution.snapshot_executor import (  # noqa: E402
    refresh_attribution_snapshot,
)

__all__ = ["refresh_attribution_snapshot"]
