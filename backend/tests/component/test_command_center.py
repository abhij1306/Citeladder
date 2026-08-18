from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.command_center.report import render_executive_pdf
from app.domain.command_center.service import get_command_center
from app.domain.opportunities import recompute as opportunity_recompute
from app.models.demand import DemandSnapshot
from app.models.project import Project
from tests.component.opportunity_helpers import _add_site, _seed_base, _seed_scenario

pytestmark = pytest.mark.asyncio


async def test_command_center_uses_persisted_state_and_report(
    db_session: AsyncSession,
) -> None:
    scenario = await _seed_scenario(db_session)
    await opportunity_recompute.recompute(
        db_session,
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
    )
    project = await db_session.scalar(
        select(Project).where(Project.id == scenario.project_id)
    )
    assert project is not None

    response = await get_command_center(
        db_session,
        workspace_id=scenario.workspace_id,
        project=project,
    )

    assert response.project.brand_name == "Acme Corp"
    assert response.measurement.audit_id == scenario.audit_id
    assert response.measurement.comparable_audit_id is None
    assert response.state.visibility.delta is None
    assert response.state.share_of_voice.value is None
    assert response.state.brand_rank.value == 1
    assert response.actions
    assert all(action.evidence_summary["count"] > 0 for action in response.actions)

    pdf = render_executive_pdf(response)
    assert pdf.startswith(b"%PDF")
    assert b"CiteLadder" in pdf
    assert b"Evidence appendix" in pdf
    assert b"does not establish causation" in pdf


async def test_command_center_projects_crawl_and_demand_before_first_audit(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    crawl, _issue_a, _issue_b = await _add_site(
        db_session, workspace_id=workspace_id, project_id=project_id
    )
    demand = DemandSnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 31),
        source_hash="a" * 64,
        formula_version="demand-formula-v1",
        analyzer_version="demand-analyzer-v1",
    )
    db_session.add(demand)
    await db_session.commit()
    project = await db_session.get(Project, project_id)
    assert project is not None

    response = await get_command_center(
        db_session, workspace_id=workspace_id, project=project
    )

    assert response.measurement is None
    assert response.report_available is False
    assert response.loop.analyzed.state == "observed"
    assert response.loop.analyzed.coverage == ["site_health", "search_demand"]
    assert response.loop.analyzed.observed_at in {crawl.completed_at, demand.created_at}
    assert response.loop.tracked.state == "not_run"
    assert response.track.citation_share.value is None
    assert response.next_action.kind == "connect"
