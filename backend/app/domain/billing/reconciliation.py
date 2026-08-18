"""Bounded, idempotent reconciliation of pending commercial activations.

Without this, ONE missed webhook leaves a paying customer with no grants and no
recovery path. The sweep claims a bounded batch of pending rows with
``FOR UPDATE SKIP LOCKED``, COMMITS the claim/read boundary before any network
I/O (invariant 8), fetches the provider's own authoritative record, and calls
the SAME ``activate_pending`` transaction the webhook uses — so a late webhook
racing a manual sweep produces exactly one subscription row and one grant
bundle.

Outcomes: an authoritative failed state marks the row failed; no provider
record after the abandon window marks it abandoned; an unknown or retryable
state leaves it pending for the next sweep.

This module holds ALL the logic so it is unit-testable; ``scripts/
reconcile_billing.py`` is a thin one-shot CLI over it. There is deliberately no
scheduler and no worker loop.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import (
    BillingProvider,
    BillingProviderError,
    ProviderPayment,
)
from app.core.config.billing_contracts import (
    ACTIVATION_ABANDONED,
    ACTIVATION_ACTIVATED,
    ACTIVATION_AUTHORITY_RECONCILIATION,
    ACTIVATION_FAILED,
    ACTIVATION_KIND_TOPUP,
    ACTIVATION_PENDING,
    PAYMENT_FAILED,
    PAYMENT_PAID,
    RAZORPAY_STATUS_MAP,
    REASON_ACTIVATION_EXPIRED,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_CANCEL_SCHEDULED,
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_EXPIRED,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.domain.billing.activations import (
    ActivationRejectedError,
    ProviderRecord,
    activate_pending,
)
from app.models.billing import PendingActivation

logger = logging.getLogger("app.billing")

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]

_TERMINAL_PROVIDER_STATES = frozenset({PAYMENT_FAILED})
_TERMINAL_SUBSCRIPTION_STATES = frozenset(
    {SUBSCRIPTION_CANCELLED, SUBSCRIPTION_EXPIRED}
)
_SETTLEABLE_SUBSCRIPTION_STATES = frozenset(
    {SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCEL_SCHEDULED}
)


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    """SAFE counts only — no account id, provider id, amount, or message."""

    claimed: int = 0
    activated: int = 0
    failed: int = 0
    abandoned: int = 0
    still_pending: int = 0
    errors: int = 0

    def merge(self, other: ReconciliationSummary) -> ReconciliationSummary:
        return ReconciliationSummary(
            claimed=self.claimed + other.claimed,
            activated=self.activated + other.activated,
            failed=self.failed + other.failed,
            abandoned=self.abandoned + other.abandoned,
            still_pending=self.still_pending + other.still_pending,
            errors=self.errors + other.errors,
        )

    def as_counts(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "activated": self.activated,
            "failed": self.failed,
            "abandoned": self.abandoned,
            "still_pending": self.still_pending,
            "errors": self.errors,
        }


@dataclass(frozen=True, slots=True)
class _Claim:
    """The safe fields a claimed row contributes to the provider read."""

    pending_id: uuid.UUID
    activation_kind: str
    external_reference: str
    created_at: datetime


async def _claim_batch(
    session: AsyncSession, *, now: datetime, stale_after: timedelta, batch_size: int
) -> tuple[_Claim, ...]:
    """Claim a bounded batch with SKIP LOCKED and COMMIT the read boundary."""
    rows = (
        (
            await session.execute(
                select(PendingActivation)
                .where(
                    PendingActivation.status == ACTIVATION_PENDING,
                    PendingActivation.created_at <= now - stale_after,
                )
                .order_by(PendingActivation.created_at)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    claims = tuple(
        _Claim(
            pending_id=row.id,
            activation_kind=row.activation_kind,
            external_reference=row.external_reference or "",
            created_at=row.created_at,
        )
        for row in rows
    )
    # Never hold a transaction across provider I/O (invariant 8).
    await session.commit()
    return claims


async def _fetch_provider_record(
    provider: BillingProvider, claim: _Claim
) -> ProviderRecord | None:
    """The provider's authoritative record, or None when it has none."""
    if not claim.external_reference:
        return None
    if claim.activation_kind == ACTIVATION_KIND_TOPUP:
        return await provider.fetch_payment(claim.external_reference)
    return await provider.fetch_subscription(claim.external_reference)


