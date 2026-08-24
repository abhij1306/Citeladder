# Audit lifecycle + queue + execution guardrail configuration (invariant 1).
#
# Owns every tunable knob for the B5 audit-execution subsystem: the audit
# lifecycle statuses + the queue/task statuses, the deterministic system
# prompt-framing instructions, and the provider-agnostic execution
# guardrails (pacing, per-call ceiling, retry budget, run deadline, lease TTL,
# heartbeat interval). Orchestration, the planner, and the worker READ these;
# they never hard-code the literals inline. Adapted from the reference
# ``config/ai_visibility.py`` guardrail knobs.
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, Final, TypeGuard

from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    # Type-only: config never imports a model at runtime (circular import).
    from app.models.audit import AuditTask

from app.core.config.projects import (
    BENCHMARK_MODE_CONSUMER_LIKE,
    BENCHMARK_MODE_CONTROLLED_LOCALIZED,
)
from app.core.config.task_queue import (
    ERROR_MAX_ATTEMPTS,
    PostgresQueueSpec,
)

# --- Audit lifecycle statuses --------------------------------------------
# The state machine (``app/orchestration/audit_state.py``) enforces the legal
# transitions between these.
AUDIT_STATUS_DRAFT: Final = "draft"
AUDIT_STATUS_VALIDATING: Final = "validating"
AUDIT_STATUS_QUEUED: Final = "queued"
AUDIT_STATUS_RUNNING: Final = "running"
AUDIT_STATUS_ANALYZING: Final = "analyzing"
AUDIT_STATUS_REPORTING: Final = "reporting"
AUDIT_STATUS_COMPLETED: Final = "completed"
AUDIT_STATUS_PARTIALLY_COMPLETED: Final = "partially_completed"
AUDIT_STATUS_FAILED: Final = "failed"
AUDIT_STATUS_CANCELLED: Final = "cancelled"

AUDIT_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        AUDIT_STATUS_COMPLETED,
        AUDIT_STATUS_PARTIALLY_COMPLETED,
        AUDIT_STATUS_FAILED,
        AUDIT_STATUS_CANCELLED,
    }
)
# Statuses at which a cooperative cancel is still meaningful (a live worker can
# stop at its boundary). ``reporting`` is intentionally excluded: by then
# execution + analysis are done and the state machine treats REPORTING ->
# CANCELLED as illegal (there is no live worker left to stop cooperatively).
AUDIT_ACTIVE_STATUSES: Final[frozenset[str]] = frozenset(
    {
        AUDIT_STATUS_DRAFT,
        AUDIT_STATUS_VALIDATING,
        AUDIT_STATUS_QUEUED,
        AUDIT_STATUS_RUNNING,
        AUDIT_STATUS_ANALYZING,
    }
)

# --- Audit triggers -------------------------------------------------------
# What initiated a run (closed vocabulary; ``Audit.trigger`` is String(16)).
# PR1 produces only ``manual`` (API) and ``system`` (dev seed) runs; a later
# schedule/trial caller passes its own token. The manual-run rolling rate
# (``manual_runs_per_day``) counts ONLY ``manual`` rows.
AUDIT_TRIGGER_MANUAL: Final = "manual"
AUDIT_TRIGGER_TRIAL: Final = "trial"
AUDIT_TRIGGER_SCHEDULED: Final = "scheduled"
AUDIT_TRIGGER_SYSTEM: Final = "system"
AUDIT_TRIGGER_REPAIR: Final = "repair"
AUDIT_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        AUDIT_TRIGGER_MANUAL,
        AUDIT_TRIGGER_TRIAL,
        AUDIT_TRIGGER_SCHEDULED,
        AUDIT_TRIGGER_SYSTEM,
        AUDIT_TRIGGER_REPAIR,
    }
)

# Pre-claim queue status for funded tasks (slice23 Task 4 Part B): the planner
# writes each funded task in this NON-claimable state, reserves its credits in
# the same transaction, and only then flips it to ``TASK_STATUS_QUEUED``, so a
# worker can never claim an unreserved funded task. Never a member of
# ``TASK_CLAIMABLE_STATUSES``.
TASK_STATUS_PENDING_RESERVATION: Final = "pending_reservation"

