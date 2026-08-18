# Audit planner (invariant 9 — deterministic; invariant 3 — frozen snapshots).
#
# Adapts the reference ``ai_visibility/service.create_run`` + ``cancel_run`` to
# CiteLadder's workspace-scoped, UUID, BYOK-routed model. ``create_audit``:
#   1. resolves + authorizes the project and prompt source (workspace-scoped);
#   2. resolves one provider route per requested logical engine from the
#      workspace's ``ProviderConnection``s (never the key — invariant 6);
#   3. freezes prompt + engine + scoring snapshots (invariant 3);
#   4. generates one slot per (prompt x engine x repetition), shuffles them with
#      the stored 64-bit seed (invariant 9), and enqueues one ``AuditTask`` per
#      slot with a stable idempotency key.
# ``cancel_audit`` is cooperative: it flips the audit to ``cancelled`` and
# terminalizes unfinished tasks so a live worker stops at its boundary.
from __future__ import annotations

import hashlib
import logging
import random
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.abuse import abuse_settings
from app.core.config.audits import (
    AUDIT_ACTIVE_STATUSES,
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_DRAFT,
    AUDIT_STATUS_QUEUED,
    AUDIT_STATUS_VALIDATING,
    AUDIT_TRIGGER_TRIAL,
    AUDIT_TRIGGERS,
    CODE_PROMPT_COUNT_EXCEEDED,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
    EVENT_AUDIT_CANCELLED,
    EVENT_AUDIT_CREATED,
    EVENT_AUDIT_QUEUED,
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_POLICY_KEY,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_PENDING_RESERVATION,
    TASK_STATUS_QUEUED,
    TASK_TERMINAL_STATUSES,
    MeasurementModePolicy,
    audit_settings,
    frozen_policy_configuration,
    measurement_policy_for_mode,
    system_instruction_for_mode,
)
from app.core.config.billing_contracts import (
    TELEMETRY_FUNDED_BUDGET_EXHAUSTED,
)
from app.core.config.billing_settings import billing_settings
from app.core.config.commerce import (
    SHOPPING_SURFACE_MEASUREMENT,
    SHOPPING_SURFACES,
)
from app.core.config.costs import (
    MICRO_USD_PER_USD,
    ExpectedExecutionCost,
    RouteIdentity,
    expected_execution_cost,
)
from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    CODE_FUNDED_BUDGET_EXHAUSTED,
    CODE_FUNDED_COST_UNRESOLVED,
    CREDENTIAL_MODE_BYOK,
    CREDENTIAL_MODE_FUNDED,
    KEY_BENCHMARK_CREDITS,
    KEY_PULSE_CREDITS,
)
from app.core.config.projects import (
    BENCHMARK_MODES,
    DEFAULT_BENCHMARK_MODE,
    MAX_REPETITIONS,
    MIN_REPETITIONS,
)
from app.core.config.prompts import PROMPT_STATUS_ACTIVE
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_BYOK,
    LOGICAL_ENGINES,
    TELEMETRY_FUNDED_ADMISSION_DENIED,
    is_endpoint_approved,
    is_route_approved,
    measurement_route,
    route_policy,
)
from app.domain.abuse.service import reserve_workspace_capacity
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.entitlements.enforcement import (
    RateAdmissionDeniedError,
    evaluate_manual_run_admission,
    lock_billing_account_capacity,
)
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
    no_capability_entitlement,
)
from app.domain.products.shim import project_product_identity
from app.domain.projects.shim import project_scoring_identity
from app.domain.prompts.topical_binding import (
    BINDING_FAILURE_MESSAGES,
    TopicalBindingError,
    build_project_vocabulary,
    has_project_binding_context,
    validate_prompt_binding,
)
from app.domain.providers.credentials import (
    ExecutionCredentialsUnavailableError,
    ResolvedCredential,
    resolve_execution_credentials,
)
from app.models.audit import (
    Audit,
    AuditEngineSnapshot,
    AuditPromptSnapshot,
    AuditTask,
)
from app.models.brand import Brand
from app.models.product import CompetitorProduct
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet
from app.models.provider import ProviderConnection, ProviderRoute

logger = logging.getLogger("app.billing")


