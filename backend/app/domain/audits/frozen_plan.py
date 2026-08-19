"""Deterministic audit policy and provenance freezing."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config.audits import (
    AUDIT_TRIGGER_TRIAL,
    AUDIT_TRIGGERS,
    CODE_PROMPT_COUNT_EXCEEDED,
    CODE_PROMPT_COUNT_POLICY_UNCONFIGURED,
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_POLICY_KEY,
    MeasurementModePolicy,
    audit_settings,
    frozen_policy_configuration,
    measurement_policy_for_mode,
    system_instruction_for_mode,
)
from app.core.config.commerce import SHOPPING_SURFACES
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
