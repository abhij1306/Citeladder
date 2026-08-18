"""Account/workspace entitlement resolution and Site Health projection.

The pure fold lives in ``resolver.py``; this module is the only DB boundary:
it loads grants, revocations, the current base subscription end, and the
persisted ``BillingAccount.entitlement_lifecycle_version`` (on EVERY lookup,
so the versioned cache key stays replica-safe), then invokes the fold at the
caller's ``at``. Every failure fails closed: corrupt input, a missing
account/link, or an incomplete fold yields ``entitlement_unresolved`` with
empty capabilities — never a partial fold and never a default profile.

There is deliberately NO ``funded_execution_allowed`` helper: a resolved
credit allowance is a grant sum and does not prove unspent balance. Funded
authorization is proven only by a successful ledger reservation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.billing_contracts import (
    SUBSCRIPTION_KIND_BASE,
)
from app.core.config.entitlements import CAPABILITY_REGISTRY, KEY_MONITORED_URLS
from app.core.config.site_health_runtime import (
    runtime_policy_for_allowance,
)
from app.domain.entitlements.cache import get_cached, put_cached
from app.domain.entitlements.resolver import ResolverInputError, fold_entitlement
from app.domain.entitlements.types import (
    STATUS_RESOLVED,
    GrantInput,
    ResolvedEntitlement,
    RevocationInput,
    no_capability_entitlement,
)
from app.domain.site_health.entitlements import (
    apply_runtime_policy,
    resolve_runtime,
    runtime_policy_is_current,
)
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    GrantRevocation,
    WorkspaceBillingLink,
)
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime

logger = logging.getLogger("app.billing")

# Sentinel account id for unresolved lookups with no billing account (e.g. a
# workspace with no WorkspaceBillingLink). Never persisted.
_NULL_ACCOUNT_ID = uuid.UUID(int=0)


def _unresolved(
    *,
    account_id: uuid.UUID,
    entitlement_lifecycle_version: int,
    at: datetime,
    error: str,
) -> ResolvedEntitlement:
    logger.info(
        "billing.entitlement_unresolved account_id=%s registry_revision=%s error=%s",
        account_id,
        CAPABILITY_REGISTRY.revision,
        error,
    )
    return no_capability_entitlement(
        account_id=account_id,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=entitlement_lifecycle_version,
        at=at,
        errors=(error,),
    )


async def _current_base_subscription_end(
    session: AsyncSession, account_id: uuid.UUID
) -> datetime | None:
    """The current base subscription's period end (None when unreadable)."""
    return await session.scalar(
        select(BillingSubscription.current_period_end).where(
            BillingSubscription.billing_account_id == account_id,
            BillingSubscription.is_current.is_(True),
            BillingSubscription.subscription_kind == SUBSCRIPTION_KIND_BASE,
        )
    )


