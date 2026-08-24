from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.audits import AUDIT_SCOPE_BRAND, AUDIT_STATUS_COMPLETED
from app.domain.analysis.schemas import RankingRow, VisibilityResponse
from app.domain.analysis.visibility import get_visibility
from app.domain.command_center.schemas import (
    CommandCenterCompetitor,
    CommandCenterFacts,
    CommandCenterLoop,
    CommandCenterMeasurement,
    CommandCenterMetric,
    CommandCenterMovement,
    CommandCenterNextAction,
    CommandCenterProject,
    CommandCenterResponse,
    CommandCenterState,
    CommandCenterTrackSummary,
    EvidenceState,
    ResolvedActionSummary,
)
from app.domain.opportunities.queries import list_opportunities
from app.domain.opportunities.schemas import OpportunityItem
from app.models.audit import Audit
from app.models.brand import BrandProfile, Competitor
from app.models.demand import DemandSnapshot
from app.models.integrations import IntegrationPropertyMapping
from app.models.opportunity import (
    Opportunity,
    OpportunityImplementationEvent,
    OpportunityOrder,
    OpportunitySnapshot,
    OpportunityStatusEvent,
)
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.site_health.crawl import SiteCrawl


@dataclass(frozen=True)
class ComparableAudits:
    selected: Audit
    previous: Audit | None


def _audit_identity(audit: Audit) -> tuple[str, frozenset[str], frozenset[str]]:
    prompts = frozenset(
        str(row.prompt_id) if row.prompt_id is not None else f"text:{row.text}"
        for row in audit.prompt_snapshots
        if row.cohort == "core"
    )
    engines = frozenset(row.logical_engine for row in audit.engine_snapshots)
    return audit.benchmark_mode, engines, prompts


def _is_prior_comparable(
    candidate: Audit, selected: Audit, selected_identity: tuple
) -> bool:
    return (
        candidate.id != selected.id
        and (candidate.completed_at or candidate.created_at)
        < (selected.completed_at or selected.created_at)
        and _audit_identity(candidate) == selected_identity
    )


async def _resolve_audits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
) -> ComparableAudits | None:
    query = (
        select(Audit)
        .options(
            selectinload(Audit.prompt_snapshots),
            selectinload(Audit.engine_snapshots),
        )
        .where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status == AUDIT_STATUS_COMPLETED,
            Audit.audit_scope == AUDIT_SCOPE_BRAND,
        )
        .order_by(Audit.completed_at.desc(), Audit.id.desc())
    )
    audits = list((await session.scalars(query)).unique().all())
    selected = next(
        (row for row in audits if audit_id is None or row.id == audit_id), None
    )
    if selected is None and audit_id is not None:
        raise LookupError("No completed audit is available for this project")
    if selected is None:
        return None
    selected_identity = _audit_identity(selected)
    previous = next(
        (
            row
            for row in audits
            if _is_prior_comparable(row, selected, selected_identity)
        ),
        None,
    )
    return ComparableAudits(selected=selected, previous=previous)


def _brand_row(visibility: VisibilityResponse) -> tuple[int | None, RankingRow | None]:
    for rank, row in enumerate(visibility.rankings, start=1):
        if row.is_brand:
            return rank, row
    return None, None


def _delta(current: float | int | None, previous: float | int | None):
    if current is None or previous is None:
        return None
    return round(float(current) - float(previous), 2)


def _movements(
    current: VisibilityResponse, previous: VisibilityResponse | None
) -> list[CommandCenterMovement]:
    if previous is None:
        return []
    previous_engines = {row.logical_engine: row for row in previous.per_engine}
    movements: list[CommandCenterMovement] = []
    for row in current.per_engine:
        prior = previous_engines.get(row.logical_engine)
        change = _delta(row.visibility_score, prior.visibility_score if prior else None)
        if change is None or change == 0:
            continue
        movements.append(
            CommandCenterMovement(
                label=row.logical_engine,
                direction="positive" if change > 0 else "negative",
                current=row.visibility_score,
                previous=prior.visibility_score if prior else None,
                delta=change,
            )
        )
    return sorted(movements, key=lambda row: abs(row.delta or 0), reverse=True)[:4]


