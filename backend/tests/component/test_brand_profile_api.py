"""Component coverage for workspace-scoped BrandProfile compatibility CRUD."""

from __future__ import annotations

import httpx
import pytest


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201


async def _create_project(client: httpx.AsyncClient, name: str = "Acme") -> dict:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": f"{name} visibility",
            "brand_name": name,
            "website_url": "https://acme.example",
            "country_code": "AU",
            "language_code": "en-AU",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_project_creation_provisions_empty_brand_profile(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "profile-create@example.com")
    project = await _create_project(client)
    response = await client.get(f"/api/v1/projects/{project['id']}/brand-profile")
    assert response.status_code == 200
    body = response.json()
    assert body["workspace_id"] == project["workspace_id"]
    assert body["project_id"] == project["id"]
    assert body["description"] == ""
    assert body["products_services"] == []
    assert body["sources"] == {
        "description": None,
        "positioning": None,
        "products_services": None,
        "target_audience": None,
    }


@pytest.mark.asyncio
async def test_manual_upsert_marks_supplied_fields_and_preserves_others(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "profile-upsert@example.com")
    project = await _create_project(client)
    url = f"/api/v1/projects/{project['id']}/brand-profile"
    first = await client.put(
        url,
        json={
            "description": "  A practical retailer.  ",
            "positioning": "Value-priced family basics",
            "products_services": [" Clothing ", "Homewares", "clothing"],
        },
    )
    assert first.status_code == 200
    body = first.json()
    assert body["description"] == "A practical retailer."
    assert body["products_services"] == ["Clothing", "Homewares"]
    assert body["sources"]["description"] == "manual"
    assert body["sources"]["target_audience"] is None
    second = await client.put(
        url, json={"target_audience": "Budget-conscious families"}
    )
    assert second.status_code == 200
    assert second.json()["positioning"] == "Value-priced family basics"
    assert second.json()["sources"]["target_audience"] == "manual"


@pytest.mark.asyncio
async def test_brand_profile_is_workspace_isolated(client: httpx.AsyncClient) -> None:
    await _register(client, "profile-owner@example.com")
    project = await _create_project(client)
    url = f"/api/v1/projects/{project['id']}/brand-profile"
    client.cookies.clear()
    await _register(client, "profile-other@example.com")
    assert (await client.get(url)).status_code == 404
    assert (
        await client.put(url, json={"description": "cross-tenant write"})
    ).status_code == 404


@pytest.mark.asyncio
async def test_legacy_profile_suggestion_route_is_retired(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "profile-retired@example.com")
    project = await _create_project(client)
    response = await client.post(
        f"/api/v1/projects/{project['id']}/brand-profile/suggest",
        json={},
    )
    assert response.status_code == 404
