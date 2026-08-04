# Account-capacity serialization + occupancy enforcement (slice23 Task 4).
#
# Occupancy capabilities (``project_slots`` / ``prompt_slots``) count
# PERSISTED rows across every workspace linked to one billing account; only
# deletion frees a slot. Every check runs in the SAME transaction as the
# insert it guards, under a transaction-scoped PostgreSQL advisory lock
# derived deterministically from the account UUID and a fixed config-owned
# namespace, so concurrent mutations on one account serialize at the
# database and the committed count can never exceed the grant.
#
# Lock ordering: the account-capacity lock is always the LAST lock a path
# acquires (generation takes the project then prompt-set advisory locks
# first); no path takes a project/prompt-set lock after this one, so
# opposing lock orders cannot arise.
#
# Resolution contract — fail closed where it matters:
#   - entitlement UNRESOLVED (no billing link, missing account, corrupt
#     fold) -> ``OccupancyUnresolvedError`` (API 403); nothing inserts;
#   - resolved with NO active grant for the key -> the account is
#     unprovisioned for the capability: ``allowance`` is None and the
#     mutation is not occupancy-gated (the pre-commercial contract is
#     preserved until any grant exists);
#   - resolved with an allowance -> ``current + requested`` must fit, else
#     ``OccupancyLimitExceededError`` (API 403 with safe details).
#
# ``monitored_urls`` deliberately has NO counter here: the existing
# workspace-wide active count + runtime-row lock in site_health's
# ``replace_monitored_set()`` remains the owner of that capability (its
# allowance already projects from account grants).
from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import AUDIT_TRIGGER_MANUAL
from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    CODE_MANUAL_RUN_RATE_EXCEEDED,
    CODE_OCCUPANCY_LIMIT_EXCEEDED,
    CODE_OCCUPANCY_UNRESOLVED,
    EVENT_OCCUPANCY_LIMIT_EXCEEDED,
    EVENT_OCCUPANCY_UNRESOLVED,
    KEY_MANUAL_RUNS_PER_DAY,
    KEY_PROJECT_SLOTS,
    KEY_PROMPT_SLOTS,
    MANUAL_RUNS_ROLLING_WINDOW_SECONDS,
    OCCUPANCY_LOCK_NAMESPACE,
)
from app.domain.entitlements.service import resolve_account_entitlement
from app.domain.entitlements.types import (
    STATUS_ENTITLEMENT_UNRESOLVED,
    STATUS_RESOLVED,
)
from app.models.audit import Audit
from app.models.billing import WorkspaceBillingLink
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet

logger = logging.getLogger("app.billing")


@dataclass(frozen=True, slots=True)
class OccupancySnapshot:
    """The frozen, typed outcome of one occupancy check.

    ``allowance``/``remaining`` are None when the account is unprovisioned
    for the capability (resolved entitlement, no active grant) — the check
    passes and no limit applies. ``current`` is the persisted count taken
    under the account lock; ``requested`` is the delta actually charged
    (duplicates never charge).
    """

    key: str
    allowance: int | None
    current: int
    requested: int
    remaining: int | None


class OccupancyError(RuntimeError):
    """Base for occupancy enforcement failures mapped at the API layer."""

    code: str = ""
    details: dict[str, Any] | None = None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class OccupancyUnresolvedError(OccupancyError):
    """Fail-closed denial: the account's entitlement cannot resolve (403)."""

    code = CODE_OCCUPANCY_UNRESOLVED


class OccupancyLimitExceededError(OccupancyError):
    """The requested delta would exceed the resolved allowance (403)."""

    code = CODE_OCCUPANCY_LIMIT_EXCEEDED

    def __init__(self, message: str, *, snapshot: OccupancySnapshot) -> None:
        super().__init__(message)
        self.snapshot = snapshot
        # Safe fields only: capability key + integer counts (invariant 6).
        self.details = {
            "key": snapshot.key,
            "allowance": snapshot.allowance,
            "current": snapshot.current,
            "requested": snapshot.requested,
        }


def _capacity_lock_key(account_id: uuid.UUID) -> int:
    """Derive the stable signed 64-bit advisory-lock key for one account.

    Deterministic across processes (fixed config namespace + account UUID),
    so every writer on the account contends for the same lock.
    """
    digest = hashlib.blake2b(
        OCCUPANCY_LOCK_NAMESPACE.to_bytes(4, "big") + account_id.bytes,
        digest_size=8,
        person=b"citeladder-cap",
    ).digest()
    return int.from_bytes(digest, "big", signed=True)


async def lock_billing_account_capacity(
    session: AsyncSession, account_id: uuid.UUID
) -> None:
    """Serialize occupancy-checked mutations for one billing account.

    Transaction-scoped (``pg_advisory_xact_lock``): the lock releases at
    COMMIT/ROLLBACK, so no caller can leak it, and re-acquiring inside the
    same transaction is a no-op. Non-PostgreSQL dialects (isolated unit
    tests) skip the lock; production always runs PostgreSQL.
    """
    if session.bind is None or session.bind.dialect.name != "postgresql":
        return
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)").bindparams(
            key=_capacity_lock_key(account_id)
        )
    )


