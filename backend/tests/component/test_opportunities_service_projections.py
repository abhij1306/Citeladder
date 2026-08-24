"""Opportunity list, detail, summary, export, and commerce projections.

Runs against a real (throwaway) Postgres schema via the shared fixtures: the
recompute write path (supersede-not-mutate, per-project advisory lock, the
partial unique live-target index) and the keyset-paginated read projections
can only be verified against a real database. Seed helpers live in
``tests/component/opportunity_helpers.py`` (shared with the API tests).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import (
    ANALYZER_VERSION,
    FORMULA_VERSION,
    RULE_VERSION,
)
from app.domain.opportunities import (
    commands,
    export,
    queries,
    recompute,
)
from app.domain.opportunities import (
    summary as summary_service,
)
from app.domain.opportunities.errors import (
    InvalidCursorError,
    OpportunityNotFoundError,
    OpportunityValidationError,
)
from tests.component.opportunity_helpers import (
    SCORE_BRAND_ABSENT,
    SCORE_OWNED_PAGE,
    SCORE_STRUCTURED_DATA,
    SCORE_THIN_CONTENT,
    URL_A,
    URL_B,
    _add_visibility,
    _by_rule,
    _live_rows,
    _seed_base,
    _seed_scenario,
)

pytestmark = pytest.mark.asyncio


async def test_list_ordering_filters_and_keyset_pagination(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    page = await queries.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert [item["rule_id"] for item in page["items"]] == [
        "brand_absent_high_value_prompt",
        "owned_page_not_cited",
        "missing_structured_data",
        "thin_content",
    ]
    assert [item["priority_score"] for item in page["items"]] == [
        SCORE_BRAND_ABSENT,
        SCORE_OWNED_PAGE,
        SCORE_STRUCTURED_DATA,
        SCORE_THIN_CONTENT,
    ]
    assert page["next_cursor"] is None

    page1 = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        limit=2,
    )
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None
    page2 = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        limit=2,
        cursor=page1["next_cursor"],
    )
    assert [item["rule_id"] for item in page2["items"]] == [
        "missing_structured_data",
        "thin_content",
    ]
    assert page2["next_cursor"] is None
    assert {item["id"] for item in page1["items"]}.isdisjoint(
        {item["id"] for item in page2["items"]}
    )

    # A cursor is bound to its filter scope.
    with pytest.raises(InvalidCursorError):
        await queries.list_opportunities(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            limit=2,
            cursor=page1["next_cursor"],
            severity="high",
        )
    with pytest.raises(InvalidCursorError):
        await queries.list_opportunities(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            cursor="not-a-real-cursor",
        )

    by_type = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        opportunity_type="site",
    )
    assert {item["rule_id"] for item in by_type["items"]} == {
        "missing_structured_data",
        "thin_content",
    }
    by_severity = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        severity="high",
    )
    assert [item["rule_id"] for item in by_severity["items"]] == [
        "brand_absent_high_value_prompt"
    ]
    by_floor = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        min_priority=50.0,
    )
    assert [item["priority_score"] for item in by_floor["items"]] == [
        SCORE_BRAND_ABSENT,
        SCORE_OWNED_PAGE,
    ]
    by_rule = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        rule_id="thin_content",
    )
    assert len(by_rule["items"]) == 1
    dismissed = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        status="dismissed",
    )
    assert dismissed["items"] == []

    # Unknown tokens are validation errors.
    for kwargs in (
        {"opportunity_type": "bogus"},
        {"severity": "bogus"},
        {"status": "bogus"},
        {"rule_id": "bogus"},
    ):
        with pytest.raises(OpportunityValidationError):
            await queries.list_opportunities(
                db_session,
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                **kwargs,
            )


async def test_list_defaults_to_active_statuses(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")
    await commands.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=thin.id,
        status="dismissed",
    )

    default_page = await queries.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert len(default_page["items"]) == 3
    assert all(item["rule_id"] != "thin_content" for item in default_page["items"])
    dismissed_page = await queries.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        status="dismissed",
    )
    assert [item["rule_id"] for item in dismissed_page["items"]] == ["thin_content"]


async def test_detail_projection_includes_superseded_rows(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")

    detail = await queries.get_opportunity(
        db_session, workspace_id=scn.workspace_id, opportunity_id=thin.id
    )
    assert detail["id"] == thin.id
    assert detail["remediation"]
    assert detail["evidence"]["issue_rule_id"] == "technical.thin_content"
    assert detail["source_issue_ids"] == [str(scn.issue_thin_id)]
    assert detail["source_traffic_ids"] == []
    assert detail["analyzer_version"] == ANALYZER_VERSION
    assert detail["superseded_at"] is None

    # After a recompute the OLD row is still readable, marked superseded.
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    detail = await queries.get_opportunity(
        db_session, workspace_id=scn.workspace_id, opportunity_id=thin.id
    )
    assert detail["superseded_at"] is not None
    assert detail["superseded_by_id"] is not None

    with pytest.raises(OpportunityNotFoundError):
        await queries.get_opportunity(
            db_session, workspace_id=scn.workspace_id, opportunity_id=uuid.uuid4()
        )


async def test_summary_before_and_after_recompute(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)

    before = await summary_service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert before["computed"] is False
    assert before["counts_by_type"] == {}
    assert before["total_count"] == 0
    assert before["run_id"] is None
    assert before["analyzer_version"] == ANALYZER_VERSION
    assert before["rule_version"] == RULE_VERSION
    assert before["formula_version"] == FORMULA_VERSION

    result = await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    after = await summary_service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert after["computed"] is True
    assert after["run_id"] == result["run_id"]
    assert after["total_count"] == 4
    assert after["median_priority"] == 50.0
    assert after["counts_by_type"]["visibility"] == 2
    assert after["computed_at"] is not None


async def test_export_rows_projection_and_filters(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    rows = await export.load_export_rows(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert len(rows) == 4
    by_rule = {row["rule_id"]: row for row in rows}
    # Target resolution: prompt text for visibility, URL for site.
    assert by_rule["brand_absent_high_value_prompt"]["target"] == (
        "best crm for small teams"
    )
    assert by_rule["missing_structured_data"]["target"] == URL_A
    structured = by_rule["missing_structured_data"]
    assert structured["priority_score"] == SCORE_STRUCTURED_DATA
    assert structured["rule_version"] == RULE_VERSION
    assert structured["formula_version"] == FORMULA_VERSION
    assert structured["id"]

    site_only = await export.load_export_rows(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        opportunity_type="site",
    )
    assert {row["rule_id"] for row in site_only} == {
        "missing_structured_data",
        "thin_content",
    }
    with pytest.raises(OpportunityValidationError):
        await export.load_export_rows(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            severity="bogus",
        )


# =========================================================================
# C1: backend-owned target_label on the item + detail projections
# =========================================================================
async def test_list_and_detail_carry_backend_target_label(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    page = await queries.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    labels = {item["rule_id"]: item["target_label"] for item in page["items"]}
    # Visibility targets label with the FROZEN prompt snapshot text.
    assert labels["brand_absent_high_value_prompt"] == "best crm for small teams"
    assert labels["owned_page_not_cited"] == "best crm for small teams"
    # Site targets label with their URL.
    assert labels["missing_structured_data"] == URL_A
    assert labels["thin_content"] == URL_B

    rows = await _live_rows(db_session, scn)
    brand_absent = _by_rule(rows, "brand_absent_high_value_prompt")
    detail = await queries.get_opportunity(
        db_session, workspace_id=scn.workspace_id, opportunity_id=brand_absent.id
    )
    # The detail inherits the item projection's label (featured card source).
    assert detail["target_label"] == "best crm for small teams"


# =========================================================================
# C4(c): read-time staleness on the summary projection
# =========================================================================
async def test_summary_staleness_is_read_time(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    summary = await summary_service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert summary["computed"] is True
    assert summary["stale"] is False
    assert summary["evidence_updated_at"] is not None

    # A newer completed audit lands after the snapshot -> read-time stale.
    await _add_visibility(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        prompt_ids=[scn.prompt0_id, scn.prompt1_id],
    )
    summary = await summary_service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert summary["stale"] is True

    # A refresh clears it (the snapshot is newer than the evidence again).
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    summary = await summary_service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert summary["stale"] is False


async def test_summary_stale_is_false_when_never_computed(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    summary = await summary_service.get_summary(
        db_session, workspace_id=workspace_id, project_id=project_id
    )
    assert summary["computed"] is False
    assert summary["stale"] is False
    assert summary["evidence_updated_at"] is None
