"""Opportunity source resolution, supersession, and status lifecycle tests.

Runs against a real (throwaway) Postgres schema via the shared fixtures: the
recompute write path (supersede-not-mutate, per-project advisory lock, the
partial unique live-target index) and the keyset-paginated read projections
can only be verified against a real database. Seed helpers live in
``tests/component/opportunity_helpers.py`` (shared with the API tests).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import AUDIT_STATUS_COMPLETED
from app.core.config.opportunities import (
    CODE_OPPORTUNITY_SUPERSEDED,
    OPPORTUNITY_RULES_BY_ID,
)
from app.domain.opportunities import (
    commands,
    queries,
    recompute,
)
from app.domain.opportunities.errors import (
    OpportunityNotFoundError,
    OpportunityOrderConflictError,
    OpportunitySupersededError,
    OpportunityValidationError,
)
from app.domain.opportunities.projection import _stable_key
from app.models.analysis import Citation, MetricSnapshot, ResponseAnalysis
from app.models.audit import Audit
from app.models.opportunity import (
    Opportunity,
    OpportunityStatusEvent,
)
from app.models.project import Project
from app.models.workspace import Workspace
from tests.component.opportunity_helpers import (
    _add_visibility,
    _by_rule,
    _live_rows,
    _seed_base,
    _seed_scenario,
)

pytestmark = pytest.mark.asyncio


async def test_audit_without_metric_snapshot_is_not_dashboard_ready(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, prompt_ids = await _seed_base(db_session)
    await _add_visibility(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_ids=prompt_ids,
        with_metric_snapshot=False,
    )
    await db_session.commit()

    result = await recompute.recompute(
        db_session, workspace_id=workspace_id, project_id=project_id
    )

    # Default resolution requires the aggregate snapshot (mirrors the
    # dashboard): the audit is treated as not ready, not as an error.
    assert result["audit_id"] is None
    assert result["total_count"] == 0


async def test_default_resolution_uses_latest_dashboard_ready_audit(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, prompt_ids = await _seed_base(db_session)
    await _add_visibility(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_ids=prompt_ids,
    )
    await db_session.commit()
    # A newer completed audit with no analyses (but with its snapshot).
    latest_completed_at = await db_session.scalar(
        select(func.max(Audit.completed_at)).where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status == AUDIT_STATUS_COMPLETED,
        )
    )
    assert latest_completed_at is not None
    newer = Audit(
        workspace_id=workspace_id,
        project_id=project_id,
        status=AUDIT_STATUS_COMPLETED,
        completed_at=latest_completed_at + timedelta(seconds=1),
    )
    db_session.add(newer)
    await db_session.flush()
    db_session.add(
        MetricSnapshot(
            workspace_id=workspace_id,
            audit_id=newer.id,
            project_id=project_id,
            analyzer_version="b6-analysis-1",
            scoring_rule_version="scoring-v1",
            metrics={},
        )
    )
    await db_session.commit()

    result = await recompute.recompute(
        db_session, workspace_id=workspace_id, project_id=project_id
    )

    assert result["audit_id"] == newer.id
    assert result["counts_by_type"]["visibility"] == 0


async def test_explicit_foreign_audit_is_not_found(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    foreign_workspace = Workspace(name="Foreign")
    db_session.add(foreign_workspace)
    await db_session.flush()
    foreign_project = Project(
        workspace_id=foreign_workspace.id,
        name="Foreign",
        brand_name="F",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=1,
    )
    db_session.add(foreign_project)
    await db_session.flush()
    foreign_audit = Audit(
        workspace_id=foreign_workspace.id,
        project_id=foreign_project.id,
        status=AUDIT_STATUS_COMPLETED,
    )
    db_session.add(foreign_audit)
    await db_session.commit()

    with pytest.raises(OpportunityNotFoundError):
        await recompute.recompute(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            audit_id=foreign_audit.id,
        )


async def test_missing_project_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(OpportunityNotFoundError):
        await recompute.recompute(
            db_session, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
        )
    with pytest.raises(OpportunityNotFoundError):
        await queries.list_opportunities(
            db_session, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
        )


async def test_disabled_rule_persists_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    scn = await _seed_scenario(db_session)
    monkeypatch.setattr(OPPORTUNITY_RULES_BY_ID["thin_content"], "enabled", False)

    result = await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    assert result["total_count"] == 3
    rows = await _live_rows(db_session, scn)
    assert all(row.rule_id != "thin_content" for row in rows)


# =========================================================================
# Supersede-not-mutate across recomputes
# =========================================================================
async def test_rerecompute_supersedes_carries_status_and_closes_vanished(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    first_rows = await _live_rows(db_session, scn)
    first_brand = _by_rule(first_rows, "brand_absent_high_value_prompt")
    first_thin = _by_rule(first_rows, "thin_content")
    first_structured = _by_rule(first_rows, "missing_structured_data")
    first_structured_evidence = dict(first_structured.evidence or {})

    # Human workflow state set between runs must survive the supersede.
    await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=first_brand.id,
        status="in_progress",
    )
    await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=first_thin.id,
        status="dismissed",
    )

    # The prompt-0 analysis gains an owned citation -> both visibility hits
    # vanish on the next pass.
    analysis0 = await db_session.get(ResponseAnalysis, scn.analysis0_id)
    assert analysis0 is not None
    db_session.add(
        Citation(
            workspace_id=scn.workspace_id,
            audit_id=scn.audit_id,
            analysis_id=scn.analysis0_id,
            artifact_id=analysis0.artifact_id,
            analyzer_version="b6-analysis-1",
            ordinal=2,
            url="https://acme.com/crm",
            title="Acme CRM",
            domain="acme.com",
            classification="owned",
            is_owned=True,
        )
    )
    await db_session.commit()

    result = await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    assert result["total_count"] == 2
    assert result["counts_by_status"]["open"] == 1
    assert result["counts_by_status"]["dismissed"] == 1

    live = await _live_rows(db_session, scn)
    assert {row.rule_id for row in live} == {
        "missing_structured_data",
        "thin_content",
    }
    new_thin = _by_rule(live, "thin_content")
    new_structured = _by_rule(live, "missing_structured_data")
    # New identities, carried status, byte-identical evidence.
    assert new_thin.id != first_thin.id
    assert new_thin.status == "dismissed"
    assert new_structured.id != first_structured.id
    assert new_structured.status == "open"
    assert new_structured.evidence == first_structured_evidence

    # Prior rows closed, never mutated.
    await db_session.refresh(first_brand)
    await db_session.refresh(first_thin)
    await db_session.refresh(first_structured)
    assert first_brand.superseded_at is not None
    assert first_brand.superseded_by_id is None  # vanished hit: no successor
    assert first_brand.status == "in_progress"  # untouched by the close
    assert first_thin.superseded_by_id == new_thin.id
    assert first_structured.superseded_by_id == new_structured.id


# =========================================================================
# Status mutation (the ONLY mutable field)
# =========================================================================
async def test_update_status_validates_persists_and_rejects_superseded(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")
    evidence_before = dict(thin.evidence or {})

    item = await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=thin.id,
        status="resolved",
    )
    assert item["status"] == "resolved"
    await db_session.refresh(thin)
    assert thin.status == "resolved"
    assert thin.evidence == evidence_before  # mutation touched status only

    with pytest.raises(OpportunityValidationError):
        await commands.update_status(
            db_session,
            workspace_id=scn.workspace_id,
            changed_by_user_id=scn.user_id,
            opportunity_id=thin.id,
            status="bogus",
        )
    with pytest.raises(OpportunityNotFoundError):
        await commands.update_status(
            db_session,
            workspace_id=scn.workspace_id,
            changed_by_user_id=scn.user_id,
            opportunity_id=uuid.uuid4(),
            status="resolved",
        )

    # Supersede the row, then a mutation is a coded conflict.
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    await db_session.refresh(thin)
    assert thin.superseded_at is not None
    with pytest.raises(OpportunitySupersededError) as excinfo:
        await commands.update_status(
            db_session,
            workspace_id=scn.workspace_id,
            changed_by_user_id=scn.user_id,
            opportunity_id=thin.id,
            status="open",
        )
    assert excinfo.value.code == CODE_OPPORTUNITY_SUPERSEDED


async def test_status_events_are_append_only_and_project_order_is_versioned(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    ordered_ids = [row.id for row in reversed(rows)]

    response = await commands.update_order(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        ordered_opportunity_ids=ordered_ids,
        expected_version=0,
        updated_by_user_id=scn.user_id,
    )
    assert response == {"version": 1, "ordered_opportunity_ids": ordered_ids}
    page = await queries.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert [item["id"] for item in page["items"]] == ordered_ids
    assert all(item["order_source"] == "manual" for item in page["items"])

    with pytest.raises(OpportunityOrderConflictError):
        await commands.update_order(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            ordered_opportunity_ids=ordered_ids,
            expected_version=0,
            updated_by_user_id=scn.user_id,
        )

    target = rows[0]
    await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=target.id,
        status="resolved",
        changed_by_user_id=scn.user_id,
    )
    await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=target.id,
        status="resolved",
        changed_by_user_id=scn.user_id,
    )
    events = list(
        (
            await db_session.scalars(
                select(OpportunityStatusEvent).where(
                    OpportunityStatusEvent.opportunity_id == target.id
                )
            )
        ).all()
    )
    assert [(event.previous_status, event.next_status) for event in events] == [
        ("open", "resolved")
    ]


async def test_stable_order_key_is_collision_safe() -> None:
    left = Opportunity(rule_id="rule:target", target_key="key")
    right = Opportunity(rule_id="rule", target_key="target:key")

    assert _stable_key(left) != _stable_key(right)
    assert json.loads(_stable_key(left)) == ["rule:target", "key"]
