# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.site_health_crawl_policy import (
    CORPUS_DISPOSITION_ANALYZE,
    ITEM_KIND_HTML_PAGE,
    SELECTION_SOURCE_USER,
)
from app.core.database import Base

from .common import (
    _FK_PROJECT,
    _FK_SITE_CRAWL,
    _FK_SITE_CRAWL_PHASE_RUN,
    _FK_SITE_FETCH_ARTIFACT,
    _FK_SITE_HEALTH_PROFILE,
    _FK_SITE_URL,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _ON_DELETE_SET_NULL,
    _utcnow,
)


class SiteUrl(Base):
    """Stable per-project URL identity (mutable lightweight discovery state).

    Unique ``(project_id, url_hash)``: one identity per normalized URL in a
    project across all crawls. Carries the normalized URL + hash, the display
    URL, first/last-seen crawl ids/timestamps, and the latest lightweight
    discovery status/title/content-type/depth/source. The keyset index
    ``(project_id, normalized_url, id)`` backs stable inventory cursors.
    """

    __tablename__ = "site_urls"
    __table_args__ = (
        UniqueConstraint("project_id", "url_hash", name="uq_site_url_project_hash"),
        # Backs the composite (workspace_id, project_id, site_url_id) foreign
        # key from ``SiteUrlObservation`` that pins an observation's URL to its
        # own workspace AND project (tenant-consistency guard). Including
        # ``workspace_id`` makes the observation's own ``workspace_id`` unable
        # to drift away from the URL's workspace.
        UniqueConstraint(
            "id",
            "project_id",
            "workspace_id",
            name="uq_site_urls_id_project",
        ),
        Index(
            "ix_site_urls_project_keyset",
            "project_id",
            "normalized_url",
            "id",
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
    normalized_url: Mapped[str] = mapped_column(String(2048))
    url_hash: Mapped[str] = mapped_column(String(64))
    display_url: Mapped[str] = mapped_column(String(2048), default="")
    host: Mapped[str] = mapped_column(String(255), default="")
    depth: Mapped[int] = mapped_column(Integer, default=0)
    # Corpus disposition (Site Intelligence §4). ``analyze`` items reach the
    # HTML analyzer; ``inventory_only`` items (documents, known-but-not-worth-
    # analyzing pages) stay counted in coverage without paying analysis cost;
    # ``exclude`` items are confidently irrelevant. The reason/version make the
    # decision explainable and reproducible after a classifier change.
    corpus_disposition: Mapped[str] = mapped_column(
        String(16), default=CORPUS_DISPOSITION_ANALYZE
    )
    disposition_reason: Mapped[str] = mapped_column(String(32), default="")
    disposition_version: Mapped[str] = mapped_column(String(32), default="")
    item_kind: Mapped[str] = mapped_column(String(16), default=ITEM_KIND_HTML_PAGE)
    discovery_status: Mapped[str] = mapped_column(String(24), default="")
    latest_source_kind: Mapped[str] = mapped_column(String(16), default="")
    latest_title: Mapped[str] = mapped_column(String(1024), default="")
    latest_content_type: Mapped[str] = mapped_column(String(128), default="")
    first_seen_crawl_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    last_seen_crawl_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class SiteUrlObservation(Base):
    """Immutable per-crawl discovery provenance for one URL (append-only).

    Unique ``(crawl_id, site_url_id)``: one observation row per URL per crawl,
    recording exactly how the URL was discovered (root/link/sitemap/redirect),
    the parent URL, the source fetch artifact, the depth, and the observed
    URL/final URL/status/content-type/title at discovery time.

    ``workspace_id``/``project_id`` are carried explicitly (not just derivable
    through the crawl or the URL) so composite foreign keys can pin the crawl
    AND the URL to the SAME workspace AND project: without binding
    ``workspace_id`` into those composite keys, an observation's own
    ``workspace_id`` could drift to a different workspace than its crawl/URL,
    which would undermine workspace isolation for the source-of-truth of crawl
    admission.
    """

    __tablename__ = "site_url_observations"
    __table_args__ = (
        UniqueConstraint("crawl_id", "site_url_id", name="uq_site_url_observation"),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            [
                "site_crawls.workspace_id",
                "site_crawls.project_id",
                _FK_SITE_CRAWL,
            ],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_site_url_observation_crawl_scoped",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "site_url_id"],
            [
                "site_urls.workspace_id",
                "site_urls.project_id",
                _FK_SITE_URL,
            ],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_site_url_observation_site_url_scoped",
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
        index=True,
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        index=True,
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(String(16))
    parent_site_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    source_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    phase_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL_PHASE_RUN, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    value_kind: Mapped[str] = mapped_column(String(32), default="other")
    value_priority: Mapped[int] = mapped_column(Integer, default=0)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    observed_url: Mapped[str] = mapped_column(String(2048), default="")
    final_url: Mapped[str] = mapped_column(String(2048), default="")
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), default="")
    title: Mapped[str] = mapped_column(String(1024), default="")
    rewrite_reason: Mapped[str] = mapped_column(String(64), default="")
    rewrite_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class MonitoredSiteUrl(Base):
    """Persistent project monitored-set projection (mutable, not per-crawl).

    Unique ``(project_id, site_url_id)``: one monitored membership per URL per
    project. ``active`` + ``selection_source`` (``user`` | ``free_sample``)
    drive the workspace quota. The partial-friendly index on
    ``(workspace_id, active)`` supports the atomic workspace-wide active-count
    quota check. Rows are preserved (never deleted) on downgrade — deactivated,
    not removed — so evidence/history survives capability changes.
    """

    __tablename__ = "monitored_site_urls"
    __table_args__ = (
        UniqueConstraint("project_id", "site_url_id", name="uq_monitored_site_url"),
        Index(
            "ix_monitored_site_urls_ws_active",
            "workspace_id",
            "active",
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
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    selection_source: Mapped[str] = mapped_column(
        String(16), default=SELECTION_SOURCE_USER
    )
    # The selection revision at which this row was added (nullable membership).
    selecting_membership_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    deselected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
