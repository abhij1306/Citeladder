"""Component coverage for immutable Opportunity implementation declarations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.opportunities.verification import verify_implementation_events
from app.models.analytics import AnalyticsTask
from app.models.opportunity import Opportunity, OpportunityImplementationEvent
from app.models.site_health import SiteCrawl, SiteUrl
from tests.component.opportunity_helpers import Scenario, _seed_scenario

pytestmark = pytest.mark.asyncio

_EMAIL = "implementation-events@example.com"


async def _seed_and_recompute(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Scenario, Opportunity, SiteUrl]:
    await client.post(
        "/api/v1/auth/register",
        json={"email": _EMAIL, "password": "password123"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": "password123"},
    )
    assert login.status_code == 200
    async with session_factory() as session:
        scenario = await _seed_scenario(session, email=_EMAIL)
    headers = {"X-Workspace-Id": str(scenario.workspace_id)}
    recompute = await client.post(
        f"/api/v1/projects/{scenario.project_id}/opportunities/recompute",
        headers=headers,
    )
    assert recompute.status_code == 200
    async with session_factory() as session:
        opportunity = await session.scalar(
            select(Opportunity).where(
                Opportunity.project_id == scenario.project_id,
                Opportunity.opportunity_type == "site",
                Opportunity.superseded_at.is_(None),
            )
        )
        assert opportunity is not None
        site_url = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == scenario.project_id,
                SiteUrl.normalized_url == opportunity.target_url,
            )
        )
        assert site_url is not None
        session.expunge(opportunity)
        session.expunge(site_url)
    return scenario, opportunity, site_url


async def test_declaration_is_idempotent_and_projects_declared_state(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario, opportunity, site_url = await _seed_and_recompute(
        client, session_factory
    )
    headers = {
        "X-Workspace-Id": str(scenario.workspace_id),
        "Idempotency-Key": "implementation-once",
    }
    payload = {
        "opportunity_id": str(opportunity.id),
        "target_site_url_ids": [str(site_url.id)],
        "declared_implemented_at": datetime.now(UTC).isoformat(),
        "expected_checks": [
            {
                "kind": "site_rule",
                "target_site_url_id": str(site_url.id),
                "rule_id": opportunity.rule_id,
                "expected_outcome": "pass",
            }
        ],
    }
    url = (
        f"/api/v1/projects/{scenario.project_id}"
        "/opportunities/implementation-events"
    )

    created = await client.post(url, headers=headers, json=payload)
    refreshed = await client.post(
        f"/api/v1/projects/{scenario.project_id}/opportunities/recompute",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
    )
    assert refreshed.status_code == 200
    replay = await client.post(url, headers=headers, json=payload)

    assert created.status_code == 201
    assert replay.status_code == 200
    assert created.json() == replay.json()
    assert created.json()["state"] == "declared"
    assert created.json()["limitations"] == []
    listed = await client.get(
        url, headers={"X-Workspace-Id": str(scenario.workspace_id)}
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [
        created.json()["id"]
    ]
    detail = await client.get(
        f"{url}/{created.json()['id']}",
        headers={"X-Workspace-Id": str(scenario.workspace_id)},
    )
    assert detail.status_code == 200
    assert detail.json() == created.json()
    async with session_factory() as session:
        rows = list(
            (await session.scalars(select(OpportunityImplementationEvent))).all()
        )
        assert len(rows) == 1


async def test_cross_workspace_target_is_rejected(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario, opportunity, _site_url = await _seed_and_recompute(
        client, session_factory
    )
    async with session_factory() as session:
        foreign = await _seed_scenario(session)
        foreign_target = await session.scalar(
            select(SiteUrl).where(SiteUrl.project_id == foreign.project_id)
        )
        assert foreign_target is not None
        foreign_target_id = foreign_target.id

    response = await client.post(
        f"/api/v1/projects/{scenario.project_id}/opportunities/implementation-events",
        headers={
            "X-Workspace-Id": str(scenario.workspace_id),
            "Idempotency-Key": "foreign-target",
        },
        json={
            "opportunity_id": str(opportunity.id),
            "target_site_url_ids": [str(foreign_target_id)],
            "declared_implemented_at": datetime.now(UTC).isoformat(),
            "expected_checks": [
                {
                    "kind": "site_rule",
                    "rule_id": opportunity.rule_id,
                    "expected_outcome": "pass",
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "implementation_target_conflict"


async def test_terminal_crawl_appends_all_persisted_projection_states(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    scenario, opportunity, site_url = await _seed_and_recompute(
        client, session_factory
    )
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, scenario.crawl_id)
        assert crawl is not None and crawl.completed_at is not None
        boundary = crawl.completed_at - timedelta(minutes=1)
    base_url = (
        f"/api/v1/projects/{scenario.project_id}"
        "/opportunities/implementation-events"
    )
    headers = {"X-Workspace-Id": str(scenario.workspace_id)}

    async def declare(key: str, checks: list[dict]) -> dict:
        response = await client.post(
            base_url,
            headers={**headers, "Idempotency-Key": key},
            json={
                "opportunity_id": str(opportunity.id),
                "target_site_url_ids": [str(site_url.id)],
                "declared_implemented_at": boundary.isoformat(),
                "expected_checks": checks,
            },
        )
        assert response.status_code == 201
        return response.json()

    site_check = {
        "kind": "site_rule",
        "target_site_url_id": str(site_url.id),
        "rule_id": opportunity.evidence["issue_rule_id"],
    }
    declared = await declare(
        "state-declared",
        [
            {
                "kind": "traffic_metric",
                "metric": "clicks",
                "direction": "increase",
                "expected_value": 1,
            }
        ],
    )
    verified = await declare(
        "state-verified", [{**site_check, "expected_outcome": "fail"}]
    )
    contradicted = await declare(
        "state-contradicted", [{**site_check, "expected_outcome": "pass"}]
    )
    observed = await declare(
        "state-observed",
        [
            {**site_check, "expected_outcome": "fail"},
            {
                "kind": "traffic_metric",
                "metric": "clicks",
                "direction": "increase",
                "expected_value": 1,
            },
        ],
    )
    async with session_factory() as session:
        before = {
            row.id: (row.expected_checks, row.declared_implemented_at)
            for row in (
                await session.scalars(select(OpportunityImplementationEvent))
            ).all()
        }

    await verify_implementation_events(
        session_factory,
        AnalyticsTask(
            workspace_id=scenario.workspace_id,
            project_id=scenario.project_id,
            task_kind="opportunity_verification",
            payload={
                "trigger_kind": "site_crawl",
                "trigger_id": str(scenario.crawl_id),
            },
            idempotency_key="test-verifier",
        ),
    )

    listed = await client.get(base_url, headers=headers)
    assert listed.status_code == 200
    states = {item["id"]: item for item in listed.json()["items"]}
    assert states[declared["id"]]["state"] == "declared"
    assert states[declared["id"]]["verification_events"] == []
    assert states[verified["id"]]["state"] == "verified"
    assert states[contradicted["id"]]["state"] == "contradicted"
    assert states[observed["id"]]["state"] == "observed"
    observation = states[verified["id"]]["verification_events"][0]
    assert observation["crawl_id"] == str(scenario.crawl_id)
    assert observation["source_analysis_ids"]
    assert observation["source_rule_evaluation_ids"]
    assert observation["verifier_version"] == "implementation-verifier-1"
    assert states[observed["id"]]["limitations"] == [
        "traffic_metric: unavailable from a site crawl"
    ]
    async with session_factory() as session:
        after = {
            row.id: (row.expected_checks, row.declared_implemented_at)
            for row in (
                await session.scalars(select(OpportunityImplementationEvent))
            ).all()
        }
    assert after == before
