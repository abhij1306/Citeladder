"""Atomic onboarding completion and activation contract."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.brand_discovery import BRAND_DISCOVERY_QUEUE_SPEC
from app.core.config.entitlements import KEY_PROJECT_SLOTS, KEY_PROMPT_SLOTS
from app.core.config.task_queue import TASK_STATUS_RETRY_WAIT
from app.domain.entitlements.types import GrantSpec
from app.domain.projects import discovery as discovery_domain
from app.domain.site_health.planner import CrawlPlanError
from app.models.discovery import BrandDiscovery, BrandDiscoveryTask
from app.models.project import Project
from app.models.prompt import Prompt, Topic
from app.models.site_health import SiteCrawl
from app.models.workspace import Workspace
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from tests.component.occupancy_helpers import seed_occupancy_grants


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201, response.text


def _completion_payload(*, invalid_core: bool = False) -> dict:
    core = [
        {
            "text": (
                "Why choose Acme for analytics?"
                if invalid_core and index == 0
                else f"Which analytics platform supports business need {index}?"
            ),
            "intent": "discovery",
            "cohort": "core",
        }
        for index in range(4)
    ]
    return {
        "name": "Acme Visibility",
        "profile": {"industry": "Analytics", "business_type": "b2b"},
        "domains": ["acme.com"],
        "competitors": [{"name": "Globex", "aliases": [], "domains": ["globex.com"]}],
        "prompt_groups": [
            {"topic": "Analytics", "prompts": core},
            {
                "topic": "Comparisons",
                "prompts": [
                    {
                        "text": "How does Acme compare with Globex for analytics?",
                        "intent": "comparison",
                        "cohort": "comparison",
                    }
                ],
            },
        ],
    }


async def _seed_ready_discovery(
    session: AsyncSession, workspace_id: uuid.UUID
) -> BrandDiscovery:
    row = BrandDiscovery(
        workspace_id=workspace_id,
        status="ready",
        stage="review",
        progress={
            "phase": "preparing_review",
            "completed_steps": 4,
            "total_steps": 5,
            "pages_read": 3,
            "competitors_found": 1,
            "prompts_prepared": 5,
            "updated_at": "2026-08-04T00:00:00+00:00",
        },
        input_data={
            "brand_name": "Acme",
            "website_url": "https://acme.com",
            "language_code": "en",
        },
        idempotency_key=f"discover-{uuid.uuid4()}",
    )
    session.add(row)
    await session.flush()
    return row


@pytest.mark.asyncio
async def test_discovery_failure_persists_safe_state_and_reaches_queue_retry(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "discovery-retry@example.com")
    async with session_factory() as session:
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        discovery = await _seed_ready_discovery(session, workspace_id)
        await session.commit()
        discovery_id = discovery.id

    async def _fail_acquisition(*args, **kwargs):
        raise RuntimeError("transport unavailable")

    monkeypatch.setattr(discovery_domain, "_collect_owned_site", _fail_acquisition)
    async with session_factory() as session:
        discovery = await session.get(BrandDiscovery, discovery_id)
        assert discovery is not None
        with pytest.raises(RuntimeError, match="transport unavailable"):
            await discovery_domain.process_discovery(session, discovery)

    async with session_factory() as session:
        persisted = await session.get(BrandDiscovery, discovery_id)
        assert persisted is not None
        assert persisted.status == "needs_input"
        assert "discovery_unavailable" in persisted.gaps
        assert persisted.error_detail == "RuntimeError"


@pytest.mark.asyncio
async def test_complete_is_atomic_idempotent_and_workspace_scoped(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "complete-owner@example.com")
    async with session_factory() as session:
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_id,
            grants=(
                GrantSpec(key=KEY_PROJECT_SLOTS, value=10),
                GrantSpec(key=KEY_PROMPT_SLOTS, value=100),
            ),
        )
        discovery = await _seed_ready_discovery(session, workspace_id)
        invalid = await _seed_ready_discovery(session, workspace_id)
        await session.commit()
        discovery_id = discovery.id
        invalid_id = invalid.id

    response = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "complete-1"},
        json=_completion_payload(),
    )
    assert response.status_code == 201, response.text
    completed = response.json()
    assert completed["activation_state"] == "queued"
    assert completed["page_limit"] == 10

    replay = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "complete-1"},
        json=_completion_payload(),
    )
    assert replay.status_code == 201
    assert replay.json() == completed

    conflict = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "complete-2"},
        json=_completion_payload(),
    )
    assert conflict.status_code == 409

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Project)) == 1
        assert await session.scalar(select(func.count()).select_from(SiteCrawl)) == 1
        assert await session.scalar(select(func.count()).select_from(Prompt)) == 5
        topics = list((await session.scalars(select(Topic))).all())
        assert {topic.name for topic in topics} == {"Analytics", "Comparisons"}
        prompt_counts = [
            await session.scalar(
                select(func.count())
                .select_from(Prompt)
                .where(Prompt.topic_id == topic.id)
            )
            for topic in topics
        ]
        assert all(count > 0 for count in prompt_counts)

    rejected = await client.post(
        f"/api/v1/brand-discoveries/{invalid_id}/complete",
        headers={"Idempotency-Key": "complete-invalid"},
        json=_completion_payload(invalid_core=True),
    )
    assert rejected.status_code == 409
    async with session_factory() as session:
        invalid_row = await session.get(BrandDiscovery, invalid_id)
        assert invalid_row is not None
        assert invalid_row.project_id is None
        assert await session.scalar(select(func.count()).select_from(Project)) == 1

        crawl_failure = await _seed_ready_discovery(session, workspace_id)
        await session.commit()
        crawl_failure_id = crawl_failure.id

    async def fail_crawl_plan(*_args, **_kwargs):
        raise CrawlPlanError("Could not prepare the initial website review")

    monkeypatch.setattr(discovery_domain, "start_initial_site_review", fail_crawl_plan)
    failed_activation = await client.post(
        f"/api/v1/brand-discoveries/{crawl_failure_id}/complete",
        headers={"Idempotency-Key": "complete-crawl-failure"},
        json=_completion_payload(),
    )
    assert failed_activation.status_code == 422
    async with session_factory() as session:
        failed_row = await session.get(BrandDiscovery, crawl_failure_id)
        assert failed_row is not None
        assert failed_row.project_id is None
        assert await session.scalar(select(func.count()).select_from(Project)) == 1
        assert await session.scalar(select(func.count()).select_from(SiteCrawl)) == 1

    await _register(client, "complete-foreign@example.com")
    foreign = await client.get(f"/api/v1/brand-discoveries/{discovery_id}")
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_discovery_task_uses_generic_claim_heartbeat_and_retry(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "discovery-queue@example.com")
    created = await client.post(
        "/api/v1/brand-discoveries",
        headers={"Idempotency-Key": "queue-discovery-1"},
        json={"brand_name": "Acme", "website_url": "https://acme.com"},
    )
    assert created.status_code == 202
    discovery_id = uuid.UUID(created.json()["id"])
    async with session_factory() as session:
        tasks = list(
            (
                await session.scalars(
                    select(BrandDiscoveryTask).where(
                        BrandDiscoveryTask.discovery_id == discovery_id
                    )
                )
            ).all()
        )
    assert len(tasks) == 1

    queue = PostgresTaskQueue(session_factory, BRAND_DISCOVERY_QUEUE_SPEC)
    claimed = await queue.claim(owner="discovery-test", limit=1)
    assert [task.discovery_id for task in claimed] == [discovery_id]
    assert await queue.heartbeat(task_id=claimed[0].id, owner="discovery-test")
    async with session_factory() as session:
        await session.execute(
            update(BrandDiscoveryTask)
            .where(BrandDiscoveryTask.id == claimed[0].id)
            .values(
                attempt_count=1,
                lease_expires_at=datetime.now(UTC) - timedelta(seconds=1),
            )
        )
        await session.commit()
    sweep = await queue.release_expired_detailed()
    assert sweep.reclaimed == 1
    async with session_factory() as session:
        retried = await session.get(BrandDiscoveryTask, claimed[0].id)
        assert retried is not None
        assert retried.status == TASK_STATUS_RETRY_WAIT
