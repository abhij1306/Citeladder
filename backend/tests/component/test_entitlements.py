"""Component tests for the DB-backed entitlement layer (real Postgres).

Covers what the pure fold tests cannot: the account
``entitlement_lifecycle_version`` bump contract (once per logical bundle /
revocation write, never on a replay), the synchronous Site Health runtime
re-projection on grant writes, the non-issuable-key guard, fail-closed
resolution on corrupt rows or a missing billing link, and — pinning the
autoflush=False bug class — a revocation being visible to the resolver in the
SAME transaction, before any commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.entitlements import (
    GRANT_SOURCE_PLAN,
    KEY_EXPORTS,
    KEY_MONITORED_URLS,
    KEY_PROVIDER_COPILOT,
)
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.grants import (
    GrantWriteError,
    issue_grant_bundle,
    issue_override_bundle,
    revoke_grants,
)
from app.domain.entitlements.service import (
    resolve_account_entitlement,
    resolve_workspace_entitlement,
)
from app.domain.entitlements.types import (
    STATUS_ENTITLEMENT_UNRESOLVED,
    STATUS_RESOLVED,
    GrantSpec,
)
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    WorkspaceBillingLink,
)
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from app.models.user import User
from app.models.workspace import Workspace

_NOW = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _account_with_workspace(
    session: AsyncSession,
) -> tuple[BillingAccount, Workspace, User]:
    user = User(
        email=f"ent-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    account = BillingAccount(owner_user_id=user.id)
    session.add(account)
    await session.flush()
    workspace = Workspace(name="Ent WS")
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceBillingLink(workspace_id=workspace.id, billing_account_id=account.id)
    )
    await session.commit()
    return account, workspace, user


def _bundle_kwargs(account: BillingAccount, key_suffix: str) -> dict:
    return {
        "account_id": account.id,
        "source_kind": GRANT_SOURCE_PLAN,
        "source_ref": "subscription:test",
        "catalog_revision": "billing-v1",
        "idempotency_key": f"test-bundle:{key_suffix}",
        "valid_from": _NOW - timedelta(hours=1),
        "valid_until": _NOW + timedelta(days=30),
        "period_start": _NOW - timedelta(hours=1),
        "period_end": _NOW + timedelta(days=30),
    }


@pytest.mark.asyncio
async def test_bundle_write_bumps_version_once_and_refreshes_runtime(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace, _user = await _account_with_workspace(session)
        async with session_factory() as write:
            rows = await issue_grant_bundle(
                write,
                grants=(
                    GrantSpec(key=KEY_MONITORED_URLS, value=50),
                    GrantSpec(key=KEY_EXPORTS, value=1),
                ),
                **_bundle_kwargs(account, "once"),
            )
            await write.commit()
            assert len(rows) == 2

        await session.refresh(account)
        # ONE bump per logical bundle, not one per key row.
        assert account.entitlement_lifecycle_version == 1

        # The Site Health runtime row followed the new allowance in the same
        # transaction (no lazy read needed).
        from sqlalchemy import select as _select

        runtime = await session.scalar(
            _select(WorkspaceSiteHealthRuntime).where(
                WorkspaceSiteHealthRuntime.workspace_id == workspace.id
            )
        )
        assert runtime is not None
        assert runtime.monitored_url_limit == 50
        assert runtime.count_disclosure is True
        assert runtime.resolved_entitlement_lifecycle_version == 1


@pytest.mark.asyncio
async def test_bundle_replay_is_suppressed_and_shape_conflict_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _workspace, _user = await _account_with_workspace(session)
        kwargs = _bundle_kwargs(account, "replay")
        async with session_factory() as write:
            first = await issue_grant_bundle(
                write, grants=(GrantSpec(key=KEY_MONITORED_URLS, value=50),), **kwargs
            )
            await write.commit()
        async with session_factory() as write:
            # Identical replay: the persisted bundle is returned, no new rows,
            # no second version bump.
            replayed = await issue_grant_bundle(
                write, grants=(GrantSpec(key=KEY_MONITORED_URLS, value=50),), **kwargs
            )
            await write.commit()
            assert tuple(row.id for row in replayed) == tuple(row.id for row in first)
        await session.refresh(account)
        assert account.entitlement_lifecycle_version == 1

        async with session_factory() as write:
            with pytest.raises(GrantWriteError, match="grant_bundle_conflict"):
                await issue_grant_bundle(
                    write,
                    grants=(GrantSpec(key=KEY_MONITORED_URLS, value=75),),
                    **kwargs,
                )
            await write.rollback()


@pytest.mark.asyncio
async def test_revocation_write_bumps_version_and_replay_does_not(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _workspace, _user = await _account_with_workspace(session)
        async with session_factory() as write:
            (grant,) = await issue_grant_bundle(
                write,
                grants=(GrantSpec(key=KEY_MONITORED_URLS, value=50),),
                **_bundle_kwargs(account, "revoke"),
            )
            await write.commit()
        async with session_factory() as write:
            revocations = await revoke_grants(
                write,
                grant_ids=(grant.id,),
                effective_from=_NOW,
                reason="subscription_ended",
                actor_kind="system",
                actor_user_id=None,
                idempotency_key="test-revoke:1",
            )
            await write.commit()
            assert len(revocations) == 1
        await session.refresh(account)
        # Bundle bump + revocation bump.
        assert account.entitlement_lifecycle_version == 2

        async with session_factory() as write:
            replay = await revoke_grants(
                write,
                grant_ids=(grant.id,),
                effective_from=_NOW,
                reason="subscription_ended",
                actor_kind="system",
                actor_user_id=None,
                idempotency_key="test-revoke:1",
            )
            await write.commit()
            assert len(replay) == 1
        await session.refresh(account)
        assert account.entitlement_lifecycle_version == 2


@pytest.mark.asyncio
async def test_revocation_is_visible_to_the_resolver_in_the_same_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pin the autoflush=False bug class: a revoked allowance must resolve to
    zero in the SAME transaction (no commit, no later version bump)."""
    async with session_factory() as session:
        account, _workspace, _user = await _account_with_workspace(session)
        (grant,) = await issue_grant_bundle(
            session,
            grants=(GrantSpec(key=KEY_MONITORED_URLS, value=50),),
            **_bundle_kwargs(account, "same-tx"),
        )
        resolved = await resolve_account_entitlement(
            session, account_id=account.id, at=_NOW
        )
        assert resolved.status == STATUS_RESOLVED
        assert resolved.capability_value(KEY_MONITORED_URLS) == 50

        await revoke_grants(
            session,
            grant_ids=(grant.id,),
            effective_from=_NOW,
            reason="subscription_ended",
            actor_kind="system",
            actor_user_id=None,
            idempotency_key="test-same-tx:1",
        )
        after = await resolve_account_entitlement(
            session, account_id=account.id, at=_NOW
        )
        assert after.status == STATUS_RESOLVED
        assert after.capability_value(KEY_MONITORED_URLS) == 0
        await session.commit()


