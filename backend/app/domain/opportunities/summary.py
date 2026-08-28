"""Persisted Opportunity snapshot summary and read-time freshness."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.source_mix import empty_source_projection
from app.core.config.analytics import ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    FORMULA_VERSION,
    RULE_VERSION,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
)
from app.domain.opportunities.common import (
    _AUDIT_NOT_FOUND,
    _CRAWL_NOT_FOUND,
    _iso,
    _require_project,
)
from app.domain.opportunities.recompute import _latest_snapshot, _resolve_source
from app.domain.opportunities.snapshot_projection import project_snapshot
from app.models.analysis import MetricSnapshot
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit
from app.models.demand import DemandSnapshot
from app.models.opportunity import OpportunitySnapshot
from app.models.site_health.crawl import SiteCrawl

_DASHBOARD_READY_STATUSES = (AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED)
_EVIDENCE_CRAWL_STATUSES = (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_CANCELLED,
)


async def _resolve_scored_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Audit | None:
    audit = await _resolve_source(
        session,
        Audit,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=None,
        ready_statuses=_DASHBOARD_READY_STATUSES,
        not_found_detail=_AUDIT_NOT_FOUND,
    )
    if audit is None:
        return None
    has_snapshot = await session.scalar(
        select(MetricSnapshot.id).where(
            MetricSnapshot.audit_id == audit.id,
            MetricSnapshot.workspace_id == workspace_id,
        )
    )
    return audit if has_snapshot is not None else None


async def _latest_evidence(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[datetime | None, DemandSnapshot | None]:
    audit = await _resolve_scored_audit(
        session, workspace_id=workspace_id, project_id=project_id
    )
    crawl = await _resolve_source(
        session,
        SiteCrawl,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=None,
        ready_statuses=_EVIDENCE_CRAWL_STATUSES,
        not_found_detail=_CRAWL_NOT_FOUND,
    )
    demand_snapshot = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
        .limit(1)
    )
    stamps = [
        stamp
        for stamp in (
            (audit.completed_at or audit.created_at) if audit is not None else None,
            (crawl.completed_at or crawl.created_at) if crawl is not None else None,
            demand_snapshot.created_at if demand_snapshot is not None else None,
        )
        if stamp is not None
    ]
    return (max(stamps) if stamps else None), demand_snapshot


async def get_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """Project the latest snapshot and derive freshness without writes."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    snapshot = await _latest_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    evidence_at, demand_snapshot = await _latest_evidence(
        session, workspace_id=workspace_id, project_id=project_id
    )
    stale = _summary_is_stale(snapshot, evidence_at, demand_snapshot)
    refresh_task = await session.scalar(
        select(AnalyticsTask)
        .where(
            AnalyticsTask.workspace_id == workspace_id,
            AnalyticsTask.project_id == project_id,
            AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
        )
        .order_by(AnalyticsTask.created_at.desc(), AnalyticsTask.id.desc())
        .limit(1)
    )
    activation_state = _activation_state(
        evidence_at=evidence_at,
        snapshot=snapshot,
        stale=stale,
        refresh_task=refresh_task,
    )
    if snapshot is None:
        return {
            "computed": False,
            "run_id": None,
            "audit_id": None,
            "site_crawl_id": None,
            "demand_snapshot_id": None,
            "demand_source_revision": None,
            "coverage": {},
            "limitations": [],
            "source_mix": empty_source_projection(),
            "action_path_mix": empty_source_projection(),
            "domain_rollups": [],
            "counts_by_type": {},
            "counts_by_severity": {},
            "counts_by_status": {},
            "total_count": 0,
            "median_priority": None,
            "analyzer_version": ANALYZER_VERSION,
            "rule_version": RULE_VERSION,
            "formula_version": FORMULA_VERSION,
            "computed_at": None,
            "evidence_updated_at": _iso(evidence_at),
            "stale": False,
            "activation_state": activation_state,
        }
    projected = project_snapshot(snapshot)
    projected.pop("id", None)
    projected["computed"] = True
    projected["computed_at"] = projected.pop("created_at")
    projected["evidence_updated_at"] = _iso(evidence_at)
    projected["stale"] = stale
    projected["activation_state"] = activation_state
    return projected


def _summary_is_stale(
    snapshot: OpportunitySnapshot | None,
    evidence_at: datetime | None,
    demand_snapshot: DemandSnapshot | None,
) -> bool:
    if snapshot is None:
        return False
    newer_evidence = evidence_at is not None and evidence_at > snapshot.created_at
    changed_demand = demand_snapshot is not None and (
        snapshot.demand_snapshot_id != demand_snapshot.id
        or snapshot.demand_source_revision != demand_snapshot.source_hash
    )
    return newer_evidence or changed_demand


def _activation_state(
    *,
    evidence_at: datetime | None,
    snapshot: OpportunitySnapshot | None,
    stale: bool,
    refresh_task: AnalyticsTask | None,
) -> str:
    if evidence_at is None:
        return "waiting_for_evidence"
    if snapshot is not None and not stale:
        return "ready"
    if refresh_task is not None and refresh_task.status in {
        TASK_STATUS_LEASED,
        TASK_STATUS_RUNNING,
    }:
        return "refreshing"
    if refresh_task is not None and refresh_task.status in {
        TASK_STATUS_RETRY_WAIT,
        TASK_STATUS_FAILED,
    }:
        return "delayed"
    return "queued"
