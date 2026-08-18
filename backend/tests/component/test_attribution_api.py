"""Commerce attribution read API (WS-B Task 1): the A1 vertical slice.

Pins the acceptance for ``GET /projects/{id}/commerce/attribution``:

  - contract: every served DTO mirrors the frontend zod attribution
    schemas EXACTLY (asserted as exact key-set comparisons, the A10
    pattern) plus exact served values — the GA4-only A1 method rows with
    currency-partitioned totals, classified per-source rows (``other``
    included), per-product rows (sku-resolved ``product_id``), the empty
    A2/delta/unattributed sections, and the permanently ``not_offered``
    statistical namespace;
  - reduced granularity: a connection on the channel-group item fallback
    serves ``source_granularity=default_channel_group`` with
    ``reduced_granularity=true`` and ``ai_source=null`` product rows
    (labelled, never guessed);
  - invariant 7: projections only — reads serve the PERSISTED snapshot
    (no provider call, no recomputation): deleting the source rows after
    the refresh changes nothing, and an absent snapshot serves the empty
    contract (never a 404, never a fabricated zero);
  - invariant 5: cross-workspace project access is a 404;
  - query contract: bad granularity/window -> 422.

The served-snapshot fixture drives the ``attribution_snapshot`` executor
directly over a seeded GA4 ecommerce import chain (unpersisted task:
nothing to cancel against). Requires a real Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    AI_REFERRAL_RULE_VERSION,
    ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
)
from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_FORMULA_VERSION,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_GA4,
)
from app.domain.attribution.snapshot import refresh_attribution_snapshot
from app.models.analytics import AnalyticsTask
from app.models.attribution import AttributionLink
from app.models.commerce import OrderFact
from app.models.integrations import IntegrationImportArtifact, IntegrationMetricRow
from app.models.product import Product
from tests.component.analytics_helpers import (
    ImportSeed,
    seed_ga4_import,
    seed_metric_row,
)

WINDOW = (date(2026, 7, 20), date(2026, 7, 22))

# Exact key sets mirroring the frontend zod attribution schemas (strict).
_RESPONSE_KEYS = {
    "project_id",
    "window_start",
    "window_end",
    "granularity",
    "metrics",
    "source_link_ids",
    "source_order_fact_ids",
    "source_metric_row_ids",
    "source_snapshot_ids",
    "formula_version",
    "analyzer_version",
    "created_at",
}
_METRICS_KEYS = {"deterministic", "statistical"}
_DETERMINISTIC_KEYS = {"a1", "a2", "delta", "unattributed", "coverage"}
_STATISTICAL_KEYS = {"state", "sample_size", "allocations"}
_METHOD_KEYS = {
    "method",
    "state",
    "source_granularity",
    "reduced_granularity",
    "currency",
    "coverage_rate",
    "totals",
    "by_ai_source",
    "by_product",
}
_METRIC_SET_KEYS = {
    "currency",
    "revenue",
    "orders",
    "average_order_value",
    "sessions",
    "conversion_rate",
}
_SOURCE_ROW_KEYS = {"ai_source", "currency", "metrics"}
_PRODUCT_ROW_KEYS = {
    "product_id",
    "sku",
    "name",
    "ai_source",
    "source_label",
    "currency",
    "revenue",
    "orders",
}


# ---------------------------------------------------------------------------
# API + seed helpers
# ---------------------------------------------------------------------------
async def _register(client: httpx.AsyncClient, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


async def _create_project(client: httpx.AsyncClient) -> tuple[str, str]:
    """Create a project in the caller's default workspace.

    Returns ``(project_id, workspace_id)`` so the attribution rows can be
    seeded straight into the same workspace the API authorizes against.
    """
    resp = await client.post("/api/v1/projects", json={"name": "Commerce Project"})
    assert resp.status_code == 201
    body = resp.json()
    return body["id"], body["workspace_id"]


async def _stamp_currency(
    session: AsyncSession, artifact_id: uuid.UUID, currency: str = "USD"
) -> None:
    """Persist the property currency on the artifact payload (AC3).

    The GA4 connector stamps ``metadata.currencyCode`` as a top-level
    ``currency_code`` on the sanitized page payload; the seeded artifacts
    mimic the worker's real output here (direct ORM update — the shared
    seed helpers are owned by another workstream).
    """
    artifact = await session.get(IntegrationImportArtifact, artifact_id)
    assert artifact is not None
    artifact.payload = {**(artifact.payload or {}), "currency_code": currency}


async def _seed_ecommerce_chain(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    item_dataset: str = DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
) -> ImportSeed:
    """Seed the GA4 ecommerce import chain the A1 projection consumes.

    ONE sync run carrying two artifacts (the source/medium ecommerce
    report + the selected item report — the real GA4 run produces one
    artifact per dataset page) plus the derived metric rows and one
    own-catalog Product (SKU-1). Committed by the caller.
    """
    seed = await seed_ga4_import(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        dataset=DATASET_GA4_ECOMMERCE_SOURCE_MEDIUM_DAILY,
        window=WINDOW,
    )
    await _stamp_currency(session, seed.artifact_id)
    # The item artifact on the SAME run (a run pages every template).
    item_artifact = IntegrationImportArtifact(
        workspace_id=workspace_id,
        sync_run_id=seed.sync_run_id,
        connection_id=seed.connection_id,
        provider=INTEGRATION_PROVIDER_GA4,
        dataset=item_dataset,
        query_snapshot={"dimensions": [], "metrics": []},
        payload_hash=uuid.uuid4().hex * 2,
        row_count=0,
        payload={"rows": [], "currency_code": "USD"},
    )
    session.add(item_artifact)
    await session.flush()
    item_seed = ImportSeed(
        workspace_id=workspace_id,
        project_id=project_id,
        grant_id=seed.grant_id,
        connection_id=seed.connection_id,
        sync_run_id=seed.sync_run_id,
        artifact_id=item_artifact.id,
        property_ref=seed.property_ref,
        dataset=item_dataset,
    )

    # Order-level A1 rows (source/medium ecommerce report).
    await seed_metric_row(
        session,
        seed=seed,
        row_date=date(2026, 7, 20),
        dimension_values=["chatgpt.com", "referral", "20260720"],
        metrics={"transactions": 2, "purchaseRevenue": 120.5, "sessions": 10},
    )
    await seed_metric_row(
        session,
        seed=seed,
        row_date=date(2026, 7, 21),
        dimension_values=["google", "organic", "20260721"],
        metrics={"transactions": 5, "purchaseRevenue": 300.25, "sessions": 40},
    )
    # Per-product A1 rows (the item report): SKU-1 resolves to the catalog
    # product, SKU-2 resolves to no own-catalog sku.
    if item_dataset == DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY:
        await seed_metric_row(
            session,
            seed=item_seed,
            row_date=date(2026, 7, 20),
            dimension_values=["SKU-1", "chatgpt.com", "referral", "20260720"],
            metrics={"itemRevenue": 80.0, "itemsPurchased": 1},
        )
        await seed_metric_row(
            session,
            seed=item_seed,
            row_date=date(2026, 7, 21),
            dimension_values=["SKU-2", "google", "organic", "20260721"],
            metrics={"itemRevenue": 200.25, "itemsPurchased": 4},
        )
    else:
        await seed_metric_row(
            session,
            seed=item_seed,
            row_date=date(2026, 7, 20),
            dimension_values=["SKU-1", "Referral", "20260720"],
            metrics={"itemRevenue": 80.0, "itemsPurchased": 1},
        )
        await seed_metric_row(
            session,
            seed=item_seed,
            row_date=date(2026, 7, 21),
            dimension_values=["SKU-2", "Organic Search", "20260721"],
            metrics={"itemRevenue": 200.25, "itemsPurchased": 4},
        )
    session.add(Product(project_id=project_id, sku="SKU-1", name="Widget One"))
    await session.flush()
    # The returned seed aggregates every derived row id (ecommerce + item)
    # so provenance assertions cover the full fold.
    seed.metric_row_ids.extend(item_seed.metric_row_ids)
    return seed


async def _drive_refresh(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Drive the ``attribution_snapshot`` executor (unpersisted task)."""
    task = AnalyticsTask(
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
        payload={
            "window_start": WINDOW[0].isoformat(),
            "window_end": WINDOW[1].isoformat(),
        },
        idempotency_key=uuid.uuid4().hex,
    )
    await refresh_attribution_snapshot(session_factory, task)


