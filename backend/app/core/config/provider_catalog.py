# BYOK provider catalog + answer-engine guardrails (invariant 1: config lives
# in core/config, never inline in service/adapter code).
#
# Owns the approved (logical-engine, measurement-mode) route catalog, the
# transport/engine enumerations, and the provider-agnostic guardrail knobs
# (token caps, timeouts, endpoint URLs, retry classification tokens). Adapters,
# services, and routers READ these values; they never hard-code them.
#
# ChatGPT is executable through the direct OpenAI Responses API (transport
# ``openai``). Active transports are exactly ``openai | anthropic | google`` and
# each logical engine has one Pulse route and one Benchmark route.
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    KEY_PROVIDER_COPILOT,
    KEY_PROVIDER_GROK,
    KEY_PROVIDER_PERPLEXITY,
)

# --- Logical engines (what the user asked for) ----------------------------
ENGINE_CHATGPT: Final = "chatgpt"
ENGINE_GEMINI: Final = "gemini"
ENGINE_CLAUDE: Final = "claude"
LOGICAL_ENGINES: Final[tuple[str, str, str]] = (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
)

# --- Transport providers (how we physically reach the engine) -------------
TRANSPORT_OPENAI: Final = "openai"
TRANSPORT_ANTHROPIC: Final = "anthropic"
TRANSPORT_GOOGLE: Final = "google"
# Transports a NEW BYOK ``ProviderConnection`` may declare (active surface).
ACTIVE_TRANSPORTS: Final[frozenset[str]] = frozenset(
    {TRANSPORT_OPENAI, TRANSPORT_ANTHROPIC, TRANSPORT_GOOGLE}
)

# --- Measurement routes ---------------------------------------------------
MEASUREMENT_MODE_PULSE: Final = "pulse"
MEASUREMENT_MODE_BENCHMARK: Final = "benchmark"
MEASUREMENT_MODES: Final[tuple[str, str]] = (
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_MODE_BENCHMARK,
)

# Execution-time reasoning values used by exact measurement routes and adapters.
REASONING_EFFORT_OFF: Final = "off"
REASONING_EFFORT_MINIMAL: Final = "minimal"
REASONING_EFFORT_LOW: Final = "low"
REASONING_EFFORT_UNVERIFIED: Final = "unverified"

# Whether the pinned transport model is known to match the corresponding
# consumer product. Every active route remains unverified until evidence exists.
REPRESENTATIVE_STATUS_UNVERIFIED: Final = "unverified"
REPRESENTATIVE_STATUS_VERIFIED: Final = "verified"


@dataclass(frozen=True, slots=True, kw_only=True)
class MeasurementRoute:
    logical_engine: str
    measurement_mode: str
    transport_provider: str
    transport_model: str
    retrieval_enabled: bool
    reasoning_effort: str
    reasoning_pinnable: bool
    representative_status: str


