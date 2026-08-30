"""Immutable crawl-level Site Health aggregate snapshots."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .common import (
    _FK_PROJECT,
    _FK_SITE_CRAWL,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _utcnow,
)


class SiteHealthSnapshot(Base):
    """Immutable crawl-level aggregate score and coverage snapshot."""

    __tablename__ = "site_health_snapshots"
    __table_args__ = (
        UniqueConstraint("crawl_id", name="uq_site_health_snapshot_crawl"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_PROJECT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
    )
    selected_url_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_url_count: Mapped[int] = mapped_column(Integer, default=0)
    technical_integrity_score: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    technical_integrity_coverage: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )
    technical_integrity_state: Mapped[str] = mapped_column(
        String(24), default="not_measured"
    )
    aeo_readiness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aeo_measurement_coverage: Mapped[float | None] = mapped_column(Float, nullable=True)
    aeo_measurement_state: Mapped[str] = mapped_column(
        String(24), default="not_measured"
    )
    readiness_dimensions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    aeo_readiness_diagnostic: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    search_eligibility: Mapped[str] = mapped_column(String(16), default="unknown")
    eligibility_totals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    eligibility_reasons: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    top_issues: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    web_fundamentals: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    trend: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    change_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    technical_defect_count: Mapped[int] = mapped_column(Integer, default=0)
    technical_defect_affected_page_count: Mapped[int] = mapped_column(
        Integer, default=0
    )
    aeo_readiness_gap_count: Mapped[int] = mapped_column(Integer, default=0)
    aeo_readiness_gap_affected_page_count: Mapped[int] = mapped_column(
        Integer, default=0
    )
    severity_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    category_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    coverage_state: Mapped[str] = mapped_column(String(16), default="unknown")
    coverage_evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    coverage_formula_version: Mapped[str] = mapped_column(String(32), default="")
    source_analysis_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_evaluation_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_task_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_attempt_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    scoring_version: Mapped[str] = mapped_column(String(32), default="")
    profile_version: Mapped[str] = mapped_column(String(32), default="")
    schema_contract_version: Mapped[str] = mapped_column(String(32), default="")
    presentation_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
