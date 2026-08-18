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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import BillingProvider
from app.core.config.billing_catalog import (
    AddonCatalogEntry,
    CatalogPrice,
    CommercialCatalog,
    PlanCatalogEntry,
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
    COMING_SOON_PLAN_CAPABILITY_KEYS,
    COMING_SOON_ROW_PLAN_KEYS,
    COUNTRY_VERIFICATION_DECLARED,
    CREDENTIAL_MODE_BYOK,
    CREDENTIAL_MODE_FUNDED,
    CURRENCY_MINOR_UNITS,
    LIMIT_STATE_FINITE,
    LIMIT_STATE_UNKNOWN,
    LIVE_SUBSCRIPTION_STATUSES,
    RAZORPAY_STATUS_MAP,
    REASON_BASE_SUBSCRIPTION_REQUIRED,
    REASON_CATALOG_KEY_UNKNOWN,
    REASON_CHECKOUT_UNAVAILABLE,
    REASON_NO_CURRENT_SUBSCRIPTION,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_QUANTITY_OUT_OF_BOUNDS,
    REGION_CURRENCIES,
    SUBSCRIPTION_ACTIVE,
    SUBSCRIPTION_CANCEL_SCHEDULED,
    SUBSCRIPTION_CANCELLED,
    SUBSCRIPTION_EXPIRED,
    SUBSCRIPTION_KIND_ADDON,
    SUBSCRIPTION_KIND_BASE,
    TOPUP_CREDIT_KEYS,
    USAGE_UNITS_BY_CAPABILITY_TYPE,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    GRANT_SOURCE_ADDON,
    GRANT_SOURCE_PLAN,
    GRANT_SOURCE_TRIAL,
    LEDGER_ENTRY_DEBIT,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
    CapabilityDefinition,
    CapabilityType,
)
from app.core.config.provider_catalog import (
    ProviderCatalogEntry,
    public_provider_routes,
)
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.billing.schemas import (
    BillingCatalogResponse,
    BillingEntitlementResponse,
    BillingUsageResponse,
    CapabilityValueResponse,
    CatalogAddonResponse,
    CatalogPlanResponse,
    CatalogProviderResponse,
    CatalogProviderRouteResponse,
    CatalogTopupResponse,
    GrantProvenanceResponse,
    MoneyResponse,
    ResolvedCapabilityResponse,
    ResolvedQuoteResponse,
    SubscriptionSummaryResponse,
    TrialGrantSummaryResponse,
    UsageGrantBalanceResponse,
    UsageItemResponse,
)
from app.domain.entitlements.grants import issue_grant_bundle, revoke_grants
from app.domain.entitlements.resolver import effective_grant_expiry
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_account,
    resolve_account_entitlement,
)
from app.domain.entitlements.types import GrantInput, GrantSpec
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    ConsumableLedger,
    GrantRevocation,
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
# Public catalog projection (pure read path)
# ---------------------------------------------------------------------------
# Renders the immutable config-owned commercial catalog into strict DTOs. It
# opens no session, reads NO workspace data, and touches no connection or probe
# (invariant 7). Every price, key, bound, and expiry comes from
# ``core/config/billing_catalog.py``; nothing commercial is computed or defaulted here.
# Invariant 6: ``CatalogPrice.provider_price_ref`` is PRIVATE and never reaches
# a DTO — only the resolved amount/currency do.


def _money(price: CatalogPrice | None) -> MoneyResponse | None:
    """Project the SAFE half of a configured price (never the private ref)."""
    if price is None:
        return None
    return MoneyResponse(currency=price.currency, amount_minor=price.amount_minor)


def _capability_value(
    definition: CapabilityDefinition, value: int | None
) -> bool | int | str | None:
    """Public form of a granted capability value (None = not granted)."""
    if value is None:
        return None
    if definition.capability_type is CapabilityType.FLAG:
        return bool(value)
    if definition.capability_type is CapabilityType.LEVEL:
        return definition.ordered_values[value]
    return value


def _plan_capabilities(plan: PlanCatalogEntry) -> list[CapabilityValueResponse]:
    """Comparison rows for one plan: granted values plus coming-soon rows.

    Coming-soon provider rows are rendered with a null value on the upper tiers
    exactly because no plan bundle grants them.
    """
    granted = {template.key: template.value for template in plan.grant_bundle}
    rows: list[CapabilityValueResponse] = []
    for definition in CAPABILITY_REGISTRY.public_entries():
        coming_soon = definition.key in COMING_SOON_PLAN_CAPABILITY_KEYS
        if coming_soon and plan.key not in COMING_SOON_ROW_PLAN_KEYS:
            continue
        if definition.key not in granted and not coming_soon:
            continue
        rows.append(
            CapabilityValueResponse(
                key=definition.key,
                capability_type=definition.capability_type.value,
                value=_capability_value(definition, granted.get(definition.key)),
                issuable=definition.issuable,
            )
        )
    return rows