class AuditValidationError(ValueError):
    """Raised when an audit request is invalid (bad prompts/engines/routes)."""


class AuditNotFoundError(LookupError):
    """Raised when an audit is missing or not in the caller's workspace."""


class FundedAdmissionError(RuntimeError):
    """Graceful funded-admission refusal (mapped at the API layer).

    Carries a config-owned code (``funded_budget_exhausted`` /
    ``funded_credits_exhausted`` / ``funded_cost_unresolved`` /
    ``entitlement_unresolved`` / ``execution_credentials_unavailable``).
    Nothing persists when raised inside the planner transaction: no audit,
    task, or ledger rows, nothing enqueued.
    """

    def __init__(
        self, message: str, *, code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


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


class PromptCountPolicyError(RuntimeError):
    """Funded/trial prompt-count admission refusal (mapped at the API layer).

    Same coded pattern as ``FundedAdmissionError``: ``prompt_count_policy_unconfigured``
    when the ``audit_prompt_count`` knob is unset (fail closed — the planner
    never invents a count) or ``prompt_count_exceeded`` when the selected
    active prompts exceed the configured count. Raised before any audit,
    task, or ledger row persists. BYOK runs never hit this error.
    """

    def __init__(
        self, message: str, *, code: str, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details


# Null funding account for the fail-closed BYOK-mode entitlement built during
# task creation: a BYOK run has no billing account and proves nothing funded
# (mirrors the entitlements resolver's own null-account sentinel).
_NULL_FUNDING_ACCOUNT_ID: Final = uuid.UUID(int=0)


@dataclass(frozen=True, slots=True)
class _ResolvedRoute:
    """One run's resolved route identity (never a key — invariant 6).

    BYOK runs point at the workspace's ``ProviderConnection``; funded runs
    resolve the catalog route here and get their concrete platform connection
    from per-task credential resolution (T11) at task creation.
    """

    logical_engine: str
    transport_provider: str
    transport_model: str
    connection_id: uuid.UUID | None
    base_url: str


def _normalize_seed(value: str | None) -> str:
    """Return a decimal string for a 64-bit unsigned seed.

    Accepts an explicit seed (any 64-bit-representable int, decimal string) or
    generates a fresh 64-bit one when omitted (invariant 9 — stored + replayed).
    """
    if value is None or not str(value).strip():
        return str(secrets.randbits(64))
    try:
        seed_int = int(str(value).strip())
    except ValueError as exc:
        raise AuditValidationError("random_seed must be an integer") from exc
    # Keep it in the unsigned 64-bit range so replay is exact.
    return str(seed_int & ((1 << 64) - 1))


def _prompt_panel_snapshot(rows: list[dict]) -> dict:
    """Stable hash of the frozen prompt panel (audit-scoping evidence)."""
    import json

    encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "panel_id": digest[:16],
        "panel_hash": digest,
        "prompt_hashes": [
            hashlib.sha256(str(r["text"]).encode("utf-8")).hexdigest() for r in rows
        ],
    }


async def _load_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    result = await session.execute(
        select(Project)
        .options(
            selectinload(Project.brand).selectinload(Brand.aliases),
            # Binding identity (topical admission): profile + topics are the
            # category side of the vocabulary; competitors are never loaded
            # into it.
            selectinload(Project.brand).selectinload(Brand.profile),
            selectinload(Project.topics),
            selectinload(Project.competitors),
            selectinload(Project.owned_domains),
            selectinload(Project.unintended_domains),
            selectinload(Project.products),
            selectinload(Project.competitor_products).selectinload(
                CompetitorProduct.competitor
            ),
        )
        .where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    project = result.scalars().unique().one_or_none()
    if project is None:
        raise AuditValidationError("Project not found")
    return project


async def _resolve_prompts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID | None,
    prompt_ids: list[uuid.UUID],
) -> list[Prompt]:
    """Resolve active, enabled prompts from a set or explicit ids, workspace-scoped."""
    stmt = (
        select(Prompt)
        .join(PromptSet, PromptSet.id == Prompt.prompt_set_id)
        .join(Project, Project.id == PromptSet.project_id)
        .where(
            Project.workspace_id == workspace_id,
            Project.id == project_id,
            Prompt.enabled.is_(True),
            # Proposed (unreviewed AI suggestions) and archived prompts are
            # never audit-eligible — only human-accepted active prompts run.
            Prompt.status == PROMPT_STATUS_ACTIVE,
        )
        .order_by(Prompt.created_at.asc())
    )
    if prompt_ids:
        stmt = stmt.where(Prompt.id.in_(prompt_ids))
    elif prompt_set_id is not None:
        stmt = stmt.where(Prompt.prompt_set_id == prompt_set_id)
    else:
        raise AuditValidationError("Either prompt_set_id or prompt_ids is required")
    prompts = list((await session.scalars(stmt)).all())
    # For an explicit id list, reject the whole request if any requested prompt
    # is missing / disabled / from another project or workspace, rather than
    # silently auditing a smaller set than the caller asked for.
    if prompt_ids:
        requested = set(prompt_ids)
        resolved_ids = {prompt.id for prompt in prompts}
        unavailable = requested - resolved_ids
        if unavailable:
            missing = ", ".join(str(pid) for pid in sorted(map(str, unavailable)))
            raise AuditValidationError(
                f"Prompt(s) not found, disabled, not active, or not in this "
                f"project: {missing}"
            )
    if not prompts:
        raise AuditValidationError("No enabled prompts to audit")
    return prompts


def _normalize_engines(engines: list[str]) -> list[str]:
    """Validate + dedupe the requested logical engines (order-preserving)."""
    normalized = [str(e).strip().lower() for e in engines]
    seen: set[str] = set()
    unique_engines: list[str] = []
    for engine in normalized:
        if engine not in LOGICAL_ENGINES:
            raise AuditValidationError(f"Unknown logical engine: {engine}")
        if engine not in seen:
            seen.add(engine)
            unique_engines.append(engine)
    return unique_engines


async def _resolve_routes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    engines: list[str],
    measurement_mode: str,
) -> dict[str, _ResolvedRoute]:
    """Pick one active BYOK route + connection per requested logical engine.

    Prefers a route flagged ``is_default`` for the engine, else the first
    active one. Raises if an engine is unknown or has no configured route.
    """
    unique_engines = _normalize_engines(engines)
    result = await session.execute(
        select(ProviderRoute, ProviderConnection)
        .join(
            ProviderConnection,
            ProviderConnection.id == ProviderRoute.connection_id,
        )
        .where(
            ProviderRoute.workspace_id == workspace_id,
            ProviderRoute.active.is_(True),
            ProviderConnection.active.is_(True),
            # Tenant route resolution is BYOK-only: a platform connection
            # must never resolve as a tenant route.
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_BYOK,
        )
        .order_by(
            ProviderRoute.is_default.desc(),
            ProviderRoute.created_at.asc(),
        )
    )
    routes: dict[str, _ResolvedRoute] = {}
    for route, connection in result.all():
        if not is_route_approved(route.logical_engine, route.transport_provider):
            continue
        if not is_endpoint_approved(
            connection.transport_provider, connection.base_url or ""
        ):
            continue
        routes.setdefault(
            route.logical_engine,
            _ResolvedRoute(
                logical_engine=route.logical_engine,
                transport_provider=route.transport_provider,
                transport_model=measurement_route(
                    route.logical_engine, measurement_mode
                ).transport_model,
                connection_id=connection.id,
                base_url=connection.base_url or "",
            ),
        )

    resolved: dict[str, _ResolvedRoute] = {}
    missing: list[str] = []
    for engine in unique_engines:
        if engine in routes:
            resolved[engine] = routes[engine]
        else:
            missing.append(engine)
    if missing:
        raise AuditValidationError(
            "No active provider route configured for engine(s): " + ", ".join(missing)
        )
    return resolved


