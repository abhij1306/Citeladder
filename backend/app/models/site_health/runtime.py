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
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.site_health_crawl_policy import (
    DISCOVERY_MODE_SAMPLE,
    SAMPLE_DISCOVERY_URL_CAP,
    SAMPLE_URL_LIMIT,
)
from app.core.database import Base

from .common import (
    _FK_PROJECT,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _utcnow,
)


class WorkspaceSiteHealthRuntime(Base):
    """Workspace Site Health runtime projection + quota serialization lock.

    Exactly one row per workspace (unique ``workspace_id``). This row is NOT a
    commercial source of truth: it is the projection of the account's resolved
    ``monitored_urls`` entitlement allowance onto neutral crawl policy, plus
    the row locked (``FOR UPDATE``) to serialize workspace-wide
    monitored-quota checks. ``resolved_*`` provenance records which resolver
    output produced the projection so callers can refresh on drift.
    """

    __tablename__ = "workspace_site_health_runtime"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_ws_site_health_runtime_workspace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_WORKSPACE, ondelete=_ON_DELETE_CASCADE),
    )
    # Resolver provenance of the last projection (fail-closed empty defaults).
    resolved_registry_revision: Mapped[str] = mapped_column(String(64), default="")
    resolved_entitlement_lifecycle_version: Mapped[int] = mapped_column(
        Integer, default=0
    )
    resolved_valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    discovery_mode: Mapped[str] = mapped_column(
        String(16), default=DISCOVERY_MODE_SAMPLE
    )
    # Sample mode caps discovery at the sample INVENTORY cap (deliberately
    # decoupled from the analysis budget below); full mode has no hard cap.
    discovery_url_cap: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=SAMPLE_DISCOVERY_URL_CAP
    )
    sample_url_limit: Mapped[int] = mapped_column(Integer, default=SAMPLE_URL_LIMIT)
    # Fail-closed: zero selectable monitored URLs until an allowance resolves.
    monitored_url_limit: Mapped[int] = mapped_column(Integer, default=0)
    # Whether total/frontier/overflow counts may be disclosed (zero = False).
    count_disclosure: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

class SiteHealthProfile(Base):
    """Project-owned mutable Site Health configuration/projection (not evidence).

    One row per project (unique ``project_id``). Holds the canonical crawl root
    URL/host, the derived primary registrable domain, the narrowing include/
    exclude globs, and the monotonic ``selection_version`` used for optimistic
    monitored-set replacement.
    """

    __tablename__ = "site_health_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_site_health_profile_project"),
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
    )
    root_url: Mapped[str] = mapped_column(String(2048), default="")
    root_host: Mapped[str] = mapped_column(String(255), default="")
    registrable_domain: Mapped[str] = mapped_column(String(255), default="")
    include_globs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    exclude_globs: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    selection_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

