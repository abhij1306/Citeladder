from __future__ import annotations

import uuid

import httpx
import pytest


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201


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
async def test_capability_catalog_exposes_exact_tool_kinds(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "agent-capabilities@example.com")
    response = await client.get("/api/v1/agent/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert {item["task_type"] for item in payload["task_catalog"]} >= {
        "build_roadmap",
        "generate_draft",
        "schedule_audit",
    }
    kinds = {item["name"]: item["kind"] for item in payload["tool_catalog"]}
    assert kinds["opportunities.read_ranked"] == "automatic"
    assert kinds["content.generate_draft"] == "save_content"
    assert kinds["audits.schedule"] == "run_audit"


@pytest.mark.asyncio
async def test_roadmap_run_freezes_context_and_replays_idempotently(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "agent-roadmap@example.com")
    project_id = await _project(client)
    conversation = await client.post(
        "/api/v1/agent/conversations",
        json={"project_id": project_id, "title": "Admissions roadmap"},
    )
    assert conversation.status_code == 201
    body = {
        "project_id": project_id,
        "conversation_id": conversation.json()["id"],
        "task_type": "build_roadmap",
        "objective": "Build a roadmap to improve qualified admissions visibility.",
        "resource_scope": {"journey": "admissions"},
    }
    first = await client.post(
        "/api/v1/agent/tasks", json=body, headers={"Idempotency-Key": "roadmap-1"}
    )
    assert first.status_code == 201, first.text
    payload = first.json()
    assert payload["status"] == "completed"
    assert payload["context"]["manifest"]["quality"]["selected_count"] == 0
    assert payload["context"]["omissions"] == [
        {"section": "site", "reason": "unavailable", "count": 1},
        {"section": "content", "reason": "unavailable", "count": 1},
        {"section": "demand", "reason": "unavailable", "count": 1},
    ]
    assert len(payload["steps"]) == 4
    assert all(step["status"] == "completed" for step in payload["steps"])
    replay = await client.post(
        "/api/v1/agent/tasks", json=body, headers={"Idempotency-Key": "roadmap-1"}
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == payload["id"]


@pytest.mark.asyncio
async def test_task_scope_and_cross_workspace_access_fail_closed(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "agent-isolation@example.com")
    project_id = await _project(client)
    first_workspace_cookies = dict(client.cookies)
    missing = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "create_brief",
            "objective": "Create a brief",
            "resource_scope": {},
        },
        headers={"Idempotency-Key": "brief-missing"},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "agent_task_invalid"

    client.cookies.clear()
    await _register(client, "agent-other-workspace@example.com")
    foreign_project_id = await _project(client, "Foreign Agent Project")
    client.cookies.clear()
    client.cookies.update(first_workspace_cookies)
    foreign = await client.get(
        "/api/v1/agent/tasks", params={"project_id": foreign_project_id}
    )
    assert foreign.status_code == 404
    assert foreign.json()["error"]["code"] == "agent_not_found"

    unknown_project = await client.get(
        "/api/v1/agent/tasks",
        params={"project_id": str(uuid.uuid4())},
    )
    assert unknown_project.status_code == 404
    assert unknown_project.json()["error"]["code"] == "agent_not_found"


@pytest.mark.asyncio
async def test_save_content_is_a_server_enforced_decision(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "agent-decision@example.com")
    project_id = await _project(client)
    response = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "generate_draft",
            "objective": "Generate the selected draft",
            "resource_scope": {"brief_id": str(uuid.uuid4())},
        },
        headers={"Idempotency-Key": "draft-decision"},
    )
    assert response.status_code == 201
    run = response.json()
    assert run["status"] == "awaiting_user"
    assert run["steps"][0]["tool_kind"] == "save_content"
    assert run["steps"][0]["status"] == "awaiting_user"

    declined = await client.post(
        f"/api/v1/agent/tasks/{run['id']}/decision",
        params={"project_id": project_id},
        json={"decision": "save_content", "confirmed": False},
    )
    assert declined.status_code == 200
    assert declined.json()["status"] == "partially_completed"
    assert declined.json()["decisions"][0]["confirmed"] is False