def _resolve_funded_routes(
    engines: list[str], measurement_mode: str
) -> dict[str, _ResolvedRoute]:
    """Resolve the catalog-approved funded route per requested engine.

    Exactly one approved transport per engine exists (invariant 10), so a
    funded run needs no TENANT connection: per-task credential resolution
    (T11) binds the concrete platform connection in the system workspace once
    the task's reservation proves funded authorization.
    """
    resolved: dict[str, _ResolvedRoute] = {}
    for engine in _normalize_engines(engines):
        try:
            catalog_route = measurement_route(engine, measurement_mode)
        except ValueError as exc:
            raise AuditValidationError(
                f"No approved funded route for engine: {engine}"
            ) from exc

        resolved[engine] = _ResolvedRoute(
            logical_engine=engine,
            transport_provider=catalog_route.transport_provider,
            transport_model=catalog_route.transport_model,
            connection_id=None,
            base_url="",
        )
    return resolved


async def _resolve_run_routes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    engines: list[str],
    credential_mode: str,
    measurement_mode: str,
) -> dict[str, _ResolvedRoute]:
    """Route resolution for one run: BYOK workspace routes or funded catalog."""
    if credential_mode == CREDENTIAL_MODE_FUNDED:
        return _resolve_funded_routes(engines, measurement_mode)
    if credential_mode != CREDENTIAL_MODE_BYOK:
        raise AuditValidationError(f"Unsupported credential_mode: {credential_mode}")
    return await _resolve_routes(
        session,
        workspace_id=workspace_id,
        engines=engines,
        measurement_mode=measurement_mode,
    )


