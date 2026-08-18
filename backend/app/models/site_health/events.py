# Site Health's UUID-keyed, workspace-scoped persistence graph. Evidence is
# append-only; projections are explicitly mutable; raw HTML is never stored.
# SiteCrawlTask retains the shared queue contract and uses generations so a
# rerun cannot collide with a cancelled task identity.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

from .common import (
    _FK_SITE_CRAWL,
    _ON_DELETE_CASCADE,
    _utcnow,
)

if TYPE_CHECKING:
    from .crawl import SiteCrawl

class SiteCrawlEvent(Base):
    """Append-only safe crawl lifecycle event (the SSE source, invariant 3).

    Payloads for sample (Free) crawls never include frontier, discarded-
    candidate, or total-site counts (product contract — no total disclosure).
    Indexed by ``created_at`` for ordered polling/streaming.
    """

    __tablename__ = "site_crawl_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    crawl_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_SITE_CRAWL, ondelete=_ON_DELETE_CASCADE),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(48))
    message: Mapped[str] = mapped_column(Text, default="")
    # Safe payload — never frontier/overflow/total counts for sample crawls.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    crawl: Mapped[SiteCrawl] = relationship("SiteCrawl", back_populates="events")