# Audit ownership scope. Brand and Commerce share the execution machinery but
# never share visibility projections.
AUDIT_SCOPE_BRAND: Final = "brand"
AUDIT_SCOPE_COMMERCE: Final = "commerce"
AUDIT_SCOPES: Final[frozenset[str]] = frozenset(
    {AUDIT_SCOPE_BRAND, AUDIT_SCOPE_COMMERCE}
)

# Grounded answers need enough room for useful citations, but
# visibility measurement does not benefit from essay-length responses. This
# neutral instruction applies to every active transport through the frozen
# request policy and never includes tracked brand or competitor identity.
AUDIT_ANSWER_INSTRUCTION: Final = (
    "Answer the question directly in 150 to 250 words. "
    "Use concise paragraphs or bullets, avoid repetition, and include citations "
    "to the most relevant sources when web search is available."
)


@dataclass(frozen=True, slots=True)
class AuditExecutionPolicy:
    """Frozen retrieval-enabled route/output policy for an audit."""

    retrieval_enabled: bool
    max_output_tokens: int
    timeout_seconds: float
    repetitions: int
    answer_instruction: str
    max_attempts: int


# --- Task (queue row) statuses -------------------------------------------
# Owned by ``config/task_queue.py`` and re-exported at the top of this module
# (``TASK_STATUS_*`` / ``TASK_TERMINAL_STATUSES`` / ``TASK_CLAIMABLE_STATUSES``
# / ``TASK_LEASED_STATUSES``) so audit callers import them from here unchanged.

# --- Attempt outcomes ----------------------------------------------------
ATTEMPT_STATUS_SUCCEEDED: Final = "succeeded"
ATTEMPT_STATUS_FAILED: Final = "failed"

# --- Audit lifecycle event types (SSE source) ----------------------------
EVENT_AUDIT_CREATED: Final = "audit.created"
EVENT_AUDIT_QUEUED: Final = "audit.queued"
EVENT_AUDIT_RUNNING: Final = "audit.running"
EVENT_AUDIT_STATUS: Final = "audit.status"
EVENT_TASK_SUCCEEDED: Final = "task.succeeded"
EVENT_TASK_FAILED: Final = "task.failed"
EVENT_TASK_RETRY: Final = "task.retry"
EVENT_AUDIT_CANCELLED: Final = "audit.cancelled"
EVENT_AUDIT_COMPLETED: Final = "audit.completed"
# Task parked on a provider-capacity decision (T4); payload carries only the
# opaque task id + retry timing (never credentials/prompts/provider bodies).
EVENT_TASK_CAPACITY_WAIT: Final = "task.capacity_wait"

# --- Provider capacity vocabulary (T4) --------------------------------------
# One owner for the pool/lease/credential vocabulary persisted on
# ``ProviderCapacityBucket`` / ``ProviderCapacityLease`` and passed through the
# ``app.orchestration.provider_capacity`` contracts (invariant 2 — never
# re-literal these strings).
#
# Pool kinds (``ProviderCapacityBucket.pool_kind``, String(16)):
POOL_KIND_TRANSPORT: Final = "transport"
POOL_KIND_CONNECTION: Final = "connection"
POOL_KIND_FUNDED_GLOBAL: Final = "funded_global"
POOL_KIND_FUNDED_ACCOUNT: Final = "funded_account"
POOL_KINDS: Final[frozenset[str]] = frozenset(
    {
        POOL_KIND_TRANSPORT,
        POOL_KIND_CONNECTION,
        POOL_KIND_FUNDED_GLOBAL,
        POOL_KIND_FUNDED_ACCOUNT,
    }
)
# Lease kinds (``ProviderCapacityLease.lease_kind``, String(16)). Concurrency
# leases are returned on release; token starts are consumed from the bucket's
# token balance at acquire time and are NEVER returned, so they are not leases.
LEASE_KIND_CONCURRENCY: Final = "concurrency"
# Which credential a task's provider call will use. BYOK acquires the
# transport + connection pools only; platform-funded acquires the transport +
# funded-global + funded-account pools.
CREDENTIAL_KIND_BYOK: Final = "byok"
CREDENTIAL_KIND_FUNDED: Final = "funded"
CREDENTIAL_KINDS: Final[frozenset[str]] = frozenset(
    {CREDENTIAL_KIND_BYOK, CREDENTIAL_KIND_FUNDED}
)
# Safe decision codes (``CapacityDecision.code``). Opaque tokens only — they
# never embed provider error bodies.
CAPACITY_CODE_CONCURRENCY: Final = "capacity_concurrency"
CAPACITY_CODE_RATE_LIMITED: Final = "capacity_rate_limited"
CAPACITY_CODE_UNCONFIGURED: Final = "capacity_unconfigured"
# Release outcomes (``CapacityOutcome.kind``).
CAPACITY_OUTCOME_SUCCEEDED: Final = "succeeded"
CAPACITY_OUTCOME_FAILED: Final = "failed"
CAPACITY_OUTCOME_RATE_LIMITED: Final = "rate_limited"
# Stamped on every bucket row; a config/knob change re-syncs a locked bucket
# to the live policy at acquire time instead of drifting silently.
CAPACITY_POLICY_VERSION: Final = "v8-t4-1"
# Telemetry event names (structured log events, funded-ledger pattern).
# Payloads carry ONLY pool kind, transport, opaque task/account ids, and retry
# timing — never credentials, prompts, or provider bodies (invariant 6).
TELEMETRY_CAPACITY_WAIT: Final = "audit.capacity.wait"
TELEMETRY_CAPACITY_RATE_LIMITED: Final = "audit.capacity.rate_limited"