def _resolve_benchmark_mode(value: str | None, project: Project) -> str:
    mode = str(value or project.benchmark_mode or DEFAULT_BENCHMARK_MODE)
    mode = mode.strip().lower()
    if mode not in BENCHMARK_MODES:
        raise AuditValidationError(f"Unsupported benchmark_mode: {mode}")
    return mode


@dataclass(frozen=True, slots=True)
class _FrozenPlan:
    """Everything the planner decided BEFORE it touches the audit row.

    ``create_audit`` is an orchestration shell: it consumes this precomputed
    result instead of branching on policy itself. Every field here is frozen
    onto the audit and never re-read from live settings afterwards
    (invariant 9).
    """

    trigger: str
    benchmark_mode: str
    measurement_mode: str
    policy: MeasurementModePolicy
    repetitions: int
    system_instruction: str
    route_policies: dict[str, dict]


def _resolve_measurement_policy(value: str | None) -> tuple[str, MeasurementModePolicy]:
    """Resolve + FREEZE the measurement-mode policy exactly once.

    Reads live settings here and nowhere else; the returned policy is what the
    audit stores and the worker executes. Fails closed on an unknown mode —
    ``measurement_policy_for_mode`` raises rather than defaulting to a cheaper
    or costlier shape.
    """
    mode = str(value or MEASUREMENT_MODE_PULSE).strip().lower()
    try:
        return mode, measurement_policy_for_mode(mode)
    except ValueError as exc:
        raise AuditValidationError(f"Unsupported measurement_mode: {mode}") from exc


def _compose_system_instruction(*, framing: str, policy: MeasurementModePolicy) -> str:
    """Compose the neutral prompt-framing instruction with the mode's addendum.

    The two axes are INDEPENDENT: ``framing`` comes from ``benchmark_mode``
    (consumer_like | controlled_localized | forced_grounded) and the addendum
    from ``measurement_mode``. Neither constrains the other, so any of the six
    combinations composes. The pulse addendum is an UNMEASURED CANDIDATE (see
    ``config/audits.PULSE_ANSWER_INSTRUCTION``); benchmark contributes "".
    Never carries brand/competitor identity (invariant 6).
    """
    return " ".join(part for part in (framing, policy.answer_instruction) if part)


def _resolve_repetitions(requested: int | None, policy: MeasurementModePolicy) -> int:
    """Repetitions for the run: an explicit request, else the mode default.

    The mode policy owns the default (pulse 1, benchmark 3) — the project's
    ``default_repetitions`` is a project-level preference that an explicit
    request still overrides, and neither may exceed the configured bounds.
    """
    reps = int(requested or policy.repetitions)
    if reps < MIN_REPETITIONS or reps > MAX_REPETITIONS:
        raise AuditValidationError(
            f"repetitions must be between {MIN_REPETITIONS} and {MAX_REPETITIONS}"
        )
    return reps


