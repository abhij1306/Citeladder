# Commerce-suite persistence models (UUID PKs, workspace-scoped).
#
# ``OrderFact`` is the immutable, sanitized order revision row: one row per
# (connection, order_ref_hash, resync_seq) — a later sync that returns the
# same order (refund/cancellation/fulfilment revision) inserts a NEW fact at
# the next sequence and consumers read the LATEST per order (old revisions
# are retained, never overwritten — invariant 3). ``FeedIssue`` is the
# deterministic catalog-feed finding row emitted by the Shopify catalog
# merge/validation (§9.2/§9.3 in-scope rules only).
#
# PII posture (invariant 6, AC7): NEITHER table carries any customer,
# order-number, address, email, phone, IP, or payment column — the worker
# sanitizes raw provider orders before the immutable artifact write, and
# these rows derive only from sanitized payloads. The order's identity is
# the opaque HMAC ``order_ref_hash``; its evidence is the allowlisted
# ``line_items``/``attribution_keys`` JSONB.
#
# Same-workspace integrity follows the models/integrations.py pattern:
# composite FKs pin connection/sync-run/artifact references to the SAME
# workspace (invariant 5).
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.commerce import (
    COMMERCE_IMPORTER_VERSION,
    ORDER_SANITIZE_VERSION,
)
from app.core.database import Base

_FK_WORKSPACE = "workspaces.id"
_FK_PROJECT = "projects.id"
_FK_PRODUCT = "products.id"
_FK_CONNECTION = "integration_connections.id"
_FK_SYNC_RUN = "integration_sync_runs.id"
_FK_IMPORT_ARTIFACT = "integration_import_artifacts.id"
_ON_DELETE_CASCADE = "CASCADE"
_ON_DELETE_SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class OrderFact(Base):
    """One immutable sanitized order revision (no PII columns, ever).

    ``resync_seq`` is allocated PER ``(connection_id, order_ref_hash)`` as
    ``max(existing)+1`` under the connection row lock — deliberately NOT
    the run-window sequence (overlapping windows can share one run
    revision while the same order legitimately revises). ``occurred_at``
    is the order's creation moment (retention horizon key);
    ``total_amount`` is the provider's CURRENT/net total as a decimal.
    """

    __tablename__ = "order_facts"
    __table_args__ = (
        # Fact identity: one immutable row per order per order revision.
        UniqueConstraint(
            "connection_id",
            "order_ref_hash",
            "resync_seq",
            name="uq_order_fact_identity",
        ),
        # Backs scoped child FKs (the Task-4 AttributionLink composite).
        UniqueConstraint("workspace_id", "id", name="uq_order_facts_ws_id"),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", _FK_CONNECTION],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_order_fact_connection_scoped",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_artifact_id"],
            ["integration_import_artifacts.workspace_id", _FK_IMPORT_ARTIFACT],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_order_fact_artifact_scoped",
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
    connection_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    # gsc | ga4 | bing | shopify (only shopify writes order facts today).
    provider: Mapped[str] = mapped_column(String(16))
    # Opaque HMAC of the raw provider order id (64 hex) — the raw id never
    # persists (invariant 6).
    order_ref_hash: Mapped[str] = mapped_column(String(64), index=True)
    resync_seq: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), default="")
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    # Allowlisted sanitized line items: [{sku, quantity, unit_price,
    # product_id|null}] — ``product_id`` is resolved post-sanitize by SKU.
    line_items: Mapped[list] = mapped_column(JSONB, default=list)
    # Allowlisted non-PII attribution evidence (sanitized URLs + UTM +
    # source name only).
    attribution_keys: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True
    )
    # Transform-code versions (invariant 4): derivation + sanitizer.
    importer_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_IMPORTER_VERSION
    )
    order_sanitize_version: Mapped[str] = mapped_column(
        String(64), default=ORDER_SANITIZE_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class FeedIssue(Base):
    """One deterministic catalog-feed finding (§9.3 in-scope rules only).

    Written by the Shopify catalog merge/validation with sanitized
    evidence + full provenance (run/artifact/importer version). The
    ``(sync_run_id, external_item_ref, rule_id)`` unique tuple makes a
    retried finalize's replay idempotent (insert ON CONFLICT DO NOTHING).
    """

    __tablename__ = "feed_issues"
    __table_args__ = (
        # Idempotent finalize replay: one row per run per item per rule.
        UniqueConstraint(
            "sync_run_id",
            "external_item_ref",
            "rule_id",
            name="uq_feed_issue_run_item_rule",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "connection_id"],
            ["integration_connections.workspace_id", _FK_CONNECTION],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_feed_issue_connection_scoped",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "sync_run_id"],
            ["integration_sync_runs.workspace_id", _FK_SYNC_RUN],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_feed_issue_sync_run_scoped",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "source_artifact_id"],
            ["integration_import_artifacts.workspace_id", _FK_IMPORT_ARTIFACT],
            ondelete=_ON_DELETE_CASCADE,
            name="fk_feed_issue_artifact_scoped",
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
    connection_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    sync_run_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    # The provider's opaque item id (Shopify: the variant id); "" for a
    # finding that could not resolve one (e.g. a missing-SKU row).
    external_item_ref: Mapped[str] = mapped_column(String(255), default="")
    # SET NULL keeps the finding when the catalog row is deleted.
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_FK_PRODUCT, ondelete=_ON_DELETE_SET_NULL),
        nullable=True,
    )
    source_artifact_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), index=True
    )
    # feed.* rule id + severity (config/commerce.py vocabularies).
    rule_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    # Sanitized finding evidence (never customer data).
    evidence: Mapped[dict] = mapped_column(JSONB, default=dict)
    importer_version: Mapped[str] = mapped_column(
        String(64), default=COMMERCE_IMPORTER_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
