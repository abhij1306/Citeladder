"""Component tests for the Shopify sync path (commerce suite, WS-B 2/3).

Runs the real ``IntegrationWorker`` against a live Postgres schema with an
injected fake Shopify Admin GraphQL endpoint (``httpx.MockTransport``).
Covers the commerce-suite worker contract:

  - The offline (non-refreshable) token is used AS-IS: no refresh request
    ever leaves, every GraphQL call carries the ``X-Shopify-Access-Token``
    header (never a Bearer token), and the URL is the config-pinned
    per-shop ``/admin/api/{version}/graphql.json``.
  - The durable cursor protocol: two outer pages replay the exact
    ``endCursor`` as the next ``after`` variable; ``query_snapshot``
    persists ``pagingMode``/``pageCursor``/``nextPageCursor``; a retry
    resumes ONLY from the immutable artifact snapshots.
  - Malformed outer or nested ``pageInfo`` and HTTP-200 GraphQL ``errors``
    fail the run terminal with ``ERROR_PROVIDER_API`` (the malformed page
    is never persisted); 429 retries; 401 marks the grant needs_reauth.
  - Order PII never survives: the artifact stores only allowlisted
    ``SanitizedOrder`` payloads and derivation inserts ``OrderFact`` rows
    keyed by the opaque salted hash.
  - Derivation: catalog merge (Product provenance), feed issues, order
    facts with SKU-resolved line items.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.config.commerce import (
    FEED_RULE_MISSING_GTIN_MPN,
    ORDER_SANITIZED_KEYS,
)
from app.core.config.integrations_contracts import (
    ERROR_GRANT_AUTH_FAILED,
    ERROR_PROVIDER_API,
    ERROR_RATE_LIMITED,
    EVENT_INTEGRATION_REAUTH_REQUIRED,
    GRANT_STATUS_CONNECTED,
    GRANT_STATUS_NEEDS_REAUTH,
)
from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_ORDERS,
    DATASET_SHOPIFY_PRODUCTS,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_TRANSPORT_SHOPIFY,
    SHOPIFY_ADMIN_API_VERSION,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_SUCCEEDED,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.integrations.sync import enqueue_sync_run
from app.models.brand import OwnedDomain
from app.models.commerce import FeedIssue, OrderFact
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
)
from app.models.product import Product
from app.models.project import Project
from app.models.workspace import Workspace
from app.workers.integration_worker import IntegrationWorker

_WINDOW = (date(2026, 7, 20), date(2026, 7, 22))
_SHOP = "volt-city.myshopify.com"
_OFFLINE_TOKEN = "shpat_offline-token-1"  # pragma: allowlist secret
_GRAPHQL_PATH = f"/admin/api/{SHOPIFY_ADMIN_API_VERSION}/graphql.json"


@pytest.fixture(autouse=True)
def _fast_pacing_and_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    # Keep request pacing out of the test timing budget and give the
    # Shopify credential branch env-injected values (never logged).
    monkeypatch.setattr(integration_settings, "shopify_requests_per_minute", 60000)
    monkeypatch.setattr(
        settings, "integration_shopify_client_id", "test-shopify-client-id"
    )
    monkeypatch.setattr(
        settings,
        "integration_shopify_client_secret",
        "test-shopify-client-secret",  # pragma: allowlist secret
    )


# --- Fake provider ----------------------------------------------------------


def _variant_node(
    suffix: str,
    *,
    sku: str = "",
    barcode: str = "012345678905",
    price: str = "64.99",
    inventory: int | None = 12,
    title: str = "Default Title",
) -> dict:
    return {
        "id": f"gid://shopify/ProductVariant/{suffix}",
        "title": title,
        "sku": sku,
        "barcode": barcode,
        "price": price,
        "inventoryQuantity": inventory,
        "updatedAt": "2026-07-21T09:00:00Z",
    }


def _product_node(
    suffix: str,
    variants: list[dict],
    *,
    variants_has_next: bool = False,
    variants_end_cursor: str | None = None,
    title: str = "VoltCity 500",
) -> dict:
    return {
        "id": f"gid://shopify/Product/{suffix}",
        "title": title,
        "handle": "voltcity-500",
        "description": "The VoltCity 500 portable charger",
        "vendor": "VoltCity",
        "productType": "Chargers",
        "status": "ACTIVE",
        "onlineStoreUrl": "https://volt-city.example/products/voltcity-500",
        "updatedAt": "2026-07-21T09:00:00Z",
        "variants": {
            "pageInfo": {
                "hasNextPage": variants_has_next,
                "endCursor": variants_end_cursor,
            },
            "nodes": variants,
        },
    }


def _order_node(suffix: str, *, sku: str = "VC-500") -> dict:
    """A RAW order node carrying the PII the sanitizer must drop."""
    return {
        "id": f"gid://shopify/Order/{suffix}",
        "createdAt": "2026-07-21T10:15:00Z",
        "updatedAt": "2026-07-21T11:00:00Z",
        "cancelledAt": None,
        "currencyCode": "USD",
        "currentTotalPriceSet": {
            "shopMoney": {"amount": "64.99", "currencyCode": "USD"}
        },
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "FULFILLED",
        "email": "buyer@example.com",
        "customer": {
            "id": "gid://shopify/Customer/1",
            "firstName": "Ada",
            "lastName": "Lovelace",
            "email": "ada@example.com",
        },
        "note": "leave at door, call 555-0100",
        "clientIp": "203.0.113.7",
        "customerJourneySummary": {
            "ready": True,
            "firstVisit": None,
            "lastVisit": {
                "landingSiteUrl": (
                    "https://volt-city.example/products/voltcity-500"
                    "?utm_source=google&utm_medium=cpc&gclid=abc123#frag"
                ),
                "referrerUrl": "https://google.com/search?q=voltcity",
                "source": "SEARCH",
                "utmParameters": {
                    "source": "google",
                    "medium": "cpc",
                    "campaign": "summer",
                    "term": None,
                    "content": None,
                },
            },
        },
        "lineItems": {
            "pageInfo": {"hasNextPage": False, "endCursor": None},
            "nodes": [
                {
                    "id": "gid://shopify/LineItem/1",
                    "sku": sku,
                    "quantity": 1,
                    "currentQuantity": 1,
                    "originalUnitPriceSet": {
                        "shopMoney": {"amount": "64.99", "currencyCode": "USD"}
                    },
                }
            ],
        },
    }


def _products_payload(
    nodes: list[dict], *, has_next: bool, end_cursor: str | None
) -> dict:
    return {
        "data": {
            "shop": {"currencyCode": "USD"},
            "products": {
                "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                "nodes": nodes,
            },
        }
    }


def _orders_payload(
    nodes: list[dict], *, has_next: bool, end_cursor: str | None
) -> dict:
    return {
        "data": {
            "orders": {
                "pageInfo": {"hasNextPage": has_next, "endCursor": end_cursor},
                "nodes": nodes,
            },
        }
    }


class _ShopifyFake:
    """The fake per-shop Admin GraphQL endpoint, routed by operation name.

    ``products_overrides`` maps an ``after`` cursor (None = first page) to
    a full ``httpx.Response`` replacement (status/payload), and likewise
    ``orders_overrides`` — the malformed/429/401 knobs.
    """

    def __init__(
        self,
        *,
        products_overrides: dict[str | None, httpx.Response] | None = None,
        orders_overrides: dict[str | None, httpx.Response] | None = None,
        variant_continuation: bool = False,
        nested_malformed: bool = False,
    ) -> None:
        self.calls: list[dict] = []
        self.urls: list[str] = []
        self.token_headers: list[str] = []
        self.auth_headers: list[str] = []
        self._products_overrides = products_overrides or {}
        self._orders_overrides = orders_overrides or {}
        self._variant_continuation = variant_continuation
        self._nested_malformed = nested_malformed

    def _record(self, request: httpx.Request, body: dict, operation: str) -> None:
        self.urls.append(str(request.url))
        self.token_headers.append(request.headers.get("x-shopify-access-token", ""))
        self.auth_headers.append(request.headers.get("authorization", ""))
        self.calls.append({"operation": operation, "variables": body["variables"]})

    def _products(self, variables: dict) -> httpx.Response:
        after = variables.get("after")
        override = self._products_overrides.get(after)
        if override is not None:
            return override
        if after is None:
            variants_next = self._variant_continuation
            if self._nested_malformed:
                page_info: dict = {"hasNextPage": True, "endCursor": None}
            elif variants_next:
                page_info = {"hasNextPage": True, "endCursor": "vc-1"}
            else:
                page_info = {"hasNextPage": False, "endCursor": None}
            product_one = _product_node(
                "p1",
                [_variant_node("v1", sku="VC-500", price="64.99")],
                variants_has_next=page_info["hasNextPage"],
                variants_end_cursor=page_info["endCursor"],
            )
            product_two = _product_node(
                "p2",
                [_variant_node("v2", sku="VC-900", barcode="", price="19.99")],
                title="VoltCity 900",
            )
            return httpx.Response(
                200,
                json=_products_payload(
                    [product_one, product_two], has_next=True, end_cursor="cursor-p1"
                ),
            )
        if after == "cursor-p1":
            product = _product_node(
                "p3",
                [_variant_node("v3", sku="VC-100", inventory=None, price="9.99")],
                title="VoltCity 100",
            )
            return httpx.Response(
                200,
                json=_products_payload([product], has_next=False, end_cursor=None),
            )
        raise AssertionError(f"unexpected products cursor: {after!r}")

    def _variants(self, variables: dict) -> httpx.Response:
        assert variables.get("id") == "gid://shopify/Product/p1"
        assert variables.get("after") == "vc-1"
        return httpx.Response(
            200,
            json={
                "data": {
                    "product": {
                        "variants": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                _variant_node("v1b", sku="VC-500-B", price="74.99")
                            ],
                        }
                    }
                }
            },
        )

    def _orders(self, variables: dict) -> httpx.Response:
        after = variables.get("after")
        override = self._orders_overrides.get(after)
        if override is not None:
            return override
        if after is None:
            return httpx.Response(
                200,
                json=_orders_payload(
                    [_order_node("o1")], has_next=True, end_cursor="cursor-o1"
                ),
            )
        if after == "cursor-o1":
            return httpx.Response(
                200,
                json=_orders_payload(
                    [_order_node("o2")], has_next=False, end_cursor=None
                ),
            )
        raise AssertionError(f"unexpected orders cursor: {after!r}")

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == _SHOP, f"unexpected host: {request.url.host}"
        assert request.url.path == _GRAPHQL_PATH, f"unexpected path: {request.url.path}"
        body = json.loads(request.content)
        query = body["query"]
        if "query ShopifyProducts" in query:
            self._record(request, body, "products")
            return self._products(body["variables"])
        if "query ShopifyProductVariants" in query:
            self._record(request, body, "variants")
            return self._variants(body["variables"])
        if "query ShopifyOrders" in query:
            self._record(request, body, "orders")
            return self._orders(body["variables"])
        if "query ShopifyOrderLineItems" in query:
            self._record(request, body, "line_items")
            raise AssertionError("no line-item continuation expected")
        if "query ShopifyConnectionProbe" in query:
            self._record(request, body, "probe")
            return httpx.Response(200, json={"data": {"shop": {"id": "gid://s/1"}}})
        raise AssertionError(f"unexpected GraphQL operation: {query[:80]}")

    def mock_transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def operation_calls(self, operation: str) -> list[dict]:
        return [
            call["variables"] for call in self.calls if call["operation"] == operation
        ]


# --- Seed + helpers ---------------------------------------------------------


async def _seed_graph(
    db_session,
    *,
    account_ref: str = _SHOP,
    mapping_ref: str | None = None,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Workspace/project + Shopify grant (offline token) + connection + mapping."""
    workspace = Workspace(name="Acme")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme Site")
    db_session.add(project)
    await db_session.flush()
    db_session.add(OwnedDomain(project_id=project.id, domain="example.com"))
    grant = IntegrationOAuthGrant(
        workspace_id=workspace.id,
        transport=INTEGRATION_TRANSPORT_SHOPIFY,
        access_token_encrypted=encrypt_secret(_OFFLINE_TOKEN),
        refresh_token_encrypted="",
        # The offline token carries NO expiry: the worker must NOT treat
        # this as near-expiry (non-refreshable transport).
        token_expires_at=None,
        granted_scopes=["read_products", "read_orders"],
        status=GRANT_STATUS_CONNECTED,
    )
    db_session.add(grant)
    await db_session.flush()
    connection = IntegrationConnection(
        workspace_id=workspace.id,
        grant_id=grant.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        label="shopify connection",
        account_ref=account_ref,
    )
    db_session.add(connection)
    await db_session.flush()
    db_session.add(
        IntegrationPropertyMapping(
            workspace_id=workspace.id,
            connection_id=connection.id,
            provider=INTEGRATION_PROVIDER_SHOPIFY,
            property_ref=mapping_ref if mapping_ref is not None else account_ref,
            project_id=project.id,
            status="active",
        )
    )
    await db_session.commit()
    return workspace.id, project.id, grant.id, connection.id


