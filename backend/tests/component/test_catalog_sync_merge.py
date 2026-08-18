"""Component tests for the §9.2 catalog merge (feed row -> Product).

Exercises ``merge_catalog_row`` against a live Postgres schema: the four
identity outcomes (create / adopt / update / duplicate-across-connections),
alias + absent-attribute preservation, deterministic variant identity
(SKU is the key, the opaque variant ref is provenance), the never-delete
contract, and Default Title normalization.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import (
    FEED_RULE_DUPLICATE_SKU_ACROSS_CONNECTIONS,
    FEED_SEVERITY_ERROR,
)
from app.core.config.integrations_contracts import (
    GRANT_STATUS_CONNECTED,
)
from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_PRODUCTS,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_TRANSPORT_SHOPIFY,
)
from app.core.security import encrypt_secret
from app.domain.commerce.catalog import (
    MERGE_OUTCOME_ADOPTED,
    MERGE_OUTCOME_CREATED,
    MERGE_OUTCOME_DUPLICATE,
    MERGE_OUTCOME_MISSING_SKU,
    MERGE_OUTCOME_UPDATED,
    merge_catalog_row,
)
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product
from app.models.project import Project
from app.models.workspace import Workspace

_SHOP = "volt-city.myshopify.com"


def _catalog_row(**overrides: object) -> dict:
    row: dict = {
        "product_ref": "gid://shopify/Product/p1",
        "variant_ref": "gid://shopify/ProductVariant/v1",
        "sku": "VC-500",
        "barcode": "012345678905",
        "title": "VoltCity 500",
        "variant_title": "Default Title",
        "description": "The VoltCity 500 portable charger",
        "vendor": "VoltCity",
        "product_type": "Chargers",
        "status": "ACTIVE",
        "url": "https://volt-city.example/products/voltcity-500",
        "price": "64.99",
        "currency": "USD",
        "inventory_quantity": 12,
        "updated_at": "2026-07-21T09:00:00Z",
    }
    row.update(overrides)
    return row


class _Graph:
    def __init__(
        self,
        *,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        connection: IntegrationConnection,
        run: IntegrationSyncRun,
        artifact: IntegrationImportArtifact,
        mapping: IntegrationPropertyMapping,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.connection = connection
        self.run = run
        self.artifact = artifact
        self.mapping = mapping


async def _seed_graph(db_session: AsyncSession, *, label: str = "shop") -> _Graph:
    workspace = Workspace(name=f"Acme {label}")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme Site")
    db_session.add(project)
    await db_session.flush()
    grant = IntegrationOAuthGrant(
        workspace_id=workspace.id,
        transport=INTEGRATION_TRANSPORT_SHOPIFY,
        access_token_encrypted=encrypt_secret("shpat_x"),  # pragma: allowlist secret
        refresh_token_encrypted="",
        token_expires_at=None,
        granted_scopes=["read_products"],
        status=GRANT_STATUS_CONNECTED,
    )
    db_session.add(grant)
    await db_session.flush()
    connection = IntegrationConnection(
        workspace_id=workspace.id,
        grant_id=grant.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        label=label,
        account_ref=_SHOP,
    )
    db_session.add(connection)
    await db_session.flush()
    mapping = IntegrationPropertyMapping(
        workspace_id=workspace.id,
        connection_id=connection.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        property_ref=_SHOP,
        project_id=project.id,
        status="active",
    )
    db_session.add(mapping)
    run = IntegrationSyncRun(
        connection_id=connection.id,
        workspace_id=workspace.id,
        sync_kind="on_demand",
        window_start=datetime(2026, 7, 20, tzinfo=UTC).date(),
        window_end=datetime(2026, 7, 22, tzinfo=UTC).date(),
        resync_seq=1,
        idempotency_key=f"catalog-merge-test-{label}",
    )
    db_session.add(run)
    await db_session.flush()
    artifact = IntegrationImportArtifact(
        sync_run_id=run.id,
        connection_id=connection.id,
        workspace_id=workspace.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        dataset=DATASET_SHOPIFY_PRODUCTS,
        query_snapshot={},
        payload_hash="0" * 64,
        row_count=1,
        payload={"rows": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    )
    db_session.add(artifact)
    await db_session.commit()
    return _Graph(
        workspace_id=workspace.id,
        project_id=project.id,
        connection=connection,
        run=run,
        artifact=artifact,
        mapping=mapping,
    )


async def _merge(db_session: AsyncSession, graph: _Graph, row: dict):
    return await merge_catalog_row(
        db_session,
        mapping=graph.mapping,
        connection=graph.connection,
        run=graph.run,
        artifact=graph.artifact,
        row=row,
    )


async def _product(db_session: AsyncSession, project_id: uuid.UUID, sku: str):
    return await db_session.scalar(
        select(Product).where(Product.project_id == project_id, Product.sku == sku)
    )


@pytest.mark.asyncio
async def test_create_stamps_synced_origin_and_provenance(db_session) -> None:
    graph = await _seed_graph(db_session)

    result = await _merge(db_session, graph, _catalog_row())

    assert result.outcome == MERGE_OUTCOME_CREATED
    assert result.finding is None
    product = result.product
    assert product is not None
    assert product.origin == "synced"
    assert product.connection_id == graph.connection.id
    assert product.external_item_ref == "gid://shopify/ProductVariant/v1"
    assert product.last_seen_sync_run_id == graph.run.id
    # Platform fields applied; "Default Title" normalized off the name.
    assert product.name == "VoltCity 500"
    assert product.price == Decimal("64.99")
    assert product.currency == "USD"
    assert product.url == "https://volt-city.example/products/voltcity-500"
    assert product.attributes == {
        "gtin": "012345678905",
        "description": "The VoltCity 500 portable charger",
        "vendor": "VoltCity",
        "product_type": "Chargers",
        "status": "ACTIVE",
        "availability": "in_stock",
    }
    assert product.variants == [
        {"name": "VoltCity 500", "sku": "VC-500", "price": 64.99}
    ]


@pytest.mark.asyncio
async def test_named_variant_builds_title_slash_variant_name(db_session) -> None:
    graph = await _seed_graph(db_session)

    result = await _merge(db_session, graph, _catalog_row(variant_title="500W / Black"))

    assert result.product is not None
    assert result.product.name == "VoltCity 500 / 500W / Black"
    assert result.product.variants[0]["name"] == "500W / Black"


@pytest.mark.asyncio
async def test_adopt_manual_product_preserves_aliases_and_absent_attributes(
    db_session,
) -> None:
    graph = await _seed_graph(db_session)
    manual = Product(
        project_id=graph.project_id,
        sku="VC-500",
        name="My Manual Name",
        origin="manual",
        price=Decimal("10.00"),
        currency="EUR",
        aliases=["VoltCity Charger", "VC500"],
        attributes={"custom_key": "keep-me", "vendor": "old-vendor"},
    )
    db_session.add(manual)
    await db_session.commit()

    result = await _merge(db_session, graph, _catalog_row(description=""))

    assert result.outcome == MERGE_OUTCOME_ADOPTED
    assert result.product is not None
    assert result.product.id == manual.id
    assert result.product.origin == "synced"
    assert result.product.connection_id == graph.connection.id
    # Platform fields overwrite.
    assert result.product.name == "VoltCity 500"
    assert result.product.price == Decimal("64.99")
    assert result.product.currency == "USD"
    # Aliases are NEVER platform-owned.
    assert result.product.aliases == ["VoltCity Charger", "VC500"]
    # Present keys overwrite; absent-from-feed keys survive; custom keys
    # survive (description was absent from this row).
    assert result.product.attributes["custom_key"] == "keep-me"
    assert result.product.attributes["vendor"] == "VoltCity"
    assert "description" not in result.product.attributes


@pytest.mark.asyncio
async def test_update_same_connection_reapplies_platform_fields(db_session) -> None:
    graph = await _seed_graph(db_session)
    first = await _merge(db_session, graph, _catalog_row())
    assert first.product is not None

    second = await _merge(
        db_session,
        graph,
        _catalog_row(
            price="69.99",
            inventory_quantity=0,
            variant_ref="gid://shopify/ProductVariant/v1",
        ),
    )

    assert second.outcome == MERGE_OUTCOME_UPDATED
    assert second.product is not None
    assert second.product.id == first.product.id
    assert second.product.price == Decimal("69.99")
    assert second.product.attributes["availability"] == "out_of_stock"


@pytest.mark.asyncio
async def test_duplicate_sku_across_connections_never_steals_the_row(
    db_session,
) -> None:
    owner_graph = await _seed_graph(db_session, label="owner shop")
    feed_graph = await _seed_graph(db_session, label="feed shop")
    # The feed mapping points at the SAME project catalog as the owner.
    feed_graph.mapping.project_id = owner_graph.project_id
    await db_session.commit()
    owner = await _merge(db_session, owner_graph, _catalog_row())
    assert owner.product is not None

    result = await _merge(
        db_session, feed_graph, _catalog_row(price="1.00", vendor="Evil")
    )

    assert result.outcome == MERGE_OUTCOME_DUPLICATE
    assert result.product is None
    assert result.finding is not None
    assert result.finding.rule_id == FEED_RULE_DUPLICATE_SKU_ACROSS_CONNECTIONS
    assert result.finding.severity == FEED_SEVERITY_ERROR
    assert result.finding.evidence == {
        "sku": "VC-500",
        "feed_connection_id": str(feed_graph.connection.id),
        "owner_connection_id": str(owner_graph.connection.id),
        "variant_ref": "gid://shopify/ProductVariant/v1",
    }
    # The owner's row is UNTOUCHED (no mutation, no provenance flip).
    product = await _product(db_session, owner_graph.project_id, "VC-500")
    assert product is not None
    assert product.connection_id == owner_graph.connection.id
    assert product.price == Decimal("64.99")
    assert product.attributes["vendor"] == "VoltCity"


@pytest.mark.asyncio
async def test_missing_sku_creates_no_product_and_no_finding(db_session) -> None:
    graph = await _seed_graph(db_session)

    result = await _merge(db_session, graph, _catalog_row(sku="  "))

    assert result.outcome == MERGE_OUTCOME_MISSING_SKU
    assert result.product is None
    assert result.finding is None
    assert await _product(db_session, graph.project_id, "") is None


@pytest.mark.asyncio
async def test_variant_identity_is_deterministic_by_sku(db_session) -> None:
    """A re-listed variant (new opaque id, same SKU) keeps its Product row."""
    graph = await _seed_graph(db_session)
    first = await _merge(db_session, graph, _catalog_row())
    assert first.product is not None

    relisted = await _merge(
        db_session,
        graph,
        _catalog_row(
            product_ref="gid://shopify/Product/p9",
            variant_ref="gid://shopify/ProductVariant/v9",
        ),
    )

    assert relisted.outcome == MERGE_OUTCOME_UPDATED
    assert relisted.product is not None
    assert relisted.product.id == first.product.id  # keyed (project, sku)
    assert relisted.product.external_item_ref == "gid://shopify/ProductVariant/v9"


@pytest.mark.asyncio
async def test_products_absent_from_the_feed_are_never_touched(db_session) -> None:
    graph = await _seed_graph(db_session)
    stale = Product(
        project_id=graph.project_id,
        sku="VC-OLD",
        name="Discontinued",
        origin="synced",
        connection_id=graph.connection.id,
        external_item_ref="gid://shopify/ProductVariant/old",
        last_seen_sync_run_id=None,
        attributes={"vendor": "VoltCity"},
    )
    db_session.add(stale)
    await db_session.commit()

    await _merge(db_session, graph, _catalog_row())

    untouched = await _product(db_session, graph.project_id, "VC-OLD")
    assert untouched is not None
    assert untouched.name == "Discontinued"
    # No delete, no update: staleness stays inferable from
    # last_seen_sync_run_id (still predating this run).
    assert untouched.last_seen_sync_run_id is None
    assert untouched.attributes == {"vendor": "VoltCity"}
