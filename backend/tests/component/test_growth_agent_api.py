from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.agent.gateway import FakeModelGateway
from app.domain.agent.service import _public_result, claim_task, execute_claimed_task
from app.models.agent import AgentTaskRun


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


def test_partial_persisted_result_is_normalized_to_the_typed_contract() -> None:
    result = _public_result({"summary": "Earlier summary", "limitations": ["Partial"]})

    assert result is not None
    assert result["summary"] == "Earlier summary"
    assert result["observations"] == []
    assert result["roadmap_items"] == []
    assert result["limitations"] == ["Partial"]
    assert set(result) == {
        "summary",
        "observations",
        "roadmap_items",
        "sources",
        "limitations",
        "artifact_refs",
    }


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
    assert first.json()["result"] is None
    assert "attempts" not in first.json()
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
async def test_unsupported_persisted_task_is_hidden_from_public_reads(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "agent-legacy-task@example.com")
    project_id = await _project(client)
    created = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Legacy task",
        },
        headers={"Idempotency-Key": "legacy-task"},
    )
    run_id = created.json()["id"]
    async with session_factory() as session:
        await session.execute(
            update(AgentTaskRun)
            .where(AgentTaskRun.id == uuid.UUID(run_id))
            .values(task_type="create_brief")
        )
        await session.commit()

    history = await client.get("/api/v1/agent/tasks", params={"project_id": project_id})
    detail = await client.get(
        f"/api/v1/agent/tasks/{run_id}", params={"project_id": project_id}
    )

    assert history.status_code == 200
    assert history.json() == []
    assert detail.status_code == 404


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
        '{"summary":"No persisted evidence is available yet.",'
        '"observations":["Site Health has not produced a snapshot."],'
        '"limitations":[]}'
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
    assert set(payload["result"]) == {
        "summary",
        "observations",
        "roadmap_items",
        "sources",
        "limitations",
        "artifact_refs",
    }
    assert payload["result"]["summary"] == "No persisted evidence is available yet."
    assert payload["result"]["observations"] == [
        "Site Health has not produced a snapshot."
    ]
    assert payload["result"]["roadmap_items"] == []
    assert {source["key"] for source in payload["result"]["sources"]} == {
        "site_health",
        "search_demand",
        "opportunities",
        "ai_visibility",
    }
    assert payload["result"]["artifact_refs"] == []
    assert "attempts" not in payload


@pytest.mark.asyncio
async def test_task_list_is_compact_while_detail_keeps_result_and_provenance(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """History remains cheap and internal evidence is selected-detail only."""
    await _register(client, "agent-list-detail@example.com")
    project_id = await _project(client)
    created = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Explain the latest persisted evidence.",
        },
        headers={"Idempotency-Key": "list-detail-1"},
    )
    run_id = created.json()["id"]
    async with session_factory() as session:
        claimed = await claim_task(
            session, owner="list-detail-worker", lease_seconds=60
        )
        assert claimed is not None
        await execute_claimed_task(
            session, run=claimed, owner="list-detail-worker", gateway=None
        )

    history = await client.get("/api/v1/agent/tasks", params={"project_id": project_id})
    assert history.status_code == 200
    listed = history.json()[0]
    assert listed["id"] == run_id
    assert "result" not in listed
    assert "attempts" not in listed

    detail = await client.get(
        f"/api/v1/agent/tasks/{run_id}", params={"project_id": project_id}
    )
    assert detail.status_code == 200
    assert detail.json()["result"]["summary"]
    assert "attempts" not in detail.json()
