"""Append-only Opportunity implementation declarations and read projection."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.opportunities import (
    IMPLEMENTATION_TARGETS_MAX,
    IMPLEMENTATION_VERIFICATION_HISTORY_MAX,
)
from app.domain.demand.page_equivalence import resolve_owned_page
from app.models.content import ContentGeneration
from app.models.opportunity import (
    Opportunity,
    OpportunityImplementationEvent,
    OpportunitySnapshot,
    OpportunityVerificationEvent,
)
from app.models.project import Project
from app.models.site_health.urls import SiteUrl


class ImplementationNotFoundError(LookupError):
    pass


class ImplementationConflictError(Exception):
    pass


class ImplementationIdempotencyConflictError(ImplementationConflictError):
    pass


@dataclass(frozen=True, slots=True)
class ImplementationDeclaration:
    opportunity_id: uuid.UUID
    target_site_url_ids: list[uuid.UUID]
    generation_id: uuid.UUID | None
    declared_implemented_at: datetime
    expected_checks: list[dict]


def _fingerprint(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(raw.encode()).hexdigest()


async def _project_and_opportunity(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_id: uuid.UUID,
) -> tuple[Project, Opportunity]:
    project = await session.scalar(
        select(Project).where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
        )
    )
    opportunity = await session.scalar(
        select(Opportunity).where(
            Opportunity.workspace_id == workspace_id,
            Opportunity.project_id == project_id,
            Opportunity.id == opportunity_id,
            Opportunity.superseded_at.is_(None),
        )
    )
    if project is None or opportunity is None:
        raise ImplementationNotFoundError("Opportunity not found")
    return project, opportunity


async def _resolve_targets(
    session: AsyncSession,
    *,
    project: Project,
    opportunity: Opportunity,
    requested_ids: list[uuid.UUID],
) -> list[uuid.UUID]:
    if len(requested_ids) > IMPLEMENTATION_TARGETS_MAX:
        raise ImplementationConflictError("Too many implementation targets")
    if requested_ids:
        rows = list(
            (
                await session.scalars(
                    select(SiteUrl).where(
                        SiteUrl.workspace_id == project.workspace_id,
                        SiteUrl.project_id == project.id,
                        SiteUrl.id.in_(requested_ids),
                    )
                )
            ).all()
        )
        if {row.id for row in rows} != set(requested_ids):
            raise ImplementationConflictError("Implementation target is unresolved")
        return list(dict.fromkeys(requested_ids))
    if not opportunity.target_url:
        return []
    resolution = await resolve_owned_page(
        session,
        workspace_id=project.workspace_id,
        project_id=project.id,
        url=opportunity.target_url,
        preferred_origin=project.website_url,
    )
    if (
        resolution.outcome not in {"exact", "resolved"}
        or resolution.site_url_id is None
    ):
        raise ImplementationConflictError(
            "Implementation target is ambiguous or unresolved"
        )
    return [resolution.site_url_id]


async def _current_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> OpportunitySnapshot:
    snapshot = await session.scalar(
        select(OpportunitySnapshot)
        .where(
            OpportunitySnapshot.workspace_id == workspace_id,
            OpportunitySnapshot.project_id == project_id,
        )
        .order_by(OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        raise ImplementationConflictError("No current opportunity snapshot")
    return snapshot


async def _validate_generation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    generation_id: uuid.UUID | None,
) -> None:
    if generation_id is None:
        return
    generation = await session.scalar(
        select(ContentGeneration.id).where(
            ContentGeneration.workspace_id == workspace_id,
            ContentGeneration.project_id == project_id,
            ContentGeneration.id == generation_id,
        )
    )
    if generation is None:
        raise ImplementationConflictError("Generation not found")


async def _idempotent_replay(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    idempotency_key: str,
    fingerprint: str,
) -> OpportunityImplementationEvent | None:
    row = await session.scalar(
        select(OpportunityImplementationEvent).where(
            OpportunityImplementationEvent.workspace_id == workspace_id,
            OpportunityImplementationEvent.idempotency_key == idempotency_key,
        )
    )
    if row is not None and row.request_fingerprint != fingerprint:
        raise ImplementationIdempotencyConflictError("Idempotency key was reused")
    return row


async def _flush_declaration(
    session: AsyncSession,
    *,
    row: OpportunityImplementationEvent,
    fingerprint: str,
) -> tuple[OpportunityImplementationEvent, bool]:
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        replay = await _idempotent_replay(
            session,
            workspace_id=row.workspace_id,
            idempotency_key=row.idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is None:
            raise ImplementationIdempotencyConflictError(
                "Idempotency key was reused"
            ) from None
        return replay, False
    return row, True


async def create_implementation_event(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    idempotency_key: str,
    declaration: ImplementationDeclaration,
) -> tuple[OpportunityImplementationEvent, bool]:
    request_payload = {
        "opportunity_id": declaration.opportunity_id,
        "target_site_url_ids": declaration.target_site_url_ids,
        "generation_id": declaration.generation_id,
        "declared_implemented_at": declaration.declared_implemented_at,
        "expected_checks": declaration.expected_checks,
    }
    fingerprint = _fingerprint(request_payload)
    existing = await _idempotent_replay(
        session,
        workspace_id=workspace_id,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return existing, False
    project, opportunity = await _project_and_opportunity(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=declaration.opportunity_id,
    )
    snapshot = await _current_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    targets = await _resolve_targets(
        session,
        project=project,
        opportunity=opportunity,
        requested_ids=declaration.target_site_url_ids,
    )
    await _validate_generation(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        generation_id=declaration.generation_id,
    )
    row = OpportunityImplementationEvent(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_id=declaration.opportunity_id,
        opportunity_snapshot_id=snapshot.id,
        target_site_url_ids=[str(item) for item in targets],
        generation_id=declaration.generation_id,
        declared_implemented_at=declaration.declared_implemented_at,
        expected_checks=declaration.expected_checks,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
    )
    return await _flush_declaration(session, row=row, fingerprint=fingerprint)


async def list_implementation_events(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    limit: int,
    opportunity_id: uuid.UUID | None = None,
) -> list[OpportunityImplementationEvent]:
    project = await session.scalar(
        select(Project.id).where(
            Project.workspace_id == workspace_id, Project.id == project_id
        )
    )
    if project is None:
        raise ImplementationNotFoundError("Project not found")
    statement = select(OpportunityImplementationEvent).where(
        OpportunityImplementationEvent.workspace_id == workspace_id,
        OpportunityImplementationEvent.project_id == project_id,
    )
    if opportunity_id is not None:
        statement = statement.where(
            OpportunityImplementationEvent.opportunity_id == opportunity_id
        )
    return list(
        (
            await session.scalars(
                statement.order_by(
                    OpportunityImplementationEvent.created_at.desc(),
                    OpportunityImplementationEvent.id.desc(),
                ).limit(limit)
            )
        ).all()
    )


async def get_implementation_event(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    event_id: uuid.UUID,
) -> OpportunityImplementationEvent:
    row = await session.scalar(
        select(OpportunityImplementationEvent).where(
            OpportunityImplementationEvent.workspace_id == workspace_id,
            OpportunityImplementationEvent.project_id == project_id,
            OpportunityImplementationEvent.id == event_id,
        )
    )
    if row is None:
        raise ImplementationNotFoundError("Implementation event not found")
    return row


async def list_verification_events(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    implementation_event_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[OpportunityVerificationEvent]]:
    if not implementation_event_ids:
        return {}
    ranked = (
        select(
            OpportunityVerificationEvent.id.label("id"),
            func.row_number()
            .over(
                partition_by=OpportunityVerificationEvent.implementation_event_id,
                order_by=(
                    OpportunityVerificationEvent.created_at.desc(),
                    OpportunityVerificationEvent.id.desc(),
                ),
            )
            .label("rank"),
        )
        .where(
            OpportunityVerificationEvent.workspace_id == workspace_id,
            OpportunityVerificationEvent.project_id == project_id,
            OpportunityVerificationEvent.implementation_event_id.in_(
                implementation_event_ids
            ),
        )
        .subquery()
    )
    rows = list(
        (
            await session.scalars(
                select(OpportunityVerificationEvent)
                .join(ranked, ranked.c.id == OpportunityVerificationEvent.id)
                .where(ranked.c.rank <= IMPLEMENTATION_VERIFICATION_HISTORY_MAX)
                .order_by(
                    OpportunityVerificationEvent.created_at.asc(),
                    OpportunityVerificationEvent.id.asc(),
                )
            )
        ).all()
    )
    grouped: dict[uuid.UUID, list[OpportunityVerificationEvent]] = {}
    for row in rows:
        grouped.setdefault(row.implementation_event_id, []).append(row)
    return grouped