def _plan_response(plan: PlanCatalogEntry, region: str) -> CatalogPlanResponse:
    base = plan.base_price(region)
    credit = plan.credit_price(region)
    checkout_available, unavailable_reason = plan_checkout_availability(plan, region)
    funded_total = (
        MoneyResponse(
            currency=base.currency,
            amount_minor=base.amount_minor + credit.amount_minor,
        )
        if base is not None and credit is not None
        else None
    )
    return CatalogPlanResponse(
        key=plan.key,
        name=plan.name,
        description=plan.description,
        cadence=plan.cadence,
        self_serve=plan.self_serve,
        contact_only=plan.contact_only,
        contact_url=billing_settings.contact_sales_url if plan.contact_only else None,
        base_price=_money(base),
        credit_price=_money(credit),
        funded_total_price=funded_total,
        checkout_available=checkout_available,
        unavailable_reason=unavailable_reason,
        capabilities=_plan_capabilities(plan),
        trial_availability=plan.trial_availability,
        trial_unavailable_reason=plan.trial_unavailable_reason,
        # Deferred trial TERMS only — trial_availability stays unavailable.
        trial_days=billing_settings.trial_days,
    )


def _addon_response(addon: AddonCatalogEntry, region: str) -> CatalogAddonResponse:
    template = addon.grant_bundle_per_unit[0]
    return CatalogAddonResponse(
        key=addon.key,
        name=addon.name,
        description=addon.description,
        cadence=addon.cadence,
        unit_price=_money(addon.price(region)),
        quantity_min=addon.quantity_bounds.minimum,
        quantity_max=addon.quantity_bounds.maximum,
        availability=addon.availability,
        unavailable_reason=addon.unavailable_reason,
        grant_key=template.key,
        grant_value_per_unit=template.value,
    )


def _topup_response(topup: TopupCatalogEntry, region: str) -> CatalogTopupResponse:
    templates = topup.grant_bundle_per_unit
    return CatalogTopupResponse(
        key=topup.key,
        name=topup.name,
        description=topup.description,
        unit_price=_money(topup.price(region)),
        quantity_min=topup.quantity_bounds.minimum,
        quantity_max=topup.quantity_bounds.maximum,
        availability=topup.availability,
        unavailable_reason=topup.unavailable_reason,
        grant_key=TOPUP_CREDIT_KEYS[topup.key],
        # Null while the pack size is UNSET — never a guessed pack.
        credits_per_unit=templates[0].value if templates else None,
        expiry_days=topup.expiry_days,
    )


def _provider_response(provider: ProviderCatalogEntry) -> CatalogProviderResponse:
    return CatalogProviderResponse(
        key=provider.key,
        label=provider.label,
        availability=provider.availability,
        unavailable_reason=provider.unavailable_reason,
        adapter_shipped=provider.adapter_shipped,
        grant_key=provider.grant_key,
        issuable=provider.issuable,
        routes=[
            CatalogProviderRouteResponse(
                logical_engine=route.logical_engine,
                measurement_mode=route.measurement_mode,
                transport_provider=route.transport_provider,
                model=route.transport_model,
            )
            for route in public_provider_routes(provider.key)
        ],
    )


def public_catalog(country_code: str | None) -> BillingCatalogResponse:
    """Render the PUBLIC catalog for a preview country.

    ``country_code=None`` is the preview: the response reports a null country
    and the config-owned preview region. Checkout still requires a submitted
    country (``SubscriptionCreateRequest.country_code``).
    """
    normalized = (country_code or "").strip().upper() or None
    region = resolve_region(normalized)
    currency = REGION_CURRENCIES[region]
    catalog: CommercialCatalog = commercial_catalog()
    return BillingCatalogResponse(
        catalog_revision=catalog.revision,
        country_code=normalized,
        region=region,
        currency=currency,
        currency_minor_units=CURRENCY_MINOR_UNITS[currency],
        plans=[_plan_response(plan, region) for plan in catalog.plans],
        addons=[_addon_response(addon, region) for addon in catalog.addons],
        topups=[_topup_response(topup, region) for topup in catalog.topups],
        providers=[_provider_response(provider) for provider in catalog.providers],
    )


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


# ---------------------------------------------------------------------------
# Authenticated ACCOUNT reads (pure projections; commit NOTHING)
# ---------------------------------------------------------------------------
# Both reads render persisted, versioned evidence: the resolver fold plus the
# consumable ledger. Neither calls a provider, re-derives a price, or repairs a
# grant (invariants 4 and 7).


