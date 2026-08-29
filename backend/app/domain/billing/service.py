"""Billing account access and subscription lifecycle projection.

The lifecycle projector replaces the old entitlement-projection mutation:
every accepted base/add-on provider event projects subscription fields,
transactionally bumps the owning account's ``entitlement_lifecycle_version``
(the cross-process entitlement invalidator), issues the period's plan/add-on
grant bundle once (deterministic idempotency key, provider-authoritative
states only — never ``trialing``), and writes effective revocations on
immediate terminal loss. Cancellation at period end leaves current grants to
their natural end and prevents the next bundle; base cancellation still bumps
the account version because moving top-up effective expiry changes even when
no grant row changes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import BillingProvider
from app.core.config.billing_catalog import (
    AddonCatalogEntry,
    CatalogPrice,
    QuantityBounds,
    TopupCatalogEntry,
    commercial_catalog,
    item_checkout_availability,
    plan_checkout_availability,
    plan_period_grant_specs,
    price_tax_minor,
    resolve_region,
    scale_grant_specs,
)
from app.core.config.billing_contracts import (
    ACTIVATION_KIND_ADDON,
    ACTIVATION_KIND_BASE,
    ACTIVATION_KIND_TOPUP,
    ACTIVATION_PENDING,
    CANCELLATION_ALREADY_SCHEDULED,
    CANCELLATION_SCHEDULED,
    COMING_SOON_ADDON_KEYS,
    COUNTRY_VERIFICATION_DECLARED,
    CREDENTIAL_MODE_BYOK,
    CREDENTIAL_MODE_FUNDED,
    LIVE_SUBSCRIPTION_STATUSES,
    RAZORPAY_STATUS_MAP,
    REASON_BASE_SUBSCRIPTION_REQUIRED,
    REASON_CATALOG_KEY_UNKNOWN,
    REASON_CHECKOUT_UNAVAILABLE,
    REASON_NO_CURRENT_SUBSCRIPTION,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_QUANTITY_OUT_OF_BOUNDS,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_CANCEL_SCHEDULED,
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_KIND_ADDON,
    SUBSCRIPTION_KIND_BASE,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.config.entitlements import (
    GRANT_SOURCE_ADDON,
    GRANT_SOURCE_PLAN,
    CapabilityType,
)
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.billing.schemas import (
    MoneyResponse,
    ResolvedQuoteResponse,
)
from app.domain.entitlements.grants import issue_grant_bundle, revoke_grants
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_account,
)
from app.domain.entitlements.types import GrantSpec
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    PendingActivation,
)
from app.models.user import User

logger = logging.getLogger("app.billing")

# Provider-authoritative states that fund the current period's grant bundle.
# ``trialing`` is deliberately NOT grant authority in PR1.
_GRANT_AUTHORITY_STATUSES = frozenset(
    {SUBSCRIPTION_ACTIVE, SUBSCRIPTION_CANCEL_SCHEDULED}
)
_TERMINAL_STATUSES = frozenset({SUBSCRIPTION_CANCELLED, SUBSCRIPTION_EXPIRED})
# Counter capability types the usage read projects.
_COUNTER_TYPES = frozenset(
    {
        CapabilityType.COUNTER_CONSUMABLE,
        CapabilityType.COUNTER_OCCUPANCY,
        CapabilityType.COUNTER_RATE,
    }
)


class BillingConflictError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SubscriptionEvent:
    """One accepted provider lifecycle projection."""

    status: str
    period_start: datetime | None
    period_end: datetime | None
    updated_at: int


def accept_subscription_event(
    subscription: BillingSubscription,
    *,
    provider_status: str,
    current_start: int | None,
    current_end: int | None,
    updated_at: int,
    cancel_at_period_end: bool,
) -> SubscriptionEvent | None:
    """Reject stale provider versions and project status/period fields.

    Returns None for a stale event (``provider_state_version`` rejects stale
    events for this subscription only — it is not a cross-process entitlement
    invalidator). Same-status events with a newer provider version are
    accepted and projected.
    """
    if updated_at and updated_at < subscription.provider_state_version:
        return None
    normalized = RAZORPAY_STATUS_MAP.get(provider_status)
    if normalized is None:
        raise BillingConflictError("unsupported_subscription_status")
    if cancel_at_period_end and normalized == SUBSCRIPTION_ACTIVE:
        normalized = SUBSCRIPTION_CANCEL_SCHEDULED
    subscription.status = normalized
    subscription.current_period_start = _timestamp(current_start)
    subscription.current_period_end = _timestamp(current_end)
    subscription.cancel_at_period_end = cancel_at_period_end
    subscription.provider_state_version = max(
        subscription.provider_state_version, updated_at
    )
    return SubscriptionEvent(
        status=normalized,
        period_start=subscription.current_period_start,
        period_end=subscription.current_period_end,
        updated_at=updated_at,
    )


def _apply_terminal_state(
    subscription: BillingSubscription, event: SubscriptionEvent, now: datetime
) -> bool:
    """Set ``is_current``/``ended_at`` on immediate terminal loss."""
    if event.status not in _TERMINAL_STATUSES:
        return False
    if event.period_end is not None and event.period_end > now:
        # Cancelled at period end: access continues to the natural end.
        return False
    subscription.is_current = False
    subscription.ended_at = now
    return True


async def _bump_account_entitlement_version(
    session: AsyncSession, account_id: uuid.UUID
) -> None:
    account = (
        await session.execute(
            select(BillingAccount)
            .where(BillingAccount.id == account_id)
            .with_for_update()
        )
    ).scalar_one()
    account.entitlement_lifecycle_version += 1


async def _issue_period_bundle(
    session: AsyncSession,
    subscription: BillingSubscription,
    event: SubscriptionEvent,
) -> None:
    """Issue the period's plan/add-on bundle once (idempotent, append-only).

    Only provider-authoritative active/charged states issue; old period
    grants are never rewritten (a replayed event resolves to the same
    deterministic idempotency key and is safely suppressed).
    """
    if event.status not in _GRANT_AUTHORITY_STATUSES:
        return
    if event.period_start is None:
        return
    templates = plan_period_grant_specs(
        subscription.catalog_key, billing_settings.catalog_version
    )
    if not templates:
        # A key the LIVE catalog no longer resolves (e.g. a removed plan key)
        # would otherwise silently issue NOTHING while the provider keeps
        # charging the subscription. Safe fields only: catalog key/revision,
        # never account identifiers (invariant 6).
        logger.warning(
            "subscription renewal resolved no grant specs",
            extra={
                "catalog_key": subscription.catalog_key,
                "catalog_revision": billing_settings.catalog_version,
            },
        )
        return
    templates = scale_grant_specs(templates, max(subscription.quantity, 1))
    period_start_key = event.period_start.isoformat()
    await issue_grant_bundle(
        session,
        account_id=subscription.billing_account_id,
        source_kind=(
            GRANT_SOURCE_ADDON
            if subscription.subscription_kind == SUBSCRIPTION_KIND_ADDON
            else GRANT_SOURCE_PLAN
        ),
        source_ref=f"subscription:{subscription.id}",
        grants=tuple(GrantSpec(key=key, value=value) for key, value in templates),
        catalog_revision=billing_settings.catalog_version,
        idempotency_key=(
            f"sub:{subscription.id}:{period_start_key}:"
            f"{billing_settings.catalog_version}"
        ),
        valid_from=event.period_start,
        valid_until=event.period_end,
        period_start=event.period_start,
        period_end=event.period_end,
    )


async def _write_terminal_revocations(
    session: AsyncSession,
    subscription: BillingSubscription,
    event: SubscriptionEvent,
    now: datetime,
) -> None:
    """Revoke this subscription's grants whose natural end is still future.

    Immediate terminal loss ends access before the grant's natural period
    end; cancellation at period end (``is_current`` kept) never reaches here.
    """
    grants = (
        (
            await session.execute(
                select(AccountGrant).where(
                    AccountGrant.billing_account_id == subscription.billing_account_id,
                    AccountGrant.source_ref == f"subscription:{subscription.id}",
                )
            )
        )
        .scalars()
        .all()
    )
    revocable = tuple(
        grant.id
        for grant in grants
        if grant.period_end is None or grant.period_end > now
    )
    if not revocable:
        return
    await revoke_grants(
        session,
        grant_ids=revocable,
        effective_from=now,
        reason="subscription_ended",
        actor_kind="system",
        actor_user_id=None,
        # Keyed by the logical event (not the per-call clock) so a redelivered
        # terminal webhook hits revoke_grants' duplicate-suppression branch
        # instead of appending a second set of revocation rows.
        idempotency_key=f"sub:{subscription.id}:terminal:{event.updated_at}",
    )


async def apply_subscription_state(
    session: AsyncSession,
    subscription: BillingSubscription,
    *,
    provider_status: str,
    current_start: int | None,
    current_end: int | None,
    updated_at: int,
    cancel_at_period_end: bool,
) -> bool:
    """Apply an authoritative provider projection; return False when stale.

    Orchestrator only: event acceptance/projection, terminal handling, the
    account-version bump, period bundle issuance, and terminal revocations
    are extracted and separately tested.
    """
    subscription = (
        await session.execute(
            select(BillingSubscription)
            .where(BillingSubscription.id == subscription.id)
            .with_for_update()
        )
    ).scalar_one()
    event = accept_subscription_event(
        subscription,
        provider_status=provider_status,
        current_start=current_start,
        current_end=current_end,
        updated_at=updated_at,
        cancel_at_period_end=cancel_at_period_end,
    )
    if event is None:
        return False
    now = datetime.now(UTC)
    terminal = _apply_terminal_state(subscription, event, now)
    await _bump_account_entitlement_version(session, subscription.billing_account_id)
    await _issue_period_bundle(session, subscription, event)
    if terminal:
        await _write_terminal_revocations(session, subscription, event, now)
    # Synchronous Site Health re-projection on every accepted lifecycle event
    # (a lost allowance must reach the worker analyze guard's runtime row
    # without waiting for a lazy planner/selection read).
    await refresh_site_health_runtime_for_account(
        session, account_id=subscription.billing_account_id, at=now
    )
    await session.flush()
    return True


async def owned_account(session: AsyncSession, user: User) -> BillingAccount:
    account = await session.scalar(
        select(BillingAccount).where(BillingAccount.owner_user_id == user.id)
    )
    if account is None:
        account = await ensure_user_billing(session, user)
        await session.commit()
    return account


def _timestamp(value: int | None) -> datetime | None:
    return datetime.fromtimestamp(value, tz=UTC) if value is not None else None


# ---------------------------------------------------------------------------
# Server-resolved quote (the SINGLE owner of a commercial charge)
# ---------------------------------------------------------------------------
# Region resolution, currency, and GST stay SERVER-SIDE: the browser submits
# only a catalog key, a quantity, a credential mode, and an ISO country.
# ``base_price`` and ``credit_price`` stay SEPARATE (funded total = base +
# credit; base is never derived from credit) and provider cost is never
# exposed. ``quote_id`` is an opaque HMAC over the safe resolved inputs PLUS
# the PRIVATE provider price ref, so it binds the displayed terms to the exact
# provider price without leaking any provider identity (invariant 6).
# ``quote_id`` is CLIENT-FACING tamper-evidence ONLY: nothing server-side ever
# verifies it — execution re-resolves catalog, region, price, and provider
# refs from the live catalog — so do NOT build a server-side quote_id check
# here; it would be security theater, not a control.


@dataclass(frozen=True, slots=True)
class ResolvedIntent:
    """One validated commercial intent plus its server-resolved quote.

    ``price_ref``/``credit_price_ref`` are PRIVATE (never a DTO field): they
    are what the provider call is allowed to name.
    """

    kind: str
    catalog_key: str
    quantity: int
    credential_mode: str
    country_code: str
    region: str
    price_ref: str
    credit_price_ref: str
    quote: ResolvedQuoteResponse


def _quote_secret() -> bytes:
    secret = billing_settings.quote_signing_secret.get_secret_value()
    if not secret:
        secret = billing_settings.razorpay_webhook_secret.get_secret_value()
    return secret.encode()


def _quote_digest(payload: Mapping[str, object]) -> str:
    """Deterministic HMAC over the canonical quote payload."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(_quote_secret(), canonical, hashlib.sha256).hexdigest()


