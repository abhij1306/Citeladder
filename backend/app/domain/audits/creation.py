"""Audit creation orchestration over frozen, persisted owners."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.abuse import abuse_settings
from app.core.config.audits import (
    AUDIT_ACTIVE_STATUSES,
    AUDIT_SCOPE_BRAND,
    AUDIT_SCOPES,
    AUDIT_STATUS_DRAFT,
    AUDIT_STATUS_QUEUED,
    AUDIT_STATUS_VALIDATING,
    EVENT_AUDIT_CREATED,
    EVENT_AUDIT_QUEUED,
    audit_settings,
)
from app.core.config.entitlements import CREDENTIAL_MODE_BYOK
from app.domain.abuse.service import reserve_workspace_capacity
from app.domain.audits.errors import AuditValidationError
from app.domain.audits.frozen_plan import (
    _evaluate_prompt_count_admission,
    _freeze_plan,
    _frozen_configuration,
)
from app.domain.audits.funded_admission import (
    _admit_funded_run,
    _expected_costs_by_engine,
)
from app.domain.audits.reads import get_audit
from app.domain.audits.resolution import (
    _load_project,
    _normalize_seed,
    _resolve_prompts,
    _resolve_run_routes,
)
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.audits.task_creation import (
    _create_audit_tasks,
    _prompt_configuration_rows,
    _shuffled_slots,
    _snapshot_objects,
)
from app.domain.commerce.audit_context import freeze_commerce_context
from app.domain.entitlements.enforcement import (
    RateAdmissionDeniedError,
    evaluate_manual_run_admission,
)
from app.models.audit import Audit


async def create_audit(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    engines: list[str],
    trigger: str,
    credential_mode: str = CREDENTIAL_MODE_BYOK,
    prompt_set_id: uuid.UUID | None = None,
    prompt_ids: list[uuid.UUID] | None = None,
    repetitions: int | None = None,
    benchmark_mode: str | None = None,
    audit_scope: str = AUDIT_SCOPE_BRAND,
    random_seed: str | None = None,
    schedule_id: uuid.UUID | None = None,
    scheduled_for: datetime | None = None,
) -> Audit:
    """Create + enqueue an audit (freeze snapshots, deterministic slot shuffle).

    Commits with all tasks ``queued`` so the worker can claim them.

    An orchestration SHELL: every policy decision (the frozen execution policy,
    repetitions, the composed system instruction, the route
    policies) is precomputed by ``_freeze_plan`` and assembled by
    ``_frozen_configuration``; the rolling manual-run rate is EVALUATED by
    ``evaluate_manual_run_admission`` and only applied here; funded admission
    (entitlement resolution, the monthly budget gate, and per-task credit
    reservations before claimability) is owned by ``_admit_funded_run`` and
    ``_create_audit_tasks``. This shell adds no branching of its own.
    """
    if audit_scope not in AUDIT_SCOPES:
        raise AuditValidationError(f"Unsupported audit_scope: {audit_scope}")
    project = await _load_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    prompts = await _resolve_prompts(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        prompt_set_id=prompt_set_id,
        prompt_ids=list(prompt_ids or []),
    )
    # ONE admission instant shared by the rate evaluation, the entitlement
    # resolution, the budget period, and every reservation timestamp.
    admission_at = datetime.now(UTC)
    routes = await _resolve_run_routes(
        session,
        workspace_id=workspace_id,
        engines=engines,
        credential_mode=credential_mode,
    )

    plan = _freeze_plan(
        project=project,
        prompts=prompts,
        routes=routes,
        trigger=trigger,
        benchmark_mode=benchmark_mode,
        repetitions=repetitions,
        audit_scope=audit_scope,
    )
    # Per-engine expected costs from the sole cost owner: consumed by the
    # funded budget gate and re-proven by per-task credential resolution.
    expected_costs = _expected_costs_by_engine(routes=routes, plan=plan)
    # Prompt-count admission is PRECOMPUTED by one extracted helper. Prompt
    # relevance was already enforced when each prompt entered the active
    # portfolio; launch must not reinterpret that persisted decision.
    _evaluate_prompt_count_admission(
        prompts=prompts,
        trigger=plan.trigger,
        credential_mode=credential_mode,
    )
    reps = plan.repetitions
    engine_list = list(routes.keys())
    total = len(prompts) * len(engine_list) * reps
    if total > audit_settings.max_tasks_per_audit:
        raise AuditValidationError(
            f"Audit would create {total} tasks, exceeding the limit of "
            f"{audit_settings.max_tasks_per_audit}"
        )

    await reserve_workspace_capacity(
        session,
        workspace_id=workspace_id,
        lock_namespace="audit-enqueue",
        model=Audit,
        active_statuses=AUDIT_ACTIVE_STATUSES,
        active_limit=abuse_settings.active_audits_per_workspace,
        active_operation="audit.active_jobs",
        usage_operation="audit.provider_tasks",
        usage_limit=abuse_settings.audit_tasks_per_workspace_daily,
        amount=total,
        retry_after_seconds=abuse_settings.active_job_retry_after_seconds,
    )

    # Rolling manual-run rate (account-scoped, under the account advisory
    # lock — acquired LAST, after the abuse workspace lock): evaluated by the
    # entitlements owner; this shell only APPLIES the typed decision. The
    # active-audit/task abuse controls above stay separate protections.
    rate_decision = await evaluate_manual_run_admission(
        session, workspace_id=workspace_id, trigger=plan.trigger, at=admission_at
    )
    if not rate_decision.allowed:
        raise RateAdmissionDeniedError(
            "The account's manual run rate allowance is exhausted",
            decision=rate_decision,
        )

    # Funded admission (no-op for BYOK): resolves the entitlement at
    # ``admission_at``, gates the UTC-month budget under the account lock,
    # and selects the mode's consumable credit key.
    funded = await _admit_funded_run(
        session,
        workspace_id=workspace_id,
        credential_mode=credential_mode,
        plan=plan,
        expected_costs=expected_costs,
        tasks_per_engine=len(prompts) * reps,
        max_attempts=plan.policy.max_attempts,
        at=admission_at,
    )

    seed = _normalize_seed(random_seed)
    prompt_rows = _prompt_configuration_rows(prompts)
    configuration = _frozen_configuration(
        project=project, plan=plan, routes=routes, prompt_rows=prompt_rows
    )
    if audit_scope == "commerce":
        configuration["commerce_measurement"] = await freeze_commerce_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt_ids=[prompt.id for prompt in prompts],
        )

    audit = Audit(
        workspace_id=workspace_id,
        project_id=project.id,
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        status=AUDIT_STATUS_DRAFT,
        trigger=plan.trigger,
        benchmark_mode=plan.benchmark_mode,
        audit_scope=audit_scope,
        system_instruction=plan.system_instruction,
        repetitions=reps,
        random_seed=seed,
        configuration=configuration,
        requested_count=total,
        # Funded worst-case monthly reservation (null for BYOK runs).
        funding_account_id=funded.account_id,
        funded_budget_period_start=funded.budget_period_start,
        funded_reserved_cost_microusd=funded.reserved_cost_microusd,
    )
    session.add(audit)
    await session.flush()  # assign audit.id

    # Freeze prompt + engine snapshots (immutable provenance, invariants 3 + 10).
    prompt_snapshots, engine_snapshots = _snapshot_objects(
        audit_id=audit.id, prompts=prompts, routes=routes
    )
    session.add_all(prompt_snapshots)
    session.add_all(engine_snapshots.values())
    await session.flush()  # assign snapshot ids

    # Build every (prompt_index, engine, repetition) slot, then shuffle it
    # deterministically with the stored seed (invariant 9). The same seed
    # reproduces the same order.
    slots = _shuffled_slots(
        prompt_count=len(prompts),
        engines=engine_list,
        repetitions=reps,
        seed=seed,
    )

    await _create_audit_tasks(
        session,
        audit=audit,
        slots=slots,
        routes=routes,
        plan=plan,
        prompt_snapshots=prompt_snapshots,
        engine_snapshots=engine_snapshots,
        funded=funded,
        expected_costs=expected_costs,
        workspace_id=workspace_id,
        at=admission_at,
    )

    # Move DRAFT -> VALIDATING -> QUEUED through the state machine so an illegal
    # move raises instead of silently corrupting the lifecycle (invariant 9).
    apply_transition(
        session,
        audit=audit,
        target=AUDIT_STATUS_VALIDATING,
        message="audit validating",
    )
    apply_transition(
        session,
        audit=audit,
        target=AUDIT_STATUS_QUEUED,
        message="audit queued",
    )
    record_event(
        session,
        audit_id=audit.id,
        event_type=EVENT_AUDIT_CREATED,
        message="audit created",
        payload={"requested_count": total, "engines": engine_list},
    )
    record_event(
        session,
        audit_id=audit.id,
        event_type=EVENT_AUDIT_QUEUED,
        message="audit queued",
        payload={"task_count": len(slots)},
    )

    await session.commit()
    # `engine_snapshots` is a lazy relationship; a bare ``session.refresh``
    # only reloads scalar columns, so accessing it later (e.g. from
    # ``AuditResponse.model_validate`` in the API layer, outside of an async
    # greenlet) raises ``MissingGreenlet``. Re-fetch through ``get_audit``,
    # which eagerly loads it via ``selectinload``, so the returned instance is
    # safe to serialize.
    return await get_audit(session, workspace_id=workspace_id, audit_id=audit.id)
