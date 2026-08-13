"""Demand snapshot persistence over existing Traffic evidence."""

from __future__ import annotations

import uuid
from datetime import date

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH
from app.domain.demand.service import demand_source_revision, recompute_demand
from app.models.analytics import AnalyticsTask
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.project import Project
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot
from app.models.workspace import Workspace


async def _create_api_project(client: httpx.AsyncClient) -> dict:
    email = f"demand-{uuid.uuid4().hex}@example.com"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 202
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 200
    response = await client.post("/api/v1/projects", json={"name": "Demand API"})
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_recompute_is_immutable_idempotent_and_preserves_provenance(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = Workspace(name="Demand workspace")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Education project",
        industry_pack_id="education",
    )
    db_session.add(project)
    await db_session.flush()
    source_row_id = str(uuid.uuid4())
    source_artifact_id = str(uuid.uuid4())
    traffic = TrafficSnapshot(
        workspace_id=workspace.id,
        project_id=project.id,
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 7),
        granularity="day",
        metrics={},
        source_metric_row_ids=[source_row_id],
        source_artifact_ids=[source_artifact_id],
    )
    db_session.add(traffic)
    await db_session.flush()
    db_session.add(
        TrafficQueryStat(
            workspace_id=workspace.id,
            project_id=project.id,
            snapshot_id=traffic.id,
            normalized_query="school admissions fees",
            metrics={"impressions": 100, "clicks": 0, "ctr": 0},
            source_metric_row_ids=[source_row_id],
            source_artifact_ids=[source_artifact_id],
        )
    )
    db_session.add(
        TrafficPageStat(
            workspace_id=workspace.id,
            project_id=project.id,
            snapshot_id=traffic.id,
            canonical_url="https://school.example/admissions",
            metrics={"sessions": 8, "engaged_sessions": 5, "key_events": 0},
            source_metric_row_ids=[source_row_id],
            source_artifact_ids=[source_artifact_id],
        )
    )
    await db_session.commit()
    task = AnalyticsTask(
        workspace_id=workspace.id,
        project_id=project.id,
        task_kind=ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
        payload={"window_start": "2026-07-01", "window_end": "2026-07-07"},
        idempotency_key=uuid.uuid4().hex,
    )

    await recompute_demand(session_factory, task)
    await recompute_demand(session_factory, task)

    assert (
        await db_session.scalar(select(func.count()).select_from(DemandSnapshot)) == 1
    )
    snapshot = (await db_session.scalars(select(DemandSnapshot))).one()
    assert (
        await demand_source_revision(
            db_session,
            workspace_id=workspace.id,
            project_id=project.id,
            window_start=date(2026, 7, 1),
            window_end=date(2026, 7, 7),
        )
        == snapshot.source_hash[:24]
    )
    assert snapshot.coverage == {"search": "observed"}
    assert snapshot.source_metric_row_ids == [source_row_id]
    signal = (await db_session.scalars(select(DemandSignal))).one()
    assert signal.metrics["clicks"] == 0
    assert signal.coverage["search_demand"] == "observed"
    opportunity_task = await db_session.scalar(
        select(AnalyticsTask).where(AnalyticsTask.task_kind == "opportunity_refresh")
    )
    assert opportunity_task is not None
    assert opportunity_task.payload["trigger_kind"] == "demand_snapshot"
    assert opportunity_task.payload["trigger_id"] == str(snapshot.id)


@pytest.mark.asyncio
async def test_latest_contract_and_removed_demand_routes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    project = await _create_api_project(client)
    snapshot = DemandSnapshot(
        workspace_id=uuid.UUID(project["workspace_id"]),
        project_id=uuid.UUID(project["id"]),
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 7),
        source_hash="a" * 64,
        source_artifact_ids=[str(uuid.uuid4())],
        source_metric_row_ids=[str(uuid.uuid4())],
        coverage={"search": "observed"},
        summary={"signal_count": 0, "counts_by_type": {}},
        formula_version="demand-priority-1",
        analyzer_version="demand-analyzer-2",
    )
    db_session.add(snapshot)
    await db_session.commit()

    prefix = f"/api/v1/projects/{project['id']}/demand"
    response = await client.get(f"{prefix}/latest")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(snapshot.id)
    assert body["signals"] == []
    assert {
        "site_snapshot_id",
        "source_audit_ids",
        "journey_version_ids",
    }.isdisjoint(body)
    for removed in ("snapshots", "capabilities", "journeys"):
        assert (await client.get(f"{prefix}/{removed}")).status_code == 404
