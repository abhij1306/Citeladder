"""Durable Postgres-queued onboarding discovery state."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.brand_discovery import (
    DISCOVERY_STATUS_QUEUED,
    brand_discovery_settings,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BrandDiscovery(Base):
    __tablename__ = "brand_discoveries"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_brand_discovery_idempotency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), default=DISCOVERY_STATUS_QUEUED, index=True
    )
    stage: Mapped[str] = mapped_column(String(32), default="queued")
    progress: Mapped[dict] = mapped_column(JSONB, default=dict)
    input_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    domains: Mapped[list] = mapped_column(JSONB, default=list)
    competitors: Mapped[list] = mapped_column(JSONB, default=list)
    topics: Mapped[list] = mapped_column(JSONB, default=list)
    prompt_suggestions: Mapped[list] = mapped_column(JSONB, default=list)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    gaps: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    error_code: Mapped[str] = mapped_column(String(32), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    initial_crawl_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_crawls.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class BrandDiscoveryTask(Base):
    """One generic queue row for exactly one discovery business record."""

    __tablename__ = "brand_discovery_tasks"
    __table_args__ = (
        UniqueConstraint("discovery_id", name="uq_brand_discovery_task_discovery"),
        UniqueConstraint("idempotency_key", name="uq_brand_discovery_task_key"),
        Index("ix_brand_discovery_tasks_claim", "status", "available_at"),
        Index("ix_brand_discovery_tasks_lease", "status", "lease_expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    discovery_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_discoveries.id", ondelete="CASCADE"),
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    task_kind: Mapped[str] = mapped_column(String(32), default="brand_discovery")
    idempotency_key: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(
        String(24), default=TASK_STATUS_QUEUED, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    randomized_position: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=brand_discovery_settings.maximum_attempts
    )
    error_code: Mapped[str] = mapped_column(String(32), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class BrandResearchSnapshot(Base):
    """Immutable provenance for the research result shown at onboarding review."""

    __tablename__ = "brand_research_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "discovery_id", "research_version", name="uq_brand_research_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    discovery_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_discoveries.id", ondelete="CASCADE"),
        index=True,
    )
    research_version: Mapped[str] = mapped_column(String(32))
    provider: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    method: Mapped[str] = mapped_column(String(64))
    extracted_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_confidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