# Exact model identity is frozen here. There is intentionally no provider
# alias, default-model fallback, or single-route compatibility view.
MEASUREMENT_ROUTES: Final[dict[tuple[str, str], MeasurementRoute]] = {
    (ENGINE_CHATGPT, MEASUREMENT_MODE_PULSE): MeasurementRoute(
        logical_engine=ENGINE_CHATGPT,
        measurement_mode=MEASUREMENT_MODE_PULSE,
        transport_provider=TRANSPORT_OPENAI,
        transport_model="gpt-5.4-nano-2026-03-17",
        retrieval_enabled=False,
        reasoning_effort=REASONING_EFFORT_OFF,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
    (ENGINE_CHATGPT, MEASUREMENT_MODE_BENCHMARK): MeasurementRoute(
        logical_engine=ENGINE_CHATGPT,
        measurement_mode=MEASUREMENT_MODE_BENCHMARK,
        transport_provider=TRANSPORT_OPENAI,
        transport_model="gpt-5.6-sol",
        retrieval_enabled=True,
        reasoning_effort=REASONING_EFFORT_OFF,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
    (ENGINE_CLAUDE, MEASUREMENT_MODE_PULSE): MeasurementRoute(
        logical_engine=ENGINE_CLAUDE,
        measurement_mode=MEASUREMENT_MODE_PULSE,
        transport_provider=TRANSPORT_ANTHROPIC,
        transport_model="claude-haiku-4-5-20251001",
        retrieval_enabled=False,
        reasoning_effort=REASONING_EFFORT_OFF,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
    (ENGINE_CLAUDE, MEASUREMENT_MODE_BENCHMARK): MeasurementRoute(
        logical_engine=ENGINE_CLAUDE,
        measurement_mode=MEASUREMENT_MODE_BENCHMARK,
        transport_provider=TRANSPORT_ANTHROPIC,
        transport_model="claude-sonnet-5",
        retrieval_enabled=True,
        reasoning_effort=REASONING_EFFORT_LOW,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
    (ENGINE_GEMINI, MEASUREMENT_MODE_PULSE): MeasurementRoute(
        logical_engine=ENGINE_GEMINI,
        measurement_mode=MEASUREMENT_MODE_PULSE,
        transport_provider=TRANSPORT_GOOGLE,
        transport_model="gemini-3.5-flash-lite",
        retrieval_enabled=False,
        reasoning_effort=REASONING_EFFORT_MINIMAL,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
    (ENGINE_GEMINI, MEASUREMENT_MODE_BENCHMARK): MeasurementRoute(
        logical_engine=ENGINE_GEMINI,
        measurement_mode=MEASUREMENT_MODE_BENCHMARK,
        transport_provider=TRANSPORT_GOOGLE,
        transport_model="gemini-3.6-flash",
        retrieval_enabled=True,
        reasoning_effort=REASONING_EFFORT_LOW,
        reasoning_pinnable=True,
        representative_status=REPRESENTATIVE_STATUS_UNVERIFIED,
    ),
}


def measurement_route(logical_engine: str, measurement_mode: str) -> MeasurementRoute:
    """Return one exact executable route; unknown identities fail closed."""
    route = MEASUREMENT_ROUTES.get((logical_engine, measurement_mode))
    if route is None:
        raise ValueError(
            f"no measurement route for ({logical_engine!r}, {measurement_mode!r})"
        )
    return route


def measurement_routes_for_engine(logical_engine: str) -> tuple[MeasurementRoute, ...]:
    return tuple(
        measurement_route(logical_engine, mode)
        for mode in MEASUREMENT_MODES
        if (logical_engine, mode) in MEASUREMENT_ROUTES
    )


# --- Execution-time route policy -----------------------------------------
# The approved route catalogue above is the sole owner of executable identity.
# This policy view is keyed by that same (engine, mode) identity; it is not a
# second catalogue, and no model id is repeated here. ``config/measurement.py``
# separately owns the offline SWEEP vocabulary; the values above are the
# execution-time pin states consumed by adapters.
#
# ``off``: reasoning/thinking is explicitly disabled on the request.
# ``unverified``: no supported low reasoning value has been established for the
# route (no fixture and no live evidence), so the route stays UNPINNED and its
# cost-sensitive funded variant is ineligible. Fails closed — never treated as
# "off".
@dataclass(frozen=True, slots=True)
class RoutePolicy:
    """Execution-time policy for one approved (engine, transport) route.

    ``reasoning_effort`` is the value the adapter pins (or the ``unverified``
    sentinel when nothing may be pinned yet); ``reasoning_pinnable`` says
    whether the route accepts an explicit reasoning control at all;
    ``representative_status`` records consumer-representativeness evidence for
    the pinned model; ``batch_enabled`` gates any batch/async submission path.
    No prompt-caching knob exists — CiteLadder requests never enable provider
    prompt caching.
    """

    reasoning_effort: str
    reasoning_pinnable: bool
    representative_status: str
    batch_enabled: bool


ROUTE_POLICIES: Final[dict[tuple[str, str], RoutePolicy]] = {
    key: RoutePolicy(
        reasoning_effort=route.reasoning_effort,
        reasoning_pinnable=route.reasoning_pinnable,
        representative_status=route.representative_status,
        batch_enabled=False,
    )
    for key, route in MEASUREMENT_ROUTES.items()
}


def route_policy(logical_engine: str, measurement_mode: str) -> RoutePolicy:
    """Execution-time policy for an approved route (fails closed).

    Raises ``ValueError`` for a route with no policy entry rather than assuming
    a permissive default: an unknown route must never silently execute with
    reasoning treated as off or batch treated as allowed.
    """
    policy = ROUTE_POLICIES.get((logical_engine, measurement_mode))
    if policy is None:
        raise ValueError(
            f"no route policy for ({logical_engine!r}, {measurement_mode!r}); "
            "approved routes must declare one"
        )
    return policy


# --- Route-owned token-bucket pacing (T4) ------------------------------------
# One entry per approved route (same keys as ``ROUTE_POLICIES``): the token
# bucket that paces provider CALL STARTS on the route's transport bucket. The
# rates are UNVERIFIED and therefore UNSET (``None``) ON PURPOSE: with no
# measured provider tier rates, funded acquisition fails CLOSED
# (``capacity_unconfigured``) and BYOK runs concurrency-only, until a live
# measurement configures real rates. ``max_cooldown_seconds`` is always set:
# it clamps any provider-advised ``Retry-After`` before the shared
# ``blocked_until`` cooldown is written, so an untrusted provider hint can
# never park a pool longer than this.
DEFAULT_ROUTE_MAX_COOLDOWN_SECONDS: Final = 60.0


@dataclass(frozen=True, slots=True)
class RouteCapacityPolicy:
    """Token-bucket pacing policy for one approved (engine, transport) route.

    ``capacity`` is the bucket's max tokens (burst size);
    ``refill_tokens_per_second`` is the sustained start rate. Both are
    ``None`` while the route's provider rates are unverified.
    """

    capacity: float | None
    refill_tokens_per_second: float | None
    max_cooldown_seconds: float


# Capacity remains transport-scoped because both measurement modes share a
# provider quota bucket. Rates stay unset until staging measurements exist.
ROUTE_CAPACITY_POLICIES: Final[dict[tuple[str, str], RouteCapacityPolicy]] = {
    (ENGINE_CLAUDE, TRANSPORT_ANTHROPIC): RouteCapacityPolicy(
        capacity=None,
        refill_tokens_per_second=None,
        max_cooldown_seconds=DEFAULT_ROUTE_MAX_COOLDOWN_SECONDS,
    ),
    (ENGINE_CHATGPT, TRANSPORT_OPENAI): RouteCapacityPolicy(
        capacity=None,
        refill_tokens_per_second=None,
        max_cooldown_seconds=DEFAULT_ROUTE_MAX_COOLDOWN_SECONDS,
    ),
    (ENGINE_GEMINI, TRANSPORT_GOOGLE): RouteCapacityPolicy(
        capacity=None,
        refill_tokens_per_second=None,
        max_cooldown_seconds=DEFAULT_ROUTE_MAX_COOLDOWN_SECONDS,
    ),
}


def route_capacity_policy(
    logical_engine: str, transport_provider: str
) -> RouteCapacityPolicy:
    """Token-bucket pacing policy for an approved route (fails closed).

    Raises ``ValueError`` for a route with no entry rather than pacing with an
    invented rate: an unconfigured approved route (``None`` rates) is a
    DELIBERATE fail-closed state; an UNKNOWN route is a bug.
    """
    policy = ROUTE_CAPACITY_POLICIES.get((logical_engine, transport_provider))
    if policy is None:
        raise ValueError(
            f"no route capacity policy for ({logical_engine!r}, "
            f"{transport_provider!r}); approved routes must declare one"
        )
    return policy


def is_reasoning_pinned_off(logical_engine: str, measurement_mode: str) -> bool:
    """True only when the route pins reasoning explicitly OFF."""
    policy = route_policy(logical_engine, measurement_mode)
    return policy.reasoning_pinnable and policy.reasoning_effort == REASONING_EFFORT_OFF


def is_route_approved(logical_engine: str, transport_provider: str) -> bool:
    """True when (engine, transport) is an approved active route."""
    return any(
        route.transport_provider == transport_provider
        for route in measurement_routes_for_engine(logical_engine)
    )


def is_approved_model(
    logical_engine: str, transport_provider: str, transport_model: str
) -> bool:
    """Validate an exact model against either shipped measurement mode."""
    return any(
        route.transport_provider == transport_provider
        and route.transport_model == transport_model
        for route in measurement_routes_for_engine(logical_engine)
    )


def is_active_transport(transport_provider: str) -> bool:
    """True when a transport may be used on an active (write/execute) path."""
    return transport_provider in ACTIVE_TRANSPORTS


def engines_for_transport(transport_provider: str) -> tuple[str, ...]:
    """Logical engines reachable through a transport, in catalog order."""
    return tuple(
        engine
        for engine in LOGICAL_ENGINES
        if any(
            route.transport_provider == transport_provider
            for route in measurement_routes_for_engine(engine)
        )
    )


def default_probe_engine(transport_provider: str) -> str:
    """A logical engine to use when probing a transport's connectivity.

    Picks the first engine the transport can serve so a connectivity test can
    build a concrete adapter/model without a caller-supplied route.
    """
    engines = engines_for_transport(transport_provider)
    return engines[0] if engines else ""


def configured_endpoint(transport_provider: str) -> str:
    """Return the sole operator-configured credential destination."""
    endpoint = {
        TRANSPORT_OPENAI: provider_catalog_settings.openai_responses_url,
        TRANSPORT_ANTHROPIC: provider_catalog_settings.anthropic_messages_url,
        TRANSPORT_GOOGLE: provider_catalog_settings.google_interactions_url,
    }.get(transport_provider, "")
    return endpoint.strip().rstrip("/")


def is_endpoint_approved(transport_provider: str, base_url: str) -> bool:
    """Allow provider defaults or the exact operator-configured endpoint only.

    A tenant-supplied URL must never choose where a stored BYOK credential is
    sent. Operators may still configure a gateway through deployment config.
    """
    approved = configured_endpoint(transport_provider)
    if not approved:
        return False
    supplied = base_url.strip().rstrip("/")
    return not supplied or supplied == approved


# --- Public provider catalog (display surface, NOT a write enum) ----------
# The public/commercial surface shows more providers than CiteLadder can
# execute: shipped BYOK engines plus explicitly COMING-SOON ones. This catalog
# is display-only. ``ACTIVE_TRANSPORTS`` stays OpenAI/Anthropic/Google only, so
# a create/test/audit routing path can never
# accept a coming-soon key just because it appears here.
PROVIDER_GROK: Final = "grok"
PROVIDER_PERPLEXITY: Final = "perplexity"
PROVIDER_COPILOT: Final = "copilot"

# Public availability vocabulary (single owner; the billing catalog reads it).
# Deliberately two-valued: workspace connection state is a separate,
# authenticated contract and never leaks into a public catalog row.
AVAILABILITY_AVAILABLE: Final = "available"
AVAILABILITY_UNAVAILABLE: Final = "unavailable"

# Safe, non-leaking reason for a coming-soon provider row.
REASON_PROVIDER_UNAVAILABLE: Final = "provider_unavailable"

# Safe reason for a shipped provider whose configured key has not (yet) been
# verified by a successful probe; the authenticated states route fails closed
# with it (an unprobed key is NEVER connected).
REASON_VERIFICATION_REQUIRED: Final = "verification_required"


def validate_availability(availability: str, reason: str | None) -> None:
    """Shared availability/reason consistency rule for any catalog row.

    An unavailable row needs a safe, non-leaking reason; an available row
    carries none. The commercial catalog (``config/billing_catalog.py``) reuses this so
    the two-token vocabulary has exactly one owner (invariant 2).
    """
    if availability == AVAILABILITY_AVAILABLE:
        if reason is not None:
            raise ValueError("an available catalog row carries no reason")
        return
    if availability != AVAILABILITY_UNAVAILABLE:
        raise ValueError(f"unsupported availability: {availability!r}")
    if not reason:
        raise ValueError("an unavailable catalog row needs a safe reason")


@dataclass(frozen=True, slots=True)
class ProviderCatalogEntry:
    """One provider row in the PUBLIC provider catalog.

    ``adapter_shipped`` says whether an execution adapter exists at all;
    ``grant_key`` is the DESCRIPTIVE capability identity for the row (it is not
    proof that anything may be granted); ``issuable`` is authoritative and is
    true only for a real, issuable entitlement-registry capability. Shipped
    BYOK engines are not grant-gated, so they are non-issuable too.
    """

    key: str
    label: str
    availability: str
    unavailable_reason: str | None
    adapter_shipped: bool
    grant_key: str
    issuable: bool

    def __post_init__(self) -> None:
        validate_availability(self.availability, self.unavailable_reason)
        if self.adapter_shipped != (self.availability == AVAILABILITY_AVAILABLE):
            raise ValueError(
                f"provider {self.key!r} availability disagrees with adapter_shipped"
            )
        definition = CAPABILITY_REGISTRY.get(self.grant_key)
        expected = definition is not None and definition.issuable
        if self.issuable and not expected:
            raise ValueError(
                f"provider {self.key!r} claims an issuable grant key it cannot have"
            )


PUBLIC_PROVIDER_CATALOG: Final[tuple[ProviderCatalogEntry, ...]] = (
    ProviderCatalogEntry(
        key=ENGINE_CHATGPT,
        label="ChatGPT",
        availability=AVAILABILITY_AVAILABLE,
        unavailable_reason=None,
        adapter_shipped=True,
        grant_key="provider.chatgpt",
        issuable=False,
    ),
    ProviderCatalogEntry(
        key=ENGINE_CLAUDE,
        label="Claude",
        availability=AVAILABILITY_AVAILABLE,
        unavailable_reason=None,
        adapter_shipped=True,
        grant_key="provider.claude",
        issuable=False,
    ),
    ProviderCatalogEntry(
        key=ENGINE_GEMINI,
        label="Gemini",
        availability=AVAILABILITY_AVAILABLE,
        unavailable_reason=None,
        adapter_shipped=True,
        grant_key="provider.gemini",
        issuable=False,
    ),
    # Coming soon: no adapter ships, no route exists, and no plan bundle may
    # issue a runnable grant for them. Copilot is additionally NON-ISSUABLE in
    # the entitlement registry — nothing may ever write it.
    ProviderCatalogEntry(
        key=PROVIDER_GROK,
        label="Grok",
        availability=AVAILABILITY_UNAVAILABLE,
        unavailable_reason=REASON_PROVIDER_UNAVAILABLE,
        adapter_shipped=False,
        grant_key=KEY_PROVIDER_GROK,
        issuable=True,
    ),
    ProviderCatalogEntry(
        key=PROVIDER_PERPLEXITY,
        label="Perplexity",
        availability=AVAILABILITY_UNAVAILABLE,
        unavailable_reason=REASON_PROVIDER_UNAVAILABLE,
        adapter_shipped=False,
        grant_key=KEY_PROVIDER_PERPLEXITY,
        issuable=True,
    ),
    ProviderCatalogEntry(
        key=PROVIDER_COPILOT,
        label="Microsoft Copilot",
        availability=AVAILABILITY_UNAVAILABLE,
        unavailable_reason=REASON_PROVIDER_UNAVAILABLE,
        adapter_shipped=False,
        grant_key=KEY_PROVIDER_COPILOT,
        issuable=False,
    ),
)


def public_provider_routes(provider_key: str) -> tuple[MeasurementRoute, ...]:
    """Approved mode-specific routes for a public catalog row.

    Each tuple is one exact mode-specific route. Coming-soon providers have no
    executable entries by construction.
    """
    return measurement_routes_for_engine(provider_key)


# --- Credential source vocabulary (T11) ------------------------------------
# Who owns the executing credential for one task: a tenant BYOK connection or
# the operator's platform-funded connection in the reserved system workspace.
CREDENTIAL_SOURCE_BYOK: Final = "byok"
CREDENTIAL_SOURCE_PLATFORM: Final = "platform"
CREDENTIAL_SOURCES: Final[frozenset[str]] = frozenset(
    {CREDENTIAL_SOURCE_BYOK, CREDENTIAL_SOURCE_PLATFORM}
)
# Selection precedence: a healthy tenant BYOK credential always wins over the
# platform-funded fallback; funded is reached only when no BYOK route can
# execute.
CREDENTIAL_SOURCE_PRECEDENCE: Final[tuple[str, str]] = (
    CREDENTIAL_SOURCE_BYOK,
    CREDENTIAL_SOURCE_PLATFORM,
)
# Coded, safe failure when neither a BYOK nor a funded-platform credential may
# execute a task. Carries no key material, no provider detail, and no system
# workspace information — the token IS the contract.
CODE_EXECUTION_CREDENTIALS_UNAVAILABLE: Final = "execution_credentials_unavailable"

# --- Credential lifecycle telemetry (T11) ----------------------------------
# Operator telemetry event names (logged, never tenant-facing DTOs). Payloads
# carry opaque ids, classification tokens, and pause/provisioning timing only
# — NEVER keys, ciphertext, prompts, answers, provider bodies, or
# authorization headers (invariant 6).
TELEMETRY_BYOK_PAUSED: Final = "provider.byok.paused"
TELEMETRY_PLATFORM_AUTH_FAILED: Final = "provider.platform.auth_failed"
TELEMETRY_PLATFORM_PROVISIONED: Final = "provider.platform.provisioned"
TELEMETRY_FUNDED_ADMISSION_DENIED: Final = "funded.execution.admission_denied"

# --- Platform provisioning identity (T11) -----------------------------------
# The reserved system workspace holds the operator's platform-funded rows
# (exactly one, enforced by the partial unique index on Workspace.is_system).
SYSTEM_WORKSPACE_NAME: Final = "CiteLadder Platform (system)"
# Environment variables the provisioning CLI reads platform keys from, keyed
# by transport. The VALUES are secret material and are only ever accepted as
# SecretStr, Fernet-encrypted before flush, and never printed or logged.
PLATFORM_CREDENTIAL_ENV_VARS: Final[dict[str, str]] = {
    TRANSPORT_OPENAI: "CITELADDER_PLATFORM_OPENAI_API_KEY",
    TRANSPORT_ANTHROPIC: "CITELADDER_PLATFORM_ANTHROPIC_API_KEY",
    TRANSPORT_GOOGLE: "CITELADDER_PLATFORM_GOOGLE_API_KEY",
}


# --- Retry / error classification tokens (recorded on tests + attempts) ---
ERROR_TIMEOUT: Final = "timeout"
ERROR_CONNECTION: Final = "connection"
ERROR_RATE_LIMIT: Final = "rate_limit"
ERROR_SERVER: Final = "server_error"
ERROR_CLIENT: Final = "client_error"
ERROR_AUTH: Final = "auth_failure"
ERROR_PARSE: Final = "parse_error"
ERROR_UNKNOWN: Final = "unknown"
ERROR_INVALID_SURFACE: Final = "invalid_surface"

RETRYABLE_ERRORS: Final[frozenset[str]] = frozenset(
    {ERROR_TIMEOUT, ERROR_CONNECTION, ERROR_RATE_LIMIT, ERROR_SERVER}
)

# --- Connectivity-test statuses -------------------------------------------
TEST_STATUS_OK: Final = "ok"
TEST_STATUS_FAILED: Final = "failed"

# Neutral, brand-free probe used by the ``/test`` endpoint. The tracked
# brand/competitor list is NEVER sent to a provider (invariant 6).
PROBE_PROMPT: Final = "Reply with the single word: ok."


class ProviderCatalogSettings(BaseSettings):
    """Tunable answer-engine knobs (env-overridable, invariant 1).

    Provider-agnostic guardrails plus the transport endpoint URLs. A single set
    of knobs bounds every transport so a stray call cannot run away in tokens or
    time regardless of provider.
    """

    model_config = SettingsConfigDict(env_prefix="PROVIDER_", extra="ignore")

    # Endpoint URLs (overridable per environment / for a self-hosted gateway).
    openai_responses_url: str = "https://api.openai.com/v1/responses"
    google_interactions_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    anthropic_messages_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    # Caps server-side web_search invocations per Anthropic request.
    anthropic_max_uses: int = 3
    # Per-call output-token cap sent to every transport payload.
    # Global fallback for any non-frozen request. Audit calls normally carry
    # their own frozen cap; keeping this aligned prevents an adapter caller from
    # accidentally permitting essay-length output.
    max_output_tokens: int = 800
    # HTTP client timeout for a single provider call.
    request_timeout_seconds: float = 60.0
    # Shorter timeout for the lightweight connectivity probe.
    test_timeout_seconds: float = 20.0
    # --- Connectivity-probe request policy (invariant 1) -----------------
    # The ``/test`` probe is a LIVENESS check, not a measurement: it proves the
    # credential + endpoint + model answer at all. Retrieval is DISABLED so a
    # connectivity test never triggers (and never pays for) a billable grounded
    # search, and the output cap is a handful of tokens because the expected
    # answer is the single word in ``PROBE_PROMPT``. Neither value is ever read
    # from the measurement caps above — a probe must not scale with them.
    test_retrieval_enabled: bool = False
    test_max_output_tokens: int = 32
    # Recoverable auth-failure pause (T11): an ERROR_AUTH-classified execution
    # pauses the credential for this many days before resolution may try it
    # again (the tenant/operator rotates the key within the grace window).
    byok_key_grace_days: int = 7


provider_catalog_settings = ProviderCatalogSettings()