def resolve_quote(
    *,
    kind: str,
    catalog_key: str,
    quantity: int,
    credential_mode: str,
    country_code: str,
    region: str,
    base: CatalogPrice,
    credit: CatalogPrice | None,
    at: datetime,
) -> ResolvedQuoteResponse:
    """Produce the signed quote for one intent (pure, no I/O).

    The total is ``(base + credit) * quantity`` plus the region tax the config
    owns; ``total_price`` is the provider charge INCLUDING tax.
    """
    base_total = base.amount_minor * quantity
    credit_total = credit.amount_minor * quantity if credit is not None else None
    funded_minor = base_total + (credit_total or 0)
    tax_minor = price_tax_minor(base) * quantity + (
        price_tax_minor(credit) * quantity if credit is not None else 0
    )
    expires_at = at + timedelta(minutes=billing_settings.quote_validity_minutes)
    revision = billing_settings.catalog_version
    quote_id = _quote_digest(
        {
            "kind": kind,
            "catalog_key": catalog_key,
            "catalog_revision": revision,
            "quantity": quantity,
            "credential_mode": credential_mode,
            "country_code": country_code,
            "region": region,
            "currency": base.currency,
            "base_minor": base_total,
            "credit_minor": credit_total,
            "tax_minor": tax_minor,
            "total_minor": funded_minor + tax_minor,
            "expires_at": expires_at.isoformat(),
            # The PRIVATE provider refs bind the quote to the exact provider
            # price. They are hashed, never returned.
            "price_ref": base.provider_price_ref,
            "credit_price_ref": credit.provider_price_ref if credit else "",
        }
    )
    return ResolvedQuoteResponse(
        quote_id=quote_id,
        catalog_revision=revision,
        catalog_key=catalog_key,
        credential_mode=credential_mode,
        country_code=country_code,
        region=region,
        base_price=MoneyResponse(currency=base.currency, amount_minor=base_total),
        credit_price=(
            MoneyResponse(currency=base.currency, amount_minor=credit_total)
            if credit_total is not None
            else None
        ),
        tax=MoneyResponse(currency=base.currency, amount_minor=tax_minor),
        total_price=MoneyResponse(
            currency=base.currency, amount_minor=funded_minor + tax_minor
        ),
        expires_at=expires_at,
    )


