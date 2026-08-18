# Product-catalog persistence models (Agentic Commerce / Product Visibility).
#
# One surface's catalog + derived rows live in this module (convention:
# ``models/site_health/``). ``Product`` mirrors ``Competitor``'s shape
# (``models/brand.py``): a first-class row with JSONB value-object arrays
# (``aliases``, ``variants``). ``CompetitorProduct`` is a separate table
# FK -> ``competitors.id`` (mirrors the Brand-vs-Competitor separation;
# competitor rows need no attribute completeness).
#
# Everything is scoped to a ``Project`` (itself workspace-scoped), so access is
# enforced through the project's workspace (invariant 5). The catalog is frozen
# into every audit's ``configuration`` at creation (``domain/products/shim.py``)
# so re-scoring is deterministic (invariant 9).
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.core.config.products import DEFAULT_PRODUCT_ORIGIN
from app.core.database import Base
from app.models.constants import (
    CASCADE_ALL_DELETE_ORPHAN,
    FK_AUDITS_ID,
    ON_DELETE_SET_NULL,
)


class Product(Base):
    """One own-catalog SKU tracked for product visibility.

    ``aliases`` and ``variants`` are JSONB value-object arrays consumed
    wholesale by the deterministic product scorer (variant names/SKUs fold
    into the matching alias set). ``price`` is nullable — a product without a
    catalog price still scores mentions/rank; price accuracy is then null.
    """

    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("project_id", "sku", name="uq_product_project_sku"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    sku: Mapped[str] = mapped_column(String(128))
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    # Value-object array: [{"name": str, "sku": str, "price": float|null}, ...]
    variants: Mapped[list] = mapped_column(JSONB, default=list)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    # Free-form attribute bag (brand/category/gtin/availability/...). The
    # deterministic completeness matrix reads config-owned keys from it.
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    # manual | imported | synced (config/products.py PRODUCT_ORIGIN_*).
    origin: Mapped[str] = mapped_column(String(32), default=DEFAULT_PRODUCT_ORIGIN)
    # Discovery provenance is immutable evidence of how this row entered the
    # catalog. A later manual edit changes catalog fields, never these links.
    source_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_discovery_candidates.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_discovery_artifacts.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    # --- Feed provenance (commerce suite; all null/"" for manual|imported) ---
    # The integration connection whose feed last carried this SKU. SET NULL
    # keeps the catalog row when the connection disconnects.
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    # The provider's opaque item id (Shopify: the variant id) — provenance
    # only; catalog identity stays (project_id, sku).
    external_item_ref: Mapped[str] = mapped_column(String(255), default="")
    # The latest sync run whose feed carried this SKU: staleness is inferred
    # by comparing this to the connection's latest successful catalog run.
    last_seen_sync_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("integration_sync_runs.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    project: Mapped[Project] = relationship("Project", back_populates="products")


class CompetitorProduct(Base):
    """One competitor product tracked for product share-of-voice.

    Separate from ``Product`` (mirrors Brand-vs-Competitor): competitor rows
    carry no variants/attributes completeness — just identity + price.
    """

    __tablename__ = "competitor_products"
    __table_args__ = (
        UniqueConstraint(
            "competitor_id", "name", name="uq_competitor_product_competitor_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("competitors.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="")
    url: Mapped[str] = mapped_column(Text, default="")
    variants: Mapped[list] = mapped_column(JSONB, default=list)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict)
    availability: Mapped[str] = mapped_column(String(64), default="")
    extraction_fresh_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_discovery_candidates.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("commerce_discovery_artifacts.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    project: Mapped[Project] = relationship(
        "Project", back_populates="competitor_products"
    )
    competitor: Mapped[Competitor] = relationship(
        "Competitor", back_populates="products"
    )


class ProductResponseAnalysis(Base):
    """Deterministic per-execution PRODUCT analysis of one raw response.

    Sibling of ``ResponseAnalysis`` (``models/analysis.py`` B6): computed from
    the same immutable ``RawResponseArtifact`` by the product analyzer pass,
    stamped with ``product_analyzer_version`` + ``product_scoring_rule_version``
    (invariant 4). One row per execution PER analyzer/rule version pair
    (D1: a persisted v1 analysis and a v2 re-score coexist); its
    ``ProductMention``/``MerchantMention`` children hang off it. Never
    touches the brand-level derived rows.
    """

    __tablename__ = "product_response_analyses"
    __table_args__ = (
        # One product analysis per execution per analyzer/rule version pair.
        UniqueConstraint(
            "task_id",
            "product_analyzer_version",
            "product_scoring_rule_version",
            name="uq_product_response_analysis_task_version",
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
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(FK_AUDITS_ID, ondelete="CASCADE"),
        index=True,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_tasks.id", ondelete="CASCADE"),
        index=True,
    )
    # Provenance (invariant 4): SET NULL keeps the analysis if the artifact is
    # ever pruned.
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_response_artifacts.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    product_analyzer_version: Mapped[str] = mapped_column(String(32))
    product_scoring_rule_version: Mapped[str] = mapped_column(String(32))

    # Denormalized provenance triple + slot identity (invariant 10).
    logical_engine: Mapped[str] = mapped_column(String(32), default="")
    transport_provider: Mapped[str] = mapped_column(String(32), default="")
    transport_model: Mapped[str] = mapped_column(String(255), default="")
    prompt_index: Mapped[int] = mapped_column(Integer, default=0)
    repetition: Mapped[int] = mapped_column(Integer, default=0)
    # Shopping-surface slot identity (§7.1): "" = answer-engine-API
    # measurement; probe surfaces stamp their configured id.
    shopping_surface: Mapped[str] = mapped_column(
        String(32), default=SHOPPING_SURFACE_MEASUREMENT
    )

    # Flat headline signals (per-execution).
    own_product_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_product_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    products_with_price_match: Mapped[int] = mapped_column(Integer, default=0)

    # Full deterministic product score dict (source of truth for aggregation).
    score: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    product_mentions: Mapped[list[ProductMention]] = relationship(
        "ProductMention",
        back_populates="analysis",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
    )
    merchant_mentions: Mapped[list[MerchantMention]] = relationship(
        "MerchantMention",
        back_populates="analysis",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
    )


class ProductMention(Base):
    """One recorded product mention in a response (invariant 4).

    Exactly one of ``product_id`` / ``competitor_product_id`` is set at write
    time (single deterministic writer). Both FKs are SET NULL and the matched
    identity is snapshotted onto the row (``matched_name``/``matched_sku``) so
    evidence survives catalog deletes — mirrors nullable
    ``AuditPromptSnapshot.prompt_id``. No exactly-one-target CHECK constraint:
    it would reject the SET NULL a catalog delete legitimately triggers.
    """

    __tablename__ = "product_mentions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(FK_AUDITS_ID, ondelete="CASCADE"),
        index=True,
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_response_analyses.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_response_artifacts.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    product_analyzer_version: Mapped[str] = mapped_column(String(32))
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    competitor_product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("competitor_products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    # Snapshotted identity (survives catalog deletes).
    matched_name: Mapped[str] = mapped_column(String(255), default="")
    matched_sku: Mapped[str] = mapped_column(String(128), default="")
    first_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Price extraction evidence (empty/absent when no price was detected).
    price_text: Mapped[str] = mapped_column(String(64), default="")
    price_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_currency: Mapped[str] = mapped_column(String(3), default="")
    # null = not verifiable (no catalog price / currency mismatch).
    price_matches_catalog: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Analyzer v2 price direction (commerce.py PRICE_RELATION_*): null =
    # unverifiable; v1 rows predate the column and read back via the
    # match/mismatch projection fallback.
    price_relation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Analyzer v2 attribute evidence: [{"dimension", "group", "text",
    # "offset"}] objects only (frequency, no valence).
    attribute_mentions: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    analysis: Mapped[ProductResponseAnalysis] = relationship(
        "ProductResponseAnalysis", back_populates="product_mentions"
    )


class MerchantMention(Base):
    """One observed buyer-destination URL attached to a product signal.

    Written by the analyzer v2 pass beside the ``ProductMention`` rows: one
    row per sanitized destination URL observed in the mention's window, with
    the same provenance and nullable live-catalog FK behavior (exactly one
    target FK is set at write time; no CHECK — a catalog delete can
    legitimately SET NULL both, §5.6/D3).
    """

    __tablename__ = "merchant_mentions"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        index=True,
    )
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(FK_AUDITS_ID, ondelete="CASCADE"),
        index=True,
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("product_response_analyses.id", ondelete="CASCADE"),
        index=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_response_artifacts.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    competitor_product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("competitor_products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    merchant_name: Mapped[str] = mapped_column(String(255))
    merchant_domain: Mapped[str] = mapped_column(String(255))
    merchant_kind: Mapped[str] = mapped_column(String(16))
    destination_url: Mapped[str] = mapped_column(Text)
    # Optional merchant price evidence (the first same-line price).
    price_text: Mapped[str] = mapped_column(String(64), default="")
    price_value: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_currency: Mapped[str] = mapped_column(String(3), default="")
    product_analyzer_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    analysis: Mapped[ProductResponseAnalysis] = relationship(
        "ProductResponseAnalysis", back_populates="merchant_mentions"
    )


class ProductMetricSnapshot(Base):
    """Per-(audit, product) aggregate product-visibility projection.

    One row per (audit, product) and per (audit, competitor_product) —
    enforced by two partial unique indexes (functional/unique ``Index``
    convention exists on ``Topic``). Computed once at finalize from persisted
    ``ProductResponseAnalysis`` rows only (invariant 7), stamped with the
    analyzer/rule versions + the exact evidence set (invariant 4).
    """

    __tablename__ = "product_metric_snapshots"
    __table_args__ = (
        # Versioned identity: v1 and v2 snapshots for the same entry
        # coexist (historical snapshots stay immutable).
        Index(
            "uq_product_metric_snapshot_product",
            "audit_id",
            "product_id",
            "product_analyzer_version",
            "product_scoring_rule_version",
            unique=True,
            postgresql_where=text("product_id IS NOT NULL"),
        ),
        Index(
            "uq_product_metric_snapshot_competitor_product",
            "audit_id",
            "competitor_product_id",
            "product_analyzer_version",
            "product_scoring_rule_version",
            unique=True,
            postgresql_where=text("competitor_product_id IS NOT NULL"),
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
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(FK_AUDITS_ID, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    # Exactly one set; SET NULL keeps the aggregate if the catalog row is
    # deleted (the ``metrics`` payload still carries the frozen identity).
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    competitor_product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("competitor_products.id", ondelete=ON_DELETE_SET_NULL),
        nullable=True,
    )
    product_analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    product_scoring_rule_version: Mapped[str] = mapped_column(String(32), default="")
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    sov_share: Mapped[float] = mapped_column(default=0.0)
    avg_rank: Mapped[float | None] = mapped_column(nullable=True)
    rank_distribution: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    price_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    price_accuracy_rate: Mapped[float | None] = mapped_column(nullable=True)
    # Analyzer v2 scalars (null on v1 rows / when their denominator is 0).
    win_rate: Mapped[float | None] = mapped_column(nullable=True)
    price_mismatch_rate: Mapped[float | None] = mapped_column(nullable=True)
    # Full aggregate dict (per-engine/per-surface breakdowns, relation
    # counts, attribute frequency, destination mix, co-placement, ...).
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Provenance (invariant 4): the exact evidence set aggregated.
    source_analysis_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_artifact_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


from app.models.brand import Competitor  # noqa: E402
from app.models.project import Project  # noqa: E402
