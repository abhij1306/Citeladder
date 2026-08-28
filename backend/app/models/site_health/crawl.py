# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_PENDING,
    CRAWL_STATUS_DRAFT,
    DISCOVERY_STATUS_PENDING,
)
from app.core.config.site_health_crawl_policy import (
    FRONTIER_PENDING,
    PHASE_RUN_RUNNING,
)
from app.core.database import Base
from app.models.constants import CASCADE_ALL_DELETE_ORPHAN

from .common import (
    _FK_PROJECT,
    _FK_SITE_CRAWL,
    _FK_SITE_HEALTH_PROFILE,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _utcnow,
)

if TYPE_CHECKING:
    from .events import SiteCrawlEvent
    from .queue import SiteCrawlTask


class SiteCrawl(Base):
    """One crawl run with independent overall/discovery/analysis sub-states.

    Freezes the entitlement/config/rule/version snapshots into ``configuration``
    at creation so a live env change never alters an in-flight run (invariant
    9). Carries the deterministic seed, the sample flag, the visible admitted/
    discovered/analyzed/failed counters, and the latest score summary. It never
    stores or exposes a full-site total for a sample crawl.
    """

    __tablename__ = "site_crawls"
    __table_args__ = (
        # Backs the composite (workspace_id, project_id, crawl_id) foreign key
        # from ``SiteUrlObservation`` that pins an observation's crawl to its
        # own workspace AND project (tenant-consistency guard). Including
        # ``workspace_id`` makes the observation's own ``workspace_id`` unable
        # to drift away from the crawl's workspace.
        UniqueConstraint(
            "id",
            "project_id",
            "workspace_id",
            name="uq_site_crawls_id_project",
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
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_PROJECT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_HEALTH_PROFILE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24), default=CRAWL_STATUS_DRAFT, index=True
    )
    discovery_status: Mapped[str] = mapped_column(
        String(24), default=DISCOVERY_STATUS_PENDING
    )
    analysis_status: Mapped[str] = mapped_column(
        String(24), default=ANALYSIS_STATUS_PENDING
    )
    root_url: Mapped[str] = mapped_column(String(2048), default="")
    # 64-bit seed stored as text so the full unsigned range survives Postgres'
    # signed bigint and reproduces the deterministic frontier order.
    random_seed: Mapped[str] = mapped_column(String(32), default="")
    # Frozen entitlement/config/rule/version snapshot (never re-read live).
    configuration: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    sample_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    # Visible counters (never a hidden full-site total for a sample crawl).
    admitted_url_count: Mapped[int] = mapped_column(Integer, default=0)
    discovered_url_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_url_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_url_count: Mapped[int] = mapped_column(Integer, default=0)
    discovery_requested_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_requested_count: Mapped[int] = mapped_column(Integer, default=0)
    inventory_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    # Why a terminal crawl is PARTIALLY_COMPLETED: unreachable URLs during
    # discovery, analyses that fell short, or both. Empty on every other status.
    # Without it the UI can only guess, and it guessed "analysis" for every
    # crawl that merely met one dead link.
    partial_reason: Mapped[str] = mapped_column(String(48), default="")
    score_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # v2 P2 (spec §5.5): bounded site-level facts written ONCE by the root
    # discover task's site setup (robots.txt AI-crawler stance, llms.txt
    # result, sitemap file list). Both the dashboard display copy and the
    # injection source for the site_root-scoped rules (facts["site"]); it
    # carries NO discovered totals, so Free non-disclosure is untouched.
    site_facts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    rule_catalog_version: Mapped[str] = mapped_column(String(32), default="")
    scoring_version: Mapped[str] = mapped_column(String(32), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tasks: Mapped[list[SiteCrawlTask]] = relationship(
        "SiteCrawlTask",
        back_populates="crawl",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
    )
    events: Mapped[list[SiteCrawlEvent]] = relationship(
        "SiteCrawlEvent",
        back_populates="crawl",
        cascade=CASCADE_ALL_DELETE_ORPHAN,
        passive_deletes=True,
        order_by="SiteCrawlEvent.created_at",
    )


class SiteCrawlPhaseRun(Base):
    """One user-started discovery or analysis batch within a resumable crawl."""

    __tablename__ = "site_crawl_phase_runs"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id", "phase", "ordinal", name="uq_site_phase_run_ordinal"
        ),
        Index("ix_site_phase_runs_crawl_phase", "crawl_id", "phase", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    phase: Mapped[str] = mapped_column(String(16))
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(
        String(16), default=PHASE_RUN_RUNNING, index=True
    )
    requested_count: Mapped[int] = mapped_column(Integer)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class SiteDiscoveryFrontier(Base):
    """Persisted, deterministic discovery candidates awaiting a later batch."""

    __tablename__ = "site_discovery_frontier"
    __table_args__ = (
        UniqueConstraint("crawl_id", "url_hash", name="uq_site_discovery_frontier_url"),
        Index(
            "ix_site_discovery_frontier_pending",
            "crawl_id",
            "status",
            desc("value_priority"),
            "parent_position",
            "link_ordinal",
            "url_hash",
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
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    normalized_url: Mapped[str] = mapped_column(String(2048))
    url_hash: Mapped[str] = mapped_column(String(64))
    depth: Mapped[int] = mapped_column(Integer, default=0)
    source_kind: Mapped[str] = mapped_column(String(16))
    value_kind: Mapped[str] = mapped_column(String(32), default="other")
    value_priority: Mapped[int] = mapped_column(Integer, default=0)
    parent_position: Mapped[int] = mapped_column(Integer, default=0)
    link_ordinal: Mapped[int] = mapped_column(Integer, default=0)
    rewrite_reason: Mapped[str] = mapped_column(String(64), default="")
    rewrite_version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default=FRONTIER_PENDING)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    admitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
