"""Workspace-scoped persisted Opportunity list/detail queries."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import (
    OPPORTUNITY_ACTIVE_STATUSES,
    OPPORTUNITY_SEVERITIES,
    OPPORTUNITY_STATUSES,
    OPPORTUNITY_TYPES,
    validate_rule_id,
)
from app.domain.opportunities.common import (
    _LIST_SCOPE,
    _OPPORTUNITY_NOT_FOUND,
    _clamp_limit,
    _require_project,
)
from app.domain.opportunities.errors import (
    InvalidCursorError,
    OpportunityNotFoundError,
    OpportunityValidationError,
)
from app.domain.opportunities.projection import (
    ordered_items,
    project_detail,
)
from app.domain.site_health.normalization import (
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.models.opportunity import Opportunity, OpportunityOrder


def _validate_filters(
    *,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
) -> None:
    if opportunity_type is not None and opportunity_type not in OPPORTUNITY_TYPES:
        raise OpportunityValidationError(
            f"unknown opportunity type: {opportunity_type!r}"
        )
    if severity is not None and severity not in OPPORTUNITY_SEVERITIES:
        raise OpportunityValidationError(f"unknown opportunity severity: {severity!r}")
    if status is not None and status not in OPPORTUNITY_STATUSES:
        raise OpportunityValidationError(f"unknown opportunity status: {status!r}")
    if rule_id is not None:
        try:
            validate_rule_id(rule_id)
        except ValueError as exc:
            raise OpportunityValidationError(str(exc)) from exc


def _filter_clauses(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
    min_priority: float | None,
) -> list:
    clauses = [
        Opportunity.workspace_id == workspace_id,
        Opportunity.project_id == project_id,
        Opportunity.superseded_at.is_(None),
    ]
    if opportunity_type:
        clauses.append(Opportunity.opportunity_type == opportunity_type)
    if severity:
        clauses.append(Opportunity.severity == severity)
    if status:
        clauses.append(Opportunity.status == status)
    else:
        clauses.append(Opportunity.status.in_(sorted(OPPORTUNITY_ACTIVE_STATUSES)))
    if rule_id:
        clauses.append(Opportunity.rule_id == rule_id)
    if min_priority is not None:
        clauses.append(Opportunity.priority_score >= min_priority)
    return clauses


def _cursor_filters(
    *,
    project_id: uuid.UUID,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
    min_priority: float | None,
) -> dict:
    return {
        "project_id": str(project_id),
        "type": opportunity_type or None,
        "severity": severity or None,
        "status": status or None,
        "rule_id": rule_id or None,
        "min_priority": min_priority,
    }


async def _load_order(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> OpportunityOrder | None:
    return await session.scalar(
        select(OpportunityOrder).where(
            OpportunityOrder.workspace_id == workspace_id,
            OpportunityOrder.project_id == project_id,
        )
    )


async def load_filtered_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
    min_priority: float | None,
    limit: int,
) -> list[Opportunity]:
    """Load the bounded persisted row set shared by catalog and exports."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    _validate_filters(
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
    )
    clauses = _filter_clauses(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    return list(
        (
            await session.scalars(
                select(Opportunity)
                .where(*clauses)
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.desc())
                .limit(limit)
            )
        ).all()
    )


async def list_opportunities(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_id: str | None = None,
    min_priority: float | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Live-row catalog page, ordered by priority then UUID."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    _validate_filters(
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
    )
    limit = _clamp_limit(limit)
    filters = _cursor_filters(
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    clauses = _filter_clauses(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    if cursor:
        try:
            score_raw, id_raw = decode_keyset_cursor(
                cursor, scope=_LIST_SCOPE, filters=filters
            )
            cursor_score = float(score_raw)
            cursor_id = uuid.UUID(id_raw)
        except ValueError as exc:
            raise InvalidCursorError(str(exc)) from exc
        clauses.append(
            or_(
                Opportunity.priority_score < cursor_score,
                and_(
                    Opportunity.priority_score == cursor_score,
                    Opportunity.id < cursor_id,
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(*clauses)
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_keyset_cursor(
            scope=_LIST_SCOPE,
            filters=filters,
            sort_values=[last.priority_score, str(last.id)],
        )
    order = await _load_order(session, workspace_id=workspace_id, project_id=project_id)
    return {"items": ordered_items(rows, order), "next_cursor": next_cursor}


async def get_opportunity(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> dict:
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    return project_detail(row)
