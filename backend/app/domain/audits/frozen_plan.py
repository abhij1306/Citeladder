"""Deterministic audit policy and provenance freezing."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config.audits import (
    AUDIT_TRIGGER_TRIAL,
    AUDIT_TRIGGERS,
    CODE_PROMPT_COUNT_EXCEEDED,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
    MEASUREMENT_POLICY_KEY,
    AuditExecutionPolicy,
    audit_execution_policy,
    audit_settings,
    frozen_policy_configuration,
    system_instruction_for_mode,
)
from app.core.config.entitlements import CREDENTIAL_MODE_FUNDED
from app.core.config.projects import (
    BENCHMARK_MODES,
    DEFAULT_BENCHMARK_MODE,
    MAX_REPETITIONS,
    MIN_REPETITIONS,
)
from app.core.config.provider_catalog import route_policy
from app.domain.audits.errors import AuditValidationError, PromptCountPolicyError
from app.domain.audits.resolution import _prompt_panel_snapshot, _ResolvedRoute
from app.domain.products.shim import project_product_identity
from app.domain.projects.shim import project_scoring_identity
from app.domain.providers.credentials import ResolvedCredential
from app.models.project import Project
from app.models.prompt import Prompt


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
    policy: AuditExecutionPolicy
    repetitions: int
    system_instruction: str
    route_policies: dict[str, dict]
    audit_scope: str


def _compose_system_instruction(*, framing: str, policy: AuditExecutionPolicy) -> str:
    """Compose neutral prompt framing with the citation answer instruction."""
    return " ".join(part for part in (framing, policy.answer_instruction) if part)


def _resolve_repetitions(requested: int | None, policy: AuditExecutionPolicy) -> int:
    """Repetitions for the run: an explicit request, else the audit default."""
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


def _evaluate_prompt_count_admission(
    *,
    prompts: list[Prompt],
    trigger: str,
    credential_mode: str,
) -> None:
    """Precompute selected-prompt count admission.

    Prompt relevance is enforced when text enters the active portfolio: manual
    creates/edits use topical binding and backend-generated prompts use signed
    generation receipts. Re-running the lossy lexical check here would reject
    already-admitted neutral synonyms and make persisted prompts unmeasurable.
    """
    _enforce_prompt_count_policy(
        prompts, trigger=trigger, credential_mode=credential_mode
    )


def _route_policy_snapshot(logical_engine: str) -> dict:
    """The frozen execution-time route policy for one approved route."""
    policy = route_policy(logical_engine)
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
    repetitions: int | None,
    audit_scope: str,
) -> _FrozenPlan:
    """Precompute every policy decision for a run, before any row is written.

    Resolves prompt framing, validates prompt length, resolves repetitions from
    the frozen audit policy, composes the system instruction, and snapshots the
    per-route execution policy.
    """
    framing_mode = _resolve_benchmark_mode(benchmark_mode, project)
    policy = audit_execution_policy()
    _validate_prompt_lengths(prompts)
    framing = system_instruction_for_mode(
        mode=framing_mode,
        country_code=project.country_code,
        language_code=project.language_code,
    )
    return _FrozenPlan(
        trigger=_validate_trigger(trigger),
        benchmark_mode=framing_mode,
        policy=policy,
        repetitions=_resolve_repetitions(repetitions, policy),
        system_instruction=_compose_system_instruction(framing=framing, policy=policy),
        route_policies={
            engine: _route_policy_snapshot(engine) for engine, route in routes.items()
        },
        audit_scope=audit_scope,
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
        **(
            project_product_identity(project)
            if plan.audit_scope == "commerce"
            else {"products": []}
        ),
        "audit_scope": plan.audit_scope,
        "trigger": plan.trigger,
        "benchmark_mode": plan.benchmark_mode,
        MEASUREMENT_POLICY_KEY: frozen_policy_configuration(plan.policy),
        "system_instruction": plan.system_instruction,
        "engines": list(routes.keys()),
        "repetitions": plan.repetitions,
        "max_attempts": plan.policy.max_attempts,
        "max_run_seconds": audit_settings.max_run_seconds,
        # The frozen per-call timeout is the audit policy's, not the generic live
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
        **plan.route_policies[engine],
        **frozen_policy_configuration(plan.policy),
    }


# ---------------------------------------------------------------------------
# Funded admission (slice23 Task 4 Part B)
# ---------------------------------------------------------------------------
