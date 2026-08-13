from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.agent.gateway import FakeModelGateway
from app.domain.agent.service import claim_task, execute_claimed_task


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 202
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login.status_code == 200


async def _project(client: httpx.AsyncClient, name: str = "Agent Project") -> str:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "brand_name": name,
            "website_url": f"https://{name.casefold().replace(' ', '-')}.example",
            "industry": "Education",
            "country_code": "IN",
            "language_code": "en-IN",
            "benchmark_mode": "consumer_like",
            "default_repetitions": 1,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


@pytest.mark.asyncio
async def test_task_is_queued_and_replayed_idempotently(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "bounded-agent@example.com")
    project_id = await _project(client)
    body = {
        "project_id": project_id,
        "task_type": "build_roadmap",
        "objective": "Build a roadmap from current persisted evidence.",
    }
    first = await client.post(
        "/api/v1/agent/tasks", json=body, headers={"Idempotency-Key": "roadmap-1"}
    )
    assert first.status_code == 201, first.text
    assert first.json()["status"] == "queued"
    assert first.json()["attempts"] == []
    replay = await client.post(
        "/api/v1/agent/tasks", json=body, headers={"Idempotency-Key": "roadmap-1"}
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_only_fixed_tasks_and_minimal_contract_are_accepted(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "bounded-contract@example.com")
    project_id = await _project(client)
    removed_task = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "generate_draft",
            "objective": "Generate content",
        },
        headers={"Idempotency-Key": "removed"},
    )
    assert removed_task.status_code == 422
    extra_field = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Explain evidence",
            "conversation_id": str(uuid.uuid4()),
        },
        headers={"Idempotency-Key": "extra"},
    )
    assert extra_field.status_code == 422
    assert (await client.get("/api/v1/agent/capabilities")).status_code == 404
    assert (await client.get("/api/v1/agent/conversations")).status_code == 404


@pytest.mark.asyncio
async def test_cancel_and_workspace_isolation(client: httpx.AsyncClient) -> None:
    await _register(client, "agent-owner@example.com")
    project_id = await _project(client)
    created = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Explain persisted evidence.",
        },
        headers={"Idempotency-Key": "cancel-1"},
    )
    run_id = created.json()["id"]
    cancelled = await client.post(
        f"/api/v1/agent/tasks/{run_id}/cancel", params={"project_id": project_id}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    owner_cookies = dict(client.cookies)
    client.cookies.clear()
    await _register(client, "agent-outsider@example.com")
    outsider_project = await _project(client, "Outsider")
    client.cookies.clear()
    client.cookies.update(owner_cookies)
    response = await client.get(
        "/api/v1/agent/tasks", params={"project_id": outsider_project}
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_worker_persists_canonical_attempts_and_minimal_result(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "agent-worker@example.com")
    project_id = await _project(client)
    created = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Explain the latest persisted evidence.",
        },
        headers={"Idempotency-Key": "worker-1"},
    )
    run_id = created.json()["id"]
    gateway = FakeModelGateway(
        '{"answer":"No evidence is available yet.","limitations":[]}'
    )
    async with session_factory() as session:
        claimed = await claim_task(session, owner="test-worker", lease_seconds=60)
        assert claimed is not None
        assert str(claimed.id) == run_id
        await execute_claimed_task(
            session, run=claimed, owner="test-worker", gateway=gateway
        )

    detail = await client.get(
        f"/api/v1/agent/tasks/{run_id}", params={"project_id": project_id}
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["status"] == "completed"
    assert set(payload["result"]) == {"answer", "limitations", "artifact_refs"}
    assert len(payload["attempts"]) == 4
    assert all(attempt["output_hash"] for attempt in payload["attempts"])
    assert all("output" not in attempt for attempt in payload["attempts"])
