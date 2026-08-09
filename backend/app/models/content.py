# AI content-generation persistence models (UUID PKs, workspace-scoped).
#
# ``ContentGeneration`` is the ``AuditTask`` pattern applied to content: an
# immutable request record that doubles as the shared-queue row (claimed via
# ``FOR UPDATE SKIP LOCKED`` through the generic ``PostgresTaskQueue``) plus
# single-writer result fields (the claiming worker is the only writer —
# invariant 3). ``ContentGenerationAttempt`` is the append-only per-provider-
# call log (one row per actual HTTP call, unique attempt number per record).
#
# Everything is scoped by ``workspace_id`` (invariant 5). Neither table ever
# stores the provider API key (invariant 6).
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config.content import CONTENT_MAX_ATTEMPTS
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.core.database import Base
from app.models.constants import CASCADE_ALL_DELETE_ORPHAN

_WORKSPACE_FK = "workspaces.id"
_PROJECT_FK = "projects.id"
_CONTENT_BRIEF_FK = "content_briefs.id"
_CONTENT_GENERATION_FK = "content_generations.id"
_SITE_SNAPSHOT_FK = "site_health_snapshots.id"
_SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ContentGeneration(Base):
    """One immutable content-generation request + queue row + result.

    The frozen inputs (prompt, output type, website-context snapshot, message
    digest/snapshot) are written at enqueue and never mutated. The queue-lease
    columns mirror ``AuditTask`` exactly so the generic queue serves this row.
    The result fields are single-writer: only the claiming worker's atomic
    ``finalize_attempt`` transaction writes them (invariant 3).

    Idempotency is workspace-scoped: the composite
    ``(workspace_id, idempotency_key)`` unique constraint lets two workspaces
    reuse the same client key while keeping replays race-safe within one.
    """

    __tablename__ = "content_generations"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_content_generation_ws_idem",
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
        PGUUID(as_uuid=True),
        ForeignKey(_PROJECT_FK, ondelete="CASCADE"),
        index=True,
    )
    opportunity_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("opportunities.id", ondelete=_SET_NULL),
        nullable=True,
        index=True,
    )
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_CONTENT_BRIEF_FK, ondelete=_SET_NULL, use_alter=True),
        nullable=True,
        index=True,
    )
    context_package_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_context_packages.id", ondelete=_SET_NULL, use_alter=True),
        nullable=True,
        index=True,
    )

    # --- Frozen inputs (written at enqueue, never mutated) ----------------
    prompt: Mapped[str] = mapped_column(Text)
    skill_id: Mapped[str] = mapped_column(String(64), default="article")
    skill_version: Mapped[str] = mapped_column(String(32), default="content-v1")
    evidence_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output_type: Mapped[str] = mapped_column(String(32))
    website_context_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # included | unavailable | disabled (config CONTEXT_STATUS_*).
    website_context_status: Mapped[str] = mapped_column(String(16), default="")
    # Allowlisted page facts + provenance ids/counts. Never the key.
    website_context_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Stable hash over (project_id, prompt, output_type, context flag): the
    # idempotency replay/conflict comparator.
    request_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    message_digest: Mapped[str] = mapped_column(String(64), default="")
    # Safe truncated copy of the provider messages (provenance). Never the key.
    message_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # --- Queue + lease state (shared column contract with AuditTask) ------
    idempotency_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(24), default=TASK_STATUS_QUEUED, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=CONTENT_MAX_ATTEMPTS)
    randomized_position: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(32), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- Result (single-writer = claiming worker, invariant 3) ------------
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provider + requested model are frozen from config at enqueue — always
    # known up front, so both are required (no empty-string/NULL sentinel).
    provider: Mapped[str] = mapped_column(String(32))
    requested_model: Mapped[str] = mapped_column(String(255))
    returned_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    output_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # What determined the provider request. NEVER the key (invariant 6).
    request_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generator_version: Mapped[str] = mapped_column(String(32), default="")
    validator_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    attempts: Mapped[list[ContentGenerationAttempt]] = relationship(
        "ContentGenerationAttempt",
        back_populates="generation",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
        order_by="ContentGenerationAttempt.attempt_number",
    )


