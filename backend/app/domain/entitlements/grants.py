# Append-only grant/revocation write service.
#
# Every write is transaction-owning-with-the-caller (the caller commits): rows
# are inserted, NEVER updated, and the owning account's
# ``entitlement_lifecycle_version`` is bumped exactly once per logical write
# under a ``BillingAccount FOR UPDATE`` lock. The versioned cache key makes
# the bump visible across every process after commit; nothing here depends on
# process-local cache invalidation.
#
# Telemetry names (safe fields only — no secrets, provider bodies/IDs, source
# refs, or payment data): ``billing.duplicate_grant_prevented`` whenever an
# idempotency replay safely suppresses a duplicate bundle.
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.entitlements import (
    ACTOR_KINDS,
    CAPABILITY_REGISTRY,
    GRANT_SOURCE_KINDS,
    GRANT_SOURCE_OVERRIDE,
    CapabilityType,
)
from app.domain.entitlements.service import (
    refresh_site_health_runtime_for_account,
)
from app.domain.entitlements.types import GrantSpec
from app.models.billing import AccountGrant, BillingAccount, GrantRevocation
from app.models.user import User

logger = logging.getLogger("app.billing")


class GrantWriteError(ValueError):
    """A grant/revocation write failed validation or conflicted."""


def _validate_revocation_inputs(
    *,
    grant_ids: tuple[uuid.UUID, ...],
    reason: str,
    actor_kind: str,
    idempotency_key: str,
) -> None:
    if actor_kind not in ACTOR_KINDS:
        raise GrantWriteError(f"unknown actor kind: {actor_kind!r}")
    if not reason or len(reason) > 255:
        raise GrantWriteError("invalid reason")
    if not idempotency_key or len(idempotency_key) > 255:
        raise GrantWriteError("invalid idempotency_key")
    if not grant_ids:
        raise GrantWriteError("no grants to revoke")


async def _load_revocation_grants(
    session: AsyncSession, grant_ids: tuple[uuid.UUID, ...]
) -> tuple[list[AccountGrant], set[uuid.UUID]]:
    grants = list(
        (
            await session.execute(
                select(AccountGrant).where(AccountGrant.id.in_(grant_ids))
            )
        )
        .scalars()
        .all()
    )
    if len({grant.id for grant in grants}) != len(set(grant_ids)):
        raise GrantWriteError("grant not found")
    account_ids = {grant.billing_account_id for grant in grants}
    if len(account_ids) != 1:
        raise GrantWriteError("revocations must target one account")
    return grants, account_ids


async def _existing_revocation_grants(
    session: AsyncSession,
    *,
    grant_ids: tuple[uuid.UUID, ...],
    idempotency_key: str,
) -> set[uuid.UUID]:
    return set(
        (
            await session.scalars(
                select(GrantRevocation.grant_id).where(
                    GrantRevocation.grant_id.in_(grant_ids),
                    GrantRevocation.idempotency_key == idempotency_key,
                )
            )
        ).all()
    )


def _build_revocations(
    grants: list[AccountGrant],
    *,
    already: set[uuid.UUID],
    effective_from: datetime,
    reason: str,
    actor_kind: str,
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
) -> tuple[GrantRevocation, ...]:
    return tuple(
        GrantRevocation(
            grant_id=grant.id,
            effective_from=effective_from,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_kind=actor_kind,
            idempotency_key=idempotency_key,
        )
        for grant in grants
        if grant.id not in already
    )


def _validate_spec(spec: GrantSpec) -> None:
    definition = CAPABILITY_REGISTRY.get(spec.key)
    if definition is None:
        raise GrantWriteError(f"unknown capability key: {spec.key!r}")
    if not definition.issuable:
        raise GrantWriteError(f"capability key is not issuable: {spec.key!r}")
    if definition.capability_type is CapabilityType.FLAG:
        if spec.value not in (0, 1):
            raise GrantWriteError(f"flag grant value not 0/1: {spec.key!r}")
    elif definition.capability_type is CapabilityType.LEVEL:
        if not 0 <= spec.value < len(definition.ordered_values):
            raise GrantWriteError(f"level grant ordinal out of range: {spec.key!r}")
    elif spec.value < 0:
        raise GrantWriteError(f"counter grant value negative: {spec.key!r}")


def _validate_bundle_inputs(
    *,
    source_kind: str,
    source_ref: str,
    grants: tuple[GrantSpec, ...],
    catalog_revision: str,
    idempotency_key: str,
) -> None:
    if source_kind not in GRANT_SOURCE_KINDS:
        raise GrantWriteError(f"unknown grant source kind: {source_kind!r}")
    if not source_ref or len(source_ref) > 255:
        raise GrantWriteError("invalid source_ref")
    if not catalog_revision or len(catalog_revision) > 64:
        raise GrantWriteError("invalid catalog_revision")
    if not idempotency_key or len(idempotency_key) > 255:
        raise GrantWriteError("invalid idempotency_key")
    if not grants:
        raise GrantWriteError("grant bundle is empty")
    keys = [spec.key for spec in grants]
    if len(keys) != len(set(keys)):
        raise GrantWriteError("grant bundle contains duplicate keys")
    for spec in grants:
        _validate_spec(spec)