# --- Error tokens specific to the run lifecycle ---------------------------
# Provider-call error tokens live in ``provider_catalog`` (reused by the
# worker); these two are orchestration-level (no provider call involved).
ERROR_RUN_DEADLINE: Final = "run_deadline_exceeded"
ERROR_CANCELLED: Final = "cancelled"
# Prompt-count admission codes for the FUNDED/TRIAL paths (the
# ``audit_prompt_count`` knob above; mapped at the API layer).
CODE_PROMPT_COUNT_POLICY_UNCONFIGURED: Final = "prompt_count_policy_unconfigured"
CODE_PROMPT_COUNT_EXCEEDED: Final = "prompt_count_exceeded"
# ``ERROR_MAX_ATTEMPTS`` is queue-neutral (re-exported from task_queue above).
ERROR_NO_CONNECTION: Final = "provider_connection_missing"

# --- Deterministic system instructions per benchmark mode -----------------
# Consumer-like sends no hidden instruction; the localized + forced-grounded
# modes prepend a neutral, brand-free instruction (invariant 6 — the brand list
# is never transmitted). Ported from the reference ``config/ai_visibility.py``.
LOCALIZED_INSTRUCTION: Final = (
    "Answer for a shopper in the market identified by ISO country code "
    "{country_code}, using language {language_code}. Prioritize retailers that "
    "serve that market and sources relevant to that market."
)
FORCED_GROUNDED_INSTRUCTION: Final = (
    "Answer the shopping question using current web information. "
    "Cite the sources supporting your recommendations."
)


def system_instruction_for_mode(
    *, mode: str, country_code: str, language_code: str
) -> str:
    """Resolve the neutral system instruction frozen onto an audit.

    Never contains any brand/competitor identity (invariant 6).
    """
    if mode == BENCHMARK_MODE_CONSUMER_LIKE:
        return ""
    localized = LOCALIZED_INSTRUCTION.format(
        country_code=(country_code or "unspecified"),
        language_code=(language_code or "unspecified"),
    )
    if mode == BENCHMARK_MODE_CONTROLLED_LOCALIZED:
        return localized
    # forced_grounded: localized + explicit grounding directive.
    return f"{localized} {FORCED_GROUNDED_INSTRUCTION}"


