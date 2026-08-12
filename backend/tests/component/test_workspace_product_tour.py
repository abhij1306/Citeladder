from __future__ import annotations

import httpx
import pytest

from app.core.config.product_tour import PRODUCT_TOUR_VERSION


async def _register(client: httpx.AsyncClient, email: str) -> str:
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
    return (await client.get("/api/v1/workspaces")).json()[0]["id"]


@pytest.mark.asyncio
async def test_product_tour_progress_resume_skip_and_replay(
    client: httpx.AsyncClient,
) -> None:
    workspace_id = await _register(client, "tour@example.com")
    url = f"/api/v1/workspaces/{workspace_id}/product-tour"

    initial = (await client.get(url)).json()
    assert initial == {
        "workspace_id": workspace_id,
        "version": PRODUCT_TOUR_VERSION,
        "status": "not_started",
        "step_id": None,
        "started_at": None,
        "completed_at": None,
    }

    progress = await client.patch(
        url,
        json={
            "version": PRODUCT_TOUR_VERSION,
            "status": "in_progress",
            "step_id": "dashboard-summaries",
        },
    )
    assert progress.status_code == 200
    started_at = progress.json()["started_at"]
    assert started_at is not None
    assert (await client.get(url)).json()["step_id"] == "dashboard-summaries"

    skipped = await client.patch(
        url,
        json={"version": PRODUCT_TOUR_VERSION, "status": "skipped"},
    )
    assert skipped.json()["status"] == "skipped"
    assert skipped.json()["completed_at"] is not None

    replay = await client.patch(
        url,
        json={
            "version": PRODUCT_TOUR_VERSION,
            "status": "in_progress",
            "step_id": "project-switcher",
        },
    )
    assert replay.json()["status"] == "in_progress"
    assert replay.json()["completed_at"] is None
    assert replay.json()["started_at"] == started_at


@pytest.mark.asyncio
async def test_product_tour_rejects_stale_version(
    client: httpx.AsyncClient,
) -> None:
    workspace_id = await _register(client, "tour-version@example.com")
    url = f"/api/v1/workspaces/{workspace_id}/product-tour"
    response = await client.patch(
        url,
        json={"version": "older-tour", "status": "completed"},
    )
    assert response.status_code == 422

    current = (await client.get(url)).json()
    assert current["version"] == PRODUCT_TOUR_VERSION
    assert current["status"] == "not_started"
    assert current["started_at"] is None
    assert current["completed_at"] is None


@pytest.mark.asyncio
async def test_product_tour_rejects_foreign_workspace(
    client: httpx.AsyncClient,
) -> None:
    foreign_workspace_id = await _register(client, "tour-owner@example.com")
    client.cookies.clear()
    await _register(client, "tour-other@example.com")

    url = f"/api/v1/workspaces/{foreign_workspace_id}/product-tour"
    assert (await client.get(url)).status_code == 404
    response = await client.patch(
        url,
        json={
            "version": PRODUCT_TOUR_VERSION,
            "status": "in_progress",
            "step_id": "project-switcher",
        },
    )
    assert response.status_code == 404
