"""Persisted audit read projections."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.audits.errors import AuditNotFoundError
from app.models.audit import Audit, AuditTask


async def get_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> Audit:
    result = await session.execute(
        select(Audit)
        .options(
            selectinload(Audit.engine_snapshots),
        )
        .where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
        )
    )
    audit = result.scalars().unique().one_or_none()
    if audit is None:
        raise AuditNotFoundError(str(audit_id))
    return audit


async def list_audits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Audit]:
    stmt = (
        select(Audit)
        .options(
            selectinload(Audit.engine_snapshots),
        )
        .where(Audit.workspace_id == workspace_id)
        .order_by(Audit.created_at.desc())
        .limit(limit)
    )
    if project_id is not None:
        stmt = stmt.where(Audit.project_id == project_id)
    return list((await session.scalars(stmt)).unique().all())


async def list_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    audit_id: uuid.UUID,
) -> list[AuditTask]:
    """List an audit's tasks in randomized execution order."""
    audit = await get_audit(session, workspace_id=workspace_id, audit_id=audit_id)
    stmt = (
        select(AuditTask)
        .where(AuditTask.audit_id == audit_id)
        .order_by(AuditTask.randomized_position.asc())
    )
    tasks = list((await session.scalars(stmt)).all())
    _attach_transient_audit_provenance(tasks, audit)
    return tasks


def _attach_transient_audit_provenance(
    tasks: list[AuditTask],
    audit: Audit,
) -> None:
    """Attach the audit's mode/configuration to each task as duck attributes.

    The response schema reads these via ``getattr`` (schemas.py). They are
    copied from the already-loaded audit, never trigger relationship lazy
    loads, and exist only for the lifetime of the request — nothing else uses
    them, so they intentionally live off the typed ORM surface.
    """
    for task in tasks:
        row = cast(Any, task)  # widen so ruff+SIM prefer the direct form
        row.audit_configuration = audit.configuration