async def get_command_center(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project: Project,
    audit_id: uuid.UUID | None = None,
) -> CommandCenterResponse:
    audits = await _resolve_audits(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        audit_id=audit_id,
    )
    current = previous = None
    if audits is not None:
        current, previous = await _load_visibility_pair(
            session,
            workspace_id=workspace_id,
            project_id=project.id,
            audits=audits,
        )
    opportunities = await list_opportunities(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        limit=8,
    )
    order_version = await session.scalar(
        select(OpportunityOrder.version).where(
            OpportunityOrder.workspace_id == workspace_id,
            OpportunityOrder.project_id == project.id,
        )
    )
    facts = await _facts(
        session, workspace_id=workspace_id, project_id=project.id, project=project
    )
    loop, evidence = await _loop_state(
        session, workspace_id=workspace_id, project_id=project.id, audits=audits
    )
    resolved_actions = await _resolved_action_summary(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        audits=audits,
    )
    return CommandCenterResponse(
        project=CommandCenterProject(
            id=project.id,
            name=project.name,
            brand_name=project.brand_name,
            website_url=project.website_url,
        ),
        facts=facts,
        loop=loop,
        next_action=await _next_action(
            session,
            workspace_id=workspace_id,
            project_id=project.id,
            actions=opportunities["items"],
            evidence=evidence,
        ),
        track=_track_summary(current, previous, audits),
        measurement=_measurement(audits) if audits is not None else None,
        state=(
            _state(current, previous)
            if current is not None
            else CommandCenterState(
                visibility=CommandCenterMetric(),
                share_of_voice=CommandCenterMetric(),
                brand_rank=CommandCenterMetric(),
            )
        ),
        movements=_movements(current, previous) if current is not None else [],
        actions=[
            OpportunityItem.model_validate(item) for item in opportunities["items"]
        ],
        action_order_version=int(order_version or 0),
        resolved_actions=resolved_actions,
        report_available=audits is not None,
    )


async def _load_visibility_pair(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audits: ComparableAudits,
) -> tuple[VisibilityResponse, VisibilityResponse | None]:
    current = await get_visibility(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit_id=audits.selected.id,
        cohort="core",
    )
    previous = (
        await get_visibility(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=audits.previous.id,
            cohort="core",
        )
        if audits.previous is not None
        else None
    )
    return current, previous


async def _facts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    project: Project,
) -> CommandCenterFacts:
    profile = await session.scalar(
        select(BrandProfile).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    competitors = list(
        (
            await session.scalars(
                select(Competitor)
                .join(Project, Project.id == Competitor.project_id)
                .where(
                    Competitor.project_id == project_id,
                    Project.workspace_id == workspace_id,
                )
                .order_by(Competitor.created_at, Competitor.id)
            )
        ).all()
    )
    return CommandCenterFacts(
        industry=project.industry,
        description=profile.description if profile else "",
        positioning=profile.positioning if profile else "",
        products_services=list(profile.products_services or []) if profile else [],
        target_audience=profile.target_audience if profile else "",
        competitors=[
            CommandCenterCompetitor(
                id=item.id, name=item.name, domains=list(item.domains or [])
            )
            for item in competitors
        ],
    )


def _evidence_state(
    *,
    observed_at,
    coverage: list[str],
    limitations: list[str],
    partial: bool = False,
) -> EvidenceState:
    return EvidenceState(
        state=("partial" if partial else "observed") if observed_at else "not_run",
        observed_at=observed_at,
        freshness="current" if observed_at else "unknown",
        coverage=coverage if observed_at else [],
        limitations=limitations,
    )


async def _loop_state(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audits: ComparableAudits | None,
) -> tuple[CommandCenterLoop, dict[str, bool]]:
    mapping, crawl, demand, snapshot = await _load_loop_evidence(
        session, workspace_id=workspace_id, project_id=project_id
    )
    implementation = await _current_implementation(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        snapshot=snapshot,
    )
    loop = _project_loop(
        mapping=mapping,
        crawl=crawl,
        demand=demand,
        implementation=implementation,
        audits=audits,
    )
    return loop, {
        "connected": mapping is not None,
        "crawled": crawl is not None,
        "tracked": audits is not None,
    }


async def _load_loop_evidence(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
):
    mapping = await session.scalar(
        select(IntegrationPropertyMapping)
        .where(
            IntegrationPropertyMapping.workspace_id == workspace_id,
            IntegrationPropertyMapping.project_id == project_id,
            IntegrationPropertyMapping.status == "active",
        )
        .order_by(IntegrationPropertyMapping.updated_at.desc())
    )
    crawl = await session.scalar(
        select(SiteCrawl)
        .where(
            SiteCrawl.workspace_id == workspace_id,
            SiteCrawl.project_id == project_id,
            SiteCrawl.status.in_(("completed", "partially_completed")),
        )
        .order_by(SiteCrawl.completed_at.desc(), SiteCrawl.id.desc())
    )
    demand = await session.scalar(
        select(DemandSnapshot)
        .where(
            DemandSnapshot.workspace_id == workspace_id,
            DemandSnapshot.project_id == project_id,
        )
        .order_by(DemandSnapshot.created_at.desc(), DemandSnapshot.id.desc())
    )
    snapshot = await session.scalar(
        select(OpportunitySnapshot)
        .where(
            OpportunitySnapshot.workspace_id == workspace_id,
            OpportunitySnapshot.project_id == project_id,
        )
        .order_by(OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc())
    )
    return mapping, crawl, demand, snapshot


async def _current_implementation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot: OpportunitySnapshot | None,
):
    if snapshot is None:
        return None
    return await session.scalar(
        select(OpportunityImplementationEvent)
        .where(
            OpportunityImplementationEvent.workspace_id == workspace_id,
            OpportunityImplementationEvent.project_id == project_id,
            OpportunityImplementationEvent.opportunity_snapshot_id == snapshot.id,
        )
        .order_by(OpportunityImplementationEvent.created_at.desc())
    )


