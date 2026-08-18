# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .common import (
    _FK_SITE_CRAWL,
    _FK_SITE_CRAWL_TASK,
    _FK_SITE_FETCH_ARTIFACT,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _ON_DELETE_SET_NULL,
    _utcnow,
)


class SiteFetchAttempt(Base):
    """Append-only diagnostic record of one actual HTTP attempt (invariant 3).

    One row per REAL network call: the fetch makes one network call per
    redirect hop, and every such call gets its own row — a blocked or failed
    call never vanishes. ``attempt_number`` stays the QUEUE-attempt number;
    ``request_ordinal`` is the deterministic per-call ordinal (0-based across
    the whole ``fetch()`` call). Order/uniqueness key:
    ``(task_id, attempt_number, request_ordinal)``.

    Records the target host (never credentials or query secrets), the method,
    the safe outcome/error token, the status, latency, and byte counts. Never
    stores a raw body or a sensitive header.
    """

    __tablename__ = "site_fetch_attempts"
    __table_args__ = (
        UniqueConstraint(
            "task_id",
            "attempt_number",
            "request_ordinal",
            name="uq_site_fetch_attempt_call",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL_TASK, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    # Deterministic per-network-call ordinal within one fetch() (0-based).
    request_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(8), default="")
    # Host only — no credentials, no query string secrets.
    target_host: Mapped[str] = mapped_column(String(255), default="")
    outcome: Mapped[str] = mapped_column(String(16), default="")
    error_code: Mapped[str] = mapped_column(String(32), default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wire_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decoded_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Safe acquisition provenance for this exact real network call. Never
    # carries provider credentials, a provider request URL, or raw response.
    acquisition_transport: Mapped[str] = mapped_column(String(32), default="")
    acquisition_rung: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquisition_trigger: Mapped[str] = mapped_column(String(32), default="")
    impersonation_profile: Mapped[str] = mapped_column(String(64), default="")
    # Bounded, transport-neutral options describing the winning rung's request
    # shape (never a credential, never a vendor request id).
    acquisition_options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    acquisition_policy_version: Mapped[str] = mapped_column(String(32), default="")
    # Set on the succeeding attempt (SET NULL if the artifact is later removed).
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

class SiteFetchArtifact(Base):
    """Immutable evidence: one successful fetch's delivery facts (invariant 3).

    Written exactly once by the claiming worker (unique ``task_id``). Stores the
    requested/final URL, the redirect chain, the status, the redacted response
    headers (allowlist only), the content type/hash, timing/byte facts, the HTTP
    version, the extractor version, and bounded normalized parsed facts for
    analyze tasks. There is NO raw HTML body column — only bounded, redacted
    normalized facts (subplan Persistence contract).
    """

    __tablename__ = "site_fetch_artifacts"
    __table_args__ = (UniqueConstraint("task_id", name="uq_site_fetch_artifact_task"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL_TASK, ondelete=_ON_DELETE_CASCADE),
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    fetch_purpose: Mapped[str] = mapped_column(String(16), default="")
    requested_url: Mapped[str] = mapped_column(String(2048), default="")
    final_url: Mapped[str] = mapped_column(String(2048), default="")
    # Ordered redirect hops (safe: URLs only, no credentials).
    redirect_chain: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Response headers, redacted to the config-owned allowlist.
    redacted_headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), default="")
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    http_version: Mapped[str] = mapped_column(String(16), default="")
    ttfb_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wire_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decoded_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Provenance of the terminal successful acquisition rung. Attempt rows hold
    # the complete ladder; this repeats the winning safe metadata for direct
    # artifact reads without joining attempts.
    acquisition_transport: Mapped[str] = mapped_column(String(32), default="")
    acquisition_rung: Mapped[int | None] = mapped_column(Integer, nullable=True)
    acquisition_trigger: Mapped[str] = mapped_column(String(32), default="")
    impersonation_profile: Mapped[str] = mapped_column(String(64), default="")
    # Bounded, transport-neutral options describing the winning rung's request
    # shape (never a credential, never a vendor request id).
    acquisition_options: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    acquisition_policy_version: Mapped[str] = mapped_column(String(32), default="")
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    # Bounded normalized parsed facts (analyze tasks). Never a raw body.
    normalized_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