class AuditSettings(BaseSettings):
    """Provider-agnostic audit execution guardrails (env-overridable).

    One set of knobs bounds every audit so a stray or throttled run cannot run
    away in tokens, time, or duration regardless of provider.
    """

    model_config = SettingsConfigDict(env_prefix="AUDIT_", extra="ignore")

    # Hard cap on slots (prompts x engines x repetitions) an audit may create.
    max_tasks_per_audit: int = 500
    # Up to N tasks a single worker keeps IN FLIGHT at once (the pipelined pump
    # refills a slot the moment its task lands — see AuditWorker.run_pipelined).
    #
    # Sized for the free-tier run shape: 10 prompts x 3 providers = 30 calls at
    # ~29s average, so 10 in flight puts a run at roughly 90s instead of the
    # ~4 minutes a concurrency of 4 gave. Paired with DB_POOL_SIZE/
    # DB_MAX_OVERFLOW (peak demand is ~2 sessions per in-flight task; the
    # startup assertion ``assert_worker_pool_capacity`` RAISES if the pool
    # cannot cover it).
    #
    # CEILING IS THE PROVIDER, NOT THIS NUMBER. Grounded answers carry the web
    # search results back in as input: measured Claude calls averaged ~16k INPUT
    # tokens each, so 10 concurrent Claude calls burst ~160k input-tokens/min and
    # will 429 on a low Anthropic tier. Raise this only as far as the account's
    # input-tokens-per-minute allowance permits, and use
    # ``min_request_interval_seconds`` to spread starts per transport.
    #
    # The worker logs this exposure at startup
    # (``_warn_if_provider_pacing_unbounded``) whenever concurrency is > 1 with
    # pacing off, so the risk is visible in the logs rather than only here.
    worker_concurrency: int = 10

    # --- Provider capacity pools (T4) ---------------------------------------
    # Frozen defaults; each is ``measurement_required`` in the gate record —
    # they bound burst shape, not provider-verified rates, until live-key
    # measurement establishes real tier ceilings. The route-owned token-bucket
    # knobs (capacity / refill rate / max cooldown) live with the route policy
    # in ``config/provider_catalog.py`` (route identity is
    # ``(logical_engine, transport_provider)``).
    #
    # In-flight ceiling for ONE workspace credential (BYOK key) on a transport
    # AND for the shared per-transport pool: one credential may not exceed the
    # transport's own concurrency envelope.
    per_transport_concurrency: int = 4
    # Total platform-funded calls in flight per transport across ALL accounts.
    funded_pool_max_concurrency: int = 12
    # Per-account slice of the funded pool, so one account's audits cannot
    # starve a sibling account (funded fairness).
    funded_pool_per_account: int = 6
    # Peak DB sessions one in-flight task can check out at once (task session +
    # heartbeat/finalize overlap). Feeds the startup pool assertion.
    worker_db_sessions_per_task: int = 2
    # Sessions reserved for non-task work in the worker process (sweeper,
    # claim, audit-state transitions) so the pool assertion leaves room for
    # them: db_pool_size + db_max_overflow must be >=
    # worker_max_inflight * worker_db_sessions_per_task + operational_headroom.
    operational_headroom: int = 4
    # Capacity-lease TTL: a crash orphans a lease, and capacity is recovered
    # only once it expires, so this must outlive the longest single provider
    # call (the benchmark timeout) plus margin.
    capacity_lease_ttl_seconds: float = 240.0
    # Retry timing parked on a task when every relevant pool is at its
    # concurrency ceiling (no provider guidance exists for this case).
    capacity_concurrency_retry_seconds: float = 2.0

    @property
    def worker_max_inflight(self) -> int:
        """Canonical T4 name for the worker's in-flight task ceiling.

        Folded onto the pre-existing ``worker_concurrency`` field (one knob,
        one owner — invariant 2): the field keeps its env var and every
        existing reader/monkeypatch; new capacity code reads this name.
        """
        return self.worker_concurrency

    # How long the loop sleeps when the queue is empty before polling again. Also
    # gates the expired-lease sweep (``AuditWorker._sweep_expired_leases``) so
    # the pool's slots share one sweep per interval instead of one each.
    poll_interval_seconds: float = 1.0
    # Minimum spacing between provider request starts, per transport, to respect
    # rate limits (mainly Gemini's low per-minute quota).
    #
    # Left at 0 ON PURPOSE. Spacing every start would serialize the pipelined
    # pump's ramp-up and undo the throughput it exists for, and the right
    # interval depends entirely on the operator's provider tier — there is no
    # default that is correct for both a tier-1 and a tier-4 account. Deployments
    # that need pacing set AUDIT_MIN_REQUEST_INTERVAL_SECONDS; the startup
    # warning above makes the unpaced default explicit rather than silent.
    min_request_interval_seconds: float = 0.0
    # Per-run wall-clock deadline. Once exceeded, remaining tasks stop at their
    # boundary and terminalize, so a run can never sit live forever. Frozen
    # onto the audit at creation and read back through
    # ``max_run_seconds_from_configuration`` (invariant 9).
    max_run_seconds: float = 1800.0
    # Retry budget for a single task (attempt_count is bounded by max_attempts).
    max_attempts: int = 5
    retry_base_delay_seconds: float = 2.0
    retry_max_delay_seconds: float = 45.0
    retry_jitter_seconds: float = 1.5
    # Lease TTL: a claimed task's lease expires after this many seconds unless
    # the worker heartbeats to extend it.
    lease_ttl_seconds: float = 120.0
    # Worker heartbeats at this cadence while a task runs.
    heartbeat_interval_seconds: float = 30.0
    # HTTP client timeout for a single provider call (passed to the adapter).
    request_timeout_seconds: float = 60.0

    # --- Retrieval-enabled route/output policy (invariant 1) -------------
    audit_max_output_tokens: int = 800
    audit_timeout_seconds: float = 60.0
    audit_repetitions: int = 3
    # Days of history folded into a trend series by the reporting projection.
    trend_smoothing_days: int = 7
    # Hard ceiling on a single frozen prompt's length (validated by the planner).
    max_prompt_chars: int = 300
    # Max number of selected active prompts one audit may run on the FUNDED
    # and TRIAL paths. UNSET (None) ON PURPOSE: those paths fail closed with
    # ``prompt_count_policy_unconfigured`` rather than inventing a count.
    # BYOK runs stay governed by their existing product limits and never read
    # this knob.
    audit_prompt_count: int | None = None

    # --- SSE audit-event stream (GET /audits/{id}/events?stream=true) -------
    # Poll cadence of the stream loop, and the idle cutoff after which it
    # stops streaming a terminal audit so the connection cannot hang forever.
    # The API layer READS these; it never hard-codes them (invariant 1).
    sse_poll_seconds: float = 1.0
    sse_terminal_grace_polls: int = 2
    # Bounds ONE event page (the JSON replay and each stream poll). A resuming
    # client carries the last id it rendered, so a capped page is a page —
    # never a silently truncated history. Mirrors the Site Health cap.
    max_event_page: int = 1_000

    def retry_delay(
        self, attempt: int, retry_after_seconds: float | None = None
    ) -> float:
        """Seconds to wait before the next attempt.

        Prefers a provider-advised ``Retry-After`` (clamped to the cap); else
        exponential backoff ``base * 2**attempt`` capped at the max, plus a
        small deterministic jitter (derived from ``attempt``, not RNG, so it
        stays reproducible).
        """
        cap = self.retry_max_delay_seconds
        if retry_after_seconds is not None:
            return min(retry_after_seconds, cap)
        base = self.retry_base_delay_seconds * (2**attempt)
        jitter = (attempt * 0.37) % 1.0 * self.retry_jitter_seconds
        return min(base, cap) + jitter