async def _grant_rows(
    session: AsyncSession, account_id: uuid.UUID
) -> tuple[tuple[AccountGrant, ...], dict[uuid.UUID, datetime]]:
    grants = (
        (
            await session.execute(
                select(AccountGrant).where(
                    AccountGrant.billing_account_id == account_id
                )
            )
        )
        .scalars()
        .all()
    )
    revocations = (
        (
            await session.execute(
                select(GrantRevocation)
                .join(AccountGrant, GrantRevocation.grant_id == AccountGrant.id)
                .where(AccountGrant.billing_account_id == account_id)
            )
        )
        .scalars()
        .all()
    )
    earliest: dict[uuid.UUID, datetime] = {}
    for revocation in revocations:
        current = earliest.get(revocation.grant_id)
        if current is None or revocation.effective_from < current:
            earliest[revocation.grant_id] = revocation.effective_from
    return tuple(grants), earliest


def _grant_input(grant: AccountGrant) -> GrantInput:
    return GrantInput(
        id=grant.id,
        key=grant.key,
        value=grant.value,
        source_kind=grant.source_kind,
        valid_from=grant.valid_from,
        valid_until=grant.valid_until,
        period_start=grant.period_start,
        period_end=grant.period_end,
    )


def _subscription_summary(
    subscription: BillingSubscription | None,
) -> SubscriptionSummaryResponse | None:
    if subscription is None:
        return None
    return SubscriptionSummaryResponse(
        catalog_key=subscription.catalog_key,
        status=subscription.status,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
    )


def _trial_summary(
    grants: tuple[AccountGrant, ...], at: datetime
) -> TrialGrantSummaryResponse | None:
    """Derived only from operator/dev/test TRIAL grants; null otherwise."""
    deadlines = [
        grant.valid_until
        for grant in grants
        if grant.source_kind == GRANT_SOURCE_TRIAL and grant.valid_until is not None
    ]
    if not deadlines:
        return None
    deadline = max(deadlines)
    remaining = (deadline - at).days
    return TrialGrantSummaryResponse(
        deadline=deadline,
        days_remaining=max(remaining, 0),
        exhausted=deadline <= at,
    )


async def account_entitlement(
    session: AsyncSession, *, account: BillingAccount, at: datetime
) -> BillingEntitlementResponse:
    """The authenticated account entitlement read (commits nothing)."""
    entitlement = await resolve_account_entitlement(
        session, account_id=account.id, at=at
    )
    grants, revoked_at = await _grant_rows(session, account.id)
    subscription = await current_base_subscription(session, account.id)
    subscription_end = (
        subscription.current_period_end if subscription is not None else None
    )
    return BillingEntitlementResponse(
        billing_account_id=account.id,
        status=entitlement.status,
        errors=list(entitlement.errors),
        registry_revision=entitlement.registry_revision,
        entitlement_lifecycle_version=entitlement.entitlement_lifecycle_version,
        resolved_at=entitlement.resolved_at,
        valid_until=entitlement.valid_until,
        subscription=_subscription_summary(subscription),
        trial_grant=_trial_summary(grants, at),
        capabilities=[
            ResolvedCapabilityResponse(
                key=capability.key,
                capability_type=capability.capability_type.value,
                value=_capability_value(
                    CAPABILITY_REGISTRY.require(capability.key), capability.value
                ),
                contributing_grant_ids=list(capability.contributing_grant_ids),
                ordered_draw_grant_ids=list(capability.ordered_draw_grant_ids),
            )
            for capability in entitlement.capabilities
        ],
        grants=[
            GrantProvenanceResponse(
                grant_id=grant.id,
                source_kind=grant.source_kind,
                key=grant.key,
                value=grant.value,
                valid_from=grant.valid_from,
                # The MOVING effective expiry (a top-up follows the current
                # subscription end), never the stored fixed date alone.
                effective_valid_until=effective_grant_expiry(
                    _grant_input(grant), subscription_end
                ),
                revoked_at=revoked_at.get(grant.id),
                catalog_revision=grant.catalog_revision,
            )
            for grant in grants
        ],
    )


async def _consumable_balances(
    session: AsyncSession, account_id: uuid.UUID
) -> dict[uuid.UUID, tuple[int, int]]:
    """Per-grant ``(consumed, reserved)`` from the immutable ledger."""
    rows = (
        await session.execute(
            select(
                ConsumableLedger.grant_id,
                ConsumableLedger.entry_kind,
                func.coalesce(func.sum(ConsumableLedger.units), 0),
            )
            .where(ConsumableLedger.billing_account_id == account_id)
            .group_by(ConsumableLedger.grant_id, ConsumableLedger.entry_kind)
        )
    ).all()
    totals: dict[uuid.UUID, dict[str, int]] = {}
    for grant_id, entry_kind, units in rows:
        totals.setdefault(grant_id, {})[entry_kind] = int(units)
    balances: dict[uuid.UUID, tuple[int, int]] = {}
    for grant_id, by_kind in totals.items():
        debited = by_kind.get(LEDGER_ENTRY_DEBIT, 0)
        reserved = (
            by_kind.get(LEDGER_ENTRY_RESERVATION, 0)
            - by_kind.get(LEDGER_ENTRY_RELEASE, 0)
            - debited
        )
        balances[grant_id] = (debited, max(reserved, 0))
    return balances


