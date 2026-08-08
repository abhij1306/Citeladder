# Typed project knowledge derived from crawled evidence (kernel spec Phase B).
#
# Three tables, added only after proving the existing owners cannot carry this
# cleanly (see docs/plans/knowledge-kernel-and-industry-pack-spec.md, "Phase B").
# The short version: a contradiction GROUP spans pages and has no page row to
# live on; question coverage needs a predicate-indexed lookup across the whole
# corpus; entity identity and relations are cross-page by construction; and
# review state must outlive the append-only recomputation of a page analysis.
#
# What did NOT move here: raw bodies stay in ``SiteFetchArtifact`` — every row
# below references evidence by source ID plus a bounded locator and never
# duplicates a body. ``SitePageAnalysis`` remains the sole page-understanding
# owner; these tables hold only the irreducibly cross-page part.
#
# All three are CRAWL-SCOPED derived projections, exactly like the analyses they
# come from: a recrawl builds a new set and never mutates the first, so an
# earlier snapshot stays reproducible. ``identity_key`` is project-stable, which
# is what makes two crawls comparable without either one being rewritten.
#
# IDs are DETERMINISTIC (uuid5 over the crawl plus the row's natural key), so
# replaying the same artifacts under the same versions reproduces byte-identical
# knowledge — the S2 gate — and a re-run is naturally idempotent.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.site_health import TEMPORAL_STATE_UNKNOWN
from app.core.config.site_intelligence import (
    REVIEW_STATE_OBSERVED,
    VALUE_TYPE_STRING,
)
from app.core.database import Base

_FK_WORKSPACE = "workspaces.id"
_FK_PROJECT = "projects.id"
_FK_SITE_CRAWL = "site_crawls.id"
_FK_KNOWLEDGE_ENTITY = "knowledge_entities.id"
_ON_DELETE_CASCADE = "CASCADE"

# uuid5 namespaces. Fixed constants, never regenerated: changing one would give
# every future row a different ID for the same fact and break cross-crawl
# comparison at the exact point it matters.
_NS_ENTITY = uuid.UUID("6f0e5b3a-1c2d-5e4f-8a9b-0c1d2e3f4a5b")
_NS_ASSERTION = uuid.UUID("7a1f6c4b-2d3e-5f60-9b0c-1d2e3f4a5b6c")
_NS_RELATION = uuid.UUID("8b2a7d5c-3e4f-5061-ac1d-2e3f4a5b6c7d")
_NS_CONTRADICTION = uuid.UUID("9c3b8e6d-4f50-5172-bd2e-3f4a5b6c7d8e")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def entity_id(crawl_id: uuid.UUID, entity_type_id: str, identity_key: str) -> uuid.UUID:
    """The deterministic ID for one entity in one crawl."""
    return uuid.uuid5(_NS_ENTITY, f"{crawl_id}|{entity_type_id}|{identity_key}")


def assertion_id(
    crawl_id: uuid.UUID,
    subject_entity_id: uuid.UUID,
    predicate_id: str,
    scope_key: str,
    normalized_value: str,
) -> uuid.UUID:
    """The deterministic ID for one assertion in one crawl.

    The VALUE is part of the key on purpose: two incompatible values for the
    same subject/predicate/scope are two assertions that both survive, which is
    what makes a contradiction inspectable rather than a last-writer-wins
    overwrite.
    """
    return uuid.uuid5(
        _NS_ASSERTION,
        f"{crawl_id}|{subject_entity_id}|{predicate_id}|{scope_key}|{normalized_value}",
    )


def relation_id(
    crawl_id: uuid.UUID,
    relation_type_id: str,
    source_entity_id: uuid.UUID,
    target_entity_id: uuid.UUID,
) -> uuid.UUID:
    """The deterministic ID for one relation edge in one crawl."""
    return uuid.uuid5(
        _NS_RELATION,
        f"{crawl_id}|{relation_type_id}|{source_entity_id}|{target_entity_id}",
    )


def contradiction_group_id(
    crawl_id: uuid.UUID,
    subject_entity_id: uuid.UUID,
    predicate_id: str,
    scope_key: str,
) -> uuid.UUID:
    """The deterministic group shared by every side of one disputed fact.

    Derived from what DEFINES the contradiction — same subject, same predicate,
    overlapping scope — and deliberately not from the values, so every
    conflicting value lands in the same group.
    """
    return uuid.uuid5(
        _NS_CONTRADICTION,
        f"{crawl_id}|{subject_entity_id}|{predicate_id}|{scope_key}",
    )