def _validate_prompt_lengths(prompts: list[Prompt]) -> None:
    """Reject any prompt longer than the config-owned ceiling (invariant 1)."""
    limit = audit_settings.max_prompt_chars
    too_long = [prompt for prompt in prompts if len(prompt.text or "") > limit]
    if too_long:
        raise AuditValidationError(
            f"Prompt(s) exceed the maximum length of {limit} characters"
        )


def _validate_prompt_bindings(project: Project, prompts: list[Prompt]) -> None:
    # A brand name/domain identifies the subject but provides no category
    # vocabulary for neutral measurement prompts. When crawl-backed setup did
    # not produce a profile or topic yet, keep audit creation available; the
    # stricter lexical gate resumes as soon as real category context exists.
    if not has_project_binding_context(project):
        return
    vocabulary = build_project_vocabulary(project)
    for prompt in prompts:
        result = validate_prompt_binding(prompt.text or "", vocabulary)
        if not result.accepted:
            raise TopicalBindingError(
                f"Prompt {prompt.id} cannot run: "
                f"{BINDING_FAILURE_MESSAGES[result.code]}",
                code=result.code,
                details={"prompt_id": str(prompt.id)},
            )


def _enforce_prompt_count_policy(
    prompts: list[Prompt], *, trigger: str, credential_mode: str
) -> None:
    if credential_mode != CREDENTIAL_MODE_FUNDED and trigger != AUDIT_TRIGGER_TRIAL:
        return
    limit = audit_settings.audit_prompt_count
    if limit is None:
        raise PromptCountPolicyError(
            "The audit prompt-count policy is not configured "
            "(AUDIT_AUDIT_PROMPT_COUNT); funded and trial audit creation "
            "fails closed rather than inventing a count",
            code=CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
        )
    if len(prompts) > limit:
        raise PromptCountPolicyError(
            f"Audit selected {len(prompts)} active prompts, exceeding the "
            f"configured prompt-count policy of {limit}",
            code=CODE_PROMPT_COUNT_EXCEEDED,
            details={"selected": len(prompts), "limit": limit},
        )


def _evaluate_prompt_admission(
    *,
    project: Project,
    prompts: list[Prompt],
    trigger: str,
    credential_mode: str,
) -> None:
    """Precompute topical-binding and selected-prompt count admission.

    Topical binding is required for every selected active prompt. Generation
    receipts record provenance only and never bypass relevance validation.
    """
    _validate_prompt_bindings(project, prompts)
    _enforce_prompt_count_policy(
        prompts, trigger=trigger, credential_mode=credential_mode
    )


def _route_policy_snapshot(logical_engine: str, measurement_mode: str) -> dict:
    """The frozen execution-time route policy for one approved route."""
    policy = route_policy(logical_engine, measurement_mode)
    return {
        "reasoning_effort": policy.reasoning_effort,
        "reasoning_pinnable": policy.reasoning_pinnable,
        "representative_status": policy.representative_status,
        "batch_enabled": policy.batch_enabled,
    }


def _validate_trigger(trigger: str) -> str:
    """Fail closed on a trigger outside the config-owned vocabulary."""
    normalized = str(trigger).strip().lower()
    if normalized not in AUDIT_TRIGGERS:
        raise AuditValidationError(f"Unsupported trigger: {trigger}")
    return normalized


def _freeze_plan(
    *,
    project: Project,
    prompts: list[Prompt],
    routes: dict[str, _ResolvedRoute],
    trigger: str,
    benchmark_mode: str | None,
    measurement_mode: str | None,
    repetitions: int | None,
) -> _FrozenPlan:
    """Precompute every policy decision for a run, before any row is written.

    Resolves both mode axes, validates prompt length, resolves repetitions from
    the frozen mode policy, composes the system instruction, and snapshots the
    per-route execution policy.
    """
    framing_mode = _resolve_benchmark_mode(benchmark_mode, project)
    mode, policy = _resolve_measurement_policy(measurement_mode)
    _validate_prompt_lengths(prompts)
    framing = system_instruction_for_mode(
        mode=framing_mode,
        country_code=project.country_code,
        language_code=project.language_code,
    )
    return _FrozenPlan(
        trigger=_validate_trigger(trigger),
        benchmark_mode=framing_mode,
        measurement_mode=mode,
        policy=policy,
        repetitions=_resolve_repetitions(repetitions, policy),
        system_instruction=_compose_system_instruction(framing=framing, policy=policy),
        route_policies={
            engine: _route_policy_snapshot(engine, mode)
            for engine, route in routes.items()
        },
    )