def resolve_base_intent(
    *, catalog_key: str, credential_mode: str, country_code: str, at: datetime
) -> ResolvedIntent:
    """Validate a base-plan purchase and resolve its quote server-side."""
    region = resolve_region(country_code)
    catalog = commercial_catalog()
    plan = catalog.plan(catalog_key)
    if plan is None:
        raise BillingConflictError(REASON_CATALOG_KEY_UNKNOWN)
    available, reason = plan_checkout_availability(plan, region)
    if not available:
        raise BillingConflictError(reason or REASON_CHECKOUT_UNAVAILABLE)
    base = plan.base_price(region)
    if base is None:  # pragma: no cover - availability already refused
        raise BillingConflictError(REASON_CHECKOUT_UNAVAILABLE)
    credit = (
        plan.credit_price(region) if credential_mode == CREDENTIAL_MODE_FUNDED else None
    )
    if credential_mode == CREDENTIAL_MODE_FUNDED and (
        credit is None or not credit.purchasable
    ):
        # Funded checkout stays unavailable until the margin is configured.
        raise BillingConflictError(REASON_CHECKOUT_UNAVAILABLE)
    return ResolvedIntent(
        kind=ACTIVATION_KIND_BASE,
        catalog_key=catalog_key,
        quantity=1,
        credential_mode=credential_mode,
        country_code=country_code,
        region=region,
        price_ref=base.provider_price_ref,
        credit_price_ref=credit.provider_price_ref if credit is not None else "",
        quote=resolve_quote(
            kind=ACTIVATION_KIND_BASE,
            catalog_key=catalog_key,
            quantity=1,
            credential_mode=credential_mode,
            country_code=country_code,
            region=region,
            base=base,
            credit=credit,
            at=at,
        ),
    )


