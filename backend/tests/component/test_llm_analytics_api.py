"""Component contracts for the focused persisted AI Referrals endpoint."""

from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest

WINDOW = (date(2026, 7, 20), date(2026, 7, 22))


async def _register(client: httpx.AsyncClient, email: str) -> None:
    assert (
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "password123"}
        )
    ).status_code == 202
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "password123"}
        )
    ).status_code == 200


async def _create_project(client: httpx.AsyncClient) -> tuple[str, str]:
    response = await client.post("/api/v1/projects", json={"name": "AI Referrals"})
    assert response.status_code == 201
    body = response.json()
    return body["id"], body["workspace_id"]


@pytest.mark.asyncio
async def test_ai_referrals_requires_auth_and_legacy_routes_are_absent(
    client: httpx.AsyncClient,
) -> None:
    project_id = uuid.uuid4()
    endpoint = f"/api/v1/projects/{project_id}/ai-referrals"
    assert (await client.get(endpoint)).status_code == 401
    # Pre-launch rename: no compatibility endpoint may keep the obsolete
    # mixed visibility/referral projection alive.
    assert (
        await client.get(f"/api/v1/projects/{project_id}/llm-analytics")
    ).status_code == 404


@pytest.mark.asyncio
async def test_ai_referrals_empty_projection_and_workspace_isolation(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "ai-referrals-owner@example.com")
    project_id, _ = await _create_project(client)
    endpoint = f"/api/v1/projects/{project_id}/ai-referrals"

    response = await client.get(endpoint)
    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == project_id
    assert body["referral_volume"] == []
    assert body["referral_share"] == []
    assert body["sources"] == []

    client.cookies.clear()
    await _register(client, "ai-referrals-outsider@example.com")
    assert (await client.get(endpoint)).status_code == 404