async def _seed_served_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    item_dataset: str = DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
) -> ImportSeed:
    """Seed the chain + build the persisted attribution snapshot."""
    async with session_factory() as session:
        seed = await _seed_ecommerce_chain(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            item_dataset=item_dataset,
        )
        await session.commit()
    await _drive_refresh(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )
    return seed


# ---------------------------------------------------------------------------
# Auth + workspace scoping (invariant 5)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_attribution_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/commerce/attribution")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_cross_workspace_project_is_404(client: httpx.AsyncClient) -> None:
    """User B cannot read user A's project attribution (invariant 5)."""
    await _register(client, "attribution-owner-a@example.com")
    project_id, _workspace_id = await _create_project(client)

    # Switch to user B (fresh session cookie in the same client).
    client.cookies.clear()
    await _register(client, "attribution-owner-b@example.com")

    resp = await client.get(f"/api/v1/projects/{project_id}/commerce/attribution")
    assert resp.status_code == 404
    orders = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution/orders"
    )
    assert orders.status_code == 404


# ---------------------------------------------------------------------------
# Empty contract (invariant 7: absent snapshot -> empty contract, never 404)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_contract_when_no_snapshot(client: httpx.AsyncClient) -> None:
    await _register(client, "attribution-empty@example.com")
    project_id, _workspace_id = await _create_project(client)
    url = f"/api/v1/projects/{project_id}/commerce/attribution"

    resp = await client.get(url)
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _RESPONSE_KEYS
    assert body["project_id"] == project_id
    # No window supplied: the empty contract echoes empty window bounds.
    assert body["window_start"] == ""
    assert body["window_end"] == ""
    assert body["granularity"] == "day"
    assert set(body["metrics"]) == _METRICS_KEYS
    assert body["metrics"]["deterministic"] == {
        "a1": [],
        "a2": [],
        "delta": [],
        "unattributed": [],
        "coverage": {
            "total_latest_orders": 0,
            "orders_with_evidence": 0,
            "linked_ai_orders": 0,
            "unattributed_orders": 0,
            "evidence_coverage_rate": None,
            "attributed_share": None,
            "window_start": "",
            "window_end": "",
        },
    }
    assert body["metrics"]["statistical"] == {
        "state": "not_offered",
        "sample_size": None,
        "allocations": [],
    }
    assert body["source_link_ids"] == []
    assert body["source_order_fact_ids"] == []
    assert body["source_metric_row_ids"] == []
    assert body["source_snapshot_ids"] == []
    assert body["formula_version"] == ATTRIBUTION_FORMULA_VERSION
    assert body["analyzer_version"] == ATTRIBUTION_ANALYZER_VERSION
    assert body["created_at"] is None

    # An explicit window is echoed in the empty contract.
    resp = await client.get(url, params={"from": "2026-07-01", "to": "2026-07-07"})
    assert resp.status_code == 200
    assert resp.json()["window_start"] == "2026-07-01"
    assert resp.json()["window_end"] == "2026-07-07"


