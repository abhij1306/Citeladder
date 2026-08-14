# Commerce attribution persistence models (UUID PKs, workspace-scoped).
#
# WS-B Task 1 scope: ``AttributionSnapshot`` — the rebuildable A1/A2
# attribution projection for a ``(project, window, granularity)``, computed
# from persisted ``IntegrationMetricRow`` ecommerce rows only (A1 this pass;
# A2 order-referrer links land with the Shopify order facts). Pure
# projection (invariant 7): NO provider call is ever made at read or
# refresh time, and the snapshot holds nothing not traceable to that
# persisted evidence (invariant 4 provenance id arrays + version stamps).
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_FORMULA_VERSION,
)
from app.core.database import Base

# FK target references + ondelete actions as named constants (the
# site_health / integrations pattern): a typo in a ``table.column``
# reference would otherwise silently bind the wrong parent.
_FK_WORKSPACE = "workspaces.id"
_FK_PROJECT = "projects.id"
_ON_DELETE_CASCADE = "CASCADE"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AttributionSnapshot(Base):
    """The attribution projection for one (project, window, granularity).

    Exactly ONE current snapshot per tuple — the unique constraint backs the
    refresh executor's transactional ``INSERT ... ON CONFLICT DO UPDATE``
    (the ``domain/analytics/ai_referrals_snapshot.py`` precedent), so concurrent
    refreshes serialize on the unique row and never create a duplicate
    "current" snapshot. Provenance ids stay JSONB arrays (no cross-subsystem
    FK compile dependency — the AiReferralsSnapshot precedent): the A2
    ``OrderLink``/``OrderFact`` ids (null until those land), the folded
    ``IntegrationMetricRow`` ids, and any folded snapshot ids.
    """

    __tablename__ = "attribution_snapshots"
    __table_args__ = (
        # One current snapshot per (project, window, granularity).
        UniqueConstraint(
            "project_id",
            "window_start",
            "window_end",
            "granularity",
            name="uq_attribution_snapshot_window",
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
    # The projected date window (provider data is date-grained).
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    # day | week | month (ANALYTICS_SNAPSHOT_GRANULARITIES). The A1 metrics
    # are granularity-INDEPENDENT (no series — window-level folds only);
    # every configured granularity is upserted so reads never recompute.
    granularity: Mapped[str] = mapped_column(String(8))
    # The attribution metrics document: ``deterministic`` (a1/a2/delta/
    # unattributed method sections) + ``statistical`` (persistently
    # ``not_offered`` with empty allocations in this scope).
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Provenance (invariant 4), all nullable JSONB id arrays: the A2 link +
    # order-fact ids (null until the Shopify order facts land), the folded
    # IntegrationMetricRow ids, and any folded snapshot ids.
    source_link_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_order_fact_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_metric_row_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_snapshot_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Version stamps (invariant 4) — owned by config/attribution.py.
    analyzer_version: Mapped[str] = mapped_column(
        String(64), default=ATTRIBUTION_ANALYZER_VERSION
    )
    formula_version: Mapped[str] = mapped_column(
        String(64), default=ATTRIBUTION_FORMULA_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class AttributionLink(Base):
    """One deterministic AI-attribution match for an immutable order fact."""

    __tablename__ = "attribution_links"
    __table_args__ = (
        UniqueConstraint(
            "order_fact_id",
            "matched_rule_id",
            "rule_version",
            name="uq_attribution_link_order_rule_version",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "order_fact_id"],
            ["order_facts.workspace_id", "order_facts.id"],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_attribution_link_order_fact_scoped",
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
    order_fact_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    method: Mapped[str] = mapped_column(String(24))
    confidence: Mapped[str] = mapped_column(String(16))
    matched_rule_id: Mapped[str] = mapped_column(String(64))
    rule_version: Mapped[str] = mapped_column(String(64))
    analyzer_version: Mapped[str] = mapped_column(String(64))
    evidence_refs: Mapped[dict] = mapped_column(JSONB, default=dict)
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