def _frozen_configuration(
    *,
    project: Project,
    plan: _FrozenPlan,
    routes: dict[str, _ResolvedRoute],
    prompt_rows: list[dict],
) -> dict:
    """Assemble the immutable ``Audit.configuration`` snapshot (invariant 9).

    ``engine_routes`` mirrors each ``AuditEngineSnapshot`` and additionally
    carries that route's frozen execution policy (the snapshot table itself has
    no policy column, so this mirror is the frozen home for it).
    """
    return {
        **project_scoring_identity(project),
        # Frozen product catalog (Agentic Commerce): the deterministic
        # product analyzer scores against this copy, so later catalog edits
        # never alter the audit (invariant 9).
        **project_product_identity(project),
        "trigger": plan.trigger,
        "benchmark_mode": plan.benchmark_mode,
        "measurement_mode": plan.measurement_mode,
        MEASUREMENT_POLICY_KEY: frozen_policy_configuration(plan.policy),
        "system_instruction": plan.system_instruction,
        "engines": list(routes.keys()),
        # Frozen shopping-surface gate (§7.1): ``[]`` while the gate is
        # disabled — no probe slots are generated and ``total`` is not
        # multiplied.
        "shopping_surfaces": list(SHOPPING_SURFACES),
        "repetitions": plan.repetitions,
        "max_attempts": audit_settings.max_attempts,
        "max_run_seconds": audit_settings.max_run_seconds,
        # The frozen per-call timeout is the MODE's, not the generic live
        # ``request_timeout_seconds``: an env change mid-run must never alter an
        # in-flight audit (invariant 9).
        "request_timeout_seconds": plan.policy.timeout_seconds,
        "engine_routes": {
            engine: {
                "logical_engine": engine,
                "transport_provider": route.transport_provider,
                "transport_model": route.transport_model,
                "connection_id": (
                    str(route.connection_id)
                    if route.connection_id is not None
                    else None
                ),
                **plan.route_policies[engine],
            }
            for engine, route in routes.items()
        },
        **_prompt_panel_snapshot(prompt_rows),
    }


def _task_route_snapshot(
    *,
    engine: str,
    route: _ResolvedRoute,
    plan: _FrozenPlan,
    credential: ResolvedCredential,
) -> dict:
    """Per-task frozen route + policy + credential snapshot (never a key).

    The credential block is the identity the worker LOADS at execution time
    (T11): the concrete connection and the funded reservation id (None for
    BYOK). It is frozen at admission and never re-resolved afterwards.
    """
    return {
        "logical_engine": engine,
        "transport_provider": route.transport_provider,
        "transport_model": route.transport_model,
        "credential_source": credential.credential_source,
        "connection_id": str(credential.connection_id),
        "reservation_id": (
            str(credential.reservation_id)
            if credential.reservation_id is not None
            else None
        ),
        "base_url": route.base_url,
        "measurement_mode": plan.measurement_mode,
        **plan.route_policies[engine],
        **frozen_policy_configuration(plan.policy),
    }


