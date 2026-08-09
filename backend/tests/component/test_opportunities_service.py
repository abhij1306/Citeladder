"""Component tests for the opportunities recompute service + projections.

Runs against a real (throwaway) Postgres schema via the shared fixtures: the
recompute write path (supersede-not-mutate, per-project advisory lock, the
partial unique live-target index) and the keyset-paginated read projections
can only be verified against a real database. Seed helpers live in
``tests/component/opportunity_helpers.py`` (shared with the API tests).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.analytics import ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH
from app.core.config.audits import AUDIT_STATUS_COMPLETED, AUDIT_STATUS_RUNNING
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    CODE_OPPORTUNITY_SUPERSEDED,
    FORMULA_VERSION,
    OPPORTUNITY_RULES_BY_ID,
    RULE_VERSION,
)
from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.core.config.site_health import CRAWL_STATUS_RUNNING
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.domain.opportunities import service
from app.domain.opportunities.service import (
    InvalidCursorError,
    OpportunityNotFoundError,
    OpportunityOrderConflictError,
    OpportunitySupersededError,
    OpportunityValidationError,
)
from app.models.analysis import Citation, MetricSnapshot, ResponseAnalysis
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.opportunity import (
    Opportunity,
    OpportunitySnapshot,
    OpportunityStatusEvent,
)
from app.models.product import ProductMetricSnapshot
from app.models.project import Project
from app.models.site_health import SiteCrawl, SiteIssue
from app.models.workspace import Workspace
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


async def test_unchanged_demand_snapshot_remains_fresh_and_ready(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    demand = DemandSnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 7),
        source_hash="d" * 64,
        source_artifact_ids=[],
        source_metric_row_ids=[],
        source_audit_ids=[],
        journey_version_ids=[],
        coverage={},
        summary={},
        formula_version="demand-priority-1",
        analyzer_version="demand-analyzer-1",
    )
    db_session.add(demand)
    await db_session.flush()
    source_metric_id = str(uuid.uuid4())
    db_session.add(
        DemandSignal(
            workspace_id=workspace_id,
            project_id=project_id,
            snapshot_id=demand.id,
            identity_hash="s" * 64,
            signal_type="high_impression_low_ctr",
            state="active",
            topic_cluster="admissions",
            page_url="",
            evidence={
                "target_kind": "query",
                "target": "admissions",
                "source_metric_row_ids": [source_metric_id],
            },
            metrics={"impressions": 100, "clicks": 0},
            coverage={"search_demand": "observed"},
            limitations=[],
            priority_score=80,
            priority_inputs={},
            analyzer_version="demand-analyzer-1",
            rule_version="demand-rules-1",
            formula_version="demand-priority-1",
        )
    )
    await db_session.commit()

    first = await service.recompute(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        skip_if_current=True,
    )
    second = await service.recompute(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        skip_if_current=True,
    )

    assert second["run_id"] == first["run_id"]
    assert second["demand_snapshot_id"] == demand.id
    assert (
        await db_session.scalar(select(func.count()).select_from(OpportunitySnapshot))
        == 1
    )
    summary = await service.get_summary(
        db_session, workspace_id=workspace_id, project_id=project_id
    )
    assert summary["stale"] is False
    assert summary["activation_state"] == "ready"
    assert summary["demand_source_revision"] == demand.source_hash
    opportunity_snapshot = (await db_session.scalars(select(OpportunitySnapshot))).one()
    assert opportunity_snapshot.source_analysis_ids == []
    opportunity = (await db_session.scalars(select(Opportunity))).one()
    assert opportunity.source_metric_ids == [source_metric_id]
    assert opportunity.evidence["demand_signal_id"]


async def test_automatic_refresh_task_is_unique_and_manual_success_is_ready(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    for _ in range(2):
        await service.enqueue_opportunity_refresh(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            trigger_kind="audit",
            trigger_id=scn.audit_id,
        )
    await db_session.commit()
    tasks = list(
        (
            await db_session.scalars(
                select(AnalyticsTask).where(
                    AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH
                )
            )
        ).all()
    )
    assert len(tasks) == 1
    tasks[0].status = TASK_STATUS_FAILED
    await db_session.commit()
    assert (
        await service.get_summary(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
        )
    )["activation_state"] == "delayed"

    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert (
        await service.get_summary(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
        )
    )["activation_state"] == "ready"


# =========================================================================
# Recompute: write path
# =========================================================================
async def test_recompute_persists_rows_and_snapshot_with_provenance(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)

    result = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    assert result["total_count"] == 4
    assert result["run_id"] is not None
    assert result["audit_id"] == scn.audit_id
    assert result["site_crawl_id"] == scn.crawl_id
    assert result["counts_by_type"] == {
        "site": 2,
        "topic": 0,
        "traffic": 0,
        "visibility": 2,
    }
    assert result["counts_by_severity"] == {
        "critical": 0,
        "high": 1,
        "info": 0,
        "low": 1,
        "medium": 2,
    }
    assert result["counts_by_status"] == {
        "dismissed": 0,
        "in_progress": 0,
        "open": 4,
        "resolved": 0,
    }
    # Median of [10.0, 20.0, 80.0, 120.0].
    assert result["median_priority"] == 50.0
    assert result["analyzer_version"] == ANALYZER_VERSION
    assert result["rule_version"] == RULE_VERSION
    assert result["formula_version"] == FORMULA_VERSION
    assert result["created_at"] is not None

    rows = await _live_rows(db_session, scn)
    assert len(rows) == 4

    brand_absent = _by_rule(rows, "brand_absent_high_value_prompt")
    assert brand_absent.target_key == f"prompt:{scn.prompt0_id}"
    assert brand_absent.target_prompt_id == scn.prompt0_id
    assert brand_absent.target_theme == "crm"
    assert brand_absent.opportunity_type == "visibility"
    assert brand_absent.severity == "high"
    assert brand_absent.priority_score == SCORE_BRAND_ABSENT
    assert brand_absent.status == "open"
    assert brand_absent.evidence is not None
    assert brand_absent.evidence["competitor_names"] == ["Globex"]
    assert brand_absent.evidence["prompt_intent"] == "purchase"
    assert brand_absent.evidence["prompt_text"] == "best crm for small teams"
    assert brand_absent.source_analysis_ids == [str(scn.analysis0_id)]
    assert brand_absent.source_metric_ids == [str(scn.metric_snapshot_id)]
    assert brand_absent.source_issue_ids == []
    assert brand_absent.source_traffic_ids is None
    assert brand_absent.analyzer_version == ANALYZER_VERSION
    assert brand_absent.rule_version == RULE_VERSION
    assert brand_absent.formula_version == FORMULA_VERSION

    owned_page = _by_rule(rows, "owned_page_not_cited")
    assert owned_page.target_key == f"prompt:{scn.prompt0_id}"
    assert owned_page.severity == "medium"
    assert owned_page.priority_score == SCORE_OWNED_PAGE
    assert owned_page.evidence is not None
    assert owned_page.evidence["owned_domains"] == ["acme.com"]

    structured = _by_rule(rows, "missing_structured_data")
    assert structured.target_key == f"url:{URL_A}"
    assert structured.target_url == URL_A
    assert structured.opportunity_type == "site"
    assert structured.priority_score == SCORE_STRUCTURED_DATA
    assert structured.source_issue_ids == [str(scn.issue_structured_id)]
    assert structured.evidence is not None
    assert structured.evidence["issue_rule_id"] == "aeo.structured_data_present"

    thin = _by_rule(rows, "thin_content")
    assert thin.target_key == f"url:{URL_B}"
    assert thin.priority_score == SCORE_THIN_CONTENT
    assert thin.source_issue_ids == [str(scn.issue_thin_id)]

    # The unmapped issue produced no row, and the owned-cited prompt none either.
    assert all(row.rule_id != "technical.title_missing" for row in rows)
    assert all(row.target_key != f"prompt:{scn.prompt1_id}" for row in rows)

    # The immutable snapshot persisted its sorted source-id aggregates.
    snapshot = await db_session.scalar(
        select(OpportunitySnapshot).where(
            OpportunitySnapshot.project_id == scn.project_id
        )
    )
    assert snapshot is not None
    assert snapshot.source_analysis_ids == sorted([str(scn.analysis0_id)])
    assert snapshot.source_issue_ids == sorted(
        [str(scn.issue_structured_id), str(scn.issue_thin_id)]
    )


async def test_recompute_without_sources_yields_empty_snapshot(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    await db_session.commit()

    result = await service.recompute(
        db_session, workspace_id=workspace_id, project_id=project_id
    )

    assert result["total_count"] == 0
    assert result["audit_id"] is None
    assert result["site_crawl_id"] is None
    assert result["median_priority"] is None
    assert result["counts_by_status"] == {
        "dismissed": 0,
        "in_progress": 0,
        "open": 0,
        "resolved": 0,
    }
    assert (
        await db_session.scalar(
            select(OpportunitySnapshot).where(
                OpportunitySnapshot.project_id == project_id
            )
        )
        is not None
    )


async def test_guidance_is_immutable_bounded_and_idempotent(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guidance stores a frozen input and replays only an identical key/input."""
    monkeypatch.setattr(service.settings, "app_env", "development")
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    opportunity = _by_rule(
        await _live_rows(db_session, scn), "brand_absent_high_value_prompt"
    )
    grouped = await service.get_grouped_history(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert grouped["since_previous"] == {"new": 0, "continuing": 4, "resolved": 0}
    assert all(item["occurrence_count"] == 1 for item in grouped["items"])
    opportunity.evidence = {"long": "x" * 1000}
    await db_session.commit()

    first, created = await service.create_guidance(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=opportunity.id,
        idempotency_key="guidance-1",
    )
    assert created is True
    assert first.provider == "deterministic"
    assert len(first.input_snapshot["evidence"]["long"]) < 1000
    assert len(first.input_hash) == 64

    replay, created = await service.create_guidance(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=opportunity.id,
        idempotency_key="guidance-1",
    )
    assert created is False
    assert replay.id == first.id
    history = await service.list_guidance_history(
        db_session, workspace_id=scn.workspace_id, opportunity_id=opportunity.id
    )
    assert [row.id for row in history] == [first.id]

    opportunity.status = "in_progress"
    await db_session.commit()
    with pytest.raises(service.OpportunityGuidanceIdempotencyConflictError):
        await service.create_guidance(
            db_session,
            workspace_id=scn.workspace_id,
            opportunity_id=opportunity.id,
            idempotency_key="guidance-1",
        )

    monkeypatch.setattr(service.settings, "app_env", "production")
    with pytest.raises(service.OpportunityGuidanceUnavailableError):
        await service.create_guidance(
            db_session,
            workspace_id=scn.workspace_id,
            opportunity_id=opportunity.id,
            idempotency_key="guidance-2",
        )


async def test_grouped_history_compares_the_latest_two_recompute_snapshots(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    first_snapshot = await db_session.scalar(
        select(OpportunitySnapshot)
        .where(OpportunitySnapshot.project_id == scn.project_id)
        .order_by(OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc())
        .limit(1)
    )
    assert first_snapshot is not None
    resolved = (await _live_rows(db_session, scn))[0]
    second_snapshot_at = first_snapshot.created_at + timedelta(seconds=1)
    resolved.superseded_at = second_snapshot_at
    db_session.add(
        OpportunitySnapshot(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            run_id=uuid.uuid4(),
            created_at=second_snapshot_at + timedelta(microseconds=1),
        )
    )
    await db_session.commit()

    grouped = await service.get_grouped_history(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    assert grouped["since_previous"] == {
        "new": 0,
        "continuing": 3,
        "resolved": 1,
    }
    resolved_group = next(
        item
        for item in grouped["items"]
        if item["rule_id"] == resolved.rule_id
        and item["target_key"] == resolved.target_key
    )
    assert resolved_group["transition"] == "resolved"
    assert resolved_group["current_state"] == "resolved"


async def test_recompute_without_sources_preserves_an_existing_live_set(
    db_session: AsyncSession,
) -> None:
    """No resolvable source must not destroy findings we already hold.

    ``_resolve_source`` only accepts a TERMINAL crawl and a dashboard-ready
    audit, so "no source" is the ordinary state while a crawl is RUNNING —
    and superseding on it emptied the Opportunities screen mid-crawl, which is
    exactly how a project with real findings showed zero results.
    """
    scn = await _seed_scenario(db_session)
    first = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert first["total_count"] == 4
    before = {row.id for row in await _live_rows(db_session, scn)}
    assert len(before) == 4

    # Take both sources out of scope the way a fresh run does: the crawl goes
    # back to running, the audit stops being dashboard-ready.
    crawl = await db_session.get(SiteCrawl, scn.crawl_id)
    assert crawl is not None
    crawl.status = CRAWL_STATUS_RUNNING
    crawl.completed_at = None
    audit = await db_session.get(Audit, scn.audit_id)
    assert audit is not None
    audit.status = AUDIT_STATUS_RUNNING
    await db_session.commit()

    again = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    # The live set is untouched, and the reported snapshot is the last real
    # one — not a fabricated empty result.
    after = {row.id for row in await _live_rows(db_session, scn)}
    assert after == before
    assert again["run_id"] == first["run_id"]
    assert again["total_count"] == 4
    assert again["site_crawl_id"] == scn.crawl_id
    # No new snapshot row either: nothing was computed.
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(OpportunitySnapshot)
            .where(OpportunitySnapshot.project_id == scn.project_id)
        )
        == 1
    )


async def test_recompute_with_a_source_but_no_hits_still_supersedes(
    db_session: AsyncSession,
) -> None:
    """Zero hits WITH a source is a real result (a clean project) and applies.

    The guard above keys on absent SOURCES, never on an empty hit list — a
    project whose issues were genuinely fixed must still see its opportunities
    close.
    """
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert len(await _live_rows(db_session, scn)) == 4

    # Drop the evidence the detectors fire on, keeping the sources resolvable.
    await db_session.execute(
        delete(SiteIssue).where(SiteIssue.crawl_id == scn.crawl_id)
    )
    await db_session.execute(
        delete(Citation).where(Citation.analysis_id.in_([scn.analysis0_id]))
    )
    await db_session.commit()

    result = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert result["site_crawl_id"] == scn.crawl_id
    site_rows = [
        row
        for row in await _live_rows(db_session, scn)
        if row.opportunity_type == "site"
    ]
    assert site_rows == []


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

    result = await service.recompute(
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
    newer = Audit(
        workspace_id=workspace_id,
        project_id=project_id,
        status=AUDIT_STATUS_COMPLETED,
        completed_at=datetime.now(UTC),
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

    result = await service.recompute(
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
        await service.recompute(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            audit_id=foreign_audit.id,
        )


async def test_missing_project_is_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(OpportunityNotFoundError):
        await service.recompute(
            db_session, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
        )
    with pytest.raises(OpportunityNotFoundError):
        await service.list_opportunities(
            db_session, workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
        )


async def test_disabled_rule_persists_nothing(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    scn = await _seed_scenario(db_session)
    monkeypatch.setattr(OPPORTUNITY_RULES_BY_ID["thin_content"], "enabled", False)

    result = await service.recompute(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    first_rows = await _live_rows(db_session, scn)
    first_brand = _by_rule(first_rows, "brand_absent_high_value_prompt")
    first_thin = _by_rule(first_rows, "thin_content")
    first_structured = _by_rule(first_rows, "missing_structured_data")
    first_structured_evidence = dict(first_structured.evidence or {})

    # Human workflow state set between runs must survive the supersede.
    await service.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=first_brand.id,
        status="in_progress",
    )
    await service.update_status(
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

    result = await service.recompute(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")
    evidence_before = dict(thin.evidence or {})

    item = await service.update_status(
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
        await service.update_status(
            db_session,
            workspace_id=scn.workspace_id,
            changed_by_user_id=scn.user_id,
            opportunity_id=thin.id,
            status="bogus",
        )
    with pytest.raises(OpportunityNotFoundError):
        await service.update_status(
            db_session,
            workspace_id=scn.workspace_id,
            changed_by_user_id=scn.user_id,
            opportunity_id=uuid.uuid4(),
            status="resolved",
        )

    # Supersede the row, then a mutation is a coded conflict.
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    await db_session.refresh(thin)
    assert thin.superseded_at is not None
    with pytest.raises(OpportunitySupersededError) as excinfo:
        await service.update_status(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    ordered_ids = [row.id for row in reversed(rows)]

    response = await service.update_order(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        ordered_opportunity_ids=ordered_ids,
        expected_version=0,
        updated_by_user_id=scn.user_id,
    )
    assert response == {"version": 1, "ordered_opportunity_ids": ordered_ids}
    page = await service.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert [item["id"] for item in page["items"]] == ordered_ids
    assert all(item["order_source"] == "manual" for item in page["items"])

    with pytest.raises(OpportunityOrderConflictError):
        await service.update_order(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            ordered_opportunity_ids=ordered_ids,
            expected_version=0,
            updated_by_user_id=scn.user_id,
        )

    target = rows[0]
    await service.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=target.id,
        status="resolved",
        changed_by_user_id=scn.user_id,
    )
    await service.update_status(
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

    assert service._stable_key(left) != service._stable_key(right)
    assert json.loads(service._stable_key(left)) == ["rule:target", "key"]


# =========================================================================
# Read projections: list / detail / summary / export rows
# =========================================================================
async def test_list_ordering_filters_and_keyset_pagination(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    page = await service.list_opportunities(
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

    page1 = await service.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        limit=2,
    )
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None
    page2 = await service.list_opportunities(
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
        await service.list_opportunities(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            limit=2,
            cursor=page1["next_cursor"],
            severity="high",
        )
    with pytest.raises(InvalidCursorError):
        await service.list_opportunities(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            cursor="not-a-real-cursor",
        )

    by_type = await service.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        opportunity_type="site",
    )
    assert {item["rule_id"] for item in by_type["items"]} == {
        "missing_structured_data",
        "thin_content",
    }
    by_severity = await service.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        severity="high",
    )
    assert [item["rule_id"] for item in by_severity["items"]] == [
        "brand_absent_high_value_prompt"
    ]
    by_floor = await service.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        min_priority=50.0,
    )
    assert [item["priority_score"] for item in by_floor["items"]] == [
        SCORE_BRAND_ABSENT,
        SCORE_OWNED_PAGE,
    ]
    by_rule = await service.list_opportunities(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        rule_id="thin_content",
    )
    assert len(by_rule["items"]) == 1
    dismissed = await service.list_opportunities(
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
            await service.list_opportunities(
                db_session,
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                **kwargs,
            )


async def test_list_defaults_to_active_statuses(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")
    await service.update_status(
        db_session,
        workspace_id=scn.workspace_id,
        changed_by_user_id=scn.user_id,
        opportunity_id=thin.id,
        status="dismissed",
    )

    default_page = await service.list_opportunities(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert len(default_page["items"]) == 3
    assert all(item["rule_id"] != "thin_content" for item in default_page["items"])
    dismissed_page = await service.list_opportunities(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    rows = await _live_rows(db_session, scn)
    thin = _by_rule(rows, "thin_content")

    detail = await service.get_opportunity(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    detail = await service.get_opportunity(
        db_session, workspace_id=scn.workspace_id, opportunity_id=thin.id
    )
    assert detail["superseded_at"] is not None
    assert detail["superseded_by_id"] is not None

    with pytest.raises(OpportunityNotFoundError):
        await service.get_opportunity(
            db_session, workspace_id=scn.workspace_id, opportunity_id=uuid.uuid4()
        )


async def test_summary_before_and_after_recompute(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)

    before = await service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert before["computed"] is False
    assert before["counts_by_type"] == {}
    assert before["total_count"] == 0
    assert before["run_id"] is None
    assert before["analyzer_version"] == ANALYZER_VERSION
    assert before["rule_version"] == RULE_VERSION
    assert before["formula_version"] == FORMULA_VERSION

    result = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    after = await service.get_summary(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    rows = await service.load_export_rows(
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

    site_only = await service.load_export_rows(
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
        await service.load_export_rows(
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
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    page = await service.list_opportunities(
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
    detail = await service.get_opportunity(
        db_session, workspace_id=scn.workspace_id, opportunity_id=brand_absent.id
    )
    # The detail inherits the item projection's label (featured card source).
    assert detail["target_label"] == "best crm for small teams"


# =========================================================================
# C3: commerce-derived rules over persisted product evidence
# =========================================================================
async def test_commerce_rules_fire_from_persisted_product_evidence(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    product_zero_id = uuid.uuid4()
    product_mismatch_id = uuid.uuid4()
    competitor_dom_id = uuid.uuid4()

    audit = await db_session.get(Audit, scn.audit_id)
    assert audit is not None
    # The planner freezes the catalog identity into the audit at creation.
    audit.configuration = {
        "products": [
            {"id": str(product_zero_id), "sku": "SUMMIT-40", "name": "Summit 40L"},
            {
                "id": str(product_mismatch_id),
                "sku": "VOYAGER-25",
                "name": "Voyager 25L",
            },
        ],
        "competitor_products": [
            {
                "id": str(competitor_dom_id),
                "competitor_name": "TrailBlaze",
                "name": "TrailBlaze Alpine 45",
            }
        ],
    }

    def _product_snapshot(
        entry_id: str,
        *,
        kind: str,
        mention_count: int,
        sov_share: float,
        mismatch: float | None = None,
    ) -> ProductMetricSnapshot:
        # FK columns stay null (the deleted-catalog shape): identity keys off
        # the frozen metrics["entry_id"], like the finalize write path.
        return ProductMetricSnapshot(
            workspace_id=scn.workspace_id,
            audit_id=scn.audit_id,
            project_id=scn.project_id,
            product_analyzer_version=PRODUCT_ANALYZER_VERSION,
            product_scoring_rule_version=PRODUCT_SCORING_RULE_VERSION,
            mention_count=mention_count,
            sov_share=sov_share,
            price_mismatch_rate=mismatch,
            metrics={"entry_id": entry_id, "kind": kind},
            source_analysis_ids=[str(scn.analysis0_id)],
        )

    db_session.add_all(
        [
            _product_snapshot(
                str(product_zero_id), kind="product", mention_count=0, sov_share=0.0
            ),
            _product_snapshot(
                str(product_mismatch_id),
                kind="product",
                mention_count=4,
                sov_share=0.2,
                mismatch=0.5,
            ),
            _product_snapshot(
                str(competitor_dom_id),
                kind="competitor_product",
                mention_count=9,
                sov_share=0.8,
            ),
        ]
    )
    await db_session.flush()

    result = await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert result["total_count"] == 7

    rows = await _live_rows(db_session, scn)
    not_mentioned = _by_rule(rows, "product_not_mentioned")
    assert not_mentioned.target_key == f"product:{product_zero_id}"
    assert not_mentioned.opportunity_type == "visibility"
    assert not_mentioned.severity == "high"
    assert not_mentioned.priority_score == 30.0
    assert not_mentioned.evidence is not None
    assert not_mentioned.evidence["product_name"] == "Summit 40L"
    assert not_mentioned.evidence["mention_count"] == 0
    assert not_mentioned.evidence["audit_id"] == str(scn.audit_id)
    assert len(not_mentioned.source_metric_ids) == 1
    # The mentioned product never fires the zero-mention rule.
    assert all(
        row.target_key != f"product:{product_mismatch_id}"
        or row.rule_id != "product_not_mentioned"
        for row in rows
    )

    dominates = _by_rule(rows, "competitor_product_dominates")
    assert dominates.target_key == f"competitor-product:{competitor_dom_id}"
    assert dominates.priority_score == 30.0
    assert dominates.evidence is not None
    assert dominates.evidence["competitor_name"] == "TrailBlaze"
    assert dominates.evidence["sov_share"] == 0.8

    mismatch = _by_rule(rows, "price_mention_mismatch")
    assert mismatch.target_key == f"product:{product_mismatch_id}"
    assert mismatch.priority_score == 20.0
    assert mismatch.evidence is not None
    assert mismatch.evidence["price_mismatch_rate"] == 0.5
    # (rule_id, target_key) dedup keeps exactly one row per rule per target —
    # ``_by_rule`` above asserts exact singleness for each commerce rule.


# =========================================================================
# C4(c): read-time staleness on the summary projection
# =========================================================================
async def test_summary_staleness_is_read_time(db_session: AsyncSession) -> None:
    scn = await _seed_scenario(db_session)
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    summary = await service.get_summary(
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
    summary = await service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert summary["stale"] is True

    # A refresh clears it (the snapshot is newer than the evidence again).
    await service.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    summary = await service.get_summary(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert summary["stale"] is False


async def test_summary_stale_is_false_when_never_computed(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    summary = await service.get_summary(
        db_session, workspace_id=workspace_id, project_id=project_id
    )
    assert summary["computed"] is False
    assert summary["stale"] is False
    assert summary["evidence_updated_at"] is None
