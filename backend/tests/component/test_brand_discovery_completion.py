"""Atomic project creation and durable onboarding queue contracts."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.brand_discovery import ERROR_BRAND_DISCOVERY
from app.core.config.entitlements import KEY_PROJECT_SLOTS, KEY_PROMPT_SLOTS
from app.domain.entitlements.types import GrantSpec
from app.domain.projects.onboarding import service as onboarding_service
from app.domain.projects.onboarding.site_resolution import SiteNotFoundError
from app.models.brand import BrandProfile
from app.models.discovery import (
    BrandDiscovery,
    BrandDiscoveryTask,
    BrandResearchSnapshot,
)
from app.models.project import Project
from app.models.prompt import Prompt
from app.models.site_health.crawl import SiteCrawl
from app.models.workspace import Workspace
from app.workers import brand_discovery_worker
from tests.component.occupancy_helpers import seed_occupancy_grants


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 202, response.text
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


def _completion_payload() -> dict:
    return {
        "name": "Acme Visibility",
        "profile": {
            "industry": "Software",
            "business_type": "b2b",
            "positioning": "A workflow analytics platform",
            "products_services": ["analytics software"],
            "target_audience": "enterprise marketing teams",
            "category": "workflow analytics platform",
            "category_terms": ["workflow analytics", "process mining"],
            "business_model": "b2b_saas",
            "market_scope": "global",
            "price_tier": "premium",
            "knowledge_strength": "strong",
        },
        "domains": ["acme.com"],
        "competitors": [{"name": "Globex", "domains": ["globex.com"]}],
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
            "completed_steps": 3,
            "total_steps": 4,
            "pages_read": 1,
            "competitors_found": 1,
            "prompts_prepared": 0,
            "updated_at": "2026-08-04T00:00:00+00:00",
        },
        input_data={
            "brand_name": "Acme",
            "website_url": "https://acme.com/",
            "industry": "Software",
            "subindustry": "Analytics",
            "primary_market": "US",
            "language_code": "en",
        },
        domains=["acme.com"],
        profile={
            "positioning": "A workflow analytics platform",
            "products_services": ["analytics software"],
            "target_audience": "marketing teams",
        },
        idempotency_key=f"discover-{uuid.uuid4()}",
    )
    session.add(row)
    await session.flush()
    session.add(
        BrandResearchSnapshot(
            workspace_id=workspace_id,
            discovery_id=row.id,
            research_version="brand-discovery-v2",
            method="deterministic_fixture",
            extracted_fields={"profile": row.profile},
        )
    )
    return row


@pytest.mark.asyncio
async def test_missing_site_persists_stable_blocking_error(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "discovery-missing@example.com")
    async with session_factory() as session:
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        discovery = await _seed_ready_discovery(session, workspace_id)
        await session.commit()
        discovery_id = discovery.id

    async def missing(*_args, **_kwargs):
        raise SiteNotFoundError("dns_resolution_failed")

    monkeypatch.setattr(onboarding_service, "resolve_site", missing)
    async with session_factory() as session:
        discovery = await session.get(BrandDiscovery, discovery_id)
        assert discovery is not None
        await onboarding_service.process_discovery(session, discovery)

    async with session_factory() as session:
        persisted = await session.get(BrandDiscovery, discovery_id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.error_code == "site_not_found"
        assert persisted.warnings == []


@pytest.mark.asyncio
async def test_reaper_persists_blocking_code_and_deduplicated_warning(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "discovery-reaper@example.com")
    async with session_factory() as session:
        workspace_id = await session.scalar(select(Workspace.id).limit(1))
        assert workspace_id is not None
        discovery = await _seed_ready_discovery(session, workspace_id)
        discovery.warnings = ["research_degraded"]
        await session.commit()
        discovery_id = discovery.id

    async def release_expired_detailed(*_args, **_kwargs):
        return SimpleNamespace(failed_parent_ids=(discovery_id,))

    async def claim(*_args, **_kwargs):
        return []

    monkeypatch.setattr(
        brand_discovery_worker._queue,
        "release_expired_detailed",
        release_expired_detailed,
    )
    monkeypatch.setattr(brand_discovery_worker._queue, "claim", claim)
    monkeypatch.setattr(brand_discovery_worker, "SessionLocal", session_factory)
    assert await brand_discovery_worker.run_once("reaper-test", reap=True) is False

    async with session_factory() as session:
        persisted = await session.get(BrandDiscovery, discovery_id)
        assert persisted is not None
        assert persisted.status == "failed"
        assert persisted.error_code == ERROR_BRAND_DISCOVERY
        assert persisted.warnings == ["research_degraded"]


@pytest.mark.asyncio
async def test_completion_is_atomic_idempotent_scoped_and_does_not_start_site_health(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
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
        await session.commit()
        discovery_id = discovery.id

    response = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "complete-1"},
        json=_completion_payload(),
    )
    assert response.status_code == 201, response.text
    completed = response.json()
    assert completed["crawl_id"] is None
    assert completed["warnings"] == []

    replay = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "complete-1"},
        json=_completion_payload(),
    )
    assert replay.status_code == 201
    assert replay.json() == completed

    conflict = await client.post(
        f"/api/v1/brand-discoveries/{discovery_id}/complete",
        headers={"Idempotency-Key": "different-key"},
        json=_completion_payload(),
    )
    assert conflict.status_code == 409

    async with session_factory() as session:
        project = await session.scalar(select(Project))
        assert project is not None
        assert project.industry == "Software"
        assert project.subindustry == "Analytics"
        assert project.primary_market == "US"
        assert await session.scalar(select(func.count()).select_from(Prompt)) == 10
        profile = await session.scalar(select(BrandProfile))
        assert profile is not None
        # The confirm screen asks what you sell, who buys it and where; the
        # prose fields are not on it. Whatever arrives in them is the model's
        # suggestion — or a default derived from the confirmed category — so it
        # is recorded unreviewed, with no reviewer attributed to a sentence no
        # user was shown.
        assert profile.sources["positioning"]["review_state"] == "unreviewed"
        assert profile.sources["target_audience"]["review_state"] == "unreviewed"
        assert profile.sources["target_audience"]["origin"] == "ai_suggested"
        assert profile.sources["target_audience"].get("reviewed_by") is None
        assert profile.sources["target_audience"].get("reviewed_at") is None
        assert set(profile.source_artifact_ids) == set(profile.sources)
        # The confirmed business context must survive project creation. Before
        # this existed, `business_type` and `price_tier` were collected, shown,
        # confirmed by the user and then silently dropped on the floor.
        assert profile.business_context["category"] == "workflow analytics platform"
        assert profile.business_context["business_model"] == "b2b_saas"
        assert profile.business_context["market_scope"] == "global"
        assert profile.business_context["business_type"] == "b2b"
        assert profile.business_context["price_tier"] == "premium"
        assert profile.business_context["knowledge_strength"] == "strong"
        assert len(set(profile.source_artifact_ids.values())) == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawl)
                .where(SiteCrawl.project_id == project.id)
            )
            == 0
        )

    await _register(client, "complete-foreign@example.com")
    foreign = await client.get(f"/api/v1/brand-discoveries/{discovery_id}")
    assert foreign.status_code == 404


@pytest.mark.asyncio
async def test_discovery_create_queues_once_and_requires_market(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "discovery-queue@example.com")
    missing_market = await client.post(
        "/api/v1/brand-discoveries",
        headers={"Idempotency-Key": "missing-market"},
        json={"brand_name": "Acme", "website_url": "https://acme.com"},
    )
    assert missing_market.status_code == 422

    payload = {
        "brand_name": "Acme",
        "website_url": "acme.com",
        "primary_market": "US",
    }
    created = await client.post(
        "/api/v1/brand-discoveries",
        headers={"Idempotency-Key": "queue-discovery-1"},
        json=payload,
    )
    assert created.status_code == 202, created.text
    replay = await client.post(
        "/api/v1/brand-discoveries",
        headers={"Idempotency-Key": "queue-discovery-1"},
        json=payload,
    )
    assert replay.status_code == created.status_code
    assert replay.json()["id"] == created.json()["id"]
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