# ---------------------------------------------------------------------------
# Funded admission (slice23 Task 4 Part B)
# ---------------------------------------------------------------------------
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
        # The trailing surface segment is intentional: it reserves the
        # shopping-surface identity in the idempotency key (measurement is
        # the empty string, so shipped keys end in ":").
        idempotency_key = (
            f"{audit.id}:{prompt_index}:{repetition}:{engine}:"
            f"{SHOPPING_SURFACE_MEASUREMENT}"
        )
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
            shopping_surface=SHOPPING_SURFACE_MEASUREMENT,
            prompt_text=prompt_snapshot.text,
            idempotency_key=idempotency_key,
            max_attempts=audit_settings.max_attempts,
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
    random.Random(int(seed)).shuffle(slots)
    return slots


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
    measurement_mode: str | None = None,
    random_seed: str | None = None,
    schedule_id: uuid.UUID | None = None,
    scheduled_for: datetime | None = None,
) -> Audit:
    """Create + enqueue an audit (freeze snapshots, deterministic slot shuffle).

    Commits with all tasks ``queued`` so the worker can claim them.

    An orchestration SHELL: every policy decision (both mode axes, the frozen
    measurement policy, repetitions, the composed system instruction, the route
    policies) is precomputed by ``_freeze_plan`` and assembled by
    ``_frozen_configuration``; the rolling manual-run rate is EVALUATED by
    ``evaluate_manual_run_admission`` and only applied here; funded admission
    (entitlement resolution, the monthly budget gate, and per-task credit
    reservations before claimability) is owned by ``_admit_funded_run`` and
    ``_create_audit_tasks``. This shell adds no branching of its own.
    """
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
    normalized_measurement_mode, _ = _resolve_measurement_policy(measurement_mode)
    routes = await _resolve_run_routes(
        session,
        workspace_id=workspace_id,
        engines=engines,
        credential_mode=credential_mode,
        measurement_mode=normalized_measurement_mode,
    )

    plan = _freeze_plan(
        project=project,
        prompts=prompts,
        routes=routes,
        trigger=trigger,
        benchmark_mode=benchmark_mode,
        measurement_mode=measurement_mode,
        repetitions=repetitions,
    )
    # Per-engine expected costs from the sole cost owner: consumed by the
    # funded budget gate and re-proven by per-task credential resolution.
    expected_costs = _expected_costs_by_engine(routes=routes, plan=plan)
    # Prompt admission (topical binding over every selected active prompt +
    # the funded/trial prompt-count policy) is PRECOMPUTED by one extracted
    # helper; this shell only applies its decision and stays branch-free.
    _evaluate_prompt_admission(
        project=project,
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
        max_attempts=audit_settings.max_attempts,
        at=admission_at,
    )

    seed = _normalize_seed(random_seed)
    prompt_rows = _prompt_configuration_rows(prompts)
    configuration = _frozen_configuration(
        project=project, plan=plan, routes=routes, prompt_rows=prompt_rows
    )

    audit = Audit(
        workspace_id=workspace_id,
        project_id=project.id,
        schedule_id=schedule_id,
        scheduled_for=scheduled_for,
        status=AUDIT_STATUS_DRAFT,
        trigger=plan.trigger,
        benchmark_mode=plan.benchmark_mode,
        measurement_mode=plan.measurement_mode,
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


async def get_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> Audit:
    result = await session.execute(
        select(Audit)
        .options(
            selectinload(Audit.engine_snapshots),
            selectinload(Audit.shopping_surface_snapshots),
        )
        .where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
        )
    )
    audit = result.scalars().unique().one_or_none()
    if audit is None:
        raise AuditNotFoundError(str(audit_id))
    return audit


async def list_audits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
) -> list[Audit]:
    stmt = (
        select(Audit)
        .options(
            selectinload(Audit.engine_snapshots),
            selectinload(Audit.shopping_surface_snapshots),
        )
        .where(Audit.workspace_id == workspace_id)
        .order_by(Audit.created_at.desc())
        .limit(limit)
    )
    if project_id is not None:
        stmt = stmt.where(Audit.project_id == project_id)
    return list((await session.scalars(stmt)).unique().all())


async def list_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    audit_id: uuid.UUID,
    surface: str = SHOPPING_SURFACE_MEASUREMENT,
) -> list[AuditTask]:
    """List an audit's tasks for ONE shopping surface (default measurement)."""
    audit = await get_audit(session, workspace_id=workspace_id, audit_id=audit_id)
    stmt = (
        select(AuditTask)
        .where(
            AuditTask.audit_id == audit_id,
            AuditTask.shopping_surface == surface,
        )
        .order_by(AuditTask.randomized_position.asc())
    )
    tasks = list((await session.scalars(stmt)).all())
    _attach_transient_audit_provenance(tasks, audit)
    return tasks