@pytest.mark.asyncio
async def test_override_cannot_issue_a_non_issuable_key(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _workspace, user = await _account_with_workspace(session)
        with pytest.raises(GrantWriteError, match="not issuable"):
            await issue_override_bundle(
                session,
                operator_user=user,
                account_id=account.id,
                grants=(GrantSpec(key=KEY_PROVIDER_COPILOT, value=1),),
                reason="test copilot bypass",
                valid_from=_NOW - timedelta(hours=1),
                valid_until=None,
                idempotency_key="test-copilot:1",
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_invalid_specs_are_rejected_before_any_write(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _workspace, _user = await _account_with_workspace(session)
        with pytest.raises(GrantWriteError, match="unknown capability key"):
            await issue_grant_bundle(
                session,
                grants=(GrantSpec(key="not_a_capability", value=1),),
                **_bundle_kwargs(account, "bad-key"),
            )
        with pytest.raises(GrantWriteError, match="flag grant value not 0/1"):
            await issue_grant_bundle(
                session,
                grants=(GrantSpec(key=KEY_EXPORTS, value=2),),
                **_bundle_kwargs(account, "bad-flag"),
            )
        with pytest.raises(GrantWriteError, match="counter grant value negative"):
            await issue_grant_bundle(
                session,
                grants=(GrantSpec(key=KEY_MONITORED_URLS, value=-1),),
                **_bundle_kwargs(account, "bad-counter"),
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_corrupt_grant_row_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A row that bypassed write validation fails the whole fold closed."""
    async with session_factory() as session:
        account, _workspace, _user = await _account_with_workspace(session)
        account.entitlement_lifecycle_version = 7
        session.add(
            AccountGrant(
                billing_account_id=account.id,
                source_kind=GRANT_SOURCE_PLAN,
                source_ref="subscription:corrupt",
                key="not_a_capability",
                value=1,
                valid_from=_NOW - timedelta(hours=1),
                catalog_revision="billing-v1",
                idempotency_key="corrupt:1",
            )
        )
        await session.commit()

        resolved = await resolve_account_entitlement(
            session, account_id=account.id, at=_NOW
        )
        assert resolved.status == STATUS_ENTITLEMENT_UNRESOLVED
        assert resolved.capabilities == ()
        assert resolved.capability_value(KEY_MONITORED_URLS) == 0
        assert resolved.entitlement_lifecycle_version == 7
        assert resolved.errors


@pytest.mark.asyncio
async def test_resolve_workspace_entitlement_without_link_is_unresolved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace = Workspace(name="Unlinked WS")
        session.add(workspace)
        await session.commit()

        resolved = await resolve_workspace_entitlement(
            session, workspace_id=workspace.id, at=_NOW
        )
        assert resolved.status == STATUS_ENTITLEMENT_UNRESOLVED
        assert resolved.capabilities == ()
        assert resolved.capability_value(KEY_MONITORED_URLS) == 0
