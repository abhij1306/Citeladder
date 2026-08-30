"""Bounded, append-only verification of implementation declarations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
    analytics_settings,
)
from app.core.config.opportunities import (
    IMPLEMENTATION_VERIFICATION_BATCH_MAX,
    IMPLEMENTATION_VERIFIER_VERSION,
)
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.opportunities.verification_result import build_verification_result
from app.models.analysis import MetricSnapshot
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit
from app.models.opportunity import (
    OpportunityImplementationEvent,
    OpportunityVerificationEvent,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.traffic import TrafficSnapshot


@dataclass(slots=True)
class _Evaluation:
    observed: int = 0
    matched: int = 0
    contradicted: bool = False
    analysis_ids: set[uuid.UUID] = field(default_factory=set)
    rule_evaluation_ids: set[uuid.UUID] = field(default_factory=set)
    metric_ids: set[uuid.UUID] = field(default_factory=set)
    limitations: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Source:
    kind: str
    id: uuid.UUID
    observed_at: datetime


def _target_id(
    declaration: OpportunityImplementationEvent, check: dict[str, Any]
) -> uuid.UUID | None:
    raw = check.get("target_site_url_id")
    if raw is None and len(declaration.target_site_url_ids or []) == 1:
        raw = declaration.target_site_url_ids[0]
    try:
        return uuid.UUID(str(raw)) if raw is not None else None
    except ValueError:
        return None


def _expected_rule_outcome(value: object) -> object:
    if value == "pass":
        return RULE_OUTCOME_SATISFIED
    if value == "fail":
        return RULE_OUTCOME_MISSING
    return value


async def _evaluate_site_rule(
    session: AsyncSession,
    *,
    declaration: OpportunityImplementationEvent,
    analysis: SitePageAnalysis,
    check: dict[str, Any],
    result: _Evaluation,
) -> None:
    evaluation = await session.scalar(
        select(SiteRuleEvaluation).where(
            SiteRuleEvaluation.workspace_id == declaration.workspace_id,
            SiteRuleEvaluation.analysis_id == analysis.id,
            SiteRuleEvaluation.rule_id == check.get("rule_id"),
        )
    )
    if evaluation is None or evaluation.outcome not in {
        RULE_OUTCOME_SATISFIED,
        RULE_OUTCOME_MISSING,
        RULE_OUTCOME_PARTIAL,
    }:
        result.limitations.append("site_rule: no applicable evaluation")
        return
    result.observed += 1
    result.analysis_ids.add(analysis.id)
    result.rule_evaluation_ids.add(evaluation.id)
    if evaluation.outcome == _expected_rule_outcome(check.get("expected_outcome")):
        result.matched += 1
    else:
        result.contradicted = True


async def _evaluate_page_fact(
    session: AsyncSession,
    *,
    analysis: SitePageAnalysis,
    check: dict[str, Any],
    result: _Evaluation,
) -> None:
    artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
    facts = artifact.normalized_facts if artifact is not None else None
    key = str(check.get("fact_key") or "")
    if not facts or key not in facts:
        result.limitations.append(f"page_fact: {key} unavailable")
        return
    result.observed += 1
    result.analysis_ids.add(analysis.id)
    if facts[key] == check.get("expected_value"):
        result.matched += 1
    else:
        result.contradicted = True


async def _site_evidence(
    session: AsyncSession,
    *,
    declaration: OpportunityImplementationEvent,
    crawl_id: uuid.UUID,
) -> _Evaluation:
    result = _Evaluation()
    for check in declaration.expected_checks or []:
        kind = check.get("kind")
        if kind not in {"site_rule", "page_fact"}:
            result.limitations.append(f"{kind}: unavailable from a site crawl")
            continue
        target_id = _target_id(declaration, check)
        if target_id is None:
            result.limitations.append(f"{kind}: no resolved target")
            continue
        analysis = await session.scalar(
            select(SitePageAnalysis)
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .where(
                SitePageAnalysis.workspace_id == declaration.workspace_id,
                SitePageAnalysis.project_id == declaration.project_id,
                SitePageAnalysis.crawl_id == crawl_id,
                SitePageAnalysis.site_url_id == target_id,
                SitePageAnalysis.is_current.is_(True),
                SiteFetchArtifact.fetched_at > declaration.declared_implemented_at,
            )
            .order_by(SitePageAnalysis.created_at.desc(), SitePageAnalysis.id.desc())
            .limit(1)
        )
        if analysis is None:
            result.limitations.append(f"{kind}: target was not analyzed")
            continue
        if kind == "site_rule":
            await _evaluate_site_rule(
                session,
                declaration=declaration,
                analysis=analysis,
                check=check,
                result=result,
            )
        else:
            await _evaluate_page_fact(
                session, analysis=analysis, check=check, result=result
            )
    return result


async def _audit_evidence(
    session: AsyncSession,
    *,
    declaration: OpportunityImplementationEvent,
    audit_id: uuid.UUID,
) -> _Evaluation:
    result = _Evaluation()
    snapshot = await session.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.workspace_id == declaration.workspace_id,
            MetricSnapshot.project_id == declaration.project_id,
            MetricSnapshot.audit_id == audit_id,
            MetricSnapshot.created_at > declaration.declared_implemented_at,
        )
    )
    for check in declaration.expected_checks or []:
        kind = check.get("kind")
        if kind != "visibility_metric":
            result.limitations.append(f"{kind}: unavailable from an AI audit")
            continue
        _evaluate_visibility_metric(snapshot=snapshot, check=check, result=result)
    return result


async def _traffic_evidence(
    session: AsyncSession,
    *,
    declaration: OpportunityImplementationEvent,
    snapshot_id: uuid.UUID,
) -> _Evaluation:
    result = _Evaluation()
    snapshot = await session.scalar(
        select(TrafficSnapshot).where(
            TrafficSnapshot.workspace_id == declaration.workspace_id,
            TrafficSnapshot.project_id == declaration.project_id,
            TrafficSnapshot.id == snapshot_id,
            TrafficSnapshot.created_at > declaration.declared_implemented_at,
        )
    )
    totals = ((snapshot.metrics or {}).get("totals") or {}) if snapshot else {}
    for check in declaration.expected_checks or []:
        if check.get("kind") != "traffic_metric":
            result.limitations.append(
                f"{check.get('kind')}: unavailable from a traffic snapshot"
            )
            continue
        _evaluate_traffic_metric(
            snapshot=snapshot,
            totals=totals,
            check=check,
            result=result,
        )
    return result


def _evaluate_traffic_metric(
    *,
    snapshot: TrafficSnapshot | None,
    totals: dict,
    check: dict[str, Any],
    result: _Evaluation,
) -> None:
    metric_name = str(check.get("metric") or "")
    value = totals.get(metric_name)
    expected = check.get("expected_value")
    if (
        snapshot is None
        or not isinstance(value, (int, float))
        or not isinstance(expected, (int, float))
    ):
        result.limitations.append(f"traffic_metric: {metric_name} unavailable")
        return
    result.observed += 1
    result.metric_ids.add(snapshot.id)
    if _metric_matches(
        direction=check.get("direction"),
        value=float(value),
        expected=float(expected),
        tolerance=float(check.get("tolerance") or 0),
    ):
        result.matched += 1
    else:
        result.contradicted = True


def _metric_matches(
    *, direction: object, value: float, expected: float, tolerance: float
) -> bool:
    if direction == "increase":
        return value >= expected - tolerance
    if direction == "decrease":
        return value <= expected + tolerance
    return direction == "equal" and abs(value - expected) <= tolerance


def _evaluate_visibility_metric(
    *,
    snapshot: MetricSnapshot | None,
    check: dict[str, Any],
    result: _Evaluation,
) -> None:
    if snapshot is None:
        result.limitations.append("visibility_metric: no metric snapshot")
        return
    metric_name = str(check.get("metric") or "")
    value = (
        snapshot.visibility_score
        if metric_name == "visibility_score"
        else (snapshot.metrics or {}).get(metric_name)
    )
    expected = check.get("expected_value")
    if not isinstance(value, (int, float)) or not isinstance(expected, (int, float)):
        result.limitations.append(
            f"visibility_metric: {metric_name} lacks an absolute expectation"
        )
        return
    result.observed += 1
    result.metric_ids.add(snapshot.id)
    if _metric_matches(
        direction=check.get("direction"),
        value=float(value),
        expected=float(expected),
        tolerance=float(check.get("tolerance") or 0),
    ):
        result.matched += 1
    else:
        result.contradicted = True


def _observation_kind(result: _Evaluation, total_checks: int) -> str | None:
    if result.observed == 0:
        return None
    if result.contradicted:
        return "contradicted"
    if result.observed == total_checks and result.matched == total_checks:
        return "verified"
    return "observed"


async def enqueue_implementation_verification(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    trigger_kind: str,
    trigger_id: uuid.UUID,
    trigger_revision: str | None = None,
) -> None:
    idempotency_key = (
        f"implementation-verification:{trigger_kind}:{trigger_id}:"
        f"{IMPLEMENTATION_VERIFIER_VERSION}:{trigger_revision or 'terminal'}"
    )
    await session.execute(
        pg_insert(AnalyticsTask)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            task_kind=ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
            payload={"trigger_kind": trigger_kind, "trigger_id": str(trigger_id)},
            idempotency_key=idempotency_key,
            status=TASK_STATUS_QUEUED,
            max_attempts=analytics_settings.task_max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


async def enqueue_audit_opportunity_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID,
) -> None:
    """Queue both Opportunity consumers of one terminal audit."""
    from app.domain.opportunities.queue import enqueue_opportunity_refresh

    await enqueue_opportunity_refresh(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        trigger_kind="audit",
        trigger_id=audit_id,
    )
    await enqueue_implementation_verification(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        trigger_kind="audit",
        trigger_id=audit_id,
    )


async def _verification_source(
    session: AsyncSession, *, task: AnalyticsTask
) -> _Source:
    payload = task.payload or {}
    trigger_kind = str(payload.get("trigger_kind") or "")
    try:
        trigger_id = uuid.UUID(str(payload.get("trigger_id")))
    except ValueError as exc:
        raise ValueError("Implementation verification trigger is invalid") from exc
    if trigger_kind == "site_crawl":
        source = await session.scalar(
            select(SiteCrawl).where(
                SiteCrawl.workspace_id == task.workspace_id,
                SiteCrawl.project_id == task.project_id,
                SiteCrawl.id == trigger_id,
            )
        )
        observed_at = source.completed_at if source is not None else None
    elif trigger_kind == "audit":
        audit = await session.scalar(
            select(Audit).where(
                Audit.workspace_id == task.workspace_id,
                Audit.project_id == task.project_id,
                Audit.id == trigger_id,
            )
        )
        observed_at = audit.completed_at if audit is not None else None
    elif trigger_kind == "traffic_snapshot":
        snapshot = await session.scalar(
            select(TrafficSnapshot).where(
                TrafficSnapshot.workspace_id == task.workspace_id,
                TrafficSnapshot.project_id == task.project_id,
                TrafficSnapshot.id == trigger_id,
            )
        )
        observed_at = snapshot.created_at if snapshot is not None else None
    else:
        raise ValueError("Implementation verification trigger kind is invalid")
    if observed_at is None:
        raise ValueError("Implementation verification source is not terminal")
    return _Source(trigger_kind, trigger_id, observed_at)


async def _eligible_declarations(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    observed_at: datetime,
    after: tuple[datetime, uuid.UUID] | None,
) -> list[OpportunityImplementationEvent]:
    statement = select(OpportunityImplementationEvent).where(
        OpportunityImplementationEvent.workspace_id == task.workspace_id,
        OpportunityImplementationEvent.project_id == task.project_id,
        OpportunityImplementationEvent.declared_implemented_at <= observed_at,
    )
    if after is not None:
        created_at, event_id = after
        statement = statement.where(
            or_(
                OpportunityImplementationEvent.created_at > created_at,
                and_(
                    OpportunityImplementationEvent.created_at == created_at,
                    OpportunityImplementationEvent.id > event_id,
                ),
            )
        )
    return list(
        (
            await session.scalars(
                statement.order_by(
                    OpportunityImplementationEvent.created_at.asc(),
                    OpportunityImplementationEvent.id.asc(),
                ).limit(IMPLEMENTATION_VERIFICATION_BATCH_MAX)
            )
        ).all()
    )


async def _append_observation(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    declaration: OpportunityImplementationEvent,
    result: _Evaluation,
    observation_kind: str,
    source: _Source,
) -> None:
    comparison = await build_verification_result(
        session,
        declaration=declaration,
        post_audit_id=source.id if source.kind == "audit" else None,
    )
    source_revision = int(source.observed_at.timestamp() * 1_000_000)
    event_key = (
        f"verification:{declaration.id}:{source.kind}:{source.id}:"
        f"{source_revision}:{IMPLEMENTATION_VERIFIER_VERSION}"
    )
    await session.execute(
        pg_insert(OpportunityVerificationEvent)
        .values(
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            implementation_event_id=declaration.id,
            observation_kind=observation_kind,
            observed_at=source.observed_at,
            crawl_id=source.id if source.kind == "site_crawl" else None,
            audit_id=source.id if source.kind == "audit" else None,
            source_analysis_ids=[str(item) for item in result.analysis_ids],
            source_rule_evaluation_ids=[
                str(item) for item in result.rule_evaluation_ids
            ],
            source_metric_ids=[str(item) for item in result.metric_ids],
            result=comparison,
            verifier_version=IMPLEMENTATION_VERIFIER_VERSION,
            limitations=result.limitations,
            idempotency_key=event_key,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "idempotency_key"])
    )


async def verify_implementation_events(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    """Append observations for declarations with evidence after their boundary."""
    if task.project_id is None:
        raise ValueError("Implementation verification requires project_id")
    async with session_factory() as session:
        source = await _verification_source(session, task=task)
        after: tuple[datetime, uuid.UUID] | None = None
        while True:
            declarations = await _eligible_declarations(
                session, task=task, observed_at=source.observed_at, after=after
            )
            for declaration in declarations:
                if source.kind == "site_crawl":
                    result = await _site_evidence(
                        session, declaration=declaration, crawl_id=source.id
                    )
                elif source.kind == "audit":
                    result = await _audit_evidence(
                        session, declaration=declaration, audit_id=source.id
                    )
                else:
                    result = await _traffic_evidence(
                        session, declaration=declaration, snapshot_id=source.id
                    )
                kind = _observation_kind(result, len(declaration.expected_checks or []))
                if kind is not None:
                    await _append_observation(
                        session,
                        task=task,
                        declaration=declaration,
                        result=result,
                        observation_kind=kind,
                        source=source,
                    )
            if len(declarations) < IMPLEMENTATION_VERIFICATION_BATCH_MAX:
                break
            last = declarations[-1]
            after = (last.created_at, last.id)
        await session.commit()
