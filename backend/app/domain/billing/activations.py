"""The ONE shared activation transaction (webhook and reconciliation).

``activate_pending`` is the single writer that turns a committed intent into
entitlement. Both the webhook and the manual reconciliation sweep call it, and
both keys — the pending id plus the provider's own authoritative reference —
are identical from either authority, so a late webhook racing a sweep creates
EXACTLY ONE subscription row, ONE grant bundle, and ONE lifecycle version bump.

Under the pending-row lock it:

- verifies provider identity, paid/active state, catalog revision, external
  reference, amount/currency (payments) or price ref (subscriptions), and the
  account metadata;
- returns the EXISTING activated result when already settled;
- creates/locks an activation ``IdempotencyRecord`` keyed from the pending id
  plus that authoritative provider reference;
- creates/updates ``BillingSubscription`` for base/add-on activation;
- issues ONE grant bundle with deterministic per-key idempotency;
- marks the pending row activated and stores its safe response;
- invalidates entitlement and refreshes Site Health runtime AFTER commit.

Top-up grants store ``valid_from=paid_at`` and a FIXED
``paid_at + topup_credit_valid_days`` expiry; the resolver applies the moving
current subscription end. A top-up with no readable live base subscription is
REJECTED.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import ProviderPayment, ProviderSubscription
from app.core.config.billing_catalog import (
    plan_period_grant_specs,
    scale_grant_specs,
    topup_grant_specs,
)
from app.core.config.billing_contracts import (
    ACTIVATION_ACTIVATED,
    ACTIVATION_KIND_BASE,
    ACTIVATION_KIND_TOPUP,
    ACTIVATION_PENDING,
    CADENCE_MONTHLY,
    IDEMPOTENCY_COMPLETED,
    PAYMENT_PAID,
    RAZORPAY_STATUS_MAP,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_CANCEL_SCHEDULED,
    SUBSCRIPTION_KIND_ADDON,
    SUBSCRIPTION_KIND_BASE,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.config.entitlements import GRANT_SOURCE_TOPUP
from app.domain.billing.schemas import ActivationResponse
from app.domain.billing.service import (
    apply_subscription_state,
    live_base_subscription,
)
from app.domain.entitlements.grants import issue_grant_bundle
from app.domain.entitlements.service import refresh_site_health_runtime_for_account
from app.domain.entitlements.types import GrantSpec
from app.models.billing import (
    BillingSubscription,
    IdempotencyRecord,
    PendingActivation,
)

logger = logging.getLogger("app.billing")

ProviderRecord = ProviderSubscription | ProviderPayment

_ACTIVATION_OPERATION = "activation.settle"
# Provider states that authorize activation.
_ACTIVE_SUBSCRIPTION_STATUSES = frozenset(
    {SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCEL_SCHEDULED}
)


class ActivationRejectedError(ValueError):
    """The provider record does not authorize this activation (grants nothing)."""


@dataclass(frozen=True, slots=True)
class ActivationResult:
    """The settled activation. ``already_settled`` marks a safe replay."""

    status: str
    response: ActivationResponse | None
    already_settled: bool
    grant_bundle_size: int = 0


def _activation_key(pending_id: uuid.UUID, provider_reference: str) -> str:
    """Deterministic activation idempotency key (pending + provider ref)."""
    return f"activation:{pending_id}:{provider_reference}"


def _provider_reference(record: ProviderRecord) -> str:
    if isinstance(record, ProviderSubscription):
        return record.external_subscription_id
    return record.external_payment_id


def _verify_identity(pending: PendingActivation, record: ProviderRecord) -> None:
    """Provider identity + external reference must match the pending intent."""
    reference = _provider_reference(record)
    if not reference or pending.external_reference != reference:
        raise ActivationRejectedError("external_reference_mismatch")
    if record.intent_id and record.intent_id != str(pending.id):
        raise ActivationRejectedError("intent_id_mismatch")
    if record.account_ref and record.account_ref != str(pending.billing_account_id):
        raise ActivationRejectedError("account_ref_mismatch")
    if pending.catalog_revision != billing_settings.catalog_version:
        raise ActivationRejectedError("catalog_revision_mismatch")


def _verify_payment(pending: PendingActivation, record: ProviderPayment) -> datetime:
    """Amount/currency must match the STORED server quote; returns ``paid_at``."""
    if record.status != PAYMENT_PAID:
        raise ActivationRejectedError("payment_not_paid")
    quote = pending.quote or {}
    total = quote.get("total_price") or {}
    if record.amount_minor != total.get("amount_minor") or record.currency != total.get(
        "currency"
    ):
        raise ActivationRejectedError("payment_amount_mismatch")
    if record.paid_at is None:
        raise ActivationRejectedError("payment_paid_at_missing")
    return datetime.fromtimestamp(record.paid_at, tz=UTC)


def _verify_subscription(
    pending: PendingActivation, record: ProviderSubscription
) -> None:
    normalized = RAZORPAY_STATUS_MAP.get(record.status)
    if normalized not in _ACTIVE_SUBSCRIPTION_STATUSES:
        raise ActivationRejectedError("subscription_not_active")
    if record.price_ref and pending.external_price_id != record.price_ref:
        raise ActivationRejectedError("price_ref_mismatch")


async def _claim_activation(
    session: AsyncSession, pending: PendingActivation, provider_reference: str
) -> bool:
    """Create/lock the activation idempotency record; False on a replay."""
    key = _activation_key(pending.id, provider_reference)
    existing = await session.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.billing_account_id == pending.billing_account_id,
            IdempotencyRecord.idempotency_key == key,
        )
        .with_for_update()
    )
    if existing is not None:
        return False
    session.add(
        IdempotencyRecord(
            billing_account_id=pending.billing_account_id,
            idempotency_key=key,
            operation=_ACTIVATION_OPERATION,
            request_fingerprint=pending.request_fingerprint,
            state=IDEMPOTENCY_COMPLETED,
            expires_at=pending.expires_at,
        )
    )
    await session.flush()
    return True


async def _upsert_subscription(
    session: AsyncSession, pending: PendingActivation, record: ProviderSubscription
) -> BillingSubscription:
    """Create or reuse the account's subscription row for this activation."""
    kind = (
        SUBSCRIPTION_KIND_BASE
        if pending.activation_kind == ACTIVATION_KIND_BASE
        else SUBSCRIPTION_KIND_ADDON
    )
    subscription = await session.scalar(
        select(BillingSubscription)
        .where(
            BillingSubscription.provider == pending.provider,
            BillingSubscription.external_subscription_id
            == record.external_subscription_id,
        )
        .with_for_update()
    )
    if subscription is None:
        quote = pending.quote or {}
        subscription = BillingSubscription(
            billing_account_id=pending.billing_account_id,
            provider=pending.provider,
            external_subscription_id=record.external_subscription_id,
            external_price_id=pending.external_price_id or "",
            catalog_key=pending.catalog_key,
            subscription_kind=kind,
            cadence=CADENCE_MONTHLY,
            quantity=pending.quantity,
            currency=(quote.get("total_price") or {}).get("currency", ""),
        )
        session.add(subscription)
        await session.flush()
    return subscription