def _attach_transient_audit_provenance(
    tasks: list[AuditTask],
    audit: Audit,
) -> None:
    """Attach the audit's mode/configuration to each task as duck attributes.

    The response schema reads these via ``getattr`` (schemas.py). They are
    copied from the already-loaded audit, never trigger relationship lazy
    loads, and exist only for the lifetime of the request — nothing else uses
    them, so they intentionally live off the typed ORM surface.
    """
    for task in tasks:
        row = cast(Any, task)  # widen so ruff+SIM prefer the direct form
        row.audit_measurement_mode = audit.measurement_mode
        row.audit_configuration = audit.configuration


async def _release_funded_on_cancel(
    session: AsyncSession,
    *,
    audit: Audit,
    cancelled_task_ids: set[uuid.UUID],
    at: datetime,
) -> None:
    """Release every cancelled funded task's unused reservation.

    A cancelled task is never claimed, so neither worker-side release path
    ever runs for it — without this the reservation leaks (indefinitely for
    grants with no ``valid_until``). Only the tasks THIS cancel terminalized
    are released: the bulk update's RETURNING set is exactly the rows that
    were still non-terminal once its row locks settled, so a task a worker
    already terminalized (and released) is never re-released. The audit
    configuration's frozen task-reservation map (invariant 9) carries every
    funded task's reservation id; BYOK tasks are absent from it.
    """
    task_reservations = (audit.configuration or {}).get("task_reservations") or {}
    for task_id in sorted(cancelled_task_ids, key=str):
        reservation = task_reservations.get(str(task_id))
        if reservation is None:
            continue
        await release_terminal_funded_task(
            session,
            reservation_id=uuid.UUID(str(reservation)),
            audit_id=audit.id,
            task_id=task_id,
            trigger="cancel",
            at=at,
        )


async def cancel_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> Audit:
    """Cooperatively cancel an active audit and terminalize open tasks.

    Flips the audit to ``cancelled`` (so a live worker stops at the next
    execution boundary) and marks any non-terminal task ``cancelled`` so counts
    and the UI stay consistent. This also cleans up a zombie audit whose worker
    died mid-run. Every funded task it terminalizes has its unused reservation
    released in the same transaction — a cancelled task is never claimed, so
    no worker-side release path would ever run for it.
    """
    # Lock the audit row FIRST: a worker's boundary terminalization (run
    # deadline / cooperative cancel) holds this same lock while it releases
    # the task's reservation, so this cancel either observes that committed
    # release (its own release then no-ops on the outstanding computation) or
    # commits first (the worker's boundary check then discards the task).
    # Either way exactly one release settles per reservation.
    await session.get(Audit, audit_id, with_for_update=True)
    audit = await get_audit(session, workspace_id=workspace_id, audit_id=audit_id)
    if audit.status not in AUDIT_ACTIVE_STATUSES:
        raise AuditValidationError("Only active audits can be cancelled")
    now = datetime.now(UTC)
    audit.completed_at = now
    # Route the flip through the state machine (invariant 9): AUDIT_ACTIVE_STATUSES
    # only contains statuses the machine allows to reach CANCELLED, so this never
    # raises here, but it keeps the single enforcement path and records the event.
    apply_transition(
        session,
        audit=audit,
        target=AUDIT_STATUS_CANCELLED,
        message="audit cancelled",
    )
    cancelled_task_ids = set(
        (
            await session.execute(
                update(AuditTask)
                .where(AuditTask.audit_id == audit.id)
                .where(AuditTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
                .values(
                    status=TASK_STATUS_CANCELLED,
                    lease_owner=None,
                    lease_expires_at=None,
                    completed_at=now,
                    error_code="cancelled",
                )
                .returning(AuditTask.id)
            )
        )
        .scalars()
        .all()
    )
    await _release_funded_on_cancel(
        session, audit=audit, cancelled_task_ids=cancelled_task_ids, at=now
    )
    record_event(
        session,
        audit_id=audit.id,
        event_type=EVENT_AUDIT_CANCELLED,
        message="audit cancelled",
        payload={"status": AUDIT_STATUS_CANCELLED},
    )
    await session.commit()
    # See the comment in ``create_audit``: refresh() would expire (and later
    # lazy-load) ``engine_snapshots``, which needs to stay eagerly loaded for
    # safe serialization outside the async greenlet.
    return await get_audit(session, workspace_id=workspace_id, audit_id=audit.id)