async def lock_workspace_capacity(
    session: AsyncSession, workspace_id: uuid.UUID
) -> uuid.UUID:
    """Resolve a workspace's billing account and take its capacity lock.

    The billing link is the ONLY legitimate boundary from workspace scope to
    account scope (invariant 5); a workspace with no link fails closed.
    Returns the account id for ``enforce_occupancy``.
    """
    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is None:
        logger.info(
            EVENT_OCCUPANCY_UNRESOLVED + " workspace_id=%s error=%s",
            workspace_id,
            "workspace_billing_link_missing",
        )
        raise OccupancyUnresolvedError(
            "Billing entitlement is unavailable for this workspace"
        )
    await lock_billing_account_capacity(session, account_id)
    return account_id


async def _count_project_slots(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Every Project in every workspace linked to the account."""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Project)
                .join(
                    WorkspaceBillingLink,
                    WorkspaceBillingLink.workspace_id == Project.workspace_id,
                )
                .where(WorkspaceBillingLink.billing_account_id == account_id)
            )
        ).scalar_one()
    )


async def _count_prompt_slots(session: AsyncSession, account_id: uuid.UUID) -> int:
    """Every persisted Prompt reachable through set/project/workspace links.

    Proposed, active, archived, manual, imported, and generated rows all
    count; only deletion frees a slot.
    """
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Prompt)
                .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
                .join(Project, Project.id == PromptSet.project_id)
                .join(
                    WorkspaceBillingLink,
                    WorkspaceBillingLink.workspace_id == Project.workspace_id,
                )
                .where(WorkspaceBillingLink.billing_account_id == account_id)
            )
        ).scalar_one()
    )


# Key-specific aggregate queries. ``monitored_urls`` is intentionally absent:
# site_health's ``replace_monitored_set()`` stays its enforcement owner.
_OCCUPANCY_COUNTERS: dict[str, Callable[[AsyncSession, uuid.UUID], Awaitable[int]]] = {
    KEY_PROJECT_SLOTS: _count_project_slots,
    KEY_PROMPT_SLOTS: _count_prompt_slots,
}


async def enforce_occupancy(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    key: str,
    requested_delta: int,
    at: datetime,
) -> OccupancySnapshot:
    """Check one account's occupancy allowance under the capacity lock.

    Acquires the account lock (reentrant when the caller already holds it),
    resolves the allowance through the entitlement resolver — fail closed on
    any status other than ``STATUS_RESOLVED`` — and counts persisted rows
    with the key-specific aggregate query, all in the caller's transaction.
    Raises ``OccupancyLimitExceededError`` when the rows that would actually
    insert do not fit; returns the snapshot otherwise.
    """
    counter = _OCCUPANCY_COUNTERS.get(key)
    if counter is None:
        # A key with no counter here has another owner (monitored_urls) or
        # is a programming error — never a silent pass.
        raise ValueError(f"unsupported occupancy key: {key!r}")
    await lock_billing_account_capacity(session, account_id)
    entitlement = await resolve_account_entitlement(
        session, account_id=account_id, at=at
    )
    if entitlement.status != STATUS_RESOLVED:
        logger.info(
            EVENT_OCCUPANCY_UNRESOLVED + " account_id=%s key=%s errors=%s",
            account_id,
            key,
            ",".join(entitlement.errors),
        )
        raise OccupancyUnresolvedError(
            "Billing entitlement is unavailable for this account"
        )
    capability = entitlement.capability(key)
    allowance = capability.value if capability is not None else None
    current = await counter(session, account_id)
    remaining = None if allowance is None else allowance - current - requested_delta
    snapshot = OccupancySnapshot(
        key=key,
        allowance=allowance,
        current=current,
        requested=requested_delta,
        remaining=remaining,
    )
    if remaining is not None and remaining < 0:
        logger.info(
            EVENT_OCCUPANCY_LIMIT_EXCEEDED
            + " account_id=%s key=%s allowance=%s current=%s requested=%s",
            account_id,
            key,
            allowance,
            current,
            requested_delta,
        )
        raise OccupancyLimitExceededError(
            f"The request would exceed the account's {key} allowance "
            f"({current} in use, {requested_delta} requested, "
            f"allowance {allowance})",
            snapshot=snapshot,
        )
    return snapshot


# =========================================================================
# Rolling manual-run rate admission (slice23 Task 4 Part B)
# =========================================================================
# The ``manual_runs_per_day`` rate counts PERSISTED ``Audit`` rows with the
# manual trigger created within a rolling window (the registry-owned
# ``rolling_window_seconds``, 24h) across EVERY workspace linked to the
# account — never UsageWindow rows, fixed UTC days, or the existing
# task-count abuse limit, which stays a separate operational protection.
# The evaluation runs under the account-capacity advisory lock (reentrant
# when the caller already holds it) in the same transaction as the audit
# insert it guards; ``create_audit`` only APPLIES the returned decision.


@dataclass(frozen=True, slots=True)
class RateAdmissionDecision:
    """The frozen, typed outcome of one manual-run rate evaluation.

    ``allowance``/``remaining``/``reset_at`` are safe metadata (integers and
    one timestamp — invariant 6). ``allowance`` is None when the capability
    does not gate this evaluation: a non-manual trigger, a workspace with no
    billing link, or an account with no active ``manual_runs_per_day`` grant
    (the pre-commercial contract is preserved until any grant exists).
    ``reset_at`` is when the oldest in-window run ages out.
    """

    key: str
    trigger: str
    allowed: bool
    # "" when allowed; a config-owned denial code otherwise.
    code: str
    allowance: int | None
    used: int
    remaining: int | None
    reset_at: datetime | None


class RateAdmissionDeniedError(RuntimeError):
    """A rejected manual-run admission (mapped at the API layer)."""

    def __init__(self, message: str, *, decision: RateAdmissionDecision) -> None:
        super().__init__(message)
        self.message = message
        self.decision = decision
        self.code = decision.code
        # Safe fields only: capability key + integer counts + reset instant.
        self.details = {
            "key": decision.key,
            "allowance": decision.allowance,
            "used": decision.used,
            "remaining": decision.remaining,
            "reset_at": (
                decision.reset_at.isoformat() if decision.reset_at is not None else None
            ),
        }


def _rate_decision(
    *,
    trigger: str,
    allowed: bool,
    code: str = "",
    allowance: int | None = None,
    used: int = 0,
    remaining: int | None = None,
    reset_at: datetime | None = None,
) -> RateAdmissionDecision:
    return RateAdmissionDecision(
        key=KEY_MANUAL_RUNS_PER_DAY,
        trigger=trigger,
        allowed=allowed,
        code=code,
        allowance=allowance,
        used=used,
        remaining=remaining,
        reset_at=reset_at,
    )


async def evaluate_manual_run_admission(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    trigger: str,
    at: datetime,
) -> RateAdmissionDecision:
    """Evaluate the rolling manual-run rate for one workspace's account.

    Pure query over persisted rows at the caller's ``at`` (no writes, no
    clock reads). Only the ``manual`` trigger is gated. Fails closed when a
    linked account's entitlement cannot resolve; an unlinked workspace or an
    account without an active grant is unprovisioned and not rate-gated.
    """
    if trigger != AUDIT_TRIGGER_MANUAL:
        return _rate_decision(trigger=trigger, allowed=True)
    account_id = await session.scalar(
        select(WorkspaceBillingLink.billing_account_id).where(
            WorkspaceBillingLink.workspace_id == workspace_id
        )
    )
    if account_id is None:
        return _rate_decision(trigger=trigger, allowed=True)
    await lock_billing_account_capacity(session, account_id)
    entitlement = await resolve_account_entitlement(
        session, account_id=account_id, at=at
    )
    if entitlement.status != STATUS_RESOLVED:
        return _rate_decision(
            trigger=trigger, allowed=False, code=STATUS_ENTITLEMENT_UNRESOLVED
        )
    capability = entitlement.capability(KEY_MANUAL_RUNS_PER_DAY)
    if capability is None:
        return _rate_decision(trigger=trigger, allowed=True)
    definition = CAPABILITY_REGISTRY.get(KEY_MANUAL_RUNS_PER_DAY)
    window = timedelta(
        seconds=(
            definition.rolling_window_seconds
            if definition is not None and definition.rolling_window_seconds
            else MANUAL_RUNS_ROLLING_WINDOW_SECONDS
        )
    )
    in_window = (
        select(Audit.created_at)
        .join(
            WorkspaceBillingLink,
            WorkspaceBillingLink.workspace_id == Audit.workspace_id,
        )
        .where(
            WorkspaceBillingLink.billing_account_id == account_id,
            Audit.trigger == AUDIT_TRIGGER_MANUAL,
            Audit.created_at > at - window,
        )
        .subquery()
    )
    used, oldest = (
        await session.execute(
            select(func.count(), func.min(in_window.c.created_at)).select_from(
                in_window
            )
        )
    ).one()
    used = int(used)
    allowance = capability.value
    allowed = used < allowance
    return _rate_decision(
        trigger=trigger,
        allowed=allowed,
        code="" if allowed else CODE_MANUAL_RUN_RATE_EXCEEDED,
        allowance=allowance,
        used=used,
        remaining=max(allowance - used, 0),
        reset_at=(oldest + window) if oldest is not None else None,
    )
