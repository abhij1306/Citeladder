"""Provider-neutral account billing persistence (UUID keyed)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.billing_contracts import (
    CADENCE_MONTHLY,
    PROVIDER_RAZORPAY,
    SUBSCRIPTION_KIND_BASE,
    SUBSCRIPTION_PENDING,
)
from app.core.database import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(24), default="active")
    billing_country: Mapped[str] = mapped_column(String(2), default="")
    country_verification: Mapped[str] = mapped_column(String(16), default="provisional")
    # The one persistent account-level monotonic entitlement version. Bumped
    # transactionally under a ``BillingAccount FOR UPDATE`` lock once per
    # logical grant-bundle write, once per logical revocation write, and once
    # per accepted base-or-add-on lifecycle event. Included in every
    # entitlement cache key so a grant/revocation/lifecycle change invalidates
    # the account-level cache across every process (never ``max()`` across
    # subscriptions).
    entitlement_lifecycle_version: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "entitlement_lifecycle_version >= 0",
            name="ck_billing_account_entitlement_version_nonneg",
        ),
    )


class WorkspaceBillingLink(Base):
    __tablename__ = "workspace_billing_links"

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class BillingCustomer(Base):
    __tablename__ = "billing_customers"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_customer_id", name="uq_billing_customer_external"
        ),
        UniqueConstraint(
            "billing_account_id",
            "provider",
            name="uq_billing_customer_account_provider",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(24), default=PROVIDER_RAZORPAY)
    external_customer_id: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class BillingSubscription(Base):
    __tablename__ = "billing_subscriptions"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_subscription_id",
            name="uq_billing_subscription_external",
        ),
        Index(
            "uq_billing_subscription_one_current",
            "billing_account_id",
            unique=True,
            postgresql_where=text("is_current AND subscription_kind = 'base'"),
        ),
        Index(
            "uq_billing_subscription_one_current_addon",
            "billing_account_id",
            "catalog_key",
            unique=True,
            postgresql_where=text("is_current AND subscription_kind = 'addon'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    billing_customer_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_customers.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(24), default=PROVIDER_RAZORPAY)
    external_subscription_id: Mapped[str] = mapped_column(String(255))
    external_price_id: Mapped[str] = mapped_column(String(255))
    # v8 commercial catalog key (tier_1 | tier_2 | tier_3 | addon/top-up key);
    # resolved against the config-owned catalog, never a provider display name.
    catalog_key: Mapped[str] = mapped_column(String(64), default="")
    # base | addon: one current base per account; one current row per
    # (account, catalog_key) per add-on.
    subscription_kind: Mapped[str] = mapped_column(
        String(16), default=SUBSCRIPTION_KIND_BASE
    )
    cadence: Mapped[str] = mapped_column(String(24), default=CADENCE_MONTHLY)
    # Purchased units for an add-on subscription (always 1 for a base plan).
    # The period grant bundle scales the per-unit template by this quantity.
    quantity: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(24), default=SUBSCRIPTION_PENDING)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    provider_state_version: Mapped[int] = mapped_column(Integer, default=0)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class BillingWebhookEvent(Base):
    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_event_id", name="uq_billing_webhook_external"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider: Mapped[str] = mapped_column(String(24), default=PROVIDER_RAZORPAY)
    external_event_id: Mapped[str] = mapped_column(String(255))
    event_type: Mapped[str] = mapped_column(String(128))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    safe_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    result_code: Mapped[str] = mapped_column(String(64), default="")
    error_code: Mapped[str] = mapped_column(String(64), default="")


class AccountGrant(Base):
    """One immutable capability grant to a billing account (append-only).

    A grant is never updated. Top-ups store a fixed ``purchased_at + 30 days``
    ``valid_until``; the resolver applies the moving subscription-end minimum.
    Levels are stored as integer ordinals into the registry's ``ordered_values``;
    flags accept only 0/1; every counter rejects negative values (invariant 1).
    """

    __tablename__ = "account_grants"
    __table_args__ = (
        UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            "key",
            name="uq_account_grant_bundle_key",
        ),
        CheckConstraint("value >= 0", name="ck_account_grant_value_nonneg"),
        CheckConstraint(
            "period_start IS NULL OR period_end IS NULL OR period_start < period_end",
            name="ck_account_grant_period_ordered",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until > valid_from",
            name="ck_account_grant_valid_ordered",
        ),
        Index(
            "ix_account_grant_account_key_valid",
            "billing_account_id",
            "key",
            "valid_from",
        ),
        Index("ix_account_grant_source", "source_kind", "source_ref"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    # plan | addon | topup | trial | override (config-owned vocabulary).
    source_kind: Mapped[str] = mapped_column(String(16))
    # Internal subscription/payment/override reference, never a raw provider body.
    source_ref: Mapped[str] = mapped_column(String(255))
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    catalog_revision: Mapped[str] = mapped_column(String(64))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class GrantRevocation(Base):
    """One immutable revocation of a grant (append-only, never edited)."""

    __tablename__ = "grant_revocations"
    __table_args__ = (
        UniqueConstraint(
            "grant_id", "idempotency_key", name="uq_grant_revocation_idempotency"
        ),
        Index("ix_grant_revocation_grant_effective", "grant_id", "effective_from"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("account_grants.id", ondelete="CASCADE"),
        index=True,
    )
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(255))
    # billing_owner | operator | provider | system. System/provider actions use
    # a null actor_user_id plus the actor kind.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_kind: Mapped[str] = mapped_column(String(24))
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class ConsumableLedger(Base):
    """Immutable consumable reservation/debit/release entries.

    Every row is written once and never updated. One task reservation's
    allocations share a ``reservation_id``. Converting one reserved unit into a
    billable attempt appends one release and one debit in the same transaction;
    termination appends release rows for every unused reserved unit. Audit/task
    deletion is RESTRICTED while ledger history exists so no cascade or SET
    NULL can erase ``(task_id, attempt)`` accounting identity.

    Balance per grant:
    ``grant.value - SUM(reservation.units) + SUM(release.units) - SUM(debit.units)``.
    """

    __tablename__ = "consumable_ledger"
    __table_args__ = (
        UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_consumable_ledger_idempotency",
        ),
        CheckConstraint("units > 0", name="ck_consumable_ledger_units_positive"),
        CheckConstraint(
            "(entry_kind = 'debit' AND attempt IS NOT NULL AND attempt > 0) "
            "OR (entry_kind <> 'debit' AND attempt IS NULL)",
            name="ck_consumable_ledger_attempt_shape",
        ),
        Index(
            "uq_consumable_ledger_task_attempt",
            "task_id",
            "attempt",
            unique=True,
            postgresql_where=text("entry_kind = 'debit'"),
        ),
        Index(
            "ix_consumable_ledger_grant_key_created",
            "grant_id",
            "capability_key",
            "created_at",
        ),
        Index("ix_consumable_ledger_reservation_kind", "reservation_id", "entry_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    grant_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("account_grants.id", ondelete="RESTRICT"),
    )
    capability_key: Mapped[str] = mapped_column(String(64))
    # reservation | debit | release (config-owned vocabulary).
    entry_kind: Mapped[str] = mapped_column(String(16))
    # Shared by all allocations for one task reservation.
    reservation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    audit_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audits.id", ondelete="RESTRICT"),
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("audit_tasks.id", ondelete="RESTRICT"),
    )
    # 1-based provider attempt; set and positive only for debit rows.
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units: Mapped[int] = mapped_column(Integer)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class IdempotencyRecord(Base):
    """Durable idempotency record for a billing mutation.

    A repeated key with the same ``request_fingerprint`` replays the stored
    response; a repeated key with a different fingerprint returns
    ``409 idempotency_key_reused``. ``response_body`` holds only safe DTO data
    (invariant 6).
    """

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_idempotency_record_account_key",
        ),
        Index("ix_idempotency_record_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(64))
    # SHA-256 of the canonical server-side request identity.
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    # started | completed | failed (config-owned vocabulary).
    state: Mapped[str] = mapped_column(String(16))
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class PendingActivation(Base):
    """A committed commercial intent awaiting provider activation.

    Committed before any provider I/O and never participates in entitlement
    resolution. ``checkout_url`` is validated against the allowlist before
    persistence. ``external_price_id`` is private persistence, never DTO output
    (invariant 6). Trial checkout is deferred and creates no pending activation.
    """

    __tablename__ = "pending_activations"
    __table_args__ = (
        UniqueConstraint(
            "billing_account_id",
            "idempotency_key",
            name="uq_pending_activation_account_idempotency",
        ),
        Index(
            "uq_pending_activation_provider_reference",
            "provider",
            "external_reference",
            unique=True,
            postgresql_where=text("external_reference IS NOT NULL"),
        ),
        # One-base / one-addon invariants on the UNSETTLED slot: a committed
        # pending holds the slot until reconciliation settles/abandons it, so
        # a concurrent DIFFERENT-key intent cannot reach the provider twice.
        # Top-ups are intentionally repeatable and stay unconstrained.
        Index(
            "uq_pending_activation_one_pending_base",
            "billing_account_id",
            unique=True,
            postgresql_where=text("activation_kind = 'base' AND status = 'pending'"),
        ),
        Index(
            "uq_pending_activation_one_pending_addon",
            "billing_account_id",
            "catalog_key",
            unique=True,
            postgresql_where=text("activation_kind = 'addon' AND status = 'pending'"),
        ),
        CheckConstraint("quantity > 0", name="ck_pending_activation_quantity_positive"),
        Index("ix_pending_activation_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    billing_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("billing_accounts.id", ondelete="CASCADE"),
        index=True,
    )
    # base | addon | topup (config-owned vocabulary).
    activation_kind: Mapped[str] = mapped_column(String(16))
    catalog_key: Mapped[str] = mapped_column(String(64))
    quantity: Mapped[int] = mapped_column(Integer)
    catalog_revision: Mapped[str] = mapped_column(String(64))
    # byok | funded (config-owned vocabulary).
    credential_mode: Mapped[str] = mapped_column(String(16))
    # pending | activated | failed | abandoned (config-owned vocabulary).
    status: Mapped[str] = mapped_column(String(16), default="pending")
    provider: Mapped[str] = mapped_column(String(24), default=PROVIDER_RAZORPAY)
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_price_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The server-resolved quote (safe DTO fields only, invariant 6) frozen at
    # intent time and replayed byte-equivalently on every read of this row.
    quote: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # ISO alpha-2 country and resolved region this intent was priced for; the
    # purchase re-resolves and LOCKS the submitted country server-side.
    country_code: Mapped[str] = mapped_column(String(2), default="")
    region: Mapped[str] = mapped_column(String(16), default="")
    # Which authority settled this row (webhook | reconciliation) plus its
    # opaque reference: provenance on the derived activation (invariant 4).
    settled_by: Mapped[str | None] = mapped_column(String(24), nullable=True)
    settled_authority_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
