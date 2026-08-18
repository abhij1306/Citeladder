"""Historical Opportunity occurrence and transition projection."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.opportunities.common import _iso, _require_project
from app.models.opportunity import Opportunity, OpportunitySnapshot


def _active_opportunity_at(
    occurrences: list[Opportunity], timestamp: datetime | None
) -> Opportunity | None:
    if timestamp is None:
        return next(
            (row for row in reversed(occurrences) if row.superseded_at is None), None
        )
    return next(
        (
            row
            for row in reversed(occurrences)
            if row.created_at <= timestamp
            and (row.superseded_at is None or row.superseded_at > timestamp)
        ),
        None,
    )


def _history_transition(
    current: Opportunity | None, previous: Opportunity | None
) -> str:
    if current is not None and previous is not None:
        return "continuing"
    if current is not None:
        return "new"
    return "resolved"


def _project_history_group(
    *,
    rule_id: str,
    target_key: str,
    occurrences: list[Opportunity],
    latest_at: datetime | None,
    previous_at: datetime | None,
) -> tuple[dict, str, bool]:
    current = _active_opportunity_at(occurrences, latest_at)
    previous = _active_opportunity_at(occurrences, previous_at)
    transition = _history_transition(current, previous)
    return (
        {
            "rule_id": rule_id,
            "target_key": target_key,
            "title": occurrences[-1].title or "",
            "current_state": current.status if current is not None else "resolved",
            "transition": transition,
            "occurrence_count": len(occurrences),
            "first_seen": _iso(occurrences[0].created_at),
            "last_seen": _iso(occurrences[-1].created_at),
            "timeline": [
                {"id": row.id, "status": row.status, "seen_at": _iso(row.created_at)}
                for row in occurrences
            ],
        },
        transition,
        current is not None or previous is not None,
    )


async def get_grouped_history(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """Compare grouped rows with the two latest persisted snapshots."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    snapshots = list(
        (
            await session.scalars(
                select(OpportunitySnapshot)
                .where(
                    OpportunitySnapshot.workspace_id == workspace_id,
                    OpportunitySnapshot.project_id == project_id,
                )
                .order_by(
                    OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc()
                )
                .limit(2)
            )
        ).all()
    )
    latest_snapshot = snapshots[0] if snapshots else None
    previous_snapshot = snapshots[1] if len(snapshots) > 1 else None
    rows = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.project_id == project_id,
                )
                .order_by(Opportunity.created_at.asc(), Opportunity.id.asc())
            )
        ).all()
    )
    groups: dict[tuple[str, str], list[Opportunity]] = {}
    for row in rows:
        groups.setdefault((row.rule_id, row.target_key), []).append(row)

    projected: list[dict] = []
    counts = {"new": 0, "continuing": 0, "resolved": 0}
    latest_at = latest_snapshot.created_at if latest_snapshot is not None else None
    previous_at = (
        previous_snapshot.created_at if previous_snapshot is not None else None
    )
    for (rule_id, target_key), occurrences in groups.items():
        group, transition, changed = _project_history_group(
            rule_id=rule_id,
            target_key=target_key,
            occurrences=occurrences,
            latest_at=latest_at,
            previous_at=previous_at,
        )
        if changed:
            counts[transition] += 1
        projected.append(group)
    projected.sort(
        key=lambda group: (group["last_seen"] or "", group["rule_id"]), reverse=True
    )
    return {"items": projected, "since_previous": counts}
