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
    TASK_KIND_BRAND_DISCOVERY,
    brand_discovery_settings,
)
from app.core.database import Base
from app.models.queue_mixins import QueueLeaseStateMixin


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


class BrandDiscoveryTask(QueueLeaseStateMixin, Base):
    """One generic queue row for exactly one discovery business record."""

    __tablename__ = "brand_discovery_tasks"
    __table_args__ = (
        # Scoped by kind: one discovery carries a research task AND, once its
        # review is confirmed, a completion task. Keyed on discovery_id alone
        # the second could never be inserted.
        UniqueConstraint(
            "discovery_id", "task_kind", name="uq_brand_discovery_task_discovery"
        ),
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
    task_kind: Mapped[str] = mapped_column(
        String(32), default=TASK_KIND_BRAND_DISCOVERY
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    max_attempts: Mapped[int] = mapped_column(
        Integer, default=brand_discovery_settings.maximum_attempts
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
