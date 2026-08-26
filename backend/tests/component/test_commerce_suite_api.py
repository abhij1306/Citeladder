from __future__ import annotations

import httpx
import pytest


async def _register(client: httpx.AsyncClient, email: str) -> None:
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 202
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 200


async def _project(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/projects",
        json={"name": "Commerce", "brand_name": "Acme", "competitors": []},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_catalog_import_is_idempotent_with_row_outcomes(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-import@example.com")
    project = await _project(client)
    url = f"/api/v1/projects/{project['id']}/commerce/catalog/import"
    content = (
        "canonical_url,name,brand,price,currency,sku,category\n"
        "https://shop.example/products/one,Acme One,Acme,19.00,USD,A-1,Shoes\n"
    )
    payload = {
        "filename": "catalog.csv",
        "content_type": "text/csv",
        "content": content,
    }
    first = await client.post(url, json=payload)
    assert first.status_code == 201
    assert first.json()["created"] == 1
    assert first.json()["row_outcomes"][0]["status"] == "created"
    repeated = await client.post(url, json=payload)
    assert repeated.status_code == 201
    assert repeated.json() == first.json()

    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    assert catalog.status_code == 200
    assert catalog.json()["products"][0]["canonical_url"] == (
        "https://shop.example/products/one"
    )
    assert catalog.json()["products"][0]["field_sources"]["name"]["kind"] == "csv"


@pytest.mark.asyncio
async def test_commerce_catalog_is_workspace_isolated(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-owner@example.com")
    project = await _project(client)
    await _register(client, "commerce-outsider@example.com")
    response = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_competitor_discovery_deduplicates_only_within_one_request(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-discovery@example.com")
    project = await _project(client)
    import_response = await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,brand\n"
                "https://shop.example/products/one,Acme One,Acme\n"
            ),
        },
    )
    assert import_response.status_code == 201
    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    product_id = catalog.json()["products"][0]["id"]
    url = f"/api/v1/projects/{project['id']}/commerce/competitors/discover"
    target = {"kind": "product", "id": product_id}

    first = await client.post(url, json={"targets": [target, target]})
    second = await client.post(url, json={"targets": [target]})

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["task_ids"][0] == first.json()["task_ids"][1]
    assert second.json()["task_ids"][0] != first.json()["task_ids"][0]


@pytest.mark.asyncio
async def test_catalog_edit_clears_optional_identifiers_to_null(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-edit@example.com")
    project = await _project(client)
    await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,sku,gtin,mpn\n"
                "https://shop.example/products/one,Acme One,A-1,1234567890123,M-1\n"
            ),
        },
    )
    catalog = await client.get(f"/api/v1/projects/{project['id']}/commerce/catalog")
    product_id = catalog.json()["products"][0]["id"]

    response = await client.patch(
        f"/api/v1/projects/{project['id']}/commerce/catalog/products/{product_id}",
        json={"sku": None, "gtin": None, "mpn": None},
    )

    assert response.status_code == 200
    assert response.json()["sku"] is None
    assert response.json()["gtin"] is None
    assert response.json()["mpn"] is None


@pytest.mark.asyncio
async def test_category_correction_is_persisted_and_workspace_isolated(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "commerce-category-owner@example.com")
    project = await _project(client)
    await client.post(
        f"/api/v1/projects/{project['id']}/commerce/catalog/import",
        json={
            "filename": "catalog.csv",
            "content_type": "text/csv",
            "content": (
                "canonical_url,name,category\n"
                "https://shop.example/products/one,Acme One,Shoes\n"
            ),
        },
    )
    catalog_url = f"/api/v1/projects/{project['id']}/commerce/catalog"
    category_id = (await client.get(catalog_url)).json()["categories"][0]["id"]

    response = await client.patch(
        f"{catalog_url}/categories/{category_id}",
        json={"name": "Trail shoes", "role": "leaf"},
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Trail shoes"
    assert response.json()["role"] == "leaf"
    assert response.json()["field_sources"]["name"]["kind"] == "edit"
    assert (await client.get(catalog_url)).json()["categories"][0]["name"] == (
        "Trail shoes"
    )

    await _register(client, "commerce-category-outsider@example.com")
    outsider = await client.patch(
        f"{catalog_url}/categories/{category_id}", json={"name": "Stolen"}
    )
    assert outsider.status_code == 404
