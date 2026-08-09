"""Demand snapshot persistence over existing Traffic evidence."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH
from app.domain.demand.service import (
    _ensure_pack_journey,
    demand_source_revision,
    recompute_demand,
)
from app.models.analytics import AnalyticsTask
from app.models.demand import DemandSignal, DemandSnapshot, JourneyDefinitionVersion
from app.models.project import Project
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot
from app.models.workspace import Workspace


@pytest.mark.asyncio
async def test_pack_journey_provisioning_is_concurrency_safe(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace = Workspace(name="Concurrent journeys")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Education project",
        industry_pack_id="education",
    )
    db_session.add(project)
    await db_session.commit()

    async def provision() -> None:
        async with session_factory() as session:
            await _ensure_pack_journey(
                session, workspace_id=workspace.id, project_id=project.id
            )
            await session.commit()

    await asyncio.gather(provision(), provision())

    assert (
        await db_session.scalar(
            select(func.count()).select_from(JourneyDefinitionVersion)
        )
        == 1
    )


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
    assert snapshot.coverage["search"] == "observed"
    assert snapshot.coverage["visibility"] == "unavailable"
    assert snapshot.coverage["page_identity"] == {
        "state": "observed",
        "total_pages": 1,
        "matched_pages": 0,
        "join_rate": 0.0,
        "unmatched_reasons": ["canonical_url_not_in_site_inventory"],
        "key_events": {
            "state": "observed",
            "value": 0.0,
            "interpretation": "observed_zero_limited_evidence",
        },
    }
    assert snapshot.source_metric_row_ids == [source_row_id]
    signal = (await db_session.scalars(select(DemandSignal))).one()
    assert signal.metrics["clicks"] == 0
    assert signal.coverage["search_demand"] == "observed"
    journey = (await db_session.scalars(select(JourneyDefinitionVersion))).one()
    assert journey.source_kind == "industry_pack"
    assert journey.definition["key_events"] == [
        "admissions_enquiry",
        "application_start",
        "application_submit",
    ]
    opportunity_task = await db_session.scalar(
        select(AnalyticsTask).where(AnalyticsTask.task_kind == "opportunity_refresh")
    )
    assert opportunity_task is not None
    assert opportunity_task.payload["trigger_kind"] == "demand_snapshot"
    assert opportunity_task.payload["trigger_id"] == str(snapshot.id)
