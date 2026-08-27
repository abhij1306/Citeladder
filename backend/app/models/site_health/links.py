"""Persisted per-page metrics derived from a transient crawl link graph."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

from .common import _FK_WORKSPACE, _ON_DELETE_CASCADE, _utcnow


class SitePageLinkMetric(Base):
    """One immutable, versioned internal-link projection per crawl page."""

    __tablename__ = "site_page_link_metrics"
    __table_args__ = (
        UniqueConstraint(
            "crawl_id",
            "site_url_id",
            "extractor_version",
            "formula_version",
            name="uq_site_page_link_metric",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "crawl_id"],
            [
                "site_crawls.workspace_id",
                "site_crawls.project_id",
                "site_crawls.id",
            ],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_site_page_link_metric_crawl_scoped",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id", "site_url_id"],
            [
                "site_urls.workspace_id",
                "site_urls.project_id",
                "site_urls.id",
            ],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_site_page_link_metric_site_url_scoped",
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
    project_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    crawl_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    site_url_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    inbound_count: Mapped[int] = mapped_column(Integer, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, default=0)
    main_content_inbound_count: Mapped[int] = mapped_column(Integer, default=0)
    main_content_outbound_count: Mapped[int] = mapped_column(Integer, default=0)
    nofollow_inbound_count: Mapped[int] = mapped_column(Integer, default=0)
    depth_from_home: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_page_count: Mapped[int] = mapped_column(Integer, default=0)
    top_inbound: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    top_outbound: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_artifact_ids: Mapped[list | None] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=True
    )
    extractor_version: Mapped[str] = mapped_column(String(32), default="")
    formula_version: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


__all__ = ["SitePageLinkMetric"]