class ContentGenerationAttempt(Base):
    """Append-only record of one actual provider HTTP call (invariant 3).

    One row per real call (retries + failures + a call whose result was
    discarded because the record was cancelled mid-flight). Never the key.
    """

    __tablename__ = "content_generation_attempts"
    __table_args__ = (
        UniqueConstraint(
            "content_generation_id",
            "attempt_number",
            name="uq_content_generation_attempt_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    content_generation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_CONTENT_GENERATION_FK, ondelete="CASCADE"),
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    requested_model: Mapped[str] = mapped_column(String(255), default="")
    returned_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_code: Mapped[str] = mapped_column(String(32), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    generation: Mapped[ContentGeneration] = relationship(
        "ContentGeneration", back_populates="attempts"
    )


class ContentInventoryItem(Base):
    """Immutable page/document projection for one Site snapshot."""

    __tablename__ = "content_inventory_items"
    __table_args__ = (
        UniqueConstraint(
            "site_snapshot_id", "site_analysis_id", name="uq_content_inventory_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    site_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_SITE_SNAPSHOT_FK, ondelete="CASCADE"),
        index=True,
    )
    site_analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("site_page_analyses.id", ondelete="CASCADE"),
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("site_urls.id", ondelete="CASCADE")
    )
    canonical_url: Mapped[str] = mapped_column(String(2048))
    page_kind: Mapped[str] = mapped_column(String(24))
    industry_role_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    temporal_state: Mapped[str] = mapped_column(String(16))
    purpose: Mapped[dict] = mapped_column(JSONB, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ContentStrategySnapshot(Base):
    """Immutable deterministic portfolio strategy over Site and optional Demand."""

    __tablename__ = "content_strategy_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_hash", name="uq_content_strategy_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    site_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_SITE_SNAPSHOT_FK, ondelete="CASCADE")
    )
    demand_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete=_SET_NULL),
        nullable=True,
    )
    source_hash: Mapped[str] = mapped_column(String(64))
    industry_pack_id: Mapped[str] = mapped_column(String(64))
    industry_pack_version: Mapped[str] = mapped_column(String(32))
    inventory_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    priorities: Mapped[list] = mapped_column(JSONB, default=list)
    program: Mapped[list] = mapped_column(JSONB, default=list)
    limitations: Mapped[list] = mapped_column(JSONB, default=list)
    source_versions: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ContentBrief(Base):
    """Immutable, versioned instruction artifact containing no generated prose."""

    __tablename__ = "content_briefs"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "identity_hash", name="uq_content_brief_identity"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    strategy_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_strategy_snapshots.id", ondelete=_SET_NULL),
        nullable=True,
    )
    prior_brief_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_CONTENT_BRIEF_FK, ondelete=_SET_NULL),
        nullable=True,
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    identity_hash: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    target: Mapped[dict] = mapped_column(JSONB, default=dict)
    requirements: Mapped[dict] = mapped_column(JSONB, default=dict)
    allowed_facts: Mapped[list] = mapped_column(JSONB, default=list)
    prohibited_claims: Mapped[list] = mapped_column(JSONB, default=list)
    source_refs: Mapped[list] = mapped_column(JSONB, default=list)
    verification_criteria: Mapped[list] = mapped_column(JSONB, default=list)
    industry_pack_id: Mapped[str] = mapped_column(String(64))
    industry_pack_version: Mapped[str] = mapped_column(String(32))
    brief_builder_version: Mapped[str] = mapped_column(String(32))
    evidence_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class TaskContextPackage(Base):
    """Frozen, bounded and inspectable task-specific provider context."""

    __tablename__ = "task_context_packages"
    __table_args__ = (
        UniqueConstraint(
            "brief_id", "manifest_hash", name="uq_content_context_manifest"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    brief_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_CONTENT_BRIEF_FK, ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(String(32))
    manifest: Mapped[dict] = mapped_column(JSONB)
    rendered_context: Mapped[dict] = mapped_column(JSONB)
    omissions: Mapped[list] = mapped_column(JSONB, default=list)
    selection_policy_version: Mapped[str] = mapped_column(String(32))
    manifest_hash: Mapped[str] = mapped_column(String(64))
    char_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ContentValidation(Base):
    """Immutable automatic validator result for one generated output."""

    __tablename__ = "content_validations"
    __table_args__ = (
        UniqueConstraint(
            "content_generation_id", name="uq_content_validation_generation"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    content_generation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_CONTENT_GENERATION_FK, ondelete="CASCADE")
    )
    status: Mapped[str] = mapped_column(String(16))
    blocking: Mapped[bool] = mapped_column(Boolean)
    checks: Mapped[list] = mapped_column(JSONB)
    validator_version: Mapped[str] = mapped_column(String(32))
    brief_evidence_hash: Mapped[str] = mapped_column(String(64), default="")
    context_manifest_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ContentRevision(Base):
    """User-editable draft; saving is the sole durable content decision."""

    __tablename__ = "content_revisions"
    __table_args__ = (
        UniqueConstraint(
            "content_generation_id", name="uq_content_revision_generation"
        ),
        CheckConstraint(
            "state IN ('draft','edited','saved','published_claimed','discarded')",
            name="ck_content_revision_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    content_generation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_CONTENT_GENERATION_FK, ondelete="CASCADE")
    )
    state: Mapped[str] = mapped_column(String(24), default="draft")
    visible_content: Mapped[str] = mapped_column(Text)
    structured_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    validation_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    publication_target_url: Mapped[str] = mapped_column(String(2048), default="")
    publication_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    saved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete=_SET_NULL), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class ContentRevisionTransition(Base):
    """Append-only state transition history for a revision."""

    __tablename__ = "content_revision_transitions"

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
    revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_revisions.id", ondelete="CASCADE"),
        index=True,
    )
    from_state: Mapped[str] = mapped_column(String(24))
    to_state: Mapped[str] = mapped_column(String(24))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete=_SET_NULL), nullable=True
    )
    reason: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ContentVerification(Base):
    """Immutable observation of a saved revision against a later Site snapshot."""

    __tablename__ = "content_verifications"
    __table_args__ = (
        UniqueConstraint(
            "revision_id",
            "site_snapshot_id",
            name="uq_content_verification_observation",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("content_revisions.id", ondelete="CASCADE"),
        index=True,
    )
    site_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_SITE_SNAPSHOT_FK, ondelete="CASCADE")
    )
    demand_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("demand_snapshots.id", ondelete=_SET_NULL),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(24))
    requirements: Mapped[list] = mapped_column(JSONB)
    comparison: Mapped[dict] = mapped_column(JSONB, default=dict)
    coverage: Mapped[dict] = mapped_column(JSONB, default=dict)
    verifier_version: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