def _bounded_quantity(quantity: int, bounds: QuantityBounds) -> int:
    if not bounds.minimum <= quantity <= bounds.maximum:
        raise BillingConflictError(REASON_QUANTITY_OUT_OF_BOUNDS)
    return quantity


def _resolve_pack_intent(
    *,
    kind: str,
    item: AddonCatalogEntry | TopupCatalogEntry,
    quantity: int,
    country_code: str,
    region: str,
    at: datetime,
) -> ResolvedIntent:
    """Validate a quantity-bounded pack purchase and resolve its quote.

    The ONE owner of the add-on/top-up intent shape (invariant 2): bounded
    quantity, region price, availability gate, BYOK credential mode, no
    credit line. The kind-specific guards (coming-soon, live base) stay with
    the callers.
    """
    _bounded_quantity(quantity, item.quantity_bounds)
    price = item.price(region)
    available, reason = item_checkout_availability(
        availability=item.availability, price=price, region=region
    )
    if not available or price is None:
        raise BillingConflictError(reason or REASON_CHECKOUT_UNAVAILABLE)
    return ResolvedIntent(
        kind=kind,
        catalog_key=item.key,
        quantity=quantity,
        credential_mode=CREDENTIAL_MODE_BYOK,
        country_code=country_code,
        region=region,
        price_ref=price.provider_price_ref,
        credit_price_ref="",
        quote=resolve_quote(
            kind=kind,
            catalog_key=item.key,
            quantity=quantity,
            credential_mode=CREDENTIAL_MODE_BYOK,
            country_code=country_code,
            region=region,
            base=price,
            credit=None,
            at=at,
        ),
    )


