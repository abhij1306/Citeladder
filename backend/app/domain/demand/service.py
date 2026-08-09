"""Queued Demand projection writes and projection-only reads."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, cast

from sqlalchemy import select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.demand import (
    DEMAND_ANALYZER_VERSION,
    DEMAND_FORMULA_VERSION,
    DEMAND_LIST_DEFAULT_LIMIT,
    DEMAND_LIST_MAX_LIMIT,
    DEMAND_PACK_JOURNEYS,
    DEMAND_RULE_VERSION,
    JOURNEY_SOURCE_PACK,
)
from app.core.config.prompts import PROMPT_STATUS_ACTIVE
from app.domain.demand.projection import (
    DemandSignalCandidate,
    SearchDemandInput,
    detect_question_gap_signals,
    detect_search_signals,
    stable_hash,
)
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit
from app.models.demand import (
    DemandSignal,
    DemandSnapshot,
    JourneyDefinition,
    JourneyDefinitionVersion,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.site_health import SiteHealthSnapshot
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot


async def _traffic_source(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> tuple[TrafficSnapshot | None, list[SearchDemandInput], dict[str, Any]]:
    snapshot = await session.scalar(
        select(TrafficSnapshot)
        .where(
            TrafficSnapshot.workspace_id == workspace_id,
            TrafficSnapshot.project_id == project_id,
            TrafficSnapshot.window_start == window_start,
            TrafficSnapshot.window_end == window_end,
            TrafficSnapshot.granularity == "day",
        )
        .order_by(TrafficSnapshot.created_at.desc(), TrafficSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return (
            None,
            [],
            {
                "state": "unavailable",
                "total_pages": 0,
                "matched_pages": 0,
                "join_rate": None,
                "unmatched_reasons": ["traffic_snapshot_unavailable"],
                "key_events": {"state": "unavailable", "value": None},
            },
        )
    query_rows = list(
        (
            await session.scalars(
                select(TrafficQueryStat).where(
                    TrafficQueryStat.workspace_id == workspace_id,
                    TrafficQueryStat.project_id == project_id,
                    TrafficQueryStat.snapshot_id == snapshot.id,
                )
            )
        ).all()
    )
    page_rows = list(
        (
            await session.scalars(
                select(TrafficPageStat).where(
                    TrafficPageStat.workspace_id == workspace_id,
                    TrafficPageStat.project_id == project_id,
                    TrafficPageStat.snapshot_id == snapshot.id,
                )
            )
        ).all()
    )
    inputs = _search_inputs(query_rows, page_rows)
    return snapshot, inputs, _page_identity(page_rows)


def _search_inputs(
    query_rows: list[TrafficQueryStat], page_rows: list[TrafficPageStat]
) -> list[SearchDemandInput]:
    inputs: list[SearchDemandInput] = []
    for kind, target, row in [
        *(("query", row.normalized_query, row) for row in query_rows),
        *(("page", row.canonical_url, row) for row in page_rows),
    ]:
        row = cast(Any, row)
        metrics = row.metrics or {}
        impressions = metrics.get("impressions")
        clicks = metrics.get("clicks")
        if isinstance(impressions, int | float) and isinstance(clicks, int | float):
            inputs.append(
                SearchDemandInput(
                    tuple(row.source_metric_row_ids or []),
                    tuple(row.source_artifact_ids or []),
                    kind,
                    target,
                    int(impressions),
                    int(clicks),
                )
            )
    return inputs


def _page_identity(page_rows: list[TrafficPageStat]) -> dict[str, Any]:
    matched_pages = sum(row.site_url_id is not None for row in page_rows)
    key_event_values = [
        float((row.metrics or {})["key_events"])
        for row in page_rows
        if isinstance((row.metrics or {}).get("key_events"), int | float)
    ]
    total_pages = len(page_rows)
    page_identity = {
        "state": "observed",
        "total_pages": total_pages,
        "matched_pages": matched_pages,
        "join_rate": (round(matched_pages / total_pages, 6) if total_pages else None),
        "unmatched_reasons": (
            ["canonical_url_not_in_site_inventory"]
            if matched_pages < total_pages
            else []
        ),
        "key_events": (
            {
                "state": "observed",
                "value": sum(key_event_values),
                "interpretation": (
                    "observed_zero_limited_evidence"
                    if sum(key_event_values) == 0
                    else "observed_nonzero"
                ),
            }
            if key_event_values
            else {"state": "unavailable", "value": None}
        ),
    }
    return page_identity


async def _prompt_portfolio(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict[str, Any]:
    rows = list(
        (
            await session.scalars(
                select(Prompt)
                .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
                .join(Project, Project.id == PromptSet.project_id)
                .where(
                    Project.workspace_id == workspace_id,
                    PromptSet.project_id == project_id,
                    Prompt.status == PROMPT_STATUS_ACTIVE,
                )
            )
        ).all()
    )
    by_intent: dict[str, int] = {}
    by_cohort: dict[str, int] = {}
    grounded = 0
    for row in rows:
        by_intent[row.intent or "unknown"] = (
            by_intent.get(row.intent or "unknown", 0) + 1
        )
        by_cohort[row.cohort or "unknown"] = (
            by_cohort.get(row.cohort or "unknown", 0) + 1
        )
        evidence = row.generation_evidence or {}
        if evidence.get("demand_snapshot_id") or evidence.get("demand_signal_ids"):
            grounded += 1
    return {
        "active_count": len(rows),
        "demand_grounded_count": grounded,
        "by_intent": dict(sorted(by_intent.items())),
        "by_cohort": dict(sorted(by_cohort.items())),
    }


async def _latest_site_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> SiteHealthSnapshot | None:
    return await session.scalar(
        select(SiteHealthSnapshot)
        .where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
        )
        .order_by(SiteHealthSnapshot.created_at.desc(), SiteHealthSnapshot.id.desc())
        .limit(1)
    )


async def _journey_versions(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[JourneyDefinitionVersion]:
    definitions = list(
        (
            await session.scalars(
                select(JourneyDefinition).where(
                    JourneyDefinition.workspace_id == workspace_id,
                    JourneyDefinition.project_id == project_id,
                    JourneyDefinition.status == "active",
                )
            )
        ).all()
    )
    if not definitions:
        return []
    pairs = {(row.id, row.current_version) for row in definitions}
    versions = list(
        (
            await session.scalars(
                select(JourneyDefinitionVersion).where(
                    JourneyDefinitionVersion.workspace_id == workspace_id,
                    JourneyDefinitionVersion.project_id == project_id,
                    tuple_(
                        JourneyDefinitionVersion.journey_id,
                        JourneyDefinitionVersion.version,
                    ).in_(pairs),
                )
            )
        ).all()
    )
    return versions


async def _ensure_pack_journey(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    if await session.scalar(
        select(JourneyDefinition.id)
        .where(
            JourneyDefinition.workspace_id == workspace_id,
            JourneyDefinition.project_id == project_id,
        )
        .limit(1)
    ):
        return
    pack_id = await session.scalar(
        select(Project.industry_pack_id).where(
            Project.workspace_id == workspace_id, Project.id == project_id
        )
    )
    definition = DEMAND_PACK_JOURNEYS.get(pack_id or "")
    if definition is None:
        return
    candidate_id = uuid.uuid4()
    inserted_id = await session.scalar(
        pg_insert(JourneyDefinition)
        .values(
            id=candidate_id,
            workspace_id=workspace_id,
            project_id=project_id,
            slug=definition["slug"],
            name=definition["name"],
            status="active",
            current_version=1,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "slug"])
        .returning(JourneyDefinition.id)
    )
    journey = await session.scalar(
        select(JourneyDefinition).where(
            JourneyDefinition.workspace_id == workspace_id,
            JourneyDefinition.project_id == project_id,
            JourneyDefinition.slug == definition["slug"],
        )
    )
    if journey is None:
        raise RuntimeError("journey insert conflict did not resolve an existing row")
    if inserted_id is not None:
        await session.execute(
            pg_insert(JourneyDefinitionVersion)
            .values(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                project_id=project_id,
                journey_id=journey.id,
                version=1,
                definition=definition,
                source_kind=JOURNEY_SOURCE_PACK,
                source_version="demand-pack-journeys-1",
            )
            .on_conflict_do_nothing(index_elements=["journey_id", "version"])
        )


async def _visibility_audits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[Audit]:
    return list(
        (
            await session.scalars(
                select(Audit)
                .where(
                    Audit.workspace_id == workspace_id,
                    Audit.project_id == project_id,
                    Audit.status.in_(
                        {AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED}
                    ),
                )
                .order_by(Audit.created_at.desc(), Audit.id.desc())
                .limit(2)
            )
        ).all()
    )


def _question_rows(snapshot: SiteHealthSnapshot | None) -> list[dict[str, Any]]:
    if snapshot is None or not snapshot.intelligence:
        return []
    coverage = snapshot.intelligence.get("coverage")
    if not isinstance(coverage, dict):
        return []
    questions = coverage.get("questions")
    return (
        [row for row in questions if isinstance(row, dict)]
        if isinstance(questions, list)
        else []
    )


def _source_material(
    *,
    window_start: date,
    window_end: date,
    traffic: TrafficSnapshot | None,
    search_inputs: list[SearchDemandInput],
    site: SiteHealthSnapshot | None,
    journeys: list[JourneyDefinitionVersion],
    audits: list[Audit],
    page_identity: dict[str, Any],
    prompt_portfolio: dict[str, Any],
) -> dict[str, Any]:
    metric_ids = sorted(
        {item for row in search_inputs for item in row.source_metric_row_ids}
    )
    return {
        "window": [window_start.isoformat(), window_end.isoformat()],
        "traffic_snapshot_id": str(traffic.id) if traffic else None,
        "site_snapshot_id": str(site.id) if site else None,
        "journey_version_ids": sorted(str(row.id) for row in journeys),
        "audit_ids": sorted(str(row.id) for row in audits),
        "metric_ids": metric_ids,
        "page_identity": page_identity,
        "prompt_portfolio": prompt_portfolio,
        "analyzer_version": DEMAND_ANALYZER_VERSION,
        "formula_version": DEMAND_FORMULA_VERSION,
    }


def _detect_candidates(
    search_inputs: list[SearchDemandInput], site: SiteHealthSnapshot | None
) -> list[DemandSignalCandidate]:
    candidates = detect_search_signals(search_inputs)
    if site is not None:
        candidates.extend(
            detect_question_gap_signals(_question_rows(site), site_snapshot_id=site.id)
        )
    return candidates


def _visibility_outcome(audits: list[Audit]) -> dict[str, Any]:
    return {
        "state": "observed" if audits else "unavailable",
        "sample_size": len(audits),
        "latest_audit_id": str(audits[0].id) if audits else None,
        "prior_audit_id": str(audits[1].id) if len(audits) > 1 else None,
        "latest_completed_at": (
            audits[0].completed_at.isoformat()
            if audits and audits[0].completed_at
            else None
        ),
        "comparison": "descriptive_only",
        "limitation": (
            "No completed Visibility audit is available."
            if not audits
            else "Audit outcomes are not causal evidence of a content or site change."
        ),
    }


def _snapshot_row(
    *,
    task: AnalyticsTask,
    window_start: date,
    window_end: date,
    source_hash: str,
    traffic: TrafficSnapshot | None,
    site: SiteHealthSnapshot | None,
    journeys: list[JourneyDefinitionVersion],
    audits: list[Audit],
    page_identity: dict[str, Any],
    prompt_portfolio: dict[str, Any],
    candidates: list[DemandSignalCandidate],
    metric_ids: list[str],
    artifact_ids: list[str],
    prior: DemandSnapshot | None,
) -> DemandSnapshot:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.signal_type] = counts.get(candidate.signal_type, 0) + 1
    comparison = None
    if prior is not None:
        comparison = {
            "prior_snapshot_id": str(prior.id),
            "signal_count_delta": len(candidates)
            - int((prior.summary or {}).get("signal_count", 0)),
            "causality": "not_asserted",
        }
    return DemandSnapshot(
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        window_start=window_start,
        window_end=window_end,
        source_hash=source_hash,
        site_snapshot_id=site.id if site else None,
        prior_snapshot_id=prior.id if prior else None,
        source_artifact_ids=artifact_ids,
        source_metric_row_ids=metric_ids,
        source_audit_ids=sorted(str(row.id) for row in audits),
        journey_version_ids=sorted(str(row.id) for row in journeys),
        coverage={
            "search": "observed" if traffic else "unavailable",
            "site": "observed" if site and site.intelligence else "unavailable",
            "journeys": "configured" if journeys else "unavailable",
            "visibility": "observed" if audits else "unavailable",
            "page_identity": page_identity,
        },
        summary={
            "signal_count": len(candidates),
            "counts_by_type": counts,
            "prompt_portfolio": prompt_portfolio,
            "visibility_outcome": _visibility_outcome(audits),
        },
        comparison=comparison,
        formula_version=DEMAND_FORMULA_VERSION,
        analyzer_version=DEMAND_ANALYZER_VERSION,
    )


def _add_signals(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    snapshot: DemandSnapshot,
    candidates: list[DemandSignalCandidate],
) -> None:
    session.add_all(
        [
            DemandSignal(
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                snapshot_id=snapshot.id,
                identity_hash=candidate.identity_hash,
                signal_type=candidate.signal_type,
                state=candidate.state,
                topic_cluster=candidate.topic_cluster,
                page_url=candidate.page_url,
                evidence=candidate.evidence,
                metrics=candidate.metrics,
                coverage=candidate.coverage,
                limitations=candidate.limitations,
                priority_score=candidate.priority_score,
                priority_inputs=candidate.priority_inputs,
                analyzer_version=DEMAND_ANALYZER_VERSION,
                rule_version=DEMAND_RULE_VERSION,
                formula_version=DEMAND_FORMULA_VERSION,
            )
            for candidate in candidates
        ]
    )


async def recompute_demand(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    if task.project_id is None:
        raise ValueError("demand snapshot refresh requires project_id")
    payload = task.payload or {}
    window_start = date.fromisoformat(str(payload["window_start"]))
    window_end = date.fromisoformat(str(payload["window_end"]))
    async with session_factory() as session:
        await _ensure_pack_journey(
            session, workspace_id=task.workspace_id, project_id=task.project_id
        )
        await session.flush()
        traffic, search_inputs, page_identity = await _traffic_source(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
        )
        site = await _latest_site_snapshot(
            session, workspace_id=task.workspace_id, project_id=task.project_id
        )
        journeys = await _journey_versions(
            session, workspace_id=task.workspace_id, project_id=task.project_id
        )
        audits = await _visibility_audits(
            session, workspace_id=task.workspace_id, project_id=task.project_id
        )
        prompt_portfolio = await _prompt_portfolio(
            session, workspace_id=task.workspace_id, project_id=task.project_id
        )
        candidates = _detect_candidates(search_inputs, site)
        metric_ids = sorted(
            {item for row in search_inputs for item in row.source_metric_row_ids}
        )
        artifact_ids = sorted(
            {item for row in search_inputs for item in row.source_artifact_ids}
        )
        source_material = _source_material(
            window_start=window_start,
            window_end=window_end,
            traffic=traffic,
            search_inputs=search_inputs,
            site=site,
            journeys=journeys,
            audits=audits,
            page_identity=page_identity,
            prompt_portfolio=prompt_portfolio,
        )
        source_hash = stable_hash(source_material)
        if await session.scalar(
            select(DemandSnapshot.id).where(
                DemandSnapshot.project_id == task.project_id,
                DemandSnapshot.source_hash == source_hash,
            )
        ):
            return
        prior = await session.scalar(
            select(DemandSnapshot)
            .where(
                DemandSnapshot.workspace_id == task.workspace_id,
                DemandSnapshot.project_id == task.project_id,
            )
            .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
            .limit(1)
        )
        snapshot = _snapshot_row(
            task=task,
            window_start=window_start,
            window_end=window_end,
            source_hash=source_hash,
            traffic=traffic,
            site=site,
            journeys=journeys,
            audits=audits,
            page_identity=page_identity,
            prompt_portfolio=prompt_portfolio,
            candidates=candidates,
            metric_ids=metric_ids,
            artifact_ids=artifact_ids,
            prior=prior,
        )
        session.add(snapshot)
        await session.flush()
        _add_signals(session, task=task, snapshot=snapshot, candidates=candidates)
        from app.domain.opportunities.service import enqueue_opportunity_refresh

        await enqueue_opportunity_refresh(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            trigger_kind="demand_snapshot",
            trigger_id=snapshot.id,
        )
        await session.commit()


async def list_snapshots(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int = DEMAND_LIST_DEFAULT_LIMIT,
) -> list[DemandSnapshot]:
    return list(
        (
            await session.scalars(
                select(DemandSnapshot)
                .where(
                    DemandSnapshot.workspace_id == workspace_id,
                    DemandSnapshot.project_id == project_id,
                )
                .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
                .limit(limit)
            )
        ).all()
    )


async def demand_source_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> str:
    """Stable queue revision for the exact currently persisted source set."""
    traffic, search_inputs, page_identity = await _traffic_source(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    site = await _latest_site_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    journeys = await _journey_versions(
        session, workspace_id=workspace_id, project_id=project_id
    )
    audits = await _visibility_audits(
        session, workspace_id=workspace_id, project_id=project_id
    )
    prompt_portfolio = await _prompt_portfolio(
        session, workspace_id=workspace_id, project_id=project_id
    )
    return stable_hash(
        _source_material(
            window_start=window_start,
            window_end=window_end,
            traffic=traffic,
            search_inputs=search_inputs,
            site=site,
            journeys=journeys,
            audits=audits,
            page_identity=page_identity,
            prompt_portfolio=prompt_portfolio,
        )
    )[:24]


async def get_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> DemandSnapshot | None:
    return await session.scalar(
        select(DemandSnapshot).where(
            DemandSnapshot.id == snapshot_id,
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
    )


async def list_signals(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    limit: int = DEMAND_LIST_MAX_LIMIT,
) -> list[DemandSignal]:
    return list(
        (
            await session.scalars(
                select(DemandSignal)
                .where(
                    DemandSignal.workspace_id == workspace_id,
                    DemandSignal.project_id == project_id,
                    DemandSignal.snapshot_id == snapshot_id,
                )
                .order_by(
                    DemandSignal.priority_score.desc().nullslast(), DemandSignal.id
                )
                .limit(limit)
            )
        ).all()
    )
