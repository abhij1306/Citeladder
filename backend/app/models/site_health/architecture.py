"""Immutable crawl-level observed architecture projections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .common import _FK_WORKSPACE, _ON_DELETE_CASCADE, _utcnow


class SiteObservedArchitecture(Base):
    """One replayable observed-site model for a crawl and formula version."""

    __tablename__ = "site_observed_architectures"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id",
            "extractor_version",
            "analyzer_version",
            "rule_version",
            "architecture_formula_version",
            "archetype_policy_version",
            name="uq_site_observed_architecture",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            ["site_crawls.workspace_id", "site_crawls.project_id", "site_crawls.id"],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_site_observed_architecture_crawl_scoped",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    crawl_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_health_snapshots.id", ondelete=_ON_DELETE_CASCADE),
    )
    source_brand_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    coverage_state: Mapped[str] = mapped_column(String(16), default="unknown")
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    page_kinds: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    internal_linking: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    structure_depth: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    hierarchy: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    archetype: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_analysis_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_evaluation_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_link_metric_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    rule_version: Mapped[str] = mapped_column(String(32), default="")
    architecture_formula_version: Mapped[str] = mapped_column(String(32), default="")
    archetype_policy_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


__all__ = ["SiteObservedArchitecture"]
