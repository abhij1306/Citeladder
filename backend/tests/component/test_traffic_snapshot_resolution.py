from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.traffic.query_support import load_snapshot
from app.domain.traffic.service import get_traffic_dashboard
from app.models.project import Project
from app.models.traffic import TrafficSnapshot
from app.models.workspace import Workspace


async def _seed(db_session: AsyncSession) -> tuple[Workspace, Project]:
    workspace = Workspace(name="Traffic resolution")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Traffic project")
    db_session.add(project)
    await db_session.flush()
    return workspace, project


async def test_exact_window_never_falls_back_to_newest(
    db_session: AsyncSession,
) -> None:
    workspace, project = await _seed(db_session)
    latest = TrafficSnapshot(
        workspace_id=workspace.id,
        project_id=project.id,
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 14),
        granularity="day",
        metrics={"totals": {"impressions": 9, "clicks": 1}},
    )
    db_session.add(latest)
    await db_session.commit()

    missing = await load_snapshot(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        from_date=date(2026, 7, 1),
        to_date=date(2026, 7, 31),
        granularity="day",
    )
    current = await load_snapshot(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        from_date=None,
        to_date=None,
        granularity="day",
    )

    assert missing is None
    assert current is not None and current.id == latest.id


async def test_wire_state_distinguishes_not_run_from_observed_zero(
    db_session: AsyncSession,
) -> None:
    workspace, project = await _seed(db_session)
    absent = await get_traffic_dashboard(
        db_session, workspace_id=workspace.id, project_id=project.id
    )
    assert absent.evidence_state == "not_run"

    db_session.add(
        TrafficSnapshot(
            workspace_id=workspace.id,
            project_id=project.id,
            window_start=date(2026, 8, 1),
            window_end=date(2026, 8, 14),
            granularity="day",
            metrics={"totals": {"impressions": 0, "clicks": 0}},
        )
    )
    await db_session.commit()
    observed = await get_traffic_dashboard(
        db_session, workspace_id=workspace.id, project_id=project.id
    )
    assert observed.evidence_state == "observed_zero"
