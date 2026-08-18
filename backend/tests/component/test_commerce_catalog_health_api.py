"""Persisted-only Commerce catalog-health API coverage."""

from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest

from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_PRODUCTS,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_TRANSPORT_SHOPIFY,
)
from app.core.security import encrypt_secret
from app.models.commerce import FeedIssue
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


async def _create_project(client: httpx.AsyncClient, name: str) -> dict:
    response = await client.post("/api/v1/projects", json={"name": name})
    assert response.status_code == 201
    return response.json()


async def _seed_shopify_health(
    db_session, project: dict
) -> tuple[uuid.UUID, uuid.UUID]:
    workspace_id = uuid.UUID(project["workspace_id"])
    project_id = uuid.UUID(project["id"])
    grant = IntegrationOAuthGrant(
        workspace_id=workspace_id,
        transport=INTEGRATION_TRANSPORT_SHOPIFY,
        access_token_encrypted=encrypt_secret("test-shopify-token"),
        refresh_token_encrypted="",
        granted_scopes=["read_products", "read_orders"],
        status="connected",
    )
    db_session.add(grant)
    await db_session.flush()
    connection = IntegrationConnection(
        workspace_id=workspace_id,
        grant_id=grant.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        label="Acme shop",
        account_ref="acme.myshopify.com",
    )
    db_session.add(connection)
    await db_session.flush()
    db_session.add(
        IntegrationPropertyMapping(
            workspace_id=workspace_id,
            connection_id=connection.id,
            provider=INTEGRATION_PROVIDER_SHOPIFY,
            property_ref="acme.myshopify.com",
            project_id=project_id,
            status="active",
        )
    )
    old_run = IntegrationSyncRun(
        connection_id=connection.id,
        workspace_id=workspace_id,
        sync_kind="on_demand",
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 2),
        resync_seq=0,
        idempotency_key=f"health-old-{uuid.uuid4()}",
        status="succeeded",
    )
    latest_run = IntegrationSyncRun(
        connection_id=connection.id,
        workspace_id=workspace_id,
        sync_kind="on_demand",
        window_start=date(2026, 7, 3),
        window_end=date(2026, 7, 4),
        resync_seq=0,
        idempotency_key=f"health-latest-{uuid.uuid4()}",
        status="failed",
        error_code="shopify_rate_limited",
    )
    db_session.add_all([old_run, latest_run])
    await db_session.flush()
    # Make ordering deterministic regardless of database timestamp precision.
    latest_run.created_at = old_run.created_at.replace(year=old_run.created_at.year + 1)
    old_artifact = IntegrationImportArtifact(
        sync_run_id=old_run.id,
        connection_id=connection.id,
        workspace_id=workspace_id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        dataset=DATASET_SHOPIFY_PRODUCTS,
        query_snapshot={},
        payload_hash="b" * 64,
        row_count=2,
        payload={"rows": []},
    )
    artifact = IntegrationImportArtifact(
        sync_run_id=latest_run.id,
        connection_id=connection.id,
        workspace_id=workspace_id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        dataset=DATASET_SHOPIFY_PRODUCTS,
        query_snapshot={},
        payload_hash="a" * 64,
        row_count=7,
        payload={"rows": []},
    )
    db_session.add_all([old_artifact, artifact])
    await db_session.flush()
    warning_product = Product(
        project_id=project_id,
        sku="SKU-WARN",
        name="Warning product",
        origin="synced",
        connection_id=connection.id,
        external_item_ref="gid://shopify/ProductVariant/warn",
        last_seen_sync_run_id=latest_run.id,
    )
    unavailable_product = Product(
        project_id=project_id,
        sku="SKU-OLD",
        name="Old product",
        origin="synced",
        connection_id=connection.id,
        external_item_ref="gid://shopify/ProductVariant/old",
        last_seen_sync_run_id=old_run.id,
    )
    healthy_product = Product(
        project_id=project_id,
        sku="SKU-HEALTHY",
        name="Healthy product",
        origin="synced",
        connection_id=connection.id,
        external_item_ref="gid://shopify/ProductVariant/healthy",
        last_seen_sync_run_id=latest_run.id,
    )
    unbound_product = Product(
        project_id=project_id,
        sku="SKU-MANUAL",
        name="Manual product",
        origin="manual",
    )
    db_session.add_all(
        [warning_product, unavailable_product, healthy_product, unbound_product]
    )
    await db_session.flush()
    db_session.add(
        FeedIssue(
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=connection.id,
            sync_run_id=latest_run.id,
            external_item_ref=warning_product.external_item_ref,
            product_id=warning_product.id,
            source_artifact_id=artifact.id,
            rule_id="feed.missing_gtin_mpn",
            severity="warning",
            evidence={},
        )
    )
    db_session.add_all(
        [
            FeedIssue(
                workspace_id=workspace_id,
                project_id=project_id,
                connection_id=connection.id,
                sync_run_id=old_run.id,
                external_item_ref=unavailable_product.external_item_ref,
                product_id=unavailable_product.id,
                source_artifact_id=old_artifact.id,
                rule_id="feed.missing_gtin_mpn",
                severity="warning",
                evidence={},
            ),
            FeedIssue(
                workspace_id=workspace_id,
                project_id=project_id,
                connection_id=connection.id,
                sync_run_id=old_run.id,
                external_item_ref="gid://shopify/ProductVariant/old-orphan",
                product_id=None,
                source_artifact_id=old_artifact.id,
                rule_id="feed.missing_sku",
                severity="error",
                evidence={},
            ),
        ]
    )
    db_session.add(
        FeedIssue(
            workspace_id=workspace_id,
            project_id=project_id,
            connection_id=connection.id,
            sync_run_id=latest_run.id,
            external_item_ref="gid://shopify/ProductVariant/absent",
            product_id=None,
            source_artifact_id=artifact.id,
            rule_id="feed.missing_sku",
            severity="error",
            evidence={},
        )
    )
    await db_session.commit()
    return connection.id, latest_run.id


