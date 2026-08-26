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
