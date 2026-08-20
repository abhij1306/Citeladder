"""Opportunity recompute, source coverage, guidance, and history scenarios."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.analytics import ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH
from app.core.config.audits import AUDIT_STATUS_RUNNING
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    FORMULA_VERSION,
    RULE_VERSION,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_RUNNING,
)
from app.core.config.source_patterns import SOURCE_TAXONOMY_VERSION
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.domain.opportunities import (
    guidance,
    queue,
    recompute,
)
from app.domain.opportunities import (
    history as history_service,
)
from app.domain.opportunities import (
    summary as summary_service,
)
from app.domain.opportunities.errors import (
    OpportunityGuidanceIdempotencyConflictError,
    OpportunityGuidanceUnavailableError,
)
from app.models.analysis import Citation
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit
from app.models.demand import DemandSignal, DemandSnapshot
from app.models.opportunity import (
    Opportunity,
    OpportunitySnapshot,
)
from app.models.site_health.analysis import SiteIssue
from app.models.site_health.crawl import SiteCrawl
from tests.component.opportunity_helpers import (
    SCORE_BRAND_ABSENT,
    SCORE_OWNED_PAGE,
    SCORE_STRUCTURED_DATA,
    SCORE_THIN_CONTENT,
    URL_A,
    URL_B,
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
        coverage={},
        summary={},
        formula_version="demand-priority-1",
        analyzer_version="demand-analyzer-2",
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

    first = await recompute.recompute(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        skip_if_current=True,
    )
    second = await recompute.recompute(
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
    summary = await summary_service.get_summary(
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


async def test_only_approved_query_detector_signal_becomes_an_opportunity(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    demand = DemandSnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 14),
        source_hash="e" * 64,
        source_artifact_ids=[],
        source_metric_row_ids=[],
        coverage={"query_evidence": "available"},
        summary={},
        formula_version="demand-priority-1",
        analyzer_version="demand-analyzer-3",
    )
    db_session.add(demand)
    await db_session.flush()
    source_metric_id = str(uuid.uuid4())
    common = {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "snapshot_id": demand.id,
        "state": "active",
        "page_url": "https://example.com/guide",
        "evidence": {
            "target_kind": "query",
            "target": "answer engine guide",
            "resolved_page_url": "https://example.com/guide",
            "source_metric_row_ids": [source_metric_id],
        },
        "metrics": {"impressions": 100, "position": 7.0},
        "coverage": {"query_evidence": "observed"},
        "limitations": [],
        "priority_score": 60,
        "priority_inputs": {},
        "analyzer_version": "demand-analyzer-3",
        "rule_version": "demand-rules-3",
        "formula_version": "demand-priority-1",
    }
    db_session.add_all(
        [
            DemandSignal(
                **common,
                identity_hash="t" * 64,
                signal_type="striking_distance",
                topic_cluster="answer engine guide",
            ),
            DemandSignal(
                **common,
                identity_hash="b" * 64,
                signal_type="branded_query_performance",
                topic_cluster="example guide",
            ),
        ]
    )
    await db_session.commit()

    await recompute.recompute(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        skip_if_current=False,
    )

    opportunities = list(
        (
            await db_session.scalars(
                select(Opportunity).where(
                    Opportunity.project_id == project_id,
                    Opportunity.superseded_at.is_(None),
                )
            )
        ).all()
    )
    demand_rows = [
        row for row in opportunities if row.rule_id == "striking_distance_query"
    ]
    assert len(demand_rows) == 1
    assert demand_rows[0].target_url == "https://example.com/guide"
    assert demand_rows[0].target_theme == "answer engine guide"


async def test_automatic_refresh_task_is_unique_and_manual_success_is_ready(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    for _ in range(2):
        await queue.enqueue_opportunity_refresh(
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
        await summary_service.get_summary(
            db_session,
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
        )
    )["activation_state"] == "delayed"

    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert (
        await summary_service.get_summary(
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

    result = await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )

    assert result["total_count"] == 4
    assert result["run_id"] is not None
    assert result["audit_id"] == scn.audit_id
    assert result["site_crawl_id"] == scn.crawl_id
    assert result["counts_by_type"] == {
        "commerce": 0,
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
    # The observed source pattern is projected from the PERSISTED citation rows
    # the seed wrote (one competitor-matched globex.com citation) — it must
    # survive the whole detector -> persistence path, not just the pure layer.
    source_pattern = brand_absent.evidence["source_pattern"]
    assert source_pattern["taxonomy_version"] == SOURCE_TAXONOMY_VERSION
    assert source_pattern["distinct_domain_count"] == 1
    assert source_pattern["class_counts"] == {"competitor_owned": 1}
    assert source_pattern["competitor_source_domains"] == {"Globex": ["globex.com"]}
    assert source_pattern["observed_patterns"] == ["competitor_owned_sources_cited"]
    assert source_pattern["top_citations"][0]["url"] == "https://globex.com/crm"
    assert source_pattern["recommended_action"] == "investigate_competitor_sources"
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


async def test_cancelled_site_evidence_freezes_coverage_and_limitations(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    crawl = await db_session.get(SiteCrawl, scn.crawl_id)
    assert crawl is not None
    crawl.status = CRAWL_STATUS_CANCELLED
    crawl.analyzed_url_count = 1
    crawl.failed_url_count = 1
    crawl.analysis_requested_count = 3
    crawl.score_summary = {"selected_count": 3, "analyzed_count": 1}
    await db_session.commit()

    result = await recompute.recompute(
        db_session,
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        site_crawl_id=scn.crawl_id,
    )

    assert result["coverage"] == {
        "crawl_status": "cancelled",
        "selected_url_count": 3,
        "analyzed_url_count": 1,
        "failed_url_count": 1,
        "analysis_ratio": 0.3333,
    }
    assert result["limitations"] == [
        "Site Health evidence is partial (cancelled); "
        "only completed analyses are included.",
        "Coverage: 1 of 3 selected URLs analyzed.",
    ]
    site_rows = [
        row
        for row in await _live_rows(db_session, scn)
        if row.opportunity_type == "site"
    ]
    assert site_rows
    assert all(row.evidence["coverage"] == result["coverage"] for row in site_rows)
    assert all(
        row.evidence["limitations"] == result["limitations"] for row in site_rows
    )


async def test_recompute_without_sources_yields_empty_snapshot(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _prompt_ids = await _seed_base(db_session)
    await db_session.commit()

    result = await recompute.recompute(
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
    monkeypatch.setattr(settings, "app_env", "development")
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    opportunity = _by_rule(
        await _live_rows(db_session, scn), "brand_absent_high_value_prompt"
    )
    grouped = await history_service.get_grouped_history(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert grouped["since_previous"] == {"new": 0, "continuing": 4, "resolved": 0}
    assert all(item["occurrence_count"] == 1 for item in grouped["items"])
    opportunity.evidence = {"long": "x" * 1000}
    await db_session.commit()

    first, created = await guidance.create_guidance(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=opportunity.id,
        idempotency_key="guidance-1",
    )
    assert created is True
    assert first.provider == "deterministic"
    assert len(first.input_snapshot["evidence"]["long"]) < 1000
    assert len(first.input_hash) == 64

    replay, created = await guidance.create_guidance(
        db_session,
        workspace_id=scn.workspace_id,
        opportunity_id=opportunity.id,
        idempotency_key="guidance-1",
    )
    assert created is False
    assert replay.id == first.id
    history = await guidance.list_guidance_history(
        db_session, workspace_id=scn.workspace_id, opportunity_id=opportunity.id
    )
    assert [row.id for row in history] == [first.id]

    opportunity.status = "in_progress"
    await db_session.commit()
    with pytest.raises(OpportunityGuidanceIdempotencyConflictError):
        await guidance.create_guidance(
            db_session,
            workspace_id=scn.workspace_id,
            opportunity_id=opportunity.id,
            idempotency_key="guidance-1",
        )

    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(OpportunityGuidanceUnavailableError):
        await guidance.create_guidance(
            db_session,
            workspace_id=scn.workspace_id,
            opportunity_id=opportunity.id,
            idempotency_key="guidance-2",
        )


async def test_grouped_history_compares_the_latest_two_recompute_snapshots(
    db_session: AsyncSession,
) -> None:
    scn = await _seed_scenario(db_session)
    await recompute.recompute(
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

    grouped = await history_service.get_grouped_history(
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
    first = await recompute.recompute(
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

    again = await recompute.recompute(
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
    await recompute.recompute(
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

    result = await recompute.recompute(
        db_session, workspace_id=scn.workspace_id, project_id=scn.project_id
    )
    assert result["site_crawl_id"] == scn.crawl_id
    site_rows = [
        row
        for row in await _live_rows(db_session, scn)
        if row.opportunity_type == "site"
    ]
    assert site_rows == []
