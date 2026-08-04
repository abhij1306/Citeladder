from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.command_center.report import render_executive_pdf
from app.domain.command_center.service import get_command_center
from app.domain.opportunities import service as opportunity_service
from app.models.project import Project
from tests.component.opportunity_helpers import _seed_scenario

pytestmark = pytest.mark.asyncio


async def test_command_center_uses_persisted_state_and_report(
    db_session: AsyncSession,
) -> None:
    scenario = await _seed_scenario(db_session)
    await opportunity_service.recompute(
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
