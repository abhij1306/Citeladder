# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config.site_health_contracts import (
    INITIAL_TASK_GENERATION,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_runtime import site_health_settings
from app.core.database import Base
from app.models.queue_mixins import QueueLeaseStateMixin

from .common import (
    _FK_SITE_CRAWL,
    _FK_SITE_CRAWL_TASK,
    _FK_SITE_FETCH_ARTIFACT,
    _FK_SITE_URL,
    _FK_WORKSPACE,
    _ON_DELETE_CASCADE,
    _ON_DELETE_SET_NULL,
)

if TYPE_CHECKING:
    from .crawl import SiteCrawl


class SiteCrawlTask(QueueLeaseStateMixin, Base):
    """One queue+lease row for a Site Health work unit.

    Reuses the exact queue-row column contract of ``AuditTask`` (status /
    lease_owner / lease_expires_at / heartbeat_at / attempt_count /
    max_attempts / available_at / priority / randomized_position /
    idempotency_key / error_code / error_detail / completed_at /
    result_artifact_id) so the single generic ``PostgresTaskQueue`` serves it
    unchanged (invariant 8). Double-claim is prevented by ``FOR UPDATE SKIP
    LOCKED`` plus the unique ``idempotency_key``.

    Carries an integer ``generation`` (default ``INITIAL_TASK_GENERATION`` = 0).
    Initial work is generation 0; a remove/re-add or explicit rerun of the same
    URL allocates the NEXT generation under lock, so the unique
    ``(crawl_id, task_kind, url_hash, generation)`` slot key never collides with
    a cancelled task and every rerun gets a fresh task/artifact identity.
    """

    __tablename__ = "site_crawl_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_site_crawl_task_idempotency_key"),
        UniqueConstraint(
            "crawl_id",
            "task_kind",
            "url_hash",
            "generation",
            name="uq_site_crawl_task_slot",
        ),
        # Claimable-task index (queue claim path).
        Index(
            "ix_site_crawl_tasks_claim",
            "status",
            "available_at",
        ),
        # Expired-lease sweeper index.
        Index(
            "ix_site_crawl_tasks_lease",
            "status",
            "lease_expires_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    # Nullable: a discover task may enqueue before a SiteUrl identity exists.
    site_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_CASCADE),
        nullable=True,
        index=True,
    )
    task_kind: Mapped[str] = mapped_column(String(16), default=TASK_KIND_DISCOVER)
    requested_url: Mapped[str] = mapped_column(String(2048), default="")
    url_hash: Mapped[str] = mapped_column(String(64), default="")
    # Discovery provenance for deterministic frontier ordering.
    parent_site_url_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_URL, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    source_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL_TASK, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    depth: Mapped[int] = mapped_column(Integer, default=0)
    # Task/artifact identity generation (0 = initial; rerun allocates next).
    generation: Mapped[int] = mapped_column(Integer, default=INITIAL_TASK_GENERATION)
    idempotency_key: Mapped[str] = mapped_column(String(160))

    max_attempts: Mapped[int] = mapped_column(
        Integer, default=site_health_settings.max_attempts
    )
    # Database serialization/deadlock retries are not page/network attempts.
    # They have their own bound so contention cannot consume acquisition budget.
    conflict_count: Mapped[int] = mapped_column(Integer, default=0)

    # --- Execution result (single-writer = claiming worker, invariant 3) --
    result_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_FETCH_ARTIFACT, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    # Durable cohort marker: acquisition produced a supported HTML document
    # that entered page-purpose classification for this task execution.
    classification_expected: Mapped[bool] = mapped_column(Boolean, default=False)
    crawl: Mapped[SiteCrawl] = relationship("SiteCrawl", back_populates="tasks")