def _worker(
    session_factory: async_sessionmaker[AsyncSession],
    transport: httpx.AsyncBaseTransport,
) -> IntegrationWorker:
    return IntegrationWorker(
        session_factory=session_factory, owner="shopify-test", transport=transport
    )


async def _artifacts(
    db_session, run_id: uuid.UUID, dataset: str | None = None
) -> list[IntegrationImportArtifact]:
    stmt = (
        select(IntegrationImportArtifact)
        .where(IntegrationImportArtifact.sync_run_id == run_id)
        .order_by(
            IntegrationImportArtifact.created_at.asc(),
            IntegrationImportArtifact.id.asc(),
        )
    )
    if dataset is not None:
        stmt = stmt.where(IntegrationImportArtifact.dataset == dataset)
    return list((await db_session.scalars(stmt)).all())


def _canonical_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --- Happy path + cursor protocol -------------------------------------------


@pytest.mark.asyncio
async def test_shopify_sync_end_to_end(session_factory, db_session) -> None:
    """claim -> offline token as-is -> cursor pages -> artifacts -> derivation."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ShopifyFake()

    ran = await _worker(session_factory, fake.mock_transport()).run_until_idle()
    assert ran == 1

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    assert run.error_code == ""

    # The offline token was used AS-IS: no token-endpoint request exists in
    # this fake at all (any request to a non-GraphQL path asserts), every
    # call carried the X-Shopify-Access-Token header, and NEVER a Bearer.
    assert set(fake.token_headers) == {_OFFLINE_TOKEN}
    assert set(fake.auth_headers) == {""}
    assert set(fake.urls) == {f"https://{_SHOP}{_GRAPHQL_PATH}"}

    # Cursor protocol: products paged after=None -> "cursor-p1" (the exact
    # endCursor replayed as the next `after`), orders likewise; paging
    # stopped when hasNextPage went false (no third page).
    products_vars = fake.operation_calls("products")
    assert [v["after"] for v in products_vars] == [None, "cursor-p1"]
    assert {v["first"] for v in products_vars} == {
        integration_settings.shopify_page_size
    }
    assert {v["variantFirst"] for v in products_vars} == {
        integration_settings.shopify_nested_page_size
    }
    assert products_vars[0]["query"] == (
        "updated_at:>=2026-07-20 updated_at:<=2026-07-22"
    )
    orders_vars = fake.operation_calls("orders")
    assert [v["after"] for v in orders_vars] == [None, "cursor-o1"]

    # Artifacts: 2 product pages + 2 order pages, each with the durable
    # cursor snapshot and the raw outer node count.
    product_artifacts = await _artifacts(db_session, run.id, DATASET_SHOPIFY_PRODUCTS)
    order_artifacts = await _artifacts(db_session, run.id, DATASET_SHOPIFY_ORDERS)
    assert [a.row_count for a in product_artifacts] == [2, 1]
    assert [a.row_count for a in order_artifacts] == [1, 1]
    first, second = product_artifacts
    assert first.query_snapshot["pagingMode"] == "cursor"
    assert first.query_snapshot["pageCursor"] is None
    assert first.query_snapshot["nextPageCursor"] == "cursor-p1"
    assert second.query_snapshot["pageCursor"] == "cursor-p1"
    assert second.query_snapshot["nextPageCursor"] is None
    assert first.query_snapshot["startRow"] == 0
    assert second.query_snapshot["startRow"] == 2
    for artifact in (*product_artifacts, *order_artifacts):
        assert artifact.payload_hash == _canonical_hash(artifact.payload)

    # Catalog derivation: three products, provenance stamped.
    products = list(
        (
            await db_session.scalars(
                select(Product)
                .where(Product.project_id == project_id)
                .order_by(Product.sku.asc())
            )
        ).all()
    )
    assert [p.sku for p in products] == ["VC-100", "VC-500", "VC-900"]
    vc500 = next(p for p in products if p.sku == "VC-500")
    assert vc500.origin == "synced"
    assert vc500.connection_id == connection_id
    assert vc500.external_item_ref == "gid://shopify/ProductVariant/v1"
    assert vc500.last_seen_sync_run_id == run.id
    assert vc500.name == "VoltCity 500"  # "Default Title" normalized away
    assert vc500.price == Decimal("64.99")
    assert vc500.currency == "USD"
    assert vc500.attributes["gtin"] == "012345678905"
    assert vc500.attributes["vendor"] == "VoltCity"
    assert vc500.attributes["availability"] == "in_stock"

    # Feed issues: VC-900 missing barcode (warning), VC-100 missing
    # availability (warning).
    issues = list(
        (
            await db_session.scalars(
                select(FeedIssue).where(FeedIssue.sync_run_id == run.id)
            )
        ).all()
    )
    assert {(i.external_item_ref, i.rule_id) for i in issues} == {
        ("gid://shopify/ProductVariant/v2", FEED_RULE_MISSING_GTIN_MPN),
        ("gid://shopify/ProductVariant/v3", "feed.missing_availability"),
    }

    # Order facts: one per order, resync_seq 0, SKU-resolved line items.
    facts = list(
        (
            await db_session.scalars(
                select(OrderFact).where(OrderFact.connection_id == connection_id)
            )
        ).all()
    )
    assert len(facts) == 2
    assert {f.resync_seq for f in facts} == {0}
    assert all(len(f.order_ref_hash) == 64 for f in facts)
    # Two distinct orders -> two distinct opaque hashes.
    assert len({f.order_ref_hash for f in facts}) == 2
    fact_o1 = next(f for f in facts if f.source_artifact_id == order_artifacts[0].id)
    assert fact_o1.currency == "USD"
    assert fact_o1.total_amount == Decimal("64.99")
    assert fact_o1.line_items[0]["sku"] == "VC-500"
    assert fact_o1.line_items[0]["product_id"] == str(vc500.id)
    assert fact_o1.attribution_keys["utm_source"] == "google"
    assert fact_o1.attribution_keys["utm_campaign"] == "summer"


@pytest.mark.asyncio
async def test_shopify_order_pii_never_survives(session_factory, db_session) -> None:
    """AC7: no customer PII in artifacts, facts, events, or run fields."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    await _worker(session_factory, _ShopifyFake().mock_transport()).run_until_idle()
    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED

    pii = (
        "buyer@example.com",
        "ada@example.com",
        "Ada",
        "Lovelace",
        "555-0100",
        "203.0.113.7",
        "gclid",
    )
    order_artifacts = await _artifacts(db_session, run.id, DATASET_SHOPIFY_ORDERS)
    assert len(order_artifacts) == 2
    for artifact in order_artifacts:
        serialized = json.dumps(artifact.payload)
        for needle in pii:
            assert needle not in serialized
        snapshot_serialized = json.dumps(artifact.query_snapshot)
        for needle in pii:
            assert needle not in snapshot_serialized
        for order in artifact.payload["orders"]:
            assert set(order) == ORDER_SANITIZED_KEYS
    facts = list(
        (
            await db_session.scalars(
                select(OrderFact).where(OrderFact.connection_id == connection_id)
            )
        ).all()
    )
    assert facts
    for fact in facts:
        serialized = json.dumps(
            {"line_items": fact.line_items, "attribution_keys": fact.attribution_keys}
        )
        for needle in pii:
            assert needle not in serialized
        # The raw provider order id never persists — only the salted hash.
        assert "gid://shopify/Order" not in fact.order_ref_hash
    events = list(
        (
            await db_session.scalars(
                select(IntegrationEvent).where(
                    IntegrationEvent.workspace_id == workspace_id
                )
            )
        ).all()
    )
    for event in events:
        serialized = json.dumps(event.payload) + event.message
        for needle in pii:
            assert needle not in serialized
        assert _OFFLINE_TOKEN not in serialized