def _project_loop(
    *, mapping, crawl, demand, implementation, audits: ComparableAudits | None
) -> CommandCenterLoop:
    return CommandCenterLoop(
        connected=_connected_state(mapping),
        analyzed=_analyzed_state(crawl, demand),
        acted=_acted_state(implementation),
        tracked=_tracked_state(audits),
    )


def _connected_state(mapping) -> EvidenceState:
    return _evidence_state(
        observed_at=mapping.updated_at if mapping else None,
        coverage=[mapping.provider] if mapping else [],
        limitations=[] if mapping else ["No GSC or GA4 property is connected."],
    )


def _analyzed_state(crawl, demand) -> EvidenceState:
    analyzed_at = max(
        (
            item
            for item in (
                crawl.completed_at if crawl else None,
                demand.created_at if demand else None,
            )
            if item
        ),
        default=None,
    )
    analyzed_coverage = [
        name
        for name, present in (("site_health", crawl), ("search_demand", demand))
        if present is not None
    ]
    analyzed_limitations = []
    if crawl and not demand:
        analyzed_limitations.append(
            "Search Demand is not connected or has not refreshed yet."
        )
    return _evidence_state(
        observed_at=analyzed_at,
        coverage=analyzed_coverage,
        limitations=analyzed_limitations,
        partial=bool(crawl) != bool(demand),
    )


def _acted_state(implementation) -> EvidenceState:
    return _evidence_state(
        observed_at=(
            implementation.declared_implemented_at if implementation else None
        ),
        coverage=["current_opportunity_cycle"] if implementation else [],
        limitations=(
            []
            if implementation
            else ["No implementation is declared for the current opportunity snapshot."]
        ),
    )


def _tracked_state(audits: ComparableAudits | None) -> EvidenceState:
    if audits is None:
        return _evidence_state(
            observed_at=None,
            coverage=[],
            limitations=["No visibility audit has run yet."],
        )
    return _evidence_state(
        observed_at=audits.selected.completed_at or audits.selected.created_at,
        coverage=sorted(row.logical_engine for row in audits.selected.engine_snapshots),
        limitations=[],
    )


async def _next_action(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    actions: list[dict],
    evidence: dict[str, bool],
) -> CommandCenterNextAction:
    if actions:
        action = actions[0]
        return CommandCenterNextAction(
            kind="opportunity",
            title=str(action["title"]),
            href=f"/opportunities?selected={action['id']}",
            opportunity_id=action["id"],
        )
    if not evidence["connected"]:
        return CommandCenterNextAction(
            kind="connect",
            title="Connect GSC or GA4",
            href="/settings?tab=integrations",
        )
    if not evidence["crawled"]:
        return CommandCenterNextAction(
            kind="crawl", title="Run the first site crawl", href="/site"
        )
    prompt_count = int(
        await session.scalar(
            select(func.count(Prompt.id))
            .select_from(Prompt)
            .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
            .join(Project, Project.id == PromptSet.project_id)
            .where(
                PromptSet.project_id == project_id,
                Project.workspace_id == workspace_id,
                Prompt.status == "active",
            )
        )
        or 0
    )
    if prompt_count == 0:
        return CommandCenterNextAction(
            kind="configure_prompts",
            title="Configure tracking prompts",
            href="/prompts?mode=manage",
        )
    if not evidence["tracked"]:
        return CommandCenterNextAction(
            kind="audit", title="Run the first visibility audit", href="/runs"
        )
    return CommandCenterNextAction(
        kind="monitor",
        title="Monitor — no required action",
        href="/visibility?tab=trends",
    )