audit_settings = AuditSettings()


def audit_execution_policy() -> AuditExecutionPolicy:
    """Resolve the live audit policy before the planner freezes it."""
    return AuditExecutionPolicy(
        retrieval_enabled=True,
        max_output_tokens=audit_settings.audit_max_output_tokens,
        timeout_seconds=audit_settings.audit_timeout_seconds,
        repetitions=audit_settings.audit_repetitions,
        answer_instruction=AUDIT_ANSWER_INSTRUCTION,
        max_attempts=audit_settings.max_attempts,
    )


# Key of the frozen measurement-policy block inside ``Audit.configuration``.
# One owner for the spelling: the planner writes it through
# ``frozen_policy_configuration`` and the worker reads it back through
# ``measurement_policy_from_configuration`` (invariant 2).
MEASUREMENT_POLICY_KEY: Final = "measurement_policy"


def frozen_policy_configuration(policy: AuditExecutionPolicy) -> dict:
    """Serialize a resolved policy for ``Audit.configuration`` (invariant 9).

    This is the FROZEN copy the worker executes from; nothing re-reads the live
    settings once it is written.
    """
    return {
        "retrieval_enabled": policy.retrieval_enabled,
        "max_output_tokens": policy.max_output_tokens,
        "timeout_seconds": policy.timeout_seconds,
        "repetitions": policy.repetitions,
        "answer_instruction": policy.answer_instruction,
        "max_attempts": policy.max_attempts,
    }


