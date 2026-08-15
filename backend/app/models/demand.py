"""Immutable Demand projections over persisted Traffic evidence."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_WORKSPACE_FK = "workspaces.id"
_PROJECT_FK = "projects.id"
_SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    source_hash: Mapped[str] = mapped_column(String(64))
    prior_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete=_SET_NULL),
        nullable=True,
    )
    source_artifact_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_metric_row_ids: Mapped[list] = mapped_column(JSONB, default=list)
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
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    identity_hash: Mapped[str] = mapped_column(String(64))
    signal_type: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(24), index=True)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class BrandedQueryOverride(Base):
    """Append-only user evidence overriding one exact normalized query."""

    __tablename__ = "branded_query_overrides"
    __table_args__ = (
        Index(
            "ix_branded_query_override_lookup",
            "workspace_id",
            "project_id",
            "normalized_query",
            "ordinal",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    ordinal: Mapped[int] = mapped_column(
        BigInteger, Identity(always=False), unique=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_PROJECT_FK, ondelete="CASCADE"),
        index=True,
    )
    normalized_query: Mapped[str] = mapped_column(String(512))
    classification: Mapped[str] = mapped_column(String(16))
    classifier_version: Mapped[str] = mapped_column(String(32))
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