async def _issue_topup_bundle(
    session: AsyncSession, pending: PendingActivation, paid_at: datetime
) -> int:
    """Issue the top-up bundle with a FIXED expiry; requires a live base sub."""
    await live_base_subscription(session, pending.billing_account_id)
    specs = topup_grant_specs(pending.catalog_key, pending.catalog_revision)
    if not specs:
        raise ActivationRejectedError("topup_grant_unconfigured")
    scaled = scale_grant_specs(specs, pending.quantity)
    rows = await issue_grant_bundle(
        session,
        account_id=pending.billing_account_id,
        source_kind=GRANT_SOURCE_TOPUP,
        source_ref=f"activation:{pending.id}",
        grants=tuple(GrantSpec(key=key, value=value) for key, value in scaled),
        catalog_revision=pending.catalog_revision,
        idempotency_key=f"topup:{pending.id}:{pending.catalog_revision}",
        valid_from=paid_at,
        valid_until=paid_at + timedelta(days=billing_settings.topup_credit_valid_days),
    )
    return len(rows)


async def _issue_subscription_bundle(
    session: AsyncSession,
    pending: PendingActivation,
    subscription: BillingSubscription,
    record: ProviderSubscription,
) -> int:
    """Project the provider state, which issues the period bundle exactly once."""
    specs = plan_period_grant_specs(pending.catalog_key, pending.catalog_revision)
    await apply_subscription_state(
        session,
        subscription,
        provider_status=record.status,
        current_start=record.current_start,
        current_end=record.current_end,
        updated_at=record.updated_at,
        cancel_at_period_end=record.cancel_at_period_end,
    )
    return len(specs or ())


