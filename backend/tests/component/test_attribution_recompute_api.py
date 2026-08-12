"""Project-scoped manual Commerce attribution recompute API."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.models.analytics import AnalyticsTask
from app.models.integrations import IntegrationPropertyMapping
from tests.component.analytics_helpers import DEFAULT_WINDOW, seed_ga4_import


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


async def _create_project(client: httpx.AsyncClient) -> dict:
    response = await client.post(
        "/api/v1/projects", json={"name": "Attribution recompute"}
    )
    assert response.status_code == 201
    return response.json()


async def _seed_completed_window(db_session, project: dict) -> None:
    seed = await seed_ga4_import(
        db_session,
        workspace_id=uuid.UUID(project["workspace_id"]),
        project_id=uuid.UUID(project["id"]),
        window=DEFAULT_WINDOW,
    )
    db_session.add(
        IntegrationPropertyMapping(
            workspace_id=seed.workspace_id,
            connection_id=seed.connection_id,
            provider=seed.provider,
            property_ref=seed.property_ref,
            project_id=seed.project_id,
            status="active",
        )
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_recompute_allocates_fresh_pollable_revisions(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "recompute@example.com")
    project = await _create_project(client)
    await _seed_completed_window(db_session, project)
    path = f"/api/v1/projects/{project['id']}/commerce/attribution/recompute"

    first = await client.post(path)
    second = await client.post(path)
    assert first.status_code == second.status_code == 202
    first_body, second_body = first.json(), second.json()
    assert first_body["task_id"] != second_body["task_id"]
    assert first_body["status"] == second_body["status"] == "queued"

    first_task = await db_session.get(AnalyticsTask, uuid.UUID(first_body["task_id"]))
    second_task = await db_session.get(AnalyticsTask, uuid.UUID(second_body["task_id"]))
    assert first_task is not None and second_task is not None
    assert first_task.payload == {
        "window_start": DEFAULT_WINDOW[0].isoformat(),
        "window_end": DEFAULT_WINDOW[1].isoformat(),
        "resync_seq": 0,
    }
    assert second_task.payload["resync_seq"] == 1

    poll = await client.get(f"{path}/{first_body['task_id']}")
    assert poll.status_code == 200
    assert poll.json() == first_body


@pytest.mark.asyncio
async def test_recompute_rejects_bad_window_and_cross_workspace_task(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "recompute-owner@example.com")
    project = await _create_project(client)
    await _seed_completed_window(db_session, project)
    path = f"/api/v1/projects/{project['id']}/commerce/attribution/recompute"
    invalid = await client.post(path, json={"from": "2026-07-22", "to": "2026-07-20"})
    assert invalid.status_code == 422
    task = await client.post(path)
    assert task.status_code == 202

    await client.post("/api/v1/auth/logout")
    await _register(client, "recompute-attacker@example.com")
    forbidden = await client.get(f"{path}/{task.json()['task_id']}")
    assert forbidden.status_code == 404
