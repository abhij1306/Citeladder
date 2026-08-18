"""The pure A1 attribution projection (WS-B Task 1).

``build_a1_projection`` is a PURE fold (no DB, no clock): these tests
construct ``IntegrationMetricRow`` instances in memory and pin every
formula — the currency partitions, the totals/by-source/by-product folds,
the null-denominator rules, the classifier mapping (never a guessed AI
source), the reduced-granularity fallback labelling, the latest-revision
rule, and the permanently ``not_offered`` statistical namespace.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.core.config.analytics import (
    AI_SOURCE_CHATGPT,
    AI_SOURCE_OTHER,
    AI_SOURCE_PERPLEXITY,
)
from app.core.config.attribution import (
    ATTRIBUTION_DATA_STATE_AVAILABLE,
    ATTRIBUTION_DATA_STATE_NO_DATA,
    ATTRIBUTION_METHOD_GA4_PLATFORM,
    ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    DIMENSION_KEY_SEPARATOR,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_GA4,
)
from app.domain.attribution.snapshot import (
    build_a1_projection,
    build_combined_projection,
)
from app.models.attribution import AttributionLink
from app.models.commerce import OrderFact
from app.models.integrations import IntegrationMetricRow

_WORKSPACE_ID = uuid.uuid4()
_PROJECT_ID = uuid.uuid4()
_PROPERTY_REF = "123456789"


def _row(
    *,
    dataset: str,
    dimension_values: list[str],
    metrics: dict,
    artifact_id: uuid.UUID,
    row_date: date = date(2026, 7, 20),
    resync_seq: int = 0,
    property_ref: str = _PROPERTY_REF,
) -> IntegrationMetricRow:
    """One in-memory metric row (dimension_key packed per contract C1)."""
    return IntegrationMetricRow(
        id=uuid.uuid4(),
        workspace_id=_WORKSPACE_ID,
        project_id=_PROJECT_ID,
        property_ref=property_ref,
        provider=INTEGRATION_PROVIDER_GA4,
        dataset=dataset,
        date=row_date,
        dimension_key=DIMENSION_KEY_SEPARATOR.join(dimension_values),
        metrics=metrics,
        source_artifact_id=artifact_id,
        resync_seq=resync_seq,
    )


def _ecommerce_sm_row(
    source: str,
    medium: str,
    *,
    transactions: int,
    purchase_revenue: float,
    sessions: int,
    artifact_id: uuid.UUID,
    row_date: date = date(2026, 7, 20),
    resync_seq: int = 0,
    property_ref: str = _PROPERTY_REF,
) -> IntegrationMetricRow:
    return _row(
        dataset=DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        dimension_values=[source, medium, row_date.strftime("%Y%m%d")],
        metrics={
            "transactions": transactions,
            "purchaseRevenue": purchase_revenue,
            "sessions": sessions,
        },
        artifact_id=artifact_id,
        row_date=row_date,
        resync_seq=resync_seq,
        property_ref=property_ref,
    )


def _item_primary_row(
    item_id: str,
    source: str,
    medium: str,
    *,
    item_revenue: float,
    items_purchased: int,
    artifact_id: uuid.UUID,
    row_date: date = date(2026, 7, 20),
    property_ref: str = _PROPERTY_REF,
) -> IntegrationMetricRow:
    return _row(
        dataset=DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
        dimension_values=[item_id, source, medium, row_date.strftime("%Y%m%d")],
        metrics={"itemRevenue": item_revenue, "itemsPurchased": items_purchased},
        artifact_id=artifact_id,
        row_date=row_date,
        property_ref=property_ref,
    )


def _item_fallback_row(
    item_id: str,
    channel_group: str,
    *,
    item_revenue: float,
    items_purchased: int,
    artifact_id: uuid.UUID,
    row_date: date = date(2026, 7, 20),
) -> IntegrationMetricRow:
    return _row(
        dataset=DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
        dimension_values=[item_id, channel_group, row_date.strftime("%Y%m%d")],
        metrics={"itemRevenue": item_revenue, "itemsPurchased": items_purchased},
        artifact_id=artifact_id,
        row_date=row_date,
    )


def _a1(metrics: dict) -> list[dict]:
    return metrics["deterministic"]["a1"]


def test_totals_fold_over_source_medium_rows() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=2,
            purchase_revenue=120.5,
            sessions=10,
            artifact_id=artifact_id,
        ),
        _ecommerce_sm_row(
            "google",
            "organic",
            transactions=5,
            purchase_revenue=300.25,
            sessions=40,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 21),
        ),
    ]
    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    assert a1["method"] == ATTRIBUTION_METHOD_GA4_PLATFORM
    assert a1["state"] == ATTRIBUTION_DATA_STATE_AVAILABLE
    assert (
        a1["source_granularity"] == ATTRIBUTION_SOURCE_GRANULARITY_SESSION_SOURCE_MEDIUM
    )
    assert a1["reduced_granularity"] is False
    assert a1["currency"] == "USD"
    assert a1["coverage_rate"] is None
    assert a1["totals"] == {
        "currency": "USD",
        "revenue": 420.75,
        "orders": 7,
        "average_order_value": 60.11,  # 420.75 / 7, money-rounded to 2
        "sessions": 50,
        "conversion_rate": 0.14,  # 7 / 50, rate-rounded to 4
    }
    # Both rows folded: the provenance carries both ids (sorted strings).
    assert projection.source_metric_row_ids == sorted(str(row.id) for row in rows)


def test_by_ai_source_classifies_and_includes_other() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=2,
            purchase_revenue=120.5,
            sessions=10,
            artifact_id=artifact_id,
        ),
        _ecommerce_sm_row(
            "perplexity.ai",
            "referral",
            transactions=1,
            purchase_revenue=50.0,
            sessions=5,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 21),
        ),
        _ecommerce_sm_row(
            "google",
            "organic",
            transactions=5,
            purchase_revenue=300.25,
            sessions=40,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 22),
        ),
    ]
    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    by_source = {entry["ai_source"]: entry for entry in a1["by_ai_source"]}
    # The source/medium pair classifies through the ONE deterministic rule
    # table; the unmatched google/organic pair lands in ``other`` — and
    # ``other`` is LISTED (revenue accounting reconciles to the totals).
    assert set(by_source) == {AI_SOURCE_CHATGPT, AI_SOURCE_PERPLEXITY, AI_SOURCE_OTHER}
    assert by_source[AI_SOURCE_CHATGPT]["currency"] == "USD"
    assert by_source[AI_SOURCE_CHATGPT]["metrics"]["revenue"] == 120.5
    assert by_source[AI_SOURCE_CHATGPT]["metrics"]["orders"] == 2
    assert by_source[AI_SOURCE_CHATGPT]["metrics"]["sessions"] == 10
    assert by_source[AI_SOURCE_CHATGPT]["metrics"]["average_order_value"] == 60.25
    assert by_source[AI_SOURCE_CHATGPT]["metrics"]["conversion_rate"] == 0.2
    assert by_source[AI_SOURCE_OTHER]["metrics"]["revenue"] == 300.25
    # Ordered revenue desc, then ai_source asc.
    assert [entry["ai_source"] for entry in a1["by_ai_source"]] == [
        AI_SOURCE_OTHER,  # 300.25
        AI_SOURCE_CHATGPT,  # 120.5
        AI_SOURCE_PERPLEXITY,  # 50.0
    ]


def test_null_denominators_stay_null_never_fabricated() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "google",
            "organic",
            transactions=0,
            purchase_revenue=0.0,
            sessions=0,
            artifact_id=artifact_id,
        )
    ]
    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    # orders = 0 -> AOV null; sessions = 0 -> conversion rate null.
    assert a1["totals"]["average_order_value"] is None
    assert a1["totals"]["conversion_rate"] is None
    (other,) = a1["by_ai_source"]
    assert other["metrics"]["average_order_value"] is None
    assert other["metrics"]["conversion_rate"] is None


def test_latest_revision_wins_stale_never_folds() -> None:
    artifact_id = uuid.uuid4()
    stale = _ecommerce_sm_row(
        "chatgpt.com",
        "referral",
        transactions=9,
        purchase_revenue=999.0,
        sessions=90,
        artifact_id=artifact_id,
        resync_seq=0,
    )
    current = _ecommerce_sm_row(
        "chatgpt.com",
        "referral",
        transactions=2,
        purchase_revenue=120.5,
        sessions=10,
        artifact_id=artifact_id,
        resync_seq=1,
    )
    projection = build_a1_projection(
        [stale, current], {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    assert a1["totals"]["revenue"] == 120.5
    assert a1["totals"]["orders"] == 2
    # Only the latest revision's id is provenance.
    assert projection.source_metric_row_ids == [str(current.id)]


def test_by_product_primary_rows_resolve_skus_and_labels() -> None:
    artifact_id = uuid.uuid4()
    product_id = uuid.uuid4()
    rows = [
        _item_primary_row(
            "SKU-1",
            "chatgpt.com",
            "referral",
            item_revenue=80.0,
            items_purchased=1,
            artifact_id=artifact_id,
        ),
        _item_primary_row(
            "SKU-2",
            "google",
            "organic",
            item_revenue=200.25,
            items_purchased=4,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 21),
        ),
        _item_primary_row(
            "SKU-UNKNOWN",
            "chatgpt.com",
            "referral",
            item_revenue=10.0,
            items_purchased=1,
            artifact_id=artifact_id,
        ),
    ]
    projection = build_a1_projection(
        rows,
        {"SKU-1": product_id, "SKU-2": uuid.uuid4()},
        currency_by_artifact_id={artifact_id: "USD"},
    )

    (a1,) = _a1(projection.metrics)
    products = a1["by_product"]
    # Revenue desc: SKU-2 (200.25) > SKU-1 (80.0) > SKU-UNKNOWN (10.0).
    assert [entry["sku"] for entry in products] == ["SKU-2", "SKU-1", "SKU-UNKNOWN"]
    sku2, sku1, unknown = products
    assert sku2["ai_source"] == AI_SOURCE_OTHER
    assert sku2["source_label"] == "google / organic"
    assert sku2["revenue"] == 200.25
    assert sku2["orders"] == 4
    assert sku2["currency"] == "USD"
    assert sku2["product_id"] is not None
    assert sku2["name"] == "SKU-2"  # the sku is the served name (MVP)
    assert sku1["product_id"] == str(product_id)
    assert sku1["ai_source"] == AI_SOURCE_CHATGPT
    assert sku1["source_label"] == "chatgpt.com / referral"
    # An itemId that resolves to no own-catalog sku: product_id null.
    assert unknown["product_id"] is None
    assert unknown["sku"] == unknown["name"] == "SKU-UNKNOWN"
    assert a1["reduced_granularity"] is False


def test_by_product_combines_labels_for_the_same_product_and_ai_source() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _item_primary_row(
            "SKU-1",
            source,
            "referral",
            item_revenue=revenue,
            items_purchased=orders,
            artifact_id=artifact_id,
        )
        for source, revenue, orders in (
            ("chatgpt.com", 80.0, 1),
            ("chat.openai.com", 20.0, 2),
        )
    ]

    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    (product,) = a1["by_product"]
    assert product["ai_source"] == AI_SOURCE_CHATGPT
    assert product["source_label"] == (
        "chat.openai.com / referral; chatgpt.com / referral"
    )
    assert product["revenue"] == 100.0
    assert product["orders"] == 3


def test_fallback_item_rows_label_channel_group_reduced_granularity() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _item_fallback_row(
            "SKU-1",
            "Referral",
            item_revenue=80.0,
            items_purchased=1,
            artifact_id=artifact_id,
        ),
        _item_fallback_row(
            "SKU-2",
            "Organic Search",
            item_revenue=200.25,
            items_purchased=4,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 21),
        ),
    ]
    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    # Reduced granularity is LABELLED, never guessed back into an AI source.
    assert (
        a1["source_granularity"] == ATTRIBUTION_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP
    )
    assert a1["reduced_granularity"] is True
    products = {entry["sku"]: entry for entry in a1["by_product"]}
    assert products["SKU-1"]["ai_source"] is None
    assert products["SKU-1"]["source_label"] == "Referral"
    assert products["SKU-2"]["ai_source"] is None
    assert products["SKU-2"]["source_label"] == "Organic Search"


def test_currency_partitions_never_mix() -> None:
    usd_artifact = uuid.uuid4()
    eur_artifact = uuid.uuid4()
    # Two mapped GA4 properties on one project: one USD, one EUR.
    rows = [
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=2,
            purchase_revenue=120.5,
            sessions=10,
            artifact_id=usd_artifact,
        ),
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=3,
            purchase_revenue=90.0,
            sessions=12,
            artifact_id=eur_artifact,
            property_ref="987654321",
        ),
        _item_primary_row(
            "SKU-1",
            "chatgpt.com",
            "referral",
            item_revenue=80.0,
            items_purchased=1,
            artifact_id=usd_artifact,
        ),
        _item_primary_row(
            "SKU-1",
            "chatgpt.com",
            "referral",
            item_revenue=60.0,
            items_purchased=2,
            artifact_id=eur_artifact,
            property_ref="987654321",
        ),
    ]
    projection = build_a1_projection(
        rows,
        {},
        currency_by_artifact_id={usd_artifact: "USD", eur_artifact: "EUR"},
    )

    a1 = _a1(projection.metrics)
    # One method row per currency, sorted by currency code (no FX source —
    # unlike currencies are NEVER converted or summed together).
    assert [row["currency"] for row in a1] == ["EUR", "USD"]
    eur, usd = a1
    assert eur["totals"]["revenue"] == 90.0
    assert eur["totals"]["orders"] == 3
    assert eur["totals"]["currency"] == "EUR"
    assert usd["totals"]["revenue"] == 120.5
    assert usd["totals"]["orders"] == 2
    (eur_product,) = eur["by_product"]
    assert eur_product["currency"] == "EUR"
    assert eur_product["revenue"] == 60.0
    (usd_product,) = usd["by_product"]
    assert usd_product["revenue"] == 80.0


def test_unknown_currency_rows_serve_the_no_data_partition() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=2,
            purchase_revenue=120.5,
            sessions=10,
            artifact_id=artifact_id,
        )
    ]
    # No currency persisted for the artifact (the defensive partition).
    projection = build_a1_projection(rows, {}, currency_by_artifact_id={})

    (a1,) = _a1(projection.metrics)
    assert a1["state"] == ATTRIBUTION_DATA_STATE_NO_DATA
    assert a1["source_granularity"] is None
    assert a1["reduced_granularity"] is False
    assert a1["currency"] is None
    assert a1["coverage_rate"] is None
    # Null metrics — never a fabricated zero from unmeasurable evidence.
    assert a1["totals"] == {
        "currency": None,
        "revenue": None,
        "orders": None,
        "average_order_value": None,
        "sessions": None,
        "conversion_rate": None,
    }
    assert a1["by_ai_source"] == []
    assert a1["by_product"] == []
    # Unknown-currency rows never fold into provenance.
    assert projection.source_metric_row_ids == []


def test_empty_rows_serve_one_no_data_method_row() -> None:
    projection = build_a1_projection([], {})

    (a1,) = _a1(projection.metrics)
    assert a1["method"] == ATTRIBUTION_METHOD_GA4_PLATFORM
    assert a1["state"] == ATTRIBUTION_DATA_STATE_NO_DATA
    assert a1["totals"]["revenue"] is None
    assert projection.source_metric_row_ids == []


def test_malformed_dimension_keys_are_dropped_never_guessed() -> None:
    artifact_id = uuid.uuid4()
    malformed = _row(
        dataset=DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        # Arity mismatch: the template declares 3 dims, the key packs 2.
        dimension_values=["chatgpt.com", "20260720"],
        metrics={"transactions": 5, "purchaseRevenue": 500.0, "sessions": 50},
        artifact_id=artifact_id,
    )
    valid = _ecommerce_sm_row(
        "google",
        "organic",
        transactions=1,
        purchase_revenue=10.0,
        sessions=4,
        artifact_id=artifact_id,
    )
    projection = build_a1_projection(
        [malformed, valid], {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    (a1,) = _a1(projection.metrics)
    assert a1["totals"]["revenue"] == 10.0
    assert a1["totals"]["orders"] == 1
    assert projection.source_metric_row_ids == [str(valid.id)]


def test_statistical_namespace_is_persistently_not_offered() -> None:
    projection = build_a1_projection([], {})

    metrics = projection.metrics
    assert set(metrics) == {"deterministic", "statistical"}
    # A2/delta/unattributed land with the Shopify order facts — empty
    # sections in this scope.
    assert metrics["deterministic"]["a2"] == []
    assert metrics["deterministic"]["delta"] == []
    assert metrics["deterministic"]["unattributed"] == []
    # Never a fabricated statistical estimate.
    assert metrics["statistical"] == {
        "state": "not_offered",
        "sample_size": None,
        "allocations": [],
    }


def test_metrics_serialize_identically_across_input_order() -> None:
    """Invariant 9: input row order never changes the persisted document."""
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=2,
            purchase_revenue=120.5,
            sessions=10,
            artifact_id=artifact_id,
        ),
        _ecommerce_sm_row(
            "google",
            "organic",
            transactions=5,
            purchase_revenue=300.25,
            sessions=40,
            artifact_id=artifact_id,
            row_date=date(2026, 7, 21),
        ),
        _item_primary_row(
            "SKU-1",
            "chatgpt.com",
            "referral",
            item_revenue=80.0,
            items_purchased=1,
            artifact_id=artifact_id,
        ),
    ]
    first = build_a1_projection(rows, {}, currency_by_artifact_id={artifact_id: "USD"})
    second = build_a1_projection(
        list(reversed(rows)), {}, currency_by_artifact_id={artifact_id: "USD"}
    )
    assert first.metrics == second.metrics
    assert first.source_metric_row_ids == second.source_metric_row_ids


def test_a1_source_rows_use_shared_total_ordering() -> None:
    artifact_id = uuid.uuid4()
    rows = [
        _ecommerce_sm_row(
            "perplexity.ai",
            "referral",
            transactions=1,
            purchase_revenue=10,
            sessions=1,
            artifact_id=artifact_id,
        ),
        _ecommerce_sm_row(
            "chatgpt.com",
            "referral",
            transactions=1,
            purchase_revenue=10,
            sessions=1,
            artifact_id=artifact_id,
        ),
    ]

    projection = build_a1_projection(
        rows, {}, currency_by_artifact_id={artifact_id: "USD"}
    )

    assert [
        row["ai_source"]
        for row in projection.metrics["deterministic"]["a1"][0]["by_ai_source"]
    ] == [AI_SOURCE_CHATGPT, AI_SOURCE_PERPLEXITY]


def test_a2_product_rows_tie_break_by_ai_source() -> None:
    workspace_id = uuid.uuid4()
    project_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    orders: list[OrderFact] = []
    links: list[AttributionLink] = []
    for index, ai_source in enumerate(
        (AI_SOURCE_PERPLEXITY, AI_SOURCE_CHATGPT), start=1
    ):
        order = OrderFact(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=connection_id,
            provider="shopify",
            order_ref_hash=str(index) * 64,
            resync_seq=0,
            occurred_at=datetime(2026, 7, 20, index, tzinfo=UTC),
            currency="USD",
            total_amount=Decimal("10.00"),
            line_items=[
                {"sku": "SKU-1", "quantity": 1, "unit_price": "10.00"},
                {
                    "sku": f"SKU-NON-FINITE-{index}",
                    "quantity": 1,
                    "unit_price": "nan" if index == 1 else "inf",
                },
            ],
            attribution_keys={"referrer_url": f"https://{ai_source}.example"},
            source_artifact_id=artifact_id,
        )
        orders.append(order)
        links.append(
            AttributionLink(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                order_fact_id=order.id,
                method="order_referrer",
                confidence="exact",
                matched_rule_id=f"rule-{index}",
                rule_version="v1",
                analyzer_version="v1",
                evidence_refs={"ai_source": ai_source},
                revenue_amount=Decimal("10.00"),
                currency="USD",
            )
        )
    a1 = build_a1_projection([], {}, currency_by_artifact_id={})

    projection = build_combined_projection(
        a1,
        orders,
        links,
        window_start=date(2026, 7, 20),
        window_end=date(2026, 7, 20),
    )

    assert [
        row["ai_source"]
        for row in projection.metrics["deterministic"]["a2"][0]["by_product"]
    ] == [AI_SOURCE_CHATGPT, AI_SOURCE_PERPLEXITY]
    assert {
        row["sku"] for row in projection.metrics["deterministic"]["a2"][0]["by_product"]
    } == {"SKU-1"}
