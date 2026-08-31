"""Deterministic topic recovery for an explicit prompt-generation action."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.prompts import TOPIC_ORIGIN_GENERATED
from app.domain.projects.onboarding.topic_admission import confirmed_offering_topics
from app.domain.prompts.locks import acquire_project_lock
from app.models.brand import Brand
from app.models.project import Project
from app.models.prompt import Topic


def confirmed_offerings(project: Project) -> list[str]:
    profile = project.brand.profile if project.brand is not None else None
    return list(profile.products_services or []) if profile is not None else []


async def recover_topics_from_confirmed_offerings(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> None:
    """Create generated-origin topics once, committing before provider I/O."""
    await acquire_project_lock(session, project_id)
    project = await session.scalar(
        select(Project)
        .options(
            selectinload(Project.topics),
            selectinload(Project.brand).selectinload(Brand.profile),
        )
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.topics:
        return
    project.topics.extend(
        Topic(
            id=item.topic_id,
            project_id=project.id,
            name=item.name,
            description=item.description,
            origin=TOPIC_ORIGIN_GENERATED,
        )
        for item in confirmed_offering_topics(confirmed_offerings(project))
    )
    await session.commit()
