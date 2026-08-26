"""Commerce catalog, competitor, prompt-target, and AI Shelf persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.commerce_catalog import (
    COMMERCE_COMPETITOR_PROVIDER_VERSION,
    COMMERCE_COMPETITOR_VALIDATOR_VERSION,
    COMMERCE_EDIT_VERSION,
    COMMERCE_IMPORTER_VERSION,
    COMMERCE_PROJECTOR_VERSION,
    COMMERCE_PROMPT_TEMPLATE_VERSION,
    COMMERCE_RECOMMENDATION_MATCHER_VERSION,
    COMMERCE_RECOMMENDATION_PARSER_VERSION,
    COMMERCE_SHELF_FORMULA_VERSION,
)
from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CommerceCategory(Base):
    """Current editable category projection for one project."""

    __tablename__ = "commerce_categories"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "normalized_name", name="uq_commerce_category_name"
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
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="unknown")
    canonical_url: Mapped[str] = mapped_column(Text, default="")
    editable: Mapped[bool] = mapped_column(Boolean, default=True)
    source_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_page_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    projector_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_PROJECTOR_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class CommerceProduct(Base):
    """One canonical PDP URL and its current field-level sourced projection."""

    __tablename__ = "commerce_products"
    __table_args__ = (
        UniqueConstraint("project_id", "canonical_url", name="uq_commerce_product_url"),
        Index(
            "ix_commerce_products_project_lifecycle", "project_id", "lifecycle_state"
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
    canonical_url: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(String(512), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    brand: Mapped[str] = mapped_column(String(255), default="")
    price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="")
    sku: Mapped[str] = mapped_column(String(255), default="")
    gtin: Mapped[str] = mapped_column(String(64), default="")
    mpn: Mapped[str] = mapped_column(String(255), default="")
    observed_external_id: Mapped[str] = mapped_column(String(255), default="")
    variants: Mapped[list] = mapped_column(JSONB, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_sources: Mapped[dict] = mapped_column(JSONB, default=dict)
    lifecycle_state: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class CommerceProductCategory(Base):
    """Current many-to-many category membership projection."""

    __tablename__ = "commerce_product_categories"
    __table_args__ = (
        UniqueConstraint(
            "product_id", "category_id", name="uq_commerce_product_category"
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
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_products.id", ondelete="CASCADE"),
        index=True,
    )
    category_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_categories.id", ondelete="CASCADE"),
        index=True,
    )
    source_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceCsvImport(Base):
    """Immutable bounded CSV import artifact and row outcome ledger."""

    __tablename__ = "commerce_csv_imports"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "content_hash", name="uq_commerce_csv_import_hash"
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
    content_hash: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(255), default="")
    content_type: Mapped[str] = mapped_column(String(128), default="text/csv")
    raw_payload: Mapped[str] = mapped_column(Text)
    row_outcomes: Mapped[list] = mapped_column(JSONB, default=list)
    created_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    importer_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_IMPORTER_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceProductObservation(Base):
    """Append-only product evidence from Site Health, CSV, or explicit edit."""

    __tablename__ = "commerce_product_observations"
    __table_args__ = (
        CheckConstraint(
            "(source_kind = 'site_health' AND source_analysis_id IS NOT NULL "
            "AND source_artifact_id IS NOT NULL AND csv_import_id IS NULL) OR "
            "(source_kind = 'csv' AND csv_import_id IS NOT NULL "
            "AND csv_row_number IS NOT NULL AND source_analysis_id IS NULL) OR "
            "(source_kind = 'edit' AND source_analysis_id IS NULL "
            "AND csv_import_id IS NULL)",
            name="ck_commerce_product_observation_source",
        ),
        UniqueConstraint(
            "source_analysis_id",
            "projector_version",
            name="uq_commerce_projection_analysis_version",
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
    product_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_products.id", ondelete="CASCADE"),
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(16))
    source_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_page_analyses.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_fetch_artifacts.id", ondelete="SET NULL"),
        nullable=True,
    )
    csv_import_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_csv_imports.id", ondelete="RESTRICT"),
        nullable=True,
    )
    csv_row_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observed_fields: Mapped[dict] = mapped_column(JSONB, default=dict)
    extractor_version: Mapped[str] = mapped_column(String(64), default="")
    classifier_version: Mapped[str] = mapped_column(String(64), default="")
    importer_version: Mapped[str] = mapped_column(String(64), default="")
    projector_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_PROJECTOR_VERSION
    )
    edit_version: Mapped[str] = mapped_column(String(64), default=COMMERCE_EDIT_VERSION)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceCompetitorAttempt(Base):
    """Immutable optional provider request/result attempt for one typed target."""

    __tablename__ = "commerce_competitor_attempts"
    __table_args__ = (
        UniqueConstraint(
            "task_id", "attempt_number", name="uq_commerce_competitor_attempt"
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
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("analytics_tasks.id", ondelete="CASCADE"),
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    query: Mapped[str] = mapped_column(Text)
    locale: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(24))
    result_payload: Mapped[list] = mapped_column(JSONB, default=list)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    provider_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_COMPETITOR_PROVIDER_VERSION
    )
    validator_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_COMPETITOR_VALIDATOR_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceCompetitorCandidate(Base):
    """Verified candidate or AI-observed competitor with explicit decision."""

    __tablename__ = "commerce_competitor_candidates"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "target_kind",
            "target_id",
            "canonical_url",
            name="uq_commerce_competitor_candidate",
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
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_competitor_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    canonical_url: Mapped[str] = mapped_column(Text)
    product_name: Mapped[str] = mapped_column(String(512), default="")
    brand_name: Mapped[str] = mapped_column(String(255), default="")
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_kind: Mapped[str] = mapped_column(String(24), default="provider")
    state: Mapped[str] = mapped_column(String(16), default="pending")
    decision_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommercePromptTarget(Base):
    """Typed immutable Commerce target relation for an existing Prompt."""

    __tablename__ = "commerce_prompt_targets"
    __table_args__ = (
        UniqueConstraint("prompt_id", name="uq_commerce_prompt_target_prompt"),
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
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("prompts.id", ondelete="CASCADE"), index=True
    )
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    template_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_PROMPT_TEMPLATE_VERSION
    )
    approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceRecommendationObservation(Base):
    """One append-only recognized recommendation from an immutable response."""

    __tablename__ = "commerce_recommendation_observations"
    __table_args__ = (
        Index(
            "ix_commerce_observations_audit_target",
            "audit_id",
            "target_kind",
            "target_id",
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
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_tasks.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_response_artifacts.id", ondelete="CASCADE"),
        index=True,
    )
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_products.id", ondelete="SET NULL"),
        nullable=True,
    )
    competitor_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_competitor_candidates.id", ondelete="SET NULL"),
        nullable=True,
    )
    observed_product: Mapped[str] = mapped_column(String(512), default="")
    observed_brand: Mapped[str] = mapped_column(String(255), default="")
    classification: Mapped[str] = mapped_column(String(32))
    observed_title: Mapped[str] = mapped_column(String(512), default="")
    observed_price: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    observed_currency: Mapped[str] = mapped_column(String(3), default="")
    merchant_url: Mapped[str] = mapped_column(Text, default="")
    merchant_domain: Mapped[str] = mapped_column(String(512), default="")
    surface_kind: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_observable: Mapped[bool] = mapped_column(Boolean, default=False)
    match_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    parser_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_RECOMMENDATION_PARSER_VERSION
    )
    matcher_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_RECOMMENDATION_MATCHER_VERSION
    )
    model_version: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class CommerceObservationCitation(Base):
    """Typed association; citation ownership remains with response analysis."""

    __tablename__ = "commerce_observation_citations"
    __table_args__ = (
        UniqueConstraint(
            "observation_id", "citation_id", name="uq_commerce_observation_citation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    observation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_recommendation_observations.id", ondelete="CASCADE"),
        index=True,
    )
    citation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("citations.id", ondelete="CASCADE"), index=True
    )


class CommerceShelfSnapshot(Base):
    """Immutable formula-versioned metrics for one audit and typed target."""

    __tablename__ = "commerce_shelf_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "target_kind",
            "target_id",
            "formula_version",
            name="uq_commerce_shelf_snapshot",
        ),
        Index("ix_commerce_shelf_project_created", "project_id", "created_at"),
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
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("audits.id", ondelete="CASCADE"), index=True
    )
    target_kind: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    product_visibility: Mapped[float] = mapped_column(Float, default=0.0)
    share_of_shelf: Mapped[float | None] = mapped_column(Float, nullable=True)
    average_shelf_position: Mapped[float | None] = mapped_column(Float, nullable=True)
    first_position_win_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    successful_execution_count: Mapped[int] = mapped_column(Integer, default=0)
    recognized_slot_count: Mapped[int] = mapped_column(Integer, default=0)
    ranked_execution_count: Mapped[int] = mapped_column(Integer, default=0)
    source_observation_ids: Mapped[list] = mapped_column(JSONB, default=list)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    formula_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_SHELF_FORMULA_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