def _authoritative_status(record: ProviderRecord) -> str:
    """Neutral status of a provider record: activated | failed | pending."""
    if isinstance(record, ProviderPayment):
        if record.status == PAYMENT_PAID:
            return ACTIVATION_ACTIVATED
        if record.status in _TERMINAL_PROVIDER_STATES:
            return ACTIVATION_FAILED
        return ACTIVATION_PENDING
    normalized = RAZORPAY_STATUS_MAP.get(record.status)
    if normalized in _SETTLEABLE_SUBSCRIPTION_STATES:
        return ACTIVATION_ACTIVATED
    if normalized in _TERMINAL_SUBSCRIPTION_STATES:
        return ACTIVATION_FAILED
    return ACTIVATION_PENDING


async def _mark_terminal(
    session: AsyncSession,
    pending_id: uuid.UUID,
    *,
    status: str,
    failure_code: str | None,
    now: datetime,
) -> None:
    pending = await session.scalar(
        select(PendingActivation)
        .where(
            PendingActivation.id == pending_id,
            PendingActivation.status == ACTIVATION_PENDING,
        )
        .with_for_update()
    )
    if pending is None:
        return
    pending.status = status
    pending.failed_at = now
    pending.failure_code = failure_code
    pending.checkout_url = None
    await session.commit()


async def _settle_claim(
    session: AsyncSession,
    provider: BillingProvider,
    claim: _Claim,
    *,
    now: datetime,
    abandon_after: timedelta,
) -> ReconciliationSummary:
    """Settle ONE claimed row from the provider's authoritative record."""
    try:
        record = await _fetch_provider_record(provider, claim)
    except BillingProviderError as exc:
        if exc.retryable:
            return ReconciliationSummary(claimed=1, still_pending=1)
        record = None
    if record is None:
        if claim.created_at <= now - abandon_after:
            await _mark_terminal(
                session,
                claim.pending_id,
                status=ACTIVATION_ABANDONED,
                failure_code=REASON_ACTIVATION_EXPIRED,
                now=now,
            )
            return ReconciliationSummary(claimed=1, abandoned=1)
        return ReconciliationSummary(claimed=1, still_pending=1)
    status = _authoritative_status(record)
    if status == ACTIVATION_FAILED:
        await _mark_terminal(
            session,
            claim.pending_id,
            status=ACTIVATION_FAILED,
            failure_code=record.status,
            now=now,
        )
        return ReconciliationSummary(claimed=1, failed=1)
    if status != ACTIVATION_ACTIVATED:
        return ReconciliationSummary(claimed=1, still_pending=1)
    try:
        result = await activate_pending(
            session,
            pending_id=claim.pending_id,
            provider_record=record,
            authority=ACTIVATION_AUTHORITY_RECONCILIATION,
            authority_id=str(claim.pending_id),
            at=now,
        )
    except ActivationRejectedError as exc:
        await session.rollback()
        logger.info(
            "billing.reconciliation_rejected activation_id=%s reason=%s",
            claim.pending_id,
            exc,
        )
        return ReconciliationSummary(claimed=1, errors=1)
    if result.already_settled:
        return ReconciliationSummary(claimed=1, still_pending=0, activated=0)
    return ReconciliationSummary(claimed=1, activated=1)


async def reconcile_pending_activations(
    session_factory: SessionFactory,
    provider: BillingProvider,
    *,
    now: datetime,
    batch_size: int | None = None,
    stale_after: timedelta | None = None,
    abandon_after: timedelta | None = None,
) -> ReconciliationSummary:
    """One BOUNDED, idempotent sweep over stale pending activations.

    Every window and bound comes from config (invariant 1). One session is used
    for the claim boundary and each settlement, and every settlement goes
    through the same ``activate_pending`` transaction the webhook uses.
    """
    limit = batch_size or billing_settings.reconciliation_batch_size
    stale = stale_after or timedelta(
        seconds=billing_settings.reconciliation_stale_after_seconds
    )
    abandon = abandon_after or timedelta(
        seconds=billing_settings.reconciliation_abandon_after_seconds
    )
    summary = ReconciliationSummary()
    async with session_factory() as session:
        claims = await _claim_batch(
            session, now=now, stale_after=stale, batch_size=limit
        )
        for claim in claims:
            summary = summary.merge(
                await _settle_claim(
                    session, provider, claim, now=now, abandon_after=abandon
                )
            )
    return summary


__all__ = [
    "ReconciliationSummary",
    "reconcile_pending_activations",
]
