"""Workspace-scoped recurring audit schedules.

The scheduler claims a due row with ``FOR UPDATE SKIP LOCKED`` before it
delegates run construction to the normal audit planner.  It never performs
provider I/O and stores no credentials.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.audit_schedules import (
    CADENCE_ONE_TIME,
    DEFAULT_AUDIT_SCHEDULE_TIMEZONE,
)
from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuditSchedule(Base):
    """A project-owned request to create audits on a simple cadence."""

    __tablename__ = "audit_schedules"
    __table_args__ = (
        Index("ix_audit_schedules_due", "enabled", "next_run_at"),
        Index("ix_audit_schedules_lease", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    prompt_set_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prompt_sets.id", ondelete="CASCADE"),
        index=True,
    )
    cadence: Mapped[str] = mapped_column(String(32), default=CADENCE_ONE_TIME)
    interval_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_AUDIT_SCHEDULE_TIMEZONE
    )
    engines: Mapped[list] = mapped_column(JSONB, default=list)
    repetitions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    benchmark_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