def _track_summary(
    current: VisibilityResponse | None,
    previous: VisibilityResponse | None,
    audits: ComparableAudits | None,
) -> CommandCenterTrackSummary:
    if current is None or audits is None:
        return CommandCenterTrackSummary(
            citation_share=CommandCenterMetric(),
            limitations=["No visibility audit has run yet."],
        )
    _rank, brand = _brand_row(current)
    _previous_rank, previous_brand = _brand_row(previous) if previous else (None, None)
    current_share = (
        round(brand.citation_rate * 100, 2)
        if brand and brand.citation_rate is not None
        else None
    )
    previous_share = (
        round(previous_brand.citation_rate * 100, 2)
        if previous_brand and previous_brand.citation_rate is not None
        else None
    )
    return CommandCenterTrackSummary(
        citation_share=CommandCenterMetric(
            value=current_share, delta=_delta(current_share, previous_share)
        ),
        engine_coverage=len(audits.selected.engine_snapshots),
        observed_at=audits.selected.completed_at or audits.selected.created_at,
        limitations=[] if previous else ["No comparable prior audit is available."],
    )


async def _resolved_action_summary(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audits: ComparableAudits | None,
) -> ResolvedActionSummary:
    resolved_query = (
        select(OpportunityStatusEvent, Opportunity.title)
        .join(Opportunity, Opportunity.id == OpportunityStatusEvent.opportunity_id)
        .where(
            OpportunityStatusEvent.workspace_id == workspace_id,
            OpportunityStatusEvent.project_id == project_id,
            OpportunityStatusEvent.next_status == "resolved",
        )
        .order_by(OpportunityStatusEvent.created_at.desc())
    )
    if audits and audits.previous:
        resolved_query = resolved_query.where(
            OpportunityStatusEvent.created_at
            > (audits.previous.completed_at or audits.previous.created_at)
        )
    if audits:
        resolved_query = resolved_query.where(
            OpportunityStatusEvent.created_at
            <= (audits.selected.completed_at or audits.selected.created_at)
        )
    resolved_rows = list((await session.execute(resolved_query)).all())
    return ResolvedActionSummary(
        since_audit_id=audits.previous.id if audits and audits.previous else None,
        count=len(resolved_rows),
        titles=[title for _event, title in resolved_rows[:5]],
    )


def _measurement(audits: ComparableAudits) -> CommandCenterMeasurement:
    return CommandCenterMeasurement(
        audit_id=audits.selected.id,
        completed_at=audits.selected.completed_at or audits.selected.created_at,
        benchmark_mode=audits.selected.benchmark_mode,
        logical_engines=sorted(
            row.logical_engine for row in audits.selected.engine_snapshots
        ),
        comparable_audit_id=audits.previous.id if audits.previous else None,
    )


def _share_of_voice_percent(row: RankingRow | None) -> float | None:
    # Visibility rankings persist share-of-voice as a 0..1 ratio. The command
    # center and executive report present it as a human-readable percentage.
    if row is None or row.share_of_voice is None:
        return None
    return round(row.share_of_voice * 100, 2)


def _state(
    current: VisibilityResponse, previous: VisibilityResponse | None
) -> CommandCenterState:
    current_rank, current_brand = _brand_row(current)
    previous_rank, previous_brand = _brand_row(previous) if previous else (None, None)
    current_sov = _share_of_voice_percent(current_brand)
    previous_sov = _share_of_voice_percent(previous_brand)
    return CommandCenterState(
        visibility=CommandCenterMetric(
            value=current.visibility_score,
            delta=_delta(
                current.visibility_score,
                previous.visibility_score if previous else None,
            ),
        ),
        share_of_voice=CommandCenterMetric(
            value=current_sov,
            delta=_delta(current_sov, previous_sov),
        ),
        brand_rank=CommandCenterMetric(
            value=current_rank,
            delta=_delta(current_rank, previous_rank),
        ),
    )
