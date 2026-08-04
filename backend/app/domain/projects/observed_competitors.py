"""Read and accept evidence-backed, post-audit competitor suggestions."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.observed_competitors import STATUS_ACCEPTED, STATUS_PENDING
from app.models.brand import Competitor, ObservedEntityCandidate
from app.models.project import Project


class ObservedCandidateNotFoundError(LookupError):
    pass


async def list_observed_candidates(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[ObservedEntityCandidate]:
    return list(
        (
            await session.scalars(
                select(ObservedEntityCandidate)
                .where(
                    ObservedEntityCandidate.workspace_id == workspace_id,
                    ObservedEntityCandidate.project_id == project_id,
                    ObservedEntityCandidate.status == STATUS_PENDING,
                )
                .order_by(
                    ObservedEntityCandidate.prompt_count.desc(),
                    ObservedEntityCandidate.engine_count.desc(),
                    ObservedEntityCandidate.domain.asc(),
                )
            )
        ).all()
    )


async def accept_observed_candidate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
) -> Competitor:
    candidate = await session.scalar(
        select(ObservedEntityCandidate)
        .join(Project, Project.id == ObservedEntityCandidate.project_id)
        .where(
            ObservedEntityCandidate.id == candidate_id,
            ObservedEntityCandidate.workspace_id == workspace_id,
            ObservedEntityCandidate.project_id == project_id,
            Project.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if candidate is None:
        raise ObservedCandidateNotFoundError(str(candidate_id))
    existing = await session.scalar(
        select(Competitor).where(
            Competitor.project_id == project_id,
            or_(
                func.lower(Competitor.name) == candidate.name.casefold(),
                Competitor.domains.contains([candidate.domain]),
            ),
        )
    )
    if existing is None:
        existing = Competitor(
            project_id=project_id,
            name=candidate.name,
            aliases=[candidate.name],
            domains=[candidate.domain],
        )
        session.add(existing)
    candidate.status = STATUS_ACCEPTED
    await session.commit()
    await session.refresh(existing)
    return existing