@pytest.mark.asyncio
async def test_shopify_retry_resumes_from_durable_cursor(
    session_factory, db_session
) -> None:
    """A retry resumes ONLY from the artifact snapshots — page 1 never refetched."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    # Simulate a crashed first attempt: products page 1 is already durable
    # (hasNextPage=true with its nextPageCursor persisted).
    fake_probe = _ShopifyFake()
    page1_payload = {
        "rows": [
            {
                "product_ref": "gid://shopify/Product/p1",
                "variant_ref": "gid://shopify/ProductVariant/v1",
                "sku": "VC-500",
                "barcode": "012345678905",
                "title": "VoltCity 500",
                "variant_title": "Default Title",
                "description": "d",
                "vendor": "VoltCity",
                "product_type": "Chargers",
                "status": "ACTIVE",
                "url": "https://volt-city.example/products/voltcity-500",
                "price": "64.99",
                "currency": "USD",
                "inventory_quantity": 12,
                "updated_at": "2026-07-21T09:00:00Z",
            }
        ],
        "pageInfo": {"hasNextPage": True, "endCursor": "cursor-p1"},
    }
    db_session.add(
        IntegrationImportArtifact(
            sync_run_id=run.id,
            connection_id=connection_id,
            workspace_id=workspace_id,
            provider=INTEGRATION_PROVIDER_SHOPIFY,
            dataset=DATASET_SHOPIFY_PRODUCTS,
            query_snapshot={
                "api_method": "ShopifyProducts",
                "dataset": DATASET_SHOPIFY_PRODUCTS,
                "property_ref": _SHOP,
                "startDate": _WINDOW[0].isoformat(),
                "endDate": _WINDOW[1].isoformat(),
                "dimensions": [],
                "metrics": [],
                "rowLimit": 2,
                "startRow": 0,
                "pagingMode": "cursor",
                "pageCursor": None,
                "nextPageCursor": "cursor-p1",
            },
            payload_hash=_canonical_hash(page1_payload),
            row_count=1,
            payload=page1_payload,
        )
    )
    await db_session.commit()

    await _worker(session_factory, fake_probe.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    # The pre-seeded page was NOT refetched: the first (only) products
    # request resumed at the durable nextPageCursor.
    assert [v["after"] for v in fake_probe.operation_calls("products")] == ["cursor-p1"]
    product_artifacts = await _artifacts(db_session, run.id, DATASET_SHOPIFY_PRODUCTS)
    assert len(product_artifacts) == 2  # pre-seeded + the resume page
    assert len({a.id for a in product_artifacts}) == 2


# --- Nested connection exhaustion -------------------------------------------


@pytest.mark.asyncio
async def test_shopify_nested_variant_pages_exhausted(
    session_factory, db_session
) -> None:
    """A nested variants connection is paged to its end — never truncated."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ShopifyFake(variant_continuation=True)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    variant_vars = fake.operation_calls("variants")
    assert [v["after"] for v in variant_vars] == ["vc-1"]
    assert variant_vars[0]["id"] == "gid://shopify/Product/p1"
    assert variant_vars[0]["first"] == integration_settings.shopify_nested_page_size
    # The continuation variant landed in the same artifact page.
    (first_artifact,) = (
        await _artifacts(db_session, run.id, DATASET_SHOPIFY_PRODUCTS)
    )[:1]
    skus = {row["sku"] for row in first_artifact.payload["rows"]}
    assert skus == {"VC-500", "VC-500-B", "VC-900"}


