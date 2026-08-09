"""Demand Intelligence persistence projections.

Provider rows remain owned by Integrations; site and visibility evidence keep
their current owners. These tables store only versioned journey configuration
and immutable interpretations over those persisted sources.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class JourneyDefinition(Base):
    """Project-owned journey identity with one active immutable version."""

    __tablename__ = "journey_definitions"
    __table_args__ = (
        UniqueConstraint("project_id", "slug", name="uq_journey_project_slug"),
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
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(String(96))
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class JourneyDefinitionVersion(Base):
    """Immutable version of stages, outcomes, mappings, and provenance."""

    __tablename__ = "journey_definition_versions"
    __table_args__ = (
        UniqueConstraint("journey_id", "version", name="uq_journey_definition_version"),
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
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    journey_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("journey_definitions.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)
    source_kind: Mapped[str] = mapped_column(String(24))
    source_version: Mapped[str] = mapped_column(String(64), default="")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class DemandSnapshot(Base):
    """Immutable bounded interpretation of compatible Demand evidence."""

    __tablename__ = "demand_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_hash", name="uq_demand_snapshot_source_hash"
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
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    source_hash: Mapped[str] = mapped_column(String(64))
    site_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_health_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    prior_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_artifact_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_metric_row_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_audit_ids: Mapped[list] = mapped_column(JSONB, default=list)
    journey_version_ids: Mapped[list] = mapped_column(JSONB, default=list)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    comparison: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    formula_version: Mapped[str] = mapped_column(String(32))
    analyzer_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class DemandSignal(Base):
    """One traceable interpretation inside a Demand snapshot."""

    __tablename__ = "demand_signals"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id", "identity_hash", name="uq_demand_signal_identity"
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
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    identity_hash: Mapped[str] = mapped_column(String(64))
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(24), index=True)
    audience: Mapped[str] = mapped_column(String(128), default="")
    intent: Mapped[str] = mapped_column(String(32), default="")
    journey_stage: Mapped[str] = mapped_column(String(96), default="")
    topic_cluster: Mapped[str] = mapped_column(String(512), default="")
    page_url: Mapped[str] = mapped_column(String(2048), default="")
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    limitations: Mapped[list] = mapped_column(JSONB, default=list)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_inputs: Mapped[dict] = mapped_column(JSONB, default=dict)
    analyzer_version: Mapped[str] = mapped_column(String(32))
    rule_version: Mapped[str] = mapped_column(String(32))
    formula_version: Mapped[str] = mapped_column(String(32))
    model_provenance: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