# ---------------------------------------------------------------------------
# Served snapshot (strict shapes + exact A1 values)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_serves_persisted_a1_projection(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "attribution-served@example.com")
    project_id, workspace_id = await _create_project(client)
    seed = await _seed_served_snapshot(
        session_factory,
        workspace_id=uuid.UUID(workspace_id),
        project_id=uuid.UUID(project_id),
    )
    url = f"/api/v1/projects/{project_id}/commerce/attribution"

    resp = await client.get(url, params={"from": "2026-07-20", "to": "2026-07-22"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _RESPONSE_KEYS
    assert body["project_id"] == project_id
    assert body["window_start"] == "2026-07-20"
    assert body["window_end"] == "2026-07-22"
    assert body["granularity"] == "day"
    assert body["formula_version"] == ATTRIBUTION_FORMULA_VERSION
    assert body["analyzer_version"] == ATTRIBUTION_ANALYZER_VERSION
    assert body["created_at"] is not None
    # Provenance: the four folded metric rows (2 ecommerce + 2 item).
    assert sorted(body["source_metric_row_ids"]) == sorted(
        str(row_id) for row_id in seed.metric_row_ids
    )
    assert body["source_link_ids"] == []
    assert body["source_order_fact_ids"] == []
    assert body["source_snapshot_ids"] == []

    metrics = body["metrics"]
    assert set(metrics) == _METRICS_KEYS
    deterministic = metrics["deterministic"]
    assert set(deterministic) == _DETERMINISTIC_KEYS
    # A2/delta/unattributed are empty in this scope (Task 4 lands them).
    assert deterministic["a2"] == []
    assert deterministic["delta"] == [
        {
            "currency": "USD",
            "state": "method_unavailable",
            "revenue": None,
            "orders": None,
            "average_order_value": None,
            "conversion_rate": None,
        }
    ]
    assert deterministic["unattributed"] == []
    assert metrics["statistical"] == {
        "state": "not_offered",
        "sample_size": None,
        "allocations": [],
    }

    (a1,) = deterministic["a1"]
    assert set(a1) == _METHOD_KEYS
    assert a1["method"] == "ga4_platform_attributed"
    assert a1["state"] == "available"
    assert a1["source_granularity"] == "session_source_medium"
    assert a1["reduced_granularity"] is False
    assert a1["currency"] == "USD"
    assert a1["coverage_rate"] is None
    assert set(a1["totals"]) == _METRIC_SET_KEYS
    assert a1["totals"] == {
        "currency": "USD",
        "revenue": 420.75,
        "orders": 7,
        "average_order_value": 60.11,
        "sessions": 50,
        "conversion_rate": 0.14,
    }

    # Per-source rows: classified through the deterministic rule table,
    # ``other`` included, revenue-desc order.
    by_source = a1["by_ai_source"]
    assert [entry["ai_source"] for entry in by_source] == ["other", "chatgpt"]
    for entry in by_source:
        assert set(entry) == _SOURCE_ROW_KEYS
        assert entry["currency"] == "USD"
        assert set(entry["metrics"]) == _METRIC_SET_KEYS
    assert by_source[0]["metrics"]["revenue"] == 300.25
    assert by_source[1]["metrics"] == {
        "currency": "USD",
        "revenue": 120.5,
        "orders": 2,
        "average_order_value": 60.25,
        "sessions": 10,
        "conversion_rate": 0.2,
    }

    # Per-product rows: revenue desc; SKU-1 resolves to the catalog
    # product, SKU-2 stays unresolved (product_id null).
    by_product = a1["by_product"]
    assert [entry["sku"] for entry in by_product] == ["SKU-2", "SKU-1"]
    for entry in by_product:
        assert set(entry) == _PRODUCT_ROW_KEYS
    sku2, sku1 = by_product
    assert sku2["product_id"] is None
    assert sku2["name"] == "SKU-2"
    assert sku2["ai_source"] == "other"
    assert sku2["source_label"] == "google / organic"
    assert sku2["currency"] == "USD"
    assert sku2["revenue"] == 200.25
    assert sku2["orders"] == 4
    assert sku1["product_id"] is not None
    assert sku1["ai_source"] == "chatgpt"
    assert sku1["source_label"] == "chatgpt.com / referral"

    # Without a window the project's LATEST snapshot at the granularity is
    # served (same persisted document).
    resp = await client.get(url)
    assert resp.status_code == 200
    assert resp.json()["window_start"] == "2026-07-20"
    assert resp.json()["metrics"]["deterministic"]["a1"][0]["totals"]["revenue"] == (
        420.75
    )


@pytest.mark.asyncio
async def test_reduced_granularity_fallback_is_labelled(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A connection on the channel-group item fallback serves the reduced
    granularity LABELLED — ``ai_source`` null on product rows, the channel
    group as ``source_label`` (never a guessed AI source)."""
    await _register(client, "attribution-fallback@example.com")
    project_id, workspace_id = await _create_project(client)
    await _seed_served_snapshot(
        session_factory,
        workspace_id=uuid.UUID(workspace_id),
        project_id=uuid.UUID(project_id),
        item_dataset=DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    )
    url = f"/api/v1/projects/{project_id}/commerce/attribution"

    resp = await client.get(url, params={"from": "2026-07-20", "to": "2026-07-22"})
    assert resp.status_code == 200
    (a1,) = resp.json()["metrics"]["deterministic"]["a1"]
    assert a1["source_granularity"] == "default_channel_group"
    assert a1["reduced_granularity"] is True
    products = {entry["sku"]: entry for entry in a1["by_product"]}
    assert products["SKU-1"]["ai_source"] is None
    assert products["SKU-1"]["source_label"] == "Referral"
    assert products["SKU-2"]["ai_source"] is None
    assert products["SKU-2"]["source_label"] == "Organic Search"
    # The order-level totals are granularity-independent (unchanged).
    assert a1["totals"]["revenue"] == 420.75


@pytest.mark.asyncio
async def test_read_serves_persisted_values_after_source_rows_deleted(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Invariant 7: reads never recompute — the persisted snapshot is
    served verbatim even after the source metric rows are gone (and no
    provider is ever called at read time)."""
    await _register(client, "attribution-persisted@example.com")
    project_id, workspace_id = await _create_project(client)
    await _seed_served_snapshot(
        session_factory,
        workspace_id=uuid.UUID(workspace_id),
        project_id=uuid.UUID(project_id),
    )
    url = f"/api/v1/projects/{project_id}/commerce/attribution"
    params = {"from": "2026-07-20", "to": "2026-07-22"}
    before = (await client.get(url, params=params)).json()

    async with session_factory() as session:
        await session.execute(
            delete(IntegrationMetricRow).where(
                IntegrationMetricRow.project_id == uuid.UUID(project_id)
            )
        )
        await session.commit()

    resp = await client.get(url, params=params)
    assert resp.status_code == 200
    assert resp.json() == before


# ---------------------------------------------------------------------------
# Query contract (422s)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_invalid_granularity_and_window_are_422(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "attribution-422@example.com")
    project_id, _workspace_id = await _create_project(client)
    url = f"/api/v1/projects/{project_id}/commerce/attribution"

    assert (await client.get(url, params={"granularity": "hour"})).status_code == 422
    # Half-specified window.
    assert (await client.get(url, params={"from": "2026-07-20"})).status_code == 422
    assert (await client.get(url, params={"to": "2026-07-22"})).status_code == 422
    # Inverted window.
    assert (
        await client.get(url, params={"from": "2026-07-22", "to": "2026-07-20"})
    ).status_code == 422


@pytest.mark.asyncio
async def test_combined_a2_unattributed_delta_and_safe_order_page(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "attribution-a2@example.com")
    project_id_raw, workspace_id_raw = await _create_project(client)
    project_id = uuid.UUID(project_id_raw)
    workspace_id = uuid.UUID(workspace_id_raw)
    async with session_factory() as session:
        seed = await _seed_ecommerce_chain(
            session, workspace_id=workspace_id, project_id=project_id
        )
        product_id = await session.scalar(
            select(Product.id).where(Product.project_id == project_id)
        )
        linked = OrderFact(
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=seed.connection_id,
            provider="shopify",
            order_ref_hash="a" * 64,
            resync_seq=0,
            occurred_at=datetime(2026, 7, 20, 12, tzinfo=UTC),
            currency="USD",
            total_amount=Decimal("75.00"),
            line_items=[
                {
                    "sku": "SKU-1",
                    "quantity": 1,
                    "unit_price": "75.00",
                    "product_id": str(product_id),
                }
            ],
            attribution_keys={"referrer_url": "https://chatgpt.com/c/opaque"},
            source_artifact_id=seed.artifact_id,
        )
        old_unlinked = OrderFact(
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=seed.connection_id,
            provider="shopify",
            order_ref_hash="b" * 64,
            resync_seq=0,
            occurred_at=datetime(2026, 7, 21, 12, tzinfo=UTC),
            currency="USD",
            total_amount=Decimal("100.00"),
            line_items=[],
            attribution_keys={},
            source_artifact_id=seed.artifact_id,
        )
        unlinked = OrderFact(
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=seed.connection_id,
            provider="shopify",
            order_ref_hash="b" * 64,
            resync_seq=1,
            occurred_at=datetime(2026, 7, 21, 12, tzinfo=UTC),
            currency="USD",
            total_amount=Decimal("25.00"),
            line_items=[],
            attribution_keys={},
            source_artifact_id=seed.artifact_id,
        )
        session.add_all([linked, old_unlinked, unlinked])
        await session.flush()
        session.add(
            AttributionLink(
                workspace_id=workspace_id,
                project_id=project_id,
                order_fact_id=linked.id,
                method="order_referrer",
                confidence="exact",
                matched_rule_id="host-chatgpt-com",
                rule_version=AI_REFERRAL_RULE_VERSION,
                analyzer_version=ATTRIBUTION_ANALYZER_VERSION,
                evidence_refs={"ai_source": "chatgpt", "match_signal": "referrer"},
                revenue_amount=Decimal("75.00"),
                currency="USD",
            )
        )
        await session.commit()
    await _drive_refresh(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )

    response = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution",
        params={"from": WINDOW[0].isoformat(), "to": WINDOW[1].isoformat()},
    )
    assert response.status_code == 200
    deterministic = response.json()["metrics"]["deterministic"]
    assert deterministic["a2"][0]["source_granularity"] is None
    assert deterministic["a2"][0]["coverage_rate"] == 0.5
    assert deterministic["coverage"] == {
        "total_latest_orders": 2,
        "orders_with_evidence": 1,
        "linked_ai_orders": 1,
        "unattributed_orders": 1,
        "evidence_coverage_rate": 0.5,
        "attributed_share": 0.5,
        "window_start": WINDOW[0].isoformat(),
        "window_end": WINDOW[1].isoformat(),
    }
    assert deterministic["a2"][0]["by_ai_source"][0]["ai_source"] == "chatgpt"
    assert deterministic["unattributed"] == [
        {"currency": "USD", "orders": 1, "order_share": 0.5, "revenue": 25.0}
    ]
    assert deterministic["delta"][0]["state"] == "comparable"
    assert "total" not in deterministic

    orders = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution/orders",
        params={"attribution_state": "attributed"},
    )
    assert orders.status_code == 200
    row = orders.json()["items"][0]
    assert set(row) == {
        "fact_id",
        "occurred_at",
        "line_items",
        "amount",
        "currency",
        "attribution_state",
        "method",
        "ai_source",
        "confidence",
        "rule_version",
    }
    assert row["ai_source"] == "chatgpt"
    assert "order_ref_hash" not in row

    monkeypatch.setattr(
        "app.domain.attribution.service.ATTRIBUTION_ORDERS_PAGE_SIZE", 1
    )
    first_page = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution/orders"
    )
    assert first_page.status_code == 200
    cursor = first_page.json()["next_cursor"]
    assert cursor
    replay = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution/orders",
        params={"cursor": cursor, "attribution_state": "attributed"},
    )
    assert replay.status_code == 400
    tampered = await client.get(
        f"/api/v1/projects/{project_id}/commerce/attribution/orders",
        params={"cursor": "not-a-valid-cursor"},
    )
    assert tampered.status_code == 400
