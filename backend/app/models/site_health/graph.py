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
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.site_link_graph import (
    LINK_GRAPH_ANCHOR_TEXT_MAX_LENGTH,
)
from app.core.database import Base

from .common import (
    _FK_PROJECT,
    _FK_SITE_CRAWL,
    _FK_SITE_LINK_GRAPH_SNAPSHOT,
    _FK_SITE_PAGE_ANALYSIS,
    _FK_SITE_URL,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _ON_DELETE_SET_NULL,
    _utcnow,
)


class SiteHealthSnapshot(Base):
    """Immutable crawl-level aggregate score/coverage snapshot (unique crawl).

    Unique ``crawl_id``: one aggregate snapshot per crawl. Records the
    selected/analyzed URL coverage counts, the Technical/AEO/overall scores, the
    issue/severity/category rollups, the source analysis/artifact/evaluation ID
    arrays, and the analyzer/scoring versions.
    """

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
    technical_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    aeo_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    # Severity/category rollups (safe aggregate maps).
    severity_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    category_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_analysis_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    source_evaluation_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    analyzer_version: Mapped[str] = mapped_column(String(32), default="")
    scoring_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SiteLinkGraphSnapshot(Base):
    """Immutable crawl-scoped graph projection with exact analysis provenance."""

    __tablename__ = "site_link_graph_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            [
                "site_crawls.workspace_id",
                "site_crawls.project_id",
                _FK_SITE_CRAWL,
            ],
            name="fk_site_link_graph_snapshot_crawl_scoped",
            ondelete=_ON_DELETE_CASCADE,
        ),
        UniqueConstraint(
            "workspace_id",
            "crawl_id",
            "source_analysis_hash",
            "analyzer_version",
            name="uq_site_link_graph_snapshot_identity",
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
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        index=True,
    )
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_LINK_GRAPH_SNAPSHOT, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(String(24))
    root_site_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    source_analysis_hash: Mapped[str] = mapped_column(String(64))
    source_analysis_ids: Mapped[list] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    source_artifact_ids: Mapped[list] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    analyzer_version: Mapped[str] = mapped_column(String(32))
    page_analyzer_version: Mapped[str] = mapped_column(String(32))
    extractor_version: Mapped[str] = mapped_column(String(32))
    coverage: Mapped[dict] = mapped_column(JSONB)
    limitations: Mapped[list] = mapped_column(ARRAY(Text), default=list)
    summary: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class SiteLinkGraphNode(Base):
    """One immutable node metric within a graph snapshot."""

    __tablename__ = "site_link_graph_nodes"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "site_url_id", name="uq_site_link_graph_node"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_LINK_GRAPH_SNAPSHOT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    source_analysis_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_PAGE_ANALYSIS, ondelete=_ON_DELETE_CASCADE),
    )
    normalized_url: Mapped[str] = mapped_column(String(2048))
    title: Mapped[str] = mapped_column(String(1024), default="")
    indexable: Mapped[bool] = mapped_column(Boolean, default=False)
    pagerank: Mapped[float] = mapped_column(Float)
    click_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followed_inbound_count: Mapped[int] = mapped_column(Integer, default=0)
    followed_outbound_count: Mapped[int] = mapped_column(Integer, default=0)
    near_orphan: Mapped[bool] = mapped_column(Boolean, default=False)
    weak_authority: Mapped[bool] = mapped_column(Boolean, default=False)
    over_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    hub: Mapped[bool] = mapped_column(Boolean, default=False)
    suggested_source_ids: Mapped[list] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), default=list
    )


class SiteLinkGraphEdge(Base):
    """Collapsed observed internal-link evidence for one ordered pair."""

    __tablename__ = "site_link_graph_edges"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_site_url_id",
            "target_key",
            name="uq_site_link_graph_edge",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_LINK_GRAPH_SNAPSHOT, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    source_site_url_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    target_site_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
        index=True,
    )
    target_key: Mapped[str] = mapped_column(String(2048))
    target_url: Mapped[str] = mapped_column(String(2048))
    followed: Mapped[bool] = mapped_column(Boolean, default=False)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    followed_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    nofollow_occurrence_count: Mapped[int] = mapped_column(Integer, default=0)
    anchor_texts: Mapped[list] = mapped_column(
        ARRAY(String(LINK_GRAPH_ANCHOR_TEXT_MAX_LENGTH)), default=list
    )