@pytest.mark.asyncio
async def test_catalog_health_projects_latest_sync_and_product_state(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "catalog-health@example.com")
    project = await _create_project(client, "Catalog health")
    connection_id, latest_run_id = await _seed_shopify_health(db_session, project)

    response = await client.get(
        f"/api/v1/projects/{project['id']}/commerce/catalog-health"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project["id"]
    assert body["connections"][0]["connection_id"] == str(connection_id)
    assert body["connections"][0]["latest_sync"] == {
        "sync_run_id": str(latest_run_id),
        "connection_id": str(connection_id),
        "status": "failed",
        "window_start": "2026-07-03",
        "window_end": "2026-07-04",
        "row_count": 7,
        "error_code": "shopify_rate_limited",
        "completed_at": None,
    }
    rows = {row["external_item_ref"]: row for row in body["products"]}
    assert rows["gid://shopify/ProductVariant/warn"]["status"] == "warning"
    assert rows["gid://shopify/ProductVariant/warn"]["rule_ids"] == [
        "feed.missing_gtin_mpn"
    ]
    stale = rows["gid://shopify/ProductVariant/old"]
    assert stale["status"] == "unavailable"
    assert stale["highest_severity"] is None
    assert stale["issue_count"] == 0
    assert stale["rule_ids"] == []
    assert rows["gid://shopify/ProductVariant/healthy"]["status"] == "healthy"
    assert rows["gid://shopify/ProductVariant/absent"]["product_id"] is None
    assert rows["gid://shopify/ProductVariant/absent"]["status"] == "error"
    assert "gid://shopify/ProductVariant/old-orphan" not in rows
    assert "SKU-MANUAL" not in str(body)


@pytest.mark.asyncio
async def test_catalog_health_is_workspace_scoped(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "catalog-owner@example.com")
    foreign = await _create_project(client, "Foreign project")
    await client.post("/api/v1/auth/logout")
    await _register(client, "catalog-attacker@example.com")

    response = await client.get(
        f"/api/v1/projects/{foreign['id']}/commerce/catalog-health"
    )
    assert response.status_code == 404