def resolve_addon_intent(
    *, catalog_key: str, quantity: int, country_code: str, at: datetime
) -> ResolvedIntent:
    """Validate an add-on activation and resolve its quote server-side.

    A coming-soon add-on ALWAYS refuses with ``provider_unavailable`` here —
    before any provider I/O and before any grant issuance.
    """
    if catalog_key in COMING_SOON_ADDON_KEYS:
        raise BillingConflictError(REASON_PROVIDER_UNAVAILABLE)
    region = resolve_region(country_code)
    addon = commercial_catalog().addon(catalog_key)
    if addon is None:
        raise BillingConflictError(REASON_CATALOG_KEY_UNKNOWN)
    return _resolve_pack_intent(
        kind=ACTIVATION_KIND_ADDON,
        item=addon,
        quantity=quantity,
        country_code=country_code,
        region=region,
        at=at,
    )


def resolve_topup_intent(
    *, catalog_key: str, quantity: int, country_code: str, at: datetime
) -> ResolvedIntent:
    """Validate a top-up purchase and resolve its quote server-side."""
    region = resolve_region(country_code)
    topup = commercial_catalog().topup(catalog_key)
    if topup is None:
        raise BillingConflictError(REASON_CATALOG_KEY_UNKNOWN)
    return _resolve_pack_intent(
        kind=ACTIVATION_KIND_TOPUP,
        item=topup,
        quantity=quantity,
        country_code=country_code,
        region=region,
        at=at,
    )


async def current_base_subscription(
    session: AsyncSession, account_id: uuid.UUID
) -> BillingSubscription | None:
    """The account's current base subscription (read-only; commits nothing)."""
    return await session.scalar(
        select(BillingSubscription).where(
            BillingSubscription.billing_account_id == account_id,
            BillingSubscription.is_current.is_(True),
            BillingSubscription.subscription_kind == SUBSCRIPTION_KIND_BASE,
        )
    )


async def current_addon_subscription(
    session: AsyncSession, account_id: uuid.UUID, catalog_key: str
) -> BillingSubscription | None:
    return await session.scalar(
        select(BillingSubscription).where(
            BillingSubscription.billing_account_id == account_id,
            BillingSubscription.is_current.is_(True),
            BillingSubscription.subscription_kind == SUBSCRIPTION_KIND_ADDON,
            BillingSubscription.catalog_key == catalog_key,
        )
    )


async def pending_base_activation(
    session: AsyncSession, account_id: uuid.UUID
) -> PendingActivation | None:
    """The account's UNSETTLED base intent, if one holds the one-base slot.

    A committed ``pending`` row blocks a second base purchase until
    reconciliation settles/abandons it (transitions out of ``pending`` free
    the slot); the partial unique index is the final concurrent-insert guard.
    """
    return await session.scalar(
        select(PendingActivation).where(
            PendingActivation.billing_account_id == account_id,
            PendingActivation.activation_kind == ACTIVATION_KIND_BASE,
            PendingActivation.status == ACTIVATION_PENDING,
        )
    )


