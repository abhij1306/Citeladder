"""Authenticated billing entitlement and usage projections."""
# The response projections mirror the public contract field-by-field.

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.billing_contracts import (
    LIMIT_STATE_FINITE,
    LIMIT_STATE_UNKNOWN,
    USAGE_UNITS_BY_CAPABILITY_TYPE,
)
from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    GRANT_SOURCE_TRIAL,
    LEDGER_ENTRY_DEBIT,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
    CapabilityDefinition,
    CapabilityType,
)
from app.domain.billing.catalog import _capability_value
from app.domain.billing.schemas import (
    BillingEntitlementResponse,
    BillingUsageResponse,
    GrantProvenanceResponse,
    ResolvedCapabilityResponse,
    SubscriptionSummaryResponse,
    TrialGrantSummaryResponse,
    UsageGrantBalanceResponse,
    UsageItemResponse,
)
from app.domain.entitlements.resolver import effective_grant_expiry
from app.domain.entitlements.service import resolve_account_entitlement
from app.domain.entitlements.types import GrantInput
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    ConsumableLedger,
    GrantRevocation,
)

_COUNTER_TYPES = frozenset(
    {
        CapabilityType.COUNTER_CONSUMABLE,
        CapabilityType.COUNTER_OCCUPANCY,
        CapabilityType.COUNTER_RATE,
    }
)


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
    deadlines = [
        grant.valid_until
        for grant in grants
        if grant.source_kind == GRANT_SOURCE_TRIAL and grant.valid_until is not None
    ]
    if not deadlines:
        return None
    deadline = max(deadlines)
    return TrialGrantSummaryResponse(
        deadline=deadline,
        days_remaining=max((deadline - at).days, 0),
        exhausted=deadline <= at,
    )


async def account_entitlement(
    session: AsyncSession, *, account: BillingAccount, at: datetime
) -> BillingEntitlementResponse:
    entitlement = await resolve_account_entitlement(
        session, account_id=account.id, at=at
    )
    grants, revoked_at = await _grant_rows(session, account.id)
    from app.domain.billing.service import current_base_subscription

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
    return {
        grant_id: (
            values.get(LEDGER_ENTRY_DEBIT, 0),
            max(
                values.get(LEDGER_ENTRY_RESERVATION, 0)
                - values.get(LEDGER_ENTRY_RELEASE, 0)
                - values.get(LEDGER_ENTRY_DEBIT, 0),
                0,
            ),
        )
        for grant_id, values in totals.items()
    }


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
    entitlement = await resolve_account_entitlement(
        session, account_id=account.id, at=at
    )
    grants, _ = await _grant_rows(session, account.id)
    from app.domain.billing.service import current_base_subscription

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