def _settled_response(pending: PendingActivation) -> ActivationResponse:
    if pending.quote is None:  # pragma: no cover - always stored at insert
        raise RuntimeError("pending activation has no stored quote")
    return ActivationResponse(
        activation_id=pending.id,
        kind=pending.activation_kind,
        catalog_key=pending.catalog_key,
        quantity=pending.quantity,
        status=pending.status,
        checkout_url=None,
        quote=pending.quote,
        expires_at=pending.expires_at,
        failure_code=pending.failure_code,
    )


async def activate_pending(
    session: AsyncSession,
    *,
    pending_id: uuid.UUID,
    provider_record: ProviderRecord,
    authority: str,
    authority_id: str,
    at: datetime,
) -> ActivationResult:
    """Settle one pending activation from an AUTHORITATIVE provider record.

    Called by both the webhook and the reconciliation sweep. Commits once; the
    entitlement invalidation (the account version bump inside the grant write)
    and the Site Health refresh happen inside that transaction, and the runtime
    refresh is re-run after commit so every reader sees the new allowance.
    """
    pending = await session.scalar(
        select(PendingActivation)
        .where(PendingActivation.id == pending_id)
        .with_for_update()
    )
    if pending is None:
        raise ActivationRejectedError("pending_activation_missing")
    if pending.status == ACTIVATION_ACTIVATED:
        return ActivationResult(
            status=ACTIVATION_ACTIVATED,
            response=_settled_response(pending),
            already_settled=True,
        )
    if pending.status != ACTIVATION_PENDING:
        raise ActivationRejectedError("pending_activation_not_pending")
    _verify_identity(pending, provider_record)
    account_id = pending.billing_account_id
    reference = _provider_reference(provider_record)
    if not await _claim_activation(session, pending, reference):
        return ActivationResult(
            status=pending.status,
            response=_settled_response(pending),
            already_settled=True,
        )
    bundle_size = await _settle(session, pending, provider_record, at)
    pending.status = ACTIVATION_ACTIVATED
    pending.activated_at = at
    pending.checkout_url = None
    pending.settled_by = authority
    pending.settled_authority_id = authority_id[:255]
    response = _settled_response(pending)
    await session.commit()
    # Post-commit re-projection so a lost allowance/new allowance reaches the
    # Site Health runtime row for every reader (the write itself already
    # bumped the account entitlement version).
    await refresh_site_health_runtime_for_account(session, account_id=account_id, at=at)
    await session.commit()
    return ActivationResult(
        status=ACTIVATION_ACTIVATED,
        response=response,
        already_settled=False,
        grant_bundle_size=bundle_size,
    )


async def _settle(
    session: AsyncSession,
    pending: PendingActivation,
    provider_record: ProviderRecord,
    at: datetime,
) -> int:
    """Verify the record kind and write the subscription/grant side effects."""
    if pending.activation_kind == ACTIVATION_KIND_TOPUP:
        if not isinstance(provider_record, ProviderPayment):
            raise ActivationRejectedError("provider_record_kind_mismatch")
        paid_at = _verify_payment(pending, provider_record)
        return await _issue_topup_bundle(session, pending, paid_at)
    if not isinstance(provider_record, ProviderSubscription):
        raise ActivationRejectedError("provider_record_kind_mismatch")
    _verify_subscription(pending, provider_record)
    subscription = await _upsert_subscription(session, pending, provider_record)
    return await _issue_subscription_bundle(
        session, pending, subscription, provider_record
    )


__all__ = [
    "ActivationRejectedError",
    "ActivationResult",
    "ProviderRecord",
    "activate_pending",
]