class KnowledgeEntity(Base):
    """One thing the project's corpus is about, deduplicated across pages.

    ``identity_key`` is the deterministic normalization of the pack's declared
    identity fields — it is what makes the organization named on ``/about``, on
    ``/contact``, and in every page's JSON-LD ONE row instead of three. An
    entity is created for a subject the pack recognizes, never for every proper
    noun a page mentions.
    """

    __tablename__ = "knowledge_entities"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id",
            "entity_type_id",
            "identity_key",
            name="uq_knowledge_entity_identity",
        ),
        Index("ix_knowledge_entity_crawl_type", "crawl_id", "entity_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
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
        index=True,
    )
    # Pack-declared type (e.g. ``education.organization``). Never a free string.
    entity_type_id: Mapped[str] = mapped_column(String(64))
    # Deterministic normalization of the pack's identity fields.
    identity_key: Mapped[str] = mapped_column(String(256))
    canonical_name: Mapped[str] = mapped_column(String(512), default="")
    # Bounded observed spellings and external identifiers (sameAs, registration
    # numbers). Review aids: the identity KEY is the authority.
    aliases: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    identifiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), default=REVIEW_STATE_OBSERVED)
    # ``KnowledgeSourceRef`` list: source kind + source ID + bounded locator.
    # Never an excerpt presented as the authority.
    evidence_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # How many distinct pages asserted this entity — the cheap signal for
    # "central to the site" vs "mentioned once".
    evidence_page_count: Mapped[int] = mapped_column(Integer, default=0)
    industry_pack_id: Mapped[str] = mapped_column(String(64), default="")
    industry_pack_version: Mapped[str] = mapped_column(String(32), default="")
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class KnowledgeAssertion(Base):
    """One typed subject-predicate-value claim with mandatory evidence.

    Evidence is not optional metadata: a row without ``evidence_refs`` is not a
    weaker fact, it is an invented one. Extraction drops a candidate it cannot
    point at rather than persisting it, and a missing required fact is recorded
    as a coverage gap — never as a guessed assertion.

    Conflicting values are BOTH retained and share a ``contradiction_group_id``.
    Nothing in the deterministic pipeline picks a winner; ``review_state`` stays
    ``observed`` until a person resolves it.
    """

    __tablename__ = "knowledge_assertions"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id",
            "subject_entity_id",
            "predicate_id",
            "scope_key",
            "normalized_value",
            name="uq_knowledge_assertion_claim",
        ),
        # Question coverage's hot path: "is there a current assertion for this
        # predicate in this crawl?" — reason 2 of the Phase B proof.
        Index("ix_knowledge_assertion_predicate", "crawl_id", "predicate_id"),
        Index(
            "ix_knowledge_assertion_contradiction",
            "crawl_id",
            "contradiction_group_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
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
        index=True,
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_KNOWLEDGE_ENTITY, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    # Pack-declared predicate (e.g. ``education.fee_amount``).
    predicate_id: Mapped[str] = mapped_column(String(64))
    value_type: Mapped[str] = mapped_column(String(16), default=VALUE_TYPE_STRING)
    # The value as observed, and the comparison form. Contradiction detection
    # reads ONLY the normalized value, so "INR 2,50,000" and "250000 INR" are
    # one fact rather than a fabricated conflict.
    raw_value: Mapped[str] = mapped_column(String(512), default="")
    normalized_value: Mapped[str] = mapped_column(String(512), default="")
    numeric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), default="")
    # A money value without this is dropped at extraction, not stored bare: a
    # number a report could render beside the wrong symbol is worse than a gap.
    currency: Mapped[str] = mapped_column(String(8), default="")
    # Pack-required qualifiers (grade, campus, term). ``scope_key`` is their
    # deterministic serialization and is part of both the claim identity and the
    # contradiction group — differently-scoped values are not in conflict.
    scope: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scope_key: Mapped[str] = mapped_column(String(256), default="")
    # Whether every qualifier the pack REQUIRES was evidenced rather than
    # defaulted. ``False`` marks a real claim whose applicability is unknown —
    # a fee with no stated academic year, grade, or fee type. Such claims never
    # contradict each other (two unscoped fees may be two different grades) and
    # must never be published as if scoped.
    # ``server_default`` as well as the ORM default: ``_persist`` writes these
    # rows through a Core insert, which does not apply Python-side column
    # defaults, so a NOT NULL column without one would reject every write.
    scope_complete: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=text("true")
    )
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    temporal_state: Mapped[str] = mapped_column(
        String(16), default=TEMPORAL_STATE_UNKNOWN
    )
    evidence_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    derivation_method: Mapped[str] = mapped_column(String(24), default="")
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), default=REVIEW_STATE_OBSERVED)
    # NULL when nothing disputes this claim. Set on EVERY side of a conflict.
    contradiction_group_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    industry_pack_id: Mapped[str] = mapped_column(String(64), default="")
    industry_pack_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class KnowledgeRelation(Base):
    """One typed edge between two entities (campus ``part_of`` institution).

    An edge between entities discovered on different pages cannot live on either
    endpoint's page row without electing an arbitrary owner — reason 3 of the
    Phase B proof.
    """

    __tablename__ = "knowledge_relations"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id",
            "relation_type_id",
            "source_entity_id",
            "target_entity_id",
            name="uq_knowledge_relation_edge",
        ),
        Index("ix_knowledge_relation_crawl_type", "crawl_id", "relation_type_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
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
        index=True,
    )
    relation_type_id: Mapped[str] = mapped_column(String(64))
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_KNOWLEDGE_ENTITY, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_KNOWLEDGE_ENTITY, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    qualifiers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    temporal_state: Mapped[str] = mapped_column(
        String(16), default=TEMPORAL_STATE_UNKNOWN
    )
    evidence_refs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    derivation_method: Mapped[str] = mapped_column(String(24), default="")
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_state: Mapped[str] = mapped_column(String(16), default=REVIEW_STATE_OBSERVED)
    industry_pack_id: Mapped[str] = mapped_column(String(64), default="")
    industry_pack_version: Mapped[str] = mapped_column(String(32), default="")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