def _usage_grant_rows(
    grants: tuple[AccountGrant, ...],
    key: str,
    balances: dict[uuid.UUID, tuple[int, int]],
    subscription_end: datetime | None,
) -> list[UsageGrantBalanceResponse]:
    rows: list[UsageGrantBalanceResponse] = []
    for grant in grants:
        if grant.key != key:
            continue
        consumed, reserved = balances.get(grant.id, (0, 0))
        rows.append(
            UsageGrantBalanceResponse(
                grant_id=grant.id,
                source_kind=grant.source_kind,
                allowance=grant.value,
                consumed=consumed,
                reserved=reserved,
                remaining=max(grant.value - consumed - reserved, 0),
                # The MOVING effective expiry, not the stored fixed date.
                effective_valid_until=effective_grant_expiry(
                    _grant_input(grant), subscription_end
                ),
            )
        )
    return rows


def _usage_item(
    definition: CapabilityDefinition,
    grant_rows: list[UsageGrantBalanceResponse],
    at: datetime,
) -> UsageItemResponse:
    """One counter row. Consumables are FINITE (the ledger measures them);
    occupancy/rate counters are UNKNOWN until their measurement lands.
    """
    unit = USAGE_UNITS_BY_CAPABILITY_TYPE[definition.capability_type.value]
    expiries = [
        row.effective_valid_until
        for row in grant_rows
        if row.effective_valid_until is not None
    ]
    earliest_expiry = min(expiries) if expiries else None
    if definition.capability_type is not CapabilityType.COUNTER_CONSUMABLE:
        return UsageItemResponse(
            key=definition.key,
            capability_type=definition.capability_type.value,
            unit=unit,
            limit_state=LIMIT_STATE_UNKNOWN,
            allowance=None,
            consumed=None,
            reserved=None,
            remaining=None,
            window_started_at=None,
            resets_at=_rate_window_reset(definition, at),
            earliest_expiry=earliest_expiry,
            grants=grant_rows,
        )
    allowance = sum(row.allowance for row in grant_rows)
    consumed = sum(row.consumed for row in grant_rows)
    reserved = sum(row.reserved for row in grant_rows)
    return UsageItemResponse(
        key=definition.key,
        capability_type=definition.capability_type.value,
        unit=unit,
        limit_state=LIMIT_STATE_FINITE,
        allowance=allowance,
        consumed=consumed,
        reserved=reserved,
        remaining=max(allowance - consumed - reserved, 0),
        window_started_at=None,
        resets_at=None,
        earliest_expiry=earliest_expiry,
        grants=grant_rows,
    )


def _rate_window_reset(
    definition: CapabilityDefinition, at: datetime
) -> datetime | None:
    if definition.rolling_window_seconds is None:
        return None
    return at + timedelta(seconds=definition.rolling_window_seconds)


async def account_usage(
    session: AsyncSession, *, account: BillingAccount, at: datetime
) -> BillingUsageResponse:
    """The authenticated account usage read (commits nothing)."""
    entitlement = await resolve_account_entitlement(
        session, account_id=account.id, at=at
    )
    grants, _ = await _grant_rows(session, account.id)
    subscription = await current_base_subscription(session, account.id)
    subscription_end = (
        subscription.current_period_end if subscription is not None else None
    )
    balances = await _consumable_balances(session, account.id)
    items = [
        _usage_item(
            definition,
            _usage_grant_rows(grants, definition.key, balances, subscription_end),
            at,
        )
        for definition in CAPABILITY_REGISTRY.public_entries()
        if definition.capability_type in _COUNTER_TYPES
    ]
    return BillingUsageResponse(
        billing_account_id=account.id,
        entitlement_lifecycle_version=entitlement.entitlement_lifecycle_version,
        status=entitlement.status,
        items=items,
    )


__all__ = [
    "BillingConflictError",
    "SubscriptionEvent",
    "accept_subscription_event",
    "apply_subscription_state",
    "ResolvedIntent",
    "current_addon_subscription",
    "current_base_subscription",
    "live_base_subscription",
    "persist_billing_country",
    "resolve_addon_intent",
    "resolve_base_intent",
    "resolve_quote",
    "resolve_topup_intent",
    "schedule_addon_cancellation",
    "schedule_base_cancellation",
    "owned_account",
    "public_catalog",
]
