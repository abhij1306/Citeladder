from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.audits import AUDIT_STATUS_COMPLETED
from app.domain.analysis.schemas import RankingRow, VisibilityResponse
from app.domain.analysis.service import get_visibility
from app.domain.command_center.schemas import (
    CommandCenterMeasurement,
    CommandCenterMetric,
    CommandCenterMovement,
    CommandCenterProject,
    CommandCenterResponse,
    CommandCenterState,
    ResolvedActionSummary,
)
from app.domain.opportunities.schemas import OpportunityItem
from app.domain.opportunities.service import list_opportunities
from app.models.audit import Audit
from app.models.opportunity import Opportunity, OpportunityOrder, OpportunityStatusEvent
from app.models.project import Project


@dataclass(frozen=True)
class ComparableAudits:
    selected: Audit
    previous: Audit | None


def _audit_identity(audit: Audit) -> tuple[str, str, frozenset[str], frozenset[str]]:
    prompts = frozenset(
        str(row.prompt_id) if row.prompt_id is not None else f"text:{row.text}"
        for row in audit.prompt_snapshots
        if row.cohort == "core"
    )
    engines = frozenset(row.logical_engine for row in audit.engine_snapshots)
    return audit.measurement_mode, audit.benchmark_mode, engines, prompts


async def _resolve_audits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
) -> ComparableAudits:
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
        )
        .order_by(Audit.completed_at.desc(), Audit.id.desc())
    )
    audits = list((await session.scalars(query)).unique().all())
    selected = next(
        (row for row in audits if audit_id is None or row.id == audit_id), None
    )
    if selected is None:
        raise LookupError("No completed audit is available for this project")
    selected_identity = _audit_identity(selected)
    previous = next(
        (
            row
            for row in audits
            if row.id != selected.id
            and (row.completed_at or row.created_at)
            < (selected.completed_at or selected.created_at)
            and _audit_identity(row) == selected_identity
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
    current = await get_visibility(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        audit_id=audits.selected.id,
        cohort="core",
    )
    previous = (
        await get_visibility(
            session,
            workspace_id=workspace_id,
            project_id=project.id,
            audit_id=audits.previous.id,
            cohort="core",
        )
        if audits.previous is not None
        else None
    )
    current_rank, current_brand = _brand_row(current)
    previous_rank, previous_brand = _brand_row(previous) if previous else (None, None)
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
    resolved_query = (
        select(OpportunityStatusEvent, Opportunity.title)
        .join(Opportunity, Opportunity.id == OpportunityStatusEvent.opportunity_id)
        .where(
            OpportunityStatusEvent.workspace_id == workspace_id,
            OpportunityStatusEvent.project_id == project.id,
            OpportunityStatusEvent.next_status == "resolved",
        )
        .order_by(OpportunityStatusEvent.created_at.desc())
    )
    if audits.previous and audits.previous.completed_at:
        resolved_query = resolved_query.where(
            OpportunityStatusEvent.created_at > audits.previous.completed_at
        )
    resolved_query = resolved_query.where(
        OpportunityStatusEvent.created_at
        <= (audits.selected.completed_at or audits.selected.created_at)
    )
    resolved_rows = list((await session.execute(resolved_query)).all())
    # Visibility rankings persist share-of-voice as a 0..1 ratio. The command
    # center and executive report present it as a human-readable percentage.
    current_sov = (
        round(current_brand.share_of_voice * 100, 2)
        if current_brand and current_brand.share_of_voice is not None
        else None
    )
    previous_sov = (
        round(previous_brand.share_of_voice * 100, 2)
        if previous_brand and previous_brand.share_of_voice is not None
        else None
    )
    return CommandCenterResponse(
        project=CommandCenterProject(
            id=project.id,
            name=project.name,
            brand_name=project.brand_name,
            website_url=project.website_url,
        ),
        measurement=CommandCenterMeasurement(
            audit_id=audits.selected.id,
            completed_at=audits.selected.completed_at or audits.selected.created_at,
            measurement_mode=audits.selected.measurement_mode,
            benchmark_mode=audits.selected.benchmark_mode,
            logical_engines=sorted(
                row.logical_engine for row in audits.selected.engine_snapshots
            ),
            comparable_audit_id=audits.previous.id if audits.previous else None,
        ),
        state=CommandCenterState(
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
        ),
        movements=_movements(current, previous),
        actions=[
            OpportunityItem.model_validate(item) for item in opportunities["items"]
        ],
        action_order_version=int(order_version or 0),
        resolved_actions=ResolvedActionSummary(
            since_audit_id=audits.previous.id if audits.previous else None,
            count=len(resolved_rows),
            titles=[title for _event, title in resolved_rows[:5]],
        ),
    )