# --- Failure taxonomy ---------------------------------------------------------


@pytest.mark.asyncio
async def test_shopify_malformed_outer_page_info_fails_terminal(
    session_factory, db_session
) -> None:
    """hasNextPage=true without an endCursor: terminal, page never persisted."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    malformed = httpx.Response(
        200,
        json=_products_payload(
            [_product_node("p1", [_variant_node("v1", sku="VC-500")])],
            has_next=True,
            end_cursor=None,  # continuation with no cursor = malformed
        ),
    )
    fake = _ShopifyFake(products_overrides={None: malformed})

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert run.attempt_count == 1  # terminal: no retry budget burned
    # The malformed page was NEVER persisted (validation precedes write).
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_missing_outer_page_info_fails_terminal(
    session_factory, db_session
) -> None:
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    payload = _products_payload(
        [_product_node("p1", [_variant_node("v1", sku="VC-500")])],
        has_next=False,
        end_cursor=None,
    )
    del payload["data"]["products"]["pageInfo"]  # missing entirely
    fake = _ShopifyFake(products_overrides={None: httpx.Response(200, json=payload)})

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_malformed_nested_page_info_fails_terminal(
    session_factory, db_session
) -> None:
    """Nested variants pageInfo with hasNextPage and no cursor: malformed."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ShopifyFake(nested_malformed=True)

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert run.attempt_count == 1
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_graphql_errors_on_http_200_fail_terminal(
    session_factory, db_session
) -> None:
    """Top-level GraphQL errors on HTTP 200 = non-retryable provider failure."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    errors = httpx.Response(
        200,
        json={
            "errors": [
                {
                    "message": "Field 'products' doesn't exist on type 'QueryRoot'",
                    "extensions": {"code": "undefinedField", "trace": "x" * 5000},
                }
            ]
        },
    )
    fake = _ShopifyFake(products_overrides={None: errors})

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert run.attempt_count == 1  # non-retryable: deterministic rejection
    # Only the first length-capped message surfaces — never the
    # unrestricted error payload (extensions/trace stay out).
    assert "products" in run.error_detail
    assert "undefinedField" not in run.error_detail
    assert "trace" not in run.error_detail
    assert len(run.error_detail) <= 2000
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_rate_limited_retries_with_backoff(
    session_factory, db_session
) -> None:
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    too_many = httpx.Response(429, json={"errors": "throttled"})
    fake = _ShopifyFake(products_overrides={None: too_many})

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_RETRY_WAIT
    assert run.error_code == ERROR_RATE_LIMITED
    assert run.available_at > datetime.now(UTC)
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_unauthorized_marks_grant_needs_reauth(
    session_factory, db_session
) -> None:
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    unauthorized = httpx.Response(401, json={"errors": "invalid access token"})
    fake = _ShopifyFake(products_overrides={None: unauthorized})

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_GRANT_AUTH_FAILED
    grant = await db_session.get(IntegrationOAuthGrant, grant_id)
    assert grant.status == GRANT_STATUS_NEEDS_REAUTH
    events = list(
        (
            await db_session.scalars(
                select(IntegrationEvent).where(
                    IntegrationEvent.workspace_id == workspace_id,
                    IntegrationEvent.event_type == EVENT_INTEGRATION_REAUTH_REQUIRED,
                )
            )
        ).all()
    )
    assert len(events) == 1
    assert _OFFLINE_TOKEN not in json.dumps(events[0].payload)


@pytest.mark.asyncio
async def test_shopify_hostile_account_ref_fails_closed(
    session_factory, db_session
) -> None:
    """A non-canonical account_ref never reaches a request (SSRF fail-closed)."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(
        db_session,
        account_ref="volt-city.myshopify.com.evil.com",
        mapping_ref="volt-city.myshopify.com.evil.com",
    )
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )

    def fail(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may leave for a hostile shop host")

    await _worker(session_factory, httpx.MockTransport(fail)).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_FAILED
    assert run.error_code == ERROR_PROVIDER_API
    assert await _artifacts(db_session, run.id) == []


@pytest.mark.asyncio
async def test_shopify_offline_token_never_refreshed(
    session_factory, db_session
) -> None:
    """token_expires_at=None is NOT near-expiry for a non-refreshable grant."""
    workspace_id, project_id, grant_id, connection_id = await _seed_graph(db_session)
    run = await enqueue_sync_run(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    fake = _ShopifyFake()

    await _worker(session_factory, fake.mock_transport()).run_until_idle()

    await db_session.refresh(run)
    assert run.status == TASK_STATUS_SUCCEEDED
    # The grant row is untouched: same encrypted token, still no expiry.
    grant = await db_session.get(IntegrationOAuthGrant, grant_id)
    assert decrypt_secret(grant.access_token_encrypted) == _OFFLINE_TOKEN
    assert grant.token_expires_at is None
    # Every provider call carried the ORIGINAL offline token.
    assert set(fake.token_headers) == {_OFFLINE_TOKEN}
    assert run.status == TASK_STATUS_SUCCEEDED
