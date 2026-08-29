"""Frozen audit snapshot and durable task creation."""

from __future__ import annotations

import random
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import TASK_STATUS_PENDING_RESERVATION
from app.core.config.costs import ExpectedExecutionCost
from app.core.config.entitlements import CAPABILITY_REGISTRY
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.audits.frozen_plan import _FrozenPlan, _task_route_snapshot
from app.domain.audits.funded_admission import (
    _NULL_FUNDING_ACCOUNT_ID,
    _apply_funded_credential,
    _freeze_credential_provenance,
    _FundedAdmission,
    _reserve_task_funding,
    _resolve_task_credential,
)
from app.domain.audits.resolution import _ResolvedRoute
from app.domain.entitlements.types import no_capability_entitlement
from app.domain.providers.credentials import ResolvedCredential
from app.models.audit import Audit, AuditEngineSnapshot, AuditPromptSnapshot, AuditTask
from app.models.prompt import Prompt


async def _create_audit_tasks(
    session: AsyncSession,
    *,
    audit: Audit,
    slots: list[tuple[int, str, int]],
    routes: dict[str, _ResolvedRoute],
    plan: _FrozenPlan,
    prompt_snapshots: list[AuditPromptSnapshot],
    engine_snapshots: dict[str, AuditEngineSnapshot],
    funded: _FundedAdmission,
    expected_costs: dict[str, ExpectedExecutionCost],
    workspace_id: uuid.UUID,
    at: datetime,
) -> None:
    """Create one task per shuffled slot; credentials freeze before claimable.

    Each task resolves its execution credential (T11) in this same admission
    transaction — a funded task first reserves its full ``max_attempts`` — and
    the frozen source/connection/reservation identity lands on the task's
    route snapshot, the engine snapshot, and the audit configuration
    provenance maps. A task is written NON-claimable (``pending_reservation``
    for funded) and flips to ``queued`` only with its credential frozen, so
    the row and its execution identity become visible atomically at commit.
    BYOK precedence is frozen here: a BYOK selection never falls back to
    funded mid-audit (the worker only loads frozen identities).
    """
    task_reservations: dict[str, str] = {}
    task_credentials: dict[str, dict] = {}
    engine_credentials: dict[str, ResolvedCredential] = {}
    # BYOK-mode runs carry no billing entitlement: this fail-closed value
    # proves nothing funded (no DB read, no resolver telemetry). Funded runs
    # reuse the exact entitlement resolved at the shared ``admission_at``.
    entitlement = funded.entitlement or no_capability_entitlement(
        account_id=_NULL_FUNDING_ACCOUNT_ID,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=0,
        at=at,
    )
    for position, (prompt_index, engine, repetition) in enumerate(slots):
        prompt_snapshot = prompt_snapshots[prompt_index]
        engine_snapshot = engine_snapshots[engine]
        route = routes[engine]
        idempotency_key = f"{audit.id}:{prompt_index}:{repetition}:{engine}"
        task = AuditTask(
            audit_id=audit.id,
            workspace_id=workspace_id,
            prompt_snapshot_id=prompt_snapshot.id,
            engine_snapshot_id=engine_snapshot.id,
            prompt_index=prompt_index,
            repetition=repetition,
            randomized_position=position,
            logical_engine=engine,
            transport_provider=route.transport_provider,
            transport_model=route.transport_model,
            prompt_text=prompt_snapshot.text,
            idempotency_key=idempotency_key,
            max_attempts=plan.policy.max_attempts,
            status=(
                TASK_STATUS_PENDING_RESERVATION
                if funded.enabled
                else TASK_STATUS_QUEUED
            ),
        )
        session.add(task)
        await session.flush()  # assign task.id (reservation FK + provenance)
        reservation = await _reserve_task_funding(
            session, audit=audit, task=task, funded=funded, at=at
        )
        credential = await _resolve_task_credential(
            session,
            workspace_id=workspace_id,
            engine=engine,
            account_id=funded.account_id if funded.enabled else None,
            entitlement=entitlement,
            reservation=reservation,
            expected_cost=expected_costs[engine],
            at=at,
        )
        task.provider_route_snapshot = _task_route_snapshot(
            engine=engine, route=route, plan=plan, credential=credential
        )
        # The engine snapshot records the concrete frozen connection too
        # (the platform connection for funded runs).
        engine_snapshot.connection_id = credential.connection_id
        engine_credentials[engine] = credential
        task_credentials[str(task.id)] = {
            "credential_source": credential.credential_source,
            "connection_id": str(credential.connection_id),
            "reservation_id": (
                str(credential.reservation_id)
                if credential.reservation_id is not None
                else None
            ),
        }
        if reservation is not None:
            await _apply_funded_credential(
                session,
                audit=audit,
                task=task,
                funded=funded,
                reservation=reservation,
                credential=credential,
                task_reservations=task_reservations,
                at=at,
            )
    _freeze_credential_provenance(
        audit,
        engine_credentials=engine_credentials,
        task_credentials=task_credentials,
        task_reservations=task_reservations,
        funded=funded,
        at=at,
    )


def _prompt_configuration_rows(prompts: list[Prompt]) -> list[dict[str, Any]]:
    """Reduce selected prompts to their frozen configuration fields."""
    return [
        {
            "text": prompt.text or "",
            "theme": prompt.theme or "",
            "intent": prompt.intent or "",
            "buyer_stage": prompt.buyer_stage or "",
            "prompt_intent": prompt.prompt_intent or "",
            "cohort": prompt.cohort,
        }
        for prompt in prompts
    ]


def _snapshot_objects(
    *,
    audit_id: uuid.UUID,
    prompts: list[Prompt],
    routes: dict[str, _ResolvedRoute],
) -> tuple[list[AuditPromptSnapshot], dict[str, AuditEngineSnapshot]]:
    """Construct immutable prompt and engine snapshots without persistence."""
    prompt_snapshots = [
        AuditPromptSnapshot(
            audit_id=audit_id,
            prompt_id=prompt.id,
            prompt_index=index,
            text=prompt.text or "",
            theme=prompt.theme or "",
            intent=prompt.intent or "",
            buyer_stage=prompt.buyer_stage or "",
            prompt_intent=prompt.prompt_intent or "",
            cohort=prompt.cohort,
            generation_evidence=prompt.generation_evidence,
        )
        for index, prompt in enumerate(prompts)
    ]
    engine_snapshots = {
        engine: AuditEngineSnapshot(
            audit_id=audit_id,
            logical_engine=engine,
            transport_provider=route.transport_provider,
            transport_model=route.transport_model,
            connection_id=route.connection_id,
            base_url=route.base_url,
        )
        for engine, route in routes.items()
    }
    return prompt_snapshots, engine_snapshots


def _shuffled_slots(
    *, prompt_count: int, engines: list[str], repetitions: int, seed: str
) -> list[tuple[int, str, int]]:
    """Build and deterministically shuffle every prompt/engine/run slot."""
    slots = [
        (prompt_index, engine, repetition)
        for prompt_index in range(prompt_count)
        for engine in engines
        for repetition in range(repetitions)
    ]
    # The seed is persisted specifically for reproducible scheduling; this is
    # not a secret, token, identifier, or security decision.
    random.Random(int(seed)).shuffle(slots)  # noqa: S311 - deterministic order, not crypto
    return slots