async def pending_addon_activation(
    session: AsyncSession, account_id: uuid.UUID, catalog_key: str
) -> PendingActivation | None:
    """The UNSETTLED add-on intent for (account, key), if one holds the slot."""
    return await session.scalar(
        select(PendingActivation).where(
            PendingActivation.billing_account_id == account_id,
            PendingActivation.activation_kind == ACTIVATION_KIND_ADDON,
            PendingActivation.catalog_key == catalog_key,
            PendingActivation.status == ACTIVATION_PENDING,
        )
    )


async def live_base_subscription(
    session: AsyncSession, account_id: uuid.UUID
) -> BillingSubscription:
    """The account's LIVE base subscription or a safe conflict.

    A top-up funds nothing without a readable live base subscription, so the
    purchase is refused before any provider I/O.
    """
    subscription = await current_base_subscription(session, account_id)
    if subscription is None or subscription.status not in LIVE_SUBSCRIPTION_STATUSES:
        raise BillingConflictError(REASON_BASE_SUBSCRIPTION_REQUIRED)
    return subscription


def persist_billing_country(account: BillingAccount, country_code: str) -> None:
    """LOCK the submitted ISO country on the account (single owner).

    ``/billing/profile`` is deleted, so the base purchase is the only writer of
    the persisted billing country.
    """
    account.billing_country = country_code
    account.country_verification = COUNTRY_VERIFICATION_DECLARED


async def _schedule_cancellation(
    session: AsyncSession,
    provider: BillingProvider,
    subscription: BillingSubscription,
) -> tuple[str, datetime]:
    """Ask the provider to cancel at cycle end and project the result.

    A subscription already scheduled is reported as ``already_scheduled``
    without a second provider call; current grant rows are never touched —
    period-end revocation is the natural end of the issued period and no next
    bundle is issued once cancellation is scheduled.
    """
    effective_at = subscription.current_period_end or datetime.now(UTC)
    if subscription.cancel_at_period_end:
        return CANCELLATION_ALREADY_SCHEDULED, effective_at
    result = await provider.cancel_subscription(
        subscription.external_subscription_id, at_cycle_end=True
    )
    await apply_subscription_state(
        session,
        subscription,
        provider_status=result.status,
        current_start=result.current_start,
        current_end=result.current_end,
        updated_at=result.updated_at,
        cancel_at_period_end=True,
    )
    await session.commit()
    return CANCELLATION_SCHEDULED, subscription.current_period_end or effective_at


async def schedule_base_cancellation(
    session: AsyncSession,
    provider: BillingProvider,
    *,
    account_id: uuid.UUID,
) -> tuple[str, str, datetime]:
    """Schedule the current base subscription's period-end cancellation."""
    subscription = await current_base_subscription(session, account_id)
    if subscription is None:
        raise BillingConflictError(REASON_NO_CURRENT_SUBSCRIPTION)
    catalog_key = subscription.catalog_key
    status, effective_at = await _schedule_cancellation(session, provider, subscription)
    return catalog_key, status, effective_at


async def schedule_addon_cancellation(
    session: AsyncSession,
    provider: BillingProvider,
    *,
    account_id: uuid.UUID,
    catalog_key: str,
) -> tuple[str, datetime]:
    """Schedule one add-on's period-end cancellation."""
    subscription = await current_addon_subscription(session, account_id, catalog_key)
    if subscription is None:
        raise BillingConflictError(REASON_NO_CURRENT_SUBSCRIPTION)
    return await _schedule_cancellation(session, provider, subscription)


__all__ = [
    "BillingConflictError",
    "ResolvedIntent",
    "SubscriptionEvent",
    "accept_subscription_event",
    "apply_subscription_state",
    "current_addon_subscription",
    "current_base_subscription",
    "live_base_subscription",
    "owned_account",
    "persist_billing_country",
    "resolve_addon_intent",
    "resolve_base_intent",
    "resolve_quote",
    "resolve_topup_intent",
    "schedule_addon_cancellation",
    "schedule_base_cancellation",
]