async def _load_fold_inputs(
    session: AsyncSession, account_id: uuid.UUID
) -> tuple[tuple[GrantInput, ...], tuple[RevocationInput, ...], datetime | None]:
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
    grant_inputs = tuple(
        GrantInput(
            id=row.id,
            key=row.key,
            value=row.value,
            source_kind=row.source_kind,
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            period_start=row.period_start,
            period_end=row.period_end,
        )
        for row in grants
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
    revocation_inputs = tuple(
        RevocationInput(grant_id=row.grant_id, effective_from=row.effective_from)
        for row in revocations
    )
    subscription_end = await _current_base_subscription_end(session, account_id)
    return grant_inputs, revocation_inputs, subscription_end


async def resolve_account_entitlement(
    session: AsyncSession, *, account_id: uuid.UUID, at: datetime
) -> ResolvedEntitlement:
    """Resolve one billing account's entitlement at ``at`` (cache-backed).

    Reads the persisted account version first and includes it in the cache
    key; a cache failure falls through to DB resolution and a fold failure
    fails closed. Reads commit nothing.
    """
    account = await session.get(BillingAccount, account_id)
    if account is None:
        return _unresolved(
            account_id=account_id,
            entitlement_lifecycle_version=0,
            at=at,
            error="billing_account_missing",
        )
    cached = get_cached(
        account_id=account_id,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=account.entitlement_lifecycle_version,
        at=at,
    )
    if cached is not None:
        return cached
    grants, revocations, subscription_end = await _load_fold_inputs(session, account_id)
    try:
        entitlement = fold_entitlement(
            account_id=account_id,
            grants=grants,
            revocations=revocations,
            registry=CAPABILITY_REGISTRY,
            subscription_end=subscription_end,
            entitlement_lifecycle_version=account.entitlement_lifecycle_version,
            at=at,
        )
    except ResolverInputError as exc:
        return _unresolved(
            account_id=account_id,
            entitlement_lifecycle_version=account.entitlement_lifecycle_version,
            at=at,
            error=str(exc),
        )
    put_cached(entitlement)
    return entitlement


async def resolve_workspace_entitlement(
    session: AsyncSession, *, workspace_id: uuid.UUID, at: datetime
) -> ResolvedEntitlement:
    """Resolve the entitlement for the account linked to ``workspace_id``.

    A missing ``WorkspaceBillingLink`` is unresolved/no-capability, not a
    default profile.
    """
    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is None:
        return _unresolved(
            account_id=_NULL_ACCOUNT_ID,
            entitlement_lifecycle_version=0,
            at=at,
            error="workspace_billing_link_missing",
        )
    return await resolve_account_entitlement(session, account_id=account_id, at=at)


async def refresh_site_health_runtime_for_account(
    session: AsyncSession, *, account_id: uuid.UUID, at: datetime
) -> ResolvedEntitlement:
    """Re-project every linked workspace's Site Health runtime row.

    Resolves the account ONCE, maps only the resolved ``monitored_urls``
    allowance into each runtime row via the neutral policy, and stamps the
    resolver provenance. Rewrites a row only when the projection drifted.
    Callers own commit.
    """
    entitlement = await resolve_account_entitlement(
        session, account_id=account_id, at=at
    )
    allowance = (
        entitlement.capability_value(KEY_MONITORED_URLS)
        if entitlement.status == STATUS_RESOLVED
        else 0
    )
    policy = runtime_policy_for_allowance(allowance)
    # Deterministic order: every caller re-projects the same account's rows in
    # the same sequence, so two concurrent refreshes take the runtime rows'
    # locks in one global order instead of racing into a deadlock.
    workspace_ids = (
        await session.scalars(
            select(WorkspaceBillingLink.workspace_id)
            .where(WorkspaceBillingLink.billing_account_id == account_id)
            .order_by(WorkspaceBillingLink.workspace_id.asc())
        )
    ).all()
    for workspace_id in workspace_ids:
        row = await resolve_runtime(session, workspace_id)
        if runtime_policy_is_current(row, policy):
            continue
        apply_runtime_policy(
            row,
            policy,
            resolved_registry_revision=entitlement.registry_revision,
            resolved_entitlement_lifecycle_version=(
                entitlement.entitlement_lifecycle_version
            ),
            resolved_valid_until=entitlement.valid_until,
        )
    await session.flush()
    return entitlement


async def refresh_site_health_runtime_for_workspace(
    session: AsyncSession, *, workspace_id: uuid.UUID, at: datetime
) -> WorkspaceSiteHealthRuntime:
    """Lazily re-project one workspace's runtime row from its linked account.

    Called before planner/selection reads so the row follows grant,
    revocation, and lifecycle changes. With no linked account the row
    projects the fail-closed zero-allowance sample policy.
    """
    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is not None:
        await refresh_site_health_runtime_for_account(
            session, account_id=account_id, at=at
        )
        return await resolve_runtime(session, workspace_id)
    row = await resolve_runtime(session, workspace_id)
    policy = runtime_policy_for_allowance(0)
    if not runtime_policy_is_current(row, policy):
        apply_runtime_policy(
            row,
            policy,
            resolved_registry_revision="",
            resolved_entitlement_lifecycle_version=0,
            resolved_valid_until=None,
        )
        await session.flush()
    return row
