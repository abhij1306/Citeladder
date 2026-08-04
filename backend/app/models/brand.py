# Normalized brand-identity persistence models (B-1, UUID PKs).
#
# Decision B-1 replaces the reference's JSON-blob brand identity with explicit,
# normalized rows so each alias / domain / competitor is queryable and
# individually editable. A serialization shim (``domain/projects/shim.py``)
# rebuilds the plain dict ``ScoringConfig.from_project`` expects from these rows
# so downstream scoring (B5/B6) works unchanged.
#
# Everything here is scoped to a ``Project`` (which is itself workspace-scoped),
# so access is enforced through the project's workspace (invariant 5).
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.constants import CASCADE_ALL_DELETE_ORPHAN


class BrandLogoAsset(Base):
    """Shared, domain-keyed database cache for safely fetched brand icons."""

    __tablename__ = "brand_logo_assets"
    __table_args__ = (UniqueConstraint("domain", name="uq_brand_logo_asset_domain"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16))
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    content_type: Mapped[str] = mapped_column(String(100), default="")
    image_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")
    fetched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class Brand(Base):
    """The brand a project measures. One brand per project.

    ``brand_name`` is duplicated onto ``Project.brand_name`` for convenience,
    but the aliases live in normalized ``BrandAlias`` rows.
    """

    __tablename__ = "brands"
    __table_args__ = (UniqueConstraint("project_id", name="uq_brand_project"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_logo_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    project: Mapped[Project] = relationship("Project", back_populates="brand")
    logo_asset: Mapped[BrandLogoAsset | None] = relationship("BrandLogoAsset")
    profile: Mapped[BrandProfile | None] = relationship(
        "BrandProfile",
        back_populates="brand",
        uselist=False,
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
    )
    profile_suggestions: Mapped[list[BrandProfileSuggestion]] = relationship(
        "BrandProfileSuggestion",
        back_populates="brand",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
        order_by="BrandProfileSuggestion.created_at.desc()",
    )
    aliases: Mapped[list[BrandAlias]] = relationship(
        "BrandAlias",
        back_populates="brand",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
        order_by="BrandAlias.created_at",
    )


class BrandProfile(Base):
    """Extended brand knowledge base (1:1 with ``Brand``).

    Co-authored: assisted features may draft fields, while the user remains
    authoritative. ``sources`` records per-field provenance using the tokens
    in ``config/brand_profile.py``. Direct ``workspace_id`` + ``project_id``
    keys allow every query to enforce tenant scope without relying on an
    unfiltered relationship traversal (invariant 5).

    The deterministic scorer never reads this table. Assisted features consume
    it only through the shared knowledge-base context builder.
    """

    __tablename__ = "brand_profiles"
    __table_args__ = (UniqueConstraint("brand_id", name="uq_brand_profile_brand"),)

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
        unique=True,
        index=True,
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        index=True,
    )
    # Canonical short blurb: what the brand is / sells.
    description: Mapped[str] = mapped_column(Text, default="")
    # Market positioning: price tier, differentiation, how it competes.
    positioning: Mapped[str] = mapped_column(Text, default="")
    # JSONB array of product/service category strings.
    products_services: Mapped[list[str]] = mapped_column(JSONB, default=list)
    # Who the brand serves.
    target_audience: Mapped[str] = mapped_column(Text, default="")
    # Per-field source tokens: {field_name: "manual" | "ai_suggested"}.
    # Absent key = field never set. Tokens in config/brand_profile.py.
    sources: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    # For AI-suggested fields, maps field name -> immutable suggestion UUID.
    # Manual edits remove the corresponding entry.
    source_artifact_ids: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    brand: Mapped[Brand] = relationship("Brand", back_populates="profile")


class BrandProfileSuggestion(Base):
    """Immutable default-agent draft awaiting explicit human acceptance."""

    __tablename__ = "brand_profile_suggestions"

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
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        index=True,
    )
    model_identity: Mapped[dict[str, str]] = mapped_column(JSONB)
    prompt_template_version: Mapped[str] = mapped_column(String(64))
    input_context_snapshot: Mapped[dict[str, object]] = mapped_column(JSONB)
    output: Mapped[dict[str, object]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    brand: Mapped[Brand] = relationship("Brand", back_populates="profile_suggestions")


class BrandAlias(Base):
    """An alternate spelling / trade name for a project's brand."""

    __tablename__ = "brand_aliases"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        index=True,
    )
    alias: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    brand: Mapped[Brand] = relationship("Brand", back_populates="aliases")


class Competitor(Base):
    """A competitor brand tracked for share-of-voice.

    ``aliases`` and ``domains`` are stored as JSONB string arrays on the row —
    the competitor itself is a first-class normalized entity, but its alias /
    domain lists are value-object arrays consumed wholesale by the scorer.
    """

    __tablename__ = "competitors"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    logo_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_logo_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255))
    aliases: Mapped[list] = mapped_column(JSONB, default=list)
    domains: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    project: Mapped[Project] = relationship("Project", back_populates="competitors")
    logo_asset: Mapped[BrandLogoAsset | None] = relationship("BrandLogoAsset")
    # Competitor product catalog (Agentic Commerce surface).
    products: Mapped[list[CompetitorProduct]] = relationship(
        "CompetitorProduct",
        back_populates="competitor",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
        order_by="CompetitorProduct.created_at",
    )


class OwnedDomain(Base):
    """A domain the brand owns (its answers/citations count as owned)."""

    __tablename__ = "owned_domains"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    project: Mapped[Project] = relationship("Project", back_populates="owned_domains")


class UnintendedDomain(Base):
    """A domain that must NOT be credited as owned (e.g. a support portal)."""

    __tablename__ = "unintended_domains"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )

    project: Mapped[Project] = relationship(
        "Project", back_populates="unintended_domains"
    )


class ObservedEntityCandidate(Base):
    """Immutable audit evidence for a user-confirmed competitor suggestion."""

    __tablename__ = "observed_entity_candidates"
    __table_args__ = (
        UniqueConstraint("audit_id", "domain", name="uq_observed_candidate_domain"),
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
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255))
    qualification_reason: Mapped[str] = mapped_column(Text)
    prompt_count: Mapped[int] = mapped_column(Integer)
    engine_count: Mapped[int] = mapped_column(Integer)
    market_relevant: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzer_version: Mapped[str] = mapped_column(String(32))
    source_analysis_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_artifact_ids: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


from app.models.product import CompetitorProduct  # noqa: E402
from app.models.project import Project  # noqa: E402