async def _bump_account_version(session: AsyncSession, account_id: uuid.UUID) -> None:
    account = (
        await session.execute(
            select(BillingAccount)
            .where(BillingAccount.id == account_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if account is None:
        raise GrantWriteError("billing account not found")
    account.entitlement_lifecycle_version += 1


async def _bundle_replay(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    idempotency_key: str,
    grants: tuple[GrantSpec, ...],
) -> tuple[AccountGrant, ...] | None:
    """Return the already-persisted bundle on a safe replay, else None.

    A replay with an IDENTICAL key/value shape is suppressed (one logical
    activation, one set of grants — including webhook/reconciliation races);
    a key collision with a different shape is a conflict.
    """
    existing = (
        (
            await session.execute(
                select(AccountGrant).where(
                    AccountGrant.billing_account_id == account_id,
                    AccountGrant.idempotency_key == idempotency_key,
                )
            )
        )
        .scalars()
        .all()
    )
    if not existing:
        return None
    persisted = {(row.key, row.value) for row in existing}
    requested = {(spec.key, spec.value) for spec in grants}
    if persisted != requested or len(existing) != len(grants):
        raise GrantWriteError("grant_bundle_conflict")
    logger.info(
        "billing.duplicate_grant_prevented account_id=%s key_count=%s",
        account_id,
        len(existing),
    )
    return tuple(existing)


async def issue_grant_bundle(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    source_kind: str,
    source_ref: str,
    grants: tuple[GrantSpec, ...],
    catalog_revision: str,
    idempotency_key: str,
    valid_from: datetime,
    valid_until: datetime | None,
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> tuple[AccountGrant, ...]:
    """Persist one immutable grant bundle (append-only, idempotent).

    The account version bumps ONCE per logical bundle, not once per key row.
    Never updates existing rows: a replay returns the persisted bundle, and a
    same-key different-shape replay raises ``grant_bundle_conflict``.
    """
    _validate_bundle_inputs(
        source_kind=source_kind,
        source_ref=source_ref,
        grants=grants,
        catalog_revision=catalog_revision,
        idempotency_key=idempotency_key,
    )
    replay = await _bundle_replay(
        session,
        account_id=account_id,
        idempotency_key=idempotency_key,
        grants=grants,
    )
    if replay is not None:
        return replay
    rows = tuple(
        AccountGrant(
            billing_account_id=account_id,
            source_kind=source_kind,
            source_ref=source_ref,
            key=spec.key,
            value=spec.value,
            period_start=period_start,
            period_end=period_end,
            valid_from=valid_from,
            valid_until=valid_until,
            catalog_revision=catalog_revision,
            idempotency_key=idempotency_key,
        )
        for spec in grants
    )
    session.add_all(rows)
    await _bump_account_version(session, account_id)
    await session.flush()
    # Synchronous Site Health re-projection so a new allowance is visible to
    # the runtime row (and the worker analyze guard) in the same transaction.
    await refresh_site_health_runtime_for_account(
        session, account_id=account_id, at=valid_from
    )
    return rows


async def revoke_grants(
    session: AsyncSession,
    *,
    grant_ids: tuple[uuid.UUID, ...],
    effective_from: datetime,
    reason: str,
    actor_kind: str,
    actor_user_id: uuid.UUID | None,
    idempotency_key: str,
) -> tuple[GrantRevocation, ...]:
    """Persist immutable revocations (append-only, idempotent per grant).

    Never edits or deletes a grant or revocation: access ends because the
    resolver excludes grants with an effective revocation at ``at``.
    """
    _validate_revocation_inputs(
        grant_ids=grant_ids,
        reason=reason,
        actor_kind=actor_kind,
        idempotency_key=idempotency_key,
    )
    grants, account_ids = await _load_revocation_grants(session, grant_ids)
    already = await _existing_revocation_grants(
        session, grant_ids=grant_ids, idempotency_key=idempotency_key
    )
    rows = _build_revocations(
        grants,
        already=already,
        effective_from=effective_from,
        reason=reason,
        actor_kind=actor_kind,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )
    session.add_all(rows)
    if rows:
        # A pure replay (every revocation already persisted) changes nothing,
        # so it must not churn the account version/cache key across processes.
        account_id = account_ids.pop()
        await _bump_account_version(session, account_id)
        # Flush BEFORE the re-projection: sessions run autoflush=False, so the
        # resolver's fold would otherwise miss the pending revocation rows,
        # resolve the just-lost allowance as still active, and cache that
        # stale fold under the freshly bumped version.
        await session.flush()
        # Same-transaction Site Health re-projection for the lost allowance.
        await refresh_site_health_runtime_for_account(
            session, account_id=account_id, at=effective_from
        )
    await session.flush()
    persisted = (
        (
            await session.execute(
                select(GrantRevocation).where(
                    GrantRevocation.grant_id.in_(grant_ids),
                    GrantRevocation.idempotency_key == idempotency_key,
                )
            )
        )
        .scalars()
        .all()
    )
    return tuple(persisted)


async def issue_override_bundle(
    session: AsyncSession,
    *,
    operator_user: User,
    account_id: uuid.UUID,
    grants: tuple[GrantSpec, ...],
    reason: str,
    valid_from: datetime,
    valid_until: datetime | None,
    idempotency_key: str,
) -> tuple[AccountGrant, ...]:
    """Issue an audited operator override bundle (Enterprise/exception path).

    Overrides may issue configured keys but can never bypass a non-issuable
    key (e.g. ``provider.copilot``) — the registry validation in
    ``issue_grant_bundle`` enforces it. The operator identity is recorded in
    the internal source reference; the free-text reason stays in the
    audit-safe operator log, never in a DTO.
    """
    if not reason or len(reason) > 255:
        raise GrantWriteError("invalid reason")
    logger.info(
        "billing.override_grant_issued account_id=%s operator_user_id=%s reason=%s",
        account_id,
        operator_user.id,
        reason,
    )
    return await issue_grant_bundle(
        session,
        account_id=account_id,
        source_kind=GRANT_SOURCE_OVERRIDE,
        source_ref=f"override:{operator_user.id}",
        grants=grants,
        catalog_revision=CAPABILITY_REGISTRY.revision,
        idempotency_key=idempotency_key,
        valid_from=valid_from,
        valid_until=valid_until,
    )
