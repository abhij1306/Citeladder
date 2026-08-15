"""Immutable crawl-to-crawl change projections owned by Site Health."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SiteChangeSnapshot(Base):
    """Immutable comparison projection for one exact crawl A/B pair."""

    __tablename__ = "site_change_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["crawl_a_id", "project_id", "workspace_id"],
            ["site_crawls.id", "site_crawls.project_id", "site_crawls.workspace_id"],
            ondelete="CASCADE",
            name="fk_site_change_snapshot_crawl_a_scoped",
        ),
        ForeignKeyConstraint(
            ["crawl_b_id", "project_id", "workspace_id"],
            ["site_crawls.id", "site_crawls.project_id", "site_crawls.workspace_id"],
            ondelete="CASCADE",
            name="fk_site_change_snapshot_crawl_b_scoped",
        ),
        UniqueConstraint(
            "workspace_id",
            "crawl_a_id",
            "crawl_b_id",
            "source_hash",
            "analyzer_version",
            name="uq_site_change_snapshot_identity",
        ),
        UniqueConstraint(
            "workspace_id", "id", name="uq_site_change_snapshot_ws_id"
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
    crawl_a_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    crawl_b_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        index=True,
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_change_snapshots.id", ondelete="SET NULL"),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(24))
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    root_origin: Mapped[str] = mapped_column(String(512))
    crawl_scope_hash: Mapped[str] = mapped_column(String(64))
    source_hash: Mapped[str] = mapped_column(String(64))
    source_analysis_ids: Mapped[list] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    source_artifact_ids: Mapped[list] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )
    analyzer_version: Mapped[str] = mapped_column(String(32))
    page_analyzer_version: Mapped[str] = mapped_column(String(32))
    extractor_version: Mapped[str] = mapped_column(String(32))
    complete_pair: Mapped[bool] = mapped_column(Boolean, default=False)
    coverage: Mapped[dict] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    limitations: Mapped[list] = mapped_column(ARRAY(Text), default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SiteChangeObservation(Base):
    """One immutable changed field with exact before/after provenance."""

    __tablename__ = "site_change_observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "snapshot_id"],
            ["site_change_snapshots.workspace_id", "site_change_snapshots.id"],
            ondelete="CASCADE",
            name="fk_site_change_observation_snapshot_workspace",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "implementation_event_id"],
            [
                "opportunity_implementation_events.workspace_id",
                "opportunity_implementation_events.id",
            ],
            ondelete="RESTRICT",
            name="fk_site_change_observation_implementation_workspace",
        ),
        UniqueConstraint(
            "snapshot_id", "site_url_id", "field", name="uq_site_change_observation"
        ),
        CheckConstraint(
            "change_class IN ('improvement', 'neutral-change', "
            "'potential-regression', 'critical-regression')",
            name="ck_site_change_observation_class",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("site_urls.id", ondelete="CASCADE"), index=True
    )
    normalized_url: Mapped[str] = mapped_column(String(2048))
    field: Mapped[str] = mapped_column(String(32))
    change_class: Mapped[str] = mapped_column(String(32), index=True)
    before_value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    after_value: Mapped[object | None] = mapped_column(JSONB, nullable=True)
    source_analysis_a_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_page_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_analysis_b_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_page_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_artifact_a_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_fetch_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_artifact_b_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_fetch_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_evaluation_a_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_rule_evaluations.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_evaluation_b_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_rule_evaluations.id", ondelete="SET NULL"),
        nullable=True,
    )
    expected: Mapped[bool] = mapped_column(Boolean, default=False)
    implementation_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