def max_run_seconds_from_configuration(configuration: dict | None) -> float:
    """Read the FROZEN per-run deadline out of an audit's ``configuration``.

    The planner freezes ``max_run_seconds`` at creation (invariant 9: an env
    change mid-run must never alter an in-flight audit), and the worker's
    deadline check reads ONLY this copy. Rows planned before the freeze carry
    no key; for those (and only those) the live setting is the closest
    available approximation.
    """
    frozen = (configuration or {}).get("max_run_seconds")
    if frozen is None:
        return audit_settings.max_run_seconds
    return float(frozen)


def _is_frozen_policy(value: object) -> TypeGuard[dict[str, Any]]:
    """Whether ``value`` is a fully-shaped frozen measurement policy dict."""
    if not isinstance(value, dict):
        return False
    required = {
        "retrieval_enabled",
        "max_output_tokens",
        "timeout_seconds",
        "repetitions",
        "answer_instruction",
        "max_attempts",
    }
    if not required.issubset(value):
        return False
    return (
        isinstance(value["retrieval_enabled"], bool)
        and _is_positive_int(value["max_output_tokens"])
        and _is_finite_positive_number(value["timeout_seconds"])
        and _is_positive_int(value["repetitions"])
        and isinstance(value["answer_instruction"], str)
        and _is_positive_int(value["max_attempts"])
    )


def _is_positive_int(value: object) -> bool:
    """A REAL positive int.

    ``bool`` is an ``int`` subclass, so ``True`` would otherwise validate as a
    count of one out of a poisoned frozen blob.
    """
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_finite_positive_number(value: object) -> bool:
    """Whether ``value`` is a finite positive int/float.

    An arbitrary-precision int larger than ~128 bits raises ``OverflowError``
    when converted to float by ``isfinite``; treat that as NOT finite so the
    caller falls back to the mode default rather than crashing on a poisoned
    frozen blob read back out of the DB.
    """
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return isfinite(value) and value > 0
    except OverflowError:
        return False


def measurement_policy_from_configuration(
    configuration: dict,
) -> AuditExecutionPolicy:
    """Read the frozen policy back out of an audit's ``configuration``.

    Audits planned before policy freezing use the current citation-capable
    policy. New audits always execute exactly what the planner froze.
    """
    if MEASUREMENT_POLICY_KEY not in configuration:
        return audit_execution_policy()
    frozen = configuration[MEASUREMENT_POLICY_KEY]
    if not _is_frozen_policy(frozen):
        raise ValueError("invalid frozen measurement policy")
    return AuditExecutionPolicy(
        retrieval_enabled=bool(frozen["retrieval_enabled"]),
        max_output_tokens=int(frozen["max_output_tokens"]),
        timeout_seconds=float(frozen["timeout_seconds"]),
        repetitions=int(frozen["repetitions"]),
        answer_instruction=str(frozen["answer_instruction"]),
        max_attempts=int(frozen["max_attempts"]),
    )


def _audit_model() -> type[AuditTask]:
    # Imported lazily so this config module never imports a model at import
    # time (would create a config <-> models circular import).
    from app.models.audit import AuditTask

    return AuditTask


def _audit_claim_order(model: type[AuditTask]) -> tuple:
    # Deterministic claim order: priority, then FIFO by availability, then the
    # frozen randomized slot position. Preserves the exact original audit
    # ordering (see the pre-genericization ``PostgresTaskQueue.claim``).
    return (
        model.priority.desc(),
        model.available_at.asc(),
        model.randomized_position.asc(),
    )


# The audit queue spec: parameterizes the generic ``PostgresTaskQueue`` over
# ``AuditTask`` with the audit lease TTL + claim order, preserving current
# audit queue semantics exactly.
AUDIT_QUEUE_SPEC: Final[PostgresQueueSpec[AuditTask]] = PostgresQueueSpec(
    model_ref=_audit_model,
    lease_ttl=lambda: audit_settings.lease_ttl_seconds,
    claim_order=_audit_claim_order,
    max_attempts_error=ERROR_MAX_ATTEMPTS,
)
