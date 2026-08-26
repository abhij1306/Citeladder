"""Retained Content contract: grounded generation, durable queue, provenance."""

from __future__ import annotations

import json
import uuid

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.content import (
    CONTENT_GENERATOR_VERSION,
    CONTENT_SKILL_CATALOG_VERSION,
    content_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.models.content import ContentGeneration, ContentGenerationAttempt
from app.models.project import Project
from app.workers.content_worker import ContentWorker

_CANARY_SECRET = "never-a-real-provider-secret"
_FIXTURE_MODEL = "fixture-model"
_REF_ID = "b" * 64
_CONTEXT = {
    "status": "included",
    "version": "grounding-envelope-v2",
    "allowed_facts": [],
    "prohibited_claims": [],
    "source_refs": [
        {
            "source_ref_id": _REF_ID,
            "source_kind": "crawl_fragment",
            "source_id": "33333333-3333-4333-8333-333333333333",
            "field_or_fragment": "Facts.",
            "observed_at": "2026-07-15T00:00:00Z",
            "origin": "crawl_observed",
            "review_state": "observed_untrusted",
        }
    ],
    "omissions": [],
    "budget": {"selected_count": 1, "omitted_count": 0, "character_count": 6},
}


@pytest.fixture(autouse=True)
def _configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    # Tests disable dotenv globally. This additionally pins an unresolvable
    # endpoint and an in-memory MockTransport, so no provider can be contacted.
    monkeypatch.setattr(content_settings, "provider", "gmi")
    monkeypatch.setattr(content_settings, "gmicloud_api_key", SecretStr(_CANARY_SECRET))
    monkeypatch.setattr(
        content_settings, "gmicloud_base_url", "https://provider.invalid/v1"
    )
    monkeypatch.setattr(content_settings, "gmicloud_model", _FIXTURE_MODEL)


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


async def _create_project(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": "Content Project",
            "brand_name": "Acme",
            "website_url": "https://acme.example",
            "country_code": "AU",
            "language_code": "en-AU",
            "benchmark_mode": "consumer_like",
            "default_repetitions": 1,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


async def _seed_generation(
    session_factory: async_sessionmaker[AsyncSession], project_id: str
) -> str:
    async with session_factory() as session:
        project = await session.get(Project, uuid.UUID(project_id))
        assert project is not None
        row = ContentGeneration(
            workspace_id=project.workspace_id,
            project_id=project.id,
            prompt="Write an Acme page.",
            output_type="website_page",
            skill_id="article",
            skill_version="content-v1",
            grounding_status="included",
            grounding_envelope=_CONTEXT,
            request_fingerprint="a" * 64,
            idempotency_key=str(uuid.uuid4()),
            provider="gmi",
            requested_model=content_settings.resolved_model,
            generator_version="content-v1",
        )
        session.add(row)
        await session.commit()
        return str(row.id)


def _worker(
    session_factory: async_sessionmaker[AsyncSession], transport: httpx.MockTransport
) -> ContentWorker:
    return ContentWorker(
        session_factory=session_factory, owner="content-test", transport=transport
    )


def _transport(
    *,
    status: int = 200,
    content: str = "# Acme\n\nGrounded page.",
    seen: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if status >= 400:
            return httpx.Response(status, json={"error": "boom"})
        return httpx.Response(
            200,
            json={
                "model": _FIXTURE_MODEL,
                "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 30},
            },
        )

    return httpx.MockTransport(handler)


async def test_enqueue_unavailable_grounding_and_legacy_routes_are_gone(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "content-context@example.com")
    project_id = await _create_project(client)
    response = await client.post(
        "/api/v1/content/generations",
        json={"project_id": project_id, "prompt": "Write a page."},
    )
    assert response.status_code == 201
    assert response.json()["grounding_status"] == "unavailable"
    for path in ("strategy", "inventory", "briefs", "revisions", "verifications"):
        assert (
            await client.get(
                f"/api/v1/content/{path}", params={"project_id": project_id}
            )
        ).status_code == 404


async def test_worker_preserves_frozen_grounding_and_attempt_provenance(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _register(client, "content-worker@example.com")
    generation_id = await _seed_generation(
        session_factory, await _create_project(client)
    )
    seen: list[httpx.Request] = []
    assert await _worker(session_factory, _transport(seen=seen)).run_until_idle() == 1

    detail = (await client.get(f"/api/v1/content/generations/{generation_id}")).json()
    assert detail["status"] == TASK_STATUS_SUCCEEDED
    assert detail["grounding_summary"]["crawl_fragment_count"] == 1
    assert detail["output_text"].startswith("# Acme")
    assert _CANARY_SECRET not in json.dumps(detail)
    assert seen[0].url.host == "provider.invalid"
    assert seen[0].headers["authorization"] == f"Bearer {_CANARY_SECRET}"
    sent_messages = json.loads(seen[0].content)["messages"]
    assert len(sent_messages) == 3
    assert "untrusted crawl observations" in sent_messages[-1]["content"]

    async with session_factory() as session:
        attempts = (
            await session.scalars(
                select(ContentGenerationAttempt).where(
                    ContentGenerationAttempt.content_generation_id
                    == uuid.UUID(generation_id)
                )
            )
        ).all()
    assert [(attempt.attempt_number, attempt.status) for attempt in attempts] == [
        (1, "succeeded")
    ]


async def test_worker_failure_and_cancel_keep_results_immutable(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _register(client, "content-terminal@example.com")
    project_id = await _create_project(client)
    failed_id = await _seed_generation(session_factory, project_id)
    await _worker(session_factory, _transport(status=401)).run_until_idle()
    failed = (await client.get(f"/api/v1/content/generations/{failed_id}")).json()
    assert (failed["status"], failed["error_code"], failed["output_text"]) == (
        TASK_STATUS_FAILED,
        "auth_failure",
        None,
    )

    cancelled_id = await _seed_generation(session_factory, project_id)
    cancelled = await client.post(f"/api/v1/content/generations/{cancelled_id}/cancel")
    assert cancelled.json()["status"] == TASK_STATUS_CANCELLED
    repeated = await client.post(f"/api/v1/content/generations/{cancelled_id}/cancel")
    assert repeated.status_code == 409
    assert repeated.json()["detail"] == "cancel_not_allowed"
    assert repeated.json()["error"]["code"] == "cancel_not_allowed"
    assert repeated.json()["error"]["message"] == (
        "This content generation can no longer be cancelled"
    )
    assert await _worker(session_factory, _transport()).run_until_idle() == 0
    assert (await client.get(f"/api/v1/content/generations/{cancelled_id}")).json()[
        "output_text"
    ] is None


async def test_read_actions_and_workspace_isolation(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await _register(client, "content-owner@example.com")
    project_id = await _create_project(client)
    generation_id = await _seed_generation(session_factory, project_id)
    listed = await client.get(
        "/api/v1/content/generations", params={"project_id": project_id}
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == generation_id
    assert "output_text" not in listed.json()[0]

    client.cookies.clear()
    await _register(client, "content-outsider@example.com")
    for path in (
        f"/api/v1/content/generations/{generation_id}",
        f"/api/v1/content/generations/{generation_id}/cancel",
    ):
        response = await (
            client.get(path) if path.endswith(generation_id) else client.post(path)
        )
        assert response.status_code == 404


async def test_skill_catalog_is_served_and_drives_enqueue_validation(
    client: httpx.AsyncClient,
) -> None:
    # The catalog is the frontend's only source of skill ids, so it must be
    # readable, ordered, and consistent with what enqueue will accept.
    assert (await client.get("/api/v1/content/skills")).status_code == 401

    await _register(client, "content-skills@example.com")
    response = await client.get("/api/v1/content/skills")
    assert response.status_code == 200
    body = response.json()
    assert body["default_skill_id"] == "content_page"

    skills = body["skills"]
    ids = [skill["id"] for skill in skills]
    assert ids[0] == "content_page"
    # Legacy ids persisted on existing rows must remain offered.
    for legacy in ("article", "blog", "youtube", "reddit"):
        assert legacy in ids
    # Every skill explains itself to the picker without exposing the directive.
    for skill in skills:
        assert skill["description"]
        assert skill["structure"]
        assert "directive" not in skill

    project_id = await _create_project(client)
    accepted = await client.post(
        "/api/v1/content/generations",
        json={
            "project_id": project_id,
            "prompt": "Write a post.",
            "skill_id": "linkedin",
        },
    )
    assert accepted.status_code == 201
    body = accepted.json()
    assert body["skill_id"] == "linkedin"
    # Provenance keeps the skill catalog and the generator versions apart.
    assert body["skill_version"] == CONTENT_SKILL_CATALOG_VERSION
    assert body["generator_version"] == CONTENT_GENERATOR_VERSION

    rejected = await client.post(
        "/api/v1/content/generations",
        json={"project_id": project_id, "prompt": "Write a post.", "skill_id": "nope"},
    )
    assert rejected.status_code == 422
