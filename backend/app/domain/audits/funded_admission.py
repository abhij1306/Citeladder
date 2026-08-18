"""Funded audit admission, reservations, and frozen credential provenance."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import MEASUREMENT_MODE_PULSE, TASK_STATUS_QUEUED
from app.core.config.billing_contracts import TELEMETRY_FUNDED_BUDGET_EXHAUSTED
from app.core.config.billing_settings import billing_settings
from app.core.config.costs import (
    MICRO_USD_PER_USD,
    ExpectedExecutionCost,
    RouteIdentity,
    expected_execution_cost,
)
from app.core.config.entitlements import (
    CODE_FUNDED_BUDGET_EXHAUSTED,
    CODE_FUNDED_COST_UNRESOLVED,
    CREDENTIAL_MODE_FUNDED,
    KEY_BENCHMARK_CREDITS,
    KEY_PULSE_CREDITS,
)
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_BYOK,
    TELEMETRY_FUNDED_ADMISSION_DENIED,
)
from app.domain.audits.errors import FundedAdmissionError
from app.domain.audits.frozen_plan import _FrozenPlan
from app.domain.audits.resolution import _ResolvedRoute
from app.domain.entitlements.enforcement import lock_billing_account_capacity
from app.domain.entitlements.ledger import (
    FundedCreditsExhaustedError,
    Reservation,
    release_terminal_funded_task,
    reserve_funded_task,
)
from app.domain.entitlements.service import resolve_workspace_entitlement
from app.domain.entitlements.types import (
    STATUS_ENTITLEMENT_UNRESOLVED,
    STATUS_RESOLVED,
    ResolvedEntitlement,
)
from app.domain.providers.credentials import (
    ExecutionCredentialsUnavailableError,
    ResolvedCredential,
    resolve_execution_credentials,
)
from app.models.audit import Audit, AuditTask

logger = logging.getLogger("app.billing")


def _admission_denied(
    message: str,
    *,
    code: str,
    details: dict[str, Any] | None = None,
    capability_key: str | None = None,
    account_id: uuid.UUID | None = None,
) -> FundedAdmissionError:
    """Emit ``funded.execution.admission_denied``; return the refusal to raise.

    Every funded-admission denial funnels here so the operator telemetry is
    emitted exactly once per denial with safe fields only — the config-owned
    code, an opaque account id, and the capability key (never prompts, key
    material, or provider detail, invariant 6). The specific cause keeps its
    own dedicated event too (``billing.funded_budget_exhausted`` /
    ``billing.consumable_credits_exhausted`` / ``billing.entitlement_unresolved``).
    Callers ``raise`` the returned error (chaining ``from exc`` where a cause
    exists).
    """
    logger.info(
        TELEMETRY_FUNDED_ADMISSION_DENIED + " code=%s account_id=%s capability_key=%s",
        code,
        account_id,
        capability_key,
    )
    return FundedAdmissionError(message, code=code, details=details)


# Null funding account for the fail-closed BYOK-mode entitlement built during
# task creation: a BYOK run has no billing account and proves nothing funded
# (mirrors the entitlements resolver's own null-account sentinel).
_NULL_FUNDING_ACCOUNT_ID: Final = uuid.UUID(int=0)


@dataclass(frozen=True, slots=True)
class _FundedAdmission:
    """The frozen funded-admission decision for one run (disabled for BYOK).

    ``reserved_cost_microusd`` is the audit's worst-case funded cost for the
    UTC calendar month of ``budget_period_start`` — deliberately conservative,
    never released, so concurrent admitted work cannot exceed the ceiling.
    """

    enabled: bool
    account_id: uuid.UUID | None
    capability_key: str
    entitlement: ResolvedEntitlement | None
    reserved_cost_microusd: int | None
    budget_period_start: datetime | None


_FUNDED_DISABLED = _FundedAdmission(
    enabled=False,
    account_id=None,
    capability_key="",
    entitlement=None,
    reserved_cost_microusd=None,
    budget_period_start=None,
)


def _complete_execution_cost_microusd(
    *,
    token_cost: int | None,
    search_fee: int | None,
    searches: int | None,
    retrieval_enabled: bool,
) -> int | None:
    """Micro-USD of ONE execution, or None when the estimate is incomplete.

    Completeness is exact: an absent token estimate is always incomplete;
    retrieval ON requires the search fee AND the expected-search count;
    retrieval OFF leaves the search fields not applicable — never read, never
    coerced to zero, never required.
    """
    if token_cost is None:
        return None
    if not retrieval_enabled:
        return token_cost
    if search_fee is None or searches is None:
        return None
    return token_cost + search_fee * searches


def _expected_costs_by_engine(
    *, routes: dict[str, _ResolvedRoute], plan: _FrozenPlan
) -> dict[str, ExpectedExecutionCost]:
    """Per-engine expected cost of ONE execution from the sole cost owner.

    Reads ONLY ``config/costs.expected_execution_cost``; retrieval
    applicability comes from the frozen mode policy. The same map feeds the
    funded budget gate (completeness-checked there) and per-task credential
    resolution (which re-proves completeness before any funded selection).
    """
    return {
        engine: expected_execution_cost(
            RouteIdentity(
                logical_engine=route.logical_engine,
                transport_provider=route.transport_provider,
                transport_model=route.transport_model,
            ),
            plan.measurement_mode,
            plan.policy.retrieval_enabled,
        )
        for engine, route in routes.items()
    }


def _funded_expected_cost_microusd(
    *,
    expected_costs: dict[str, ExpectedExecutionCost],
    plan: _FrozenPlan,
    tasks_per_engine: int,
    max_attempts: int,
) -> int:
    """Worst-case funded cost of the whole audit (per-task cost x attempts).

    Fails closed with ``funded_cost_unresolved`` on any incomplete estimate.
    Retrieval applicability comes from the frozen mode policy.
    """
    total = 0
    for engine, expected in expected_costs.items():
        per_execution = _complete_execution_cost_microusd(
            token_cost=expected.token_cost_microusd,
            search_fee=expected.search_fee_microusd,
            searches=expected.expected_searches,
            retrieval_enabled=plan.policy.retrieval_enabled,
        )
        if per_execution is None or not expected.complete:
            raise _admission_denied(
                f"Expected execution cost is unresolved for {engine}",
                code=CODE_FUNDED_COST_UNRESOLVED,
            )
        total += per_execution * max_attempts * tasks_per_engine
    return total


async def _admit_funded_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    credential_mode: str,
    plan: _FrozenPlan,
    expected_costs: dict[str, ExpectedExecutionCost],
    tasks_per_engine: int,
    max_attempts: int,
    at: datetime,
) -> _FundedAdmission:
    """Funded admission: entitlement resolution + monthly budget gate.

    The exact sequence for a funded task set: resolve at the shared
    ``admission_at``, fail closed unless resolved (the resolver emits
    ``billing.entitlement_unresolved``), select the mode's credit key, then
    under the account advisory lock sum the month's reserved worst-case cost
    plus the candidate against the minor-USD ceiling converted through
    ``MICRO_USD_PER_USD``. BYOK bypasses budget admission entirely.
    """
    if credential_mode != CREDENTIAL_MODE_FUNDED:
        return _FUNDED_DISABLED
    entitlement = await resolve_workspace_entitlement(
        session, workspace_id=workspace_id, at=at
    )
    if entitlement.status != STATUS_RESOLVED:
        raise _admission_denied(
            "Billing entitlement is unavailable for this workspace",
            code=STATUS_ENTITLEMENT_UNRESOLVED,
            account_id=entitlement.account_id,
        )
    capability_key = (
        KEY_PULSE_CREDITS
        if plan.measurement_mode == MEASUREMENT_MODE_PULSE
        else KEY_BENCHMARK_CREDITS
    )
    account_id = entitlement.account_id
    # The account-capacity lock is the LAST lock this path acquires (the
    # abuse workspace lock was taken earlier); it serializes every funded
    # admission on the account so the budget ceiling holds concurrently.
    await lock_billing_account_capacity(session, account_id)
    candidate = _funded_expected_cost_microusd(
        expected_costs=expected_costs,
        plan=plan,
        tasks_per_engine=tasks_per_engine,
        max_attempts=max_attempts,
    )
    period_start = at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    period_end = (period_start + timedelta(days=32)).replace(day=1)
    reserved = await session.scalar(
        select(func.coalesce(func.sum(Audit.funded_reserved_cost_microusd), 0)).where(
            Audit.funding_account_id == account_id,
            Audit.funded_budget_period_start >= period_start,
            Audit.funded_budget_period_start < period_end,
        )
    )
    ceiling_microusd = (
        billing_settings.funded_monthly_budget_minor * MICRO_USD_PER_USD // 100
    )
    if int(reserved or 0) + candidate > ceiling_microusd:
        logger.info(
            TELEMETRY_FUNDED_BUDGET_EXHAUSTED
            + " account_id=%s capability_key=%s reserved_microusd=%s",
            account_id,
            capability_key,
            int(reserved or 0),
        )
        raise _admission_denied(
            "The account's funded monthly budget is exhausted",
            code=CODE_FUNDED_BUDGET_EXHAUSTED,
            details={"capability_key": capability_key},
            capability_key=capability_key,
            account_id=account_id,
        )
    return _FundedAdmission(
        enabled=True,
        account_id=account_id,
        capability_key=capability_key,
        entitlement=entitlement,
        reserved_cost_microusd=candidate,
        budget_period_start=period_start,
    )


def _entitlement_provenance(entitlement: ResolvedEntitlement | None) -> dict:
    """Safe resolver provenance for frozen configurations (invariant 6)."""
    if entitlement is None:
        return {}
    return {
        "registry_revision": entitlement.registry_revision,
        "entitlement_lifecycle_version": entitlement.entitlement_lifecycle_version,
        "resolved_at": entitlement.resolved_at.isoformat(),
    }


def _task_funding_block(*, funded: _FundedAdmission, reservation: Reservation) -> dict:
    """Frozen per-task funding provenance for Slice 1 credential resolution."""
    return {
        "credential_mode": CREDENTIAL_MODE_FUNDED,
        "capability_key": reservation.capability_key,
        "funding_account_id": str(reservation.billing_account_id),
        "reservation_id": str(reservation.reservation_id),
        "reserved_units": reservation.units,
        "grant_allocations": [
            {"grant_id": str(allocation.grant_id), "units": allocation.units}
            for allocation in reservation.allocations
        ],
        "entitlement": _entitlement_provenance(funded.entitlement),
    }


async def _reserve_task_funding(
    session: AsyncSession,
    *,
    audit: Audit,
    task: AuditTask,
    funded: _FundedAdmission,
    at: datetime,
) -> Reservation | None:
    """This task's funded reservation (same transaction), or None for BYOK.

    A credit shortfall raises the coded ``FundedAdmissionError`` and the whole
    audit (tasks + reservations) rolls back; nothing is enqueued.
    """
    if not funded.enabled:
        return None
    assert funded.account_id is not None  # enabled implies resolved account
    try:
        return await reserve_funded_task(
            session,
            account_id=funded.account_id,
            capability_key=funded.capability_key,
            audit_id=audit.id,
            task_id=task.id,
            units=task.max_attempts,
            idempotency_key=f"{audit.id}:{task.id}:funded-reserve",
            at=at,
        )
    except FundedCreditsExhaustedError as exc:
        raise _admission_denied(
            exc.message,
            code=exc.code,
            details=exc.details,
            capability_key=funded.capability_key,
            account_id=funded.account_id,
        ) from exc


async def _resolve_task_credential(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    engine: str,
    account_id: uuid.UUID | None,
    entitlement: ResolvedEntitlement,
    reservation: Reservation | None,
    expected_cost: ExpectedExecutionCost,
    at: datetime,
) -> ResolvedCredential:
    """Per-task admission credential (T11), as a coded admission refusal.

    The resolver's ``execution_credentials_unavailable`` is translated into
    the planner's graceful admission error so the API layer renders it through
    the unified envelope; raised inside the planner transaction, nothing
    persists (no claimable task, no provider call).
    """
    try:
        return await resolve_execution_credentials(
            session,
            workspace_id=workspace_id,
            account_id=account_id,
            logical_engine=engine,
            entitlement=entitlement,
            reservation=reservation,
            expected_cost=expected_cost,
            at=at,
        )
    except ExecutionCredentialsUnavailableError as exc:
        raise _admission_denied(
            exc.message, code=exc.code, details=exc.details, account_id=account_id
        ) from exc


async def _apply_funded_credential(
    session: AsyncSession,
    *,
    audit: Audit,
    task: AuditTask,
    funded: _FundedAdmission,
    reservation: Reservation,
    credential: ResolvedCredential,
    task_reservations: dict[str, str],
    at: datetime,
) -> None:
    """Freeze the funded block, or release the reservation when BYOK won.

    BYOK precedence is absolute (T11): when a healthy tenant BYOK route exists
    for a funded request's engine, the task executes BYOK and this task's
    just-made reservation is released in the SAME transaction so no credit is
    stranded. Otherwise the reservation provenance freezes into the task's
    funding block and the task-reservation map.
    """
    if credential.credential_source == CREDENTIAL_SOURCE_BYOK:
        await release_terminal_funded_task(
            session,
            reservation_id=reservation.reservation_id,
            audit_id=audit.id,
            task_id=task.id,
            trigger="byok",
            at=at,
        )
    else:
        task.provider_route_snapshot = {
            **(task.provider_route_snapshot or {}),
            "funding": _task_funding_block(funded=funded, reservation=reservation),
        }
        task_reservations[str(task.id)] = str(reservation.reservation_id)
    task.status = TASK_STATUS_QUEUED


def _freeze_credential_provenance(
    audit: Audit,
    *,
    engine_credentials: dict[str, ResolvedCredential],
    task_credentials: dict[str, dict],
    task_reservations: dict[str, str],
    funded: _FundedAdmission,
    at: datetime,
) -> None:
    """Merge the frozen credential provenance into the audit configuration.

    Every engine route records its frozen ``credential_source`` + concrete
    ``connection_id``; ``task_credentials`` is the replay map of task id to
    its frozen credential identity (source / connection / reservation).
    """
    update: dict[str, Any] = {
        "engine_routes": {
            engine: {
                **route_config,
                "credential_source": engine_credentials[engine].credential_source,
                "connection_id": str(engine_credentials[engine].connection_id),
            }
            for engine, route_config in (audit.configuration or {})
            .get("engine_routes", {})
            .items()
            if engine in engine_credentials
        },
        "task_credentials": task_credentials,
    }
    if funded.enabled:
        update["funding"] = {
            "credential_mode": CREDENTIAL_MODE_FUNDED,
            "capability_key": funded.capability_key,
            "funding_account_id": str(funded.account_id),
            "admission_at": at.isoformat(),
            "budget_period_start": (
                funded.budget_period_start.isoformat()
                if funded.budget_period_start is not None
                else None
            ),
            "reserved_cost_microusd": funded.reserved_cost_microusd,
            "entitlement": _entitlement_provenance(funded.entitlement),
        }
        # Replay/provenance map: task id -> reservation id.
        update["task_reservations"] = task_reservations
    audit.configuration = {**(audit.configuration or {}), **update}
