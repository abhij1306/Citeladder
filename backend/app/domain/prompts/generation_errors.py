"""Scoped errors and integrity-error mapping for prompt generation."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.prompts.service import PromptSetNotFoundError
from app.models.project import Project
from app.models.prompt import PromptSet, Topic


class GenerationValidationError(ValueError):
    """Request-level validation failure (422 at the API layer)."""


async def reraise_scoped_integrity_error(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    topic_id: uuid.UUID | None,
    exc: IntegrityError,
) -> None:
    """Map only vanished scoped entities; preserve unrelated constraints."""
    set_exists = (
        await session.execute(
            select(PromptSet.id)
            .join(Project, Project.id == PromptSet.project_id)
            .where(
                PromptSet.id == prompt_set_id,
                Project.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if set_exists is None:
        raise PromptSetNotFoundError("Prompt set not found") from exc

    if topic_id is not None:
        topic_exists = (
            await session.execute(
                select(Topic.id)
                .join(Project, Project.id == Topic.project_id)
                .join(PromptSet, PromptSet.project_id == Project.id)
                .where(
                    Topic.id == topic_id,
                    PromptSet.id == prompt_set_id,
                    Project.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if topic_exists is None:
            raise GenerationValidationError(
                "topic_id is not a topic of this project"
            ) from exc

    raise exc
