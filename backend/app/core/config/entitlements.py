# Entitlement capability registry (invariant 1: all config lives in core/config).
#
# This is the ONLY owner of the v8 commercial capability vocabulary. It defines
# every capability key a grant may carry, the capability's type, and the rule
# the pure resolver fold uses to combine concurrent grants of the same key.
# Domain code reads these immutable definitions; it never hard-codes a
# capability key, a resolution rule, or a level ordering inline (invariant 1).
#
# Design contract (frozen plan, slice23 Task 1):
#   - Capability keys are stable machine keys, never marketing display names.
#   - Levels are stored in grants as INTEGER ORDINALS into ``ordered_values``;
#     serialization converts the resolved ordinal back to the public string
#     and rejects out-of-range values.
#   - Flags accept only 0 or 1; every counter rejects negative grant values.
#   - The three coming-soon provider flags resolve through the algebra, but
#     commercial activation always returns ``provider_unavailable`` and only
#     Grok/Perplexity may appear in operator/dev/test grants (Copilot is
#     non-issuable).
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final


class CapabilityType(StrEnum):
    """The shape of a capability's value and how grants combine."""

    FLAG = "flag"
    COUNTER_OCCUPANCY = "counter.occupancy"
    COUNTER_CONSUMABLE = "counter.consumable"
    COUNTER_RATE = "counter.rate"
    LEVEL = "level"


class ResolutionRule(StrEnum):
    """How concurrent grants of one capability key fold into a single value."""

    ANY = "any"  # flag: any grant with value 1 enables it
    SUM = "sum"  # counters: allowances add across concurrent grants
    MAX = "max"  # levels: the highest granted ordinal wins


# Each capability type has exactly one resolution rule it is allowed to use.
# The registry validates this pairing at construction so a misconfigured entry
# fails fast at import/boot, never silently at resolution time.
TYPE_RESOLUTION_RULES: Final[dict[CapabilityType, ResolutionRule]] = {
    CapabilityType.FLAG: ResolutionRule.ANY,
    CapabilityType.COUNTER_OCCUPANCY: ResolutionRule.SUM,
    CapabilityType.COUNTER_CONSUMABLE: ResolutionRule.SUM,
    CapabilityType.COUNTER_RATE: ResolutionRule.SUM,
    CapabilityType.LEVEL: ResolutionRule.MAX,
}

# Capability keys (stable machine keys; never a plan display name).
KEY_AUDIT_CADENCE: Final = "audit_cadence"
KEY_HISTORY_WINDOW: Final = "history_window"
KEY_SUPPORT_TIER: Final = "support_tier"
KEY_AUDIT_CREDITS: Final = "audit_credits"
KEY_PROJECT_SLOTS: Final = "project_slots"
KEY_PROMPT_SLOTS: Final = "prompt_slots"
KEY_MONITORED_URLS: Final = "monitored_urls"
KEY_FANOUT: Final = "fanout"
KEY_PROVIDER_GROK: Final = "provider.grok"
KEY_PROVIDER_PERPLEXITY: Final = "provider.perplexity"
KEY_PROVIDER_COPILOT: Final = "provider.copilot"
KEY_EXPORTS: Final = "exports"
KEY_MANUAL_RUNS_PER_DAY: Final = "manual_runs_per_day"


# The default rolling window (seconds) for rate capabilities. 86_400 = 1 day.
MANUAL_RUNS_ROLLING_WINDOW_SECONDS: Final = 86_400


@dataclass(frozen=True, slots=True)
class CapabilityDefinition:
    """Immutable definition of one capability key.

    ``rolling_window_seconds`` is set only for ``counter.rate`` capabilities.
    ``ordered_values`` is the public string ordering for ``level`` capabilities
    (grants store the integer ordinal, not the string). ``issuable=False``
    marks a key that may resolve through the algebra but must never be written
    by a plan/operator/test/dev grant (e.g. Copilot). ``public=False`` marks a
    key withheld from the public capability listing.
    """

    key: str
    capability_type: CapabilityType
    resolution_rule: ResolutionRule
    rolling_window_seconds: int | None = None
    ordered_values: tuple[str, ...] = ()
    issuable: bool = True
    public: bool = True


@dataclass(frozen=True, slots=True)
class CapabilityRegistry:
    """An immutable, construction-validated set of capability definitions."""

    revision: str
    entries: tuple[CapabilityDefinition, ...] = field(default_factory=tuple)
    _by_key: dict[str, CapabilityDefinition] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @staticmethod
    def _validate_entry(entry: CapabilityDefinition) -> None:
        expected = TYPE_RESOLUTION_RULES[entry.capability_type]
        if entry.resolution_rule is not expected:
            raise ValueError(
                f"capability {entry.key!r} has resolution rule "
                f"{entry.resolution_rule!r} inconsistent with type "
                f"{entry.capability_type!r}"
            )
        if entry.capability_type is CapabilityType.COUNTER_RATE:
            if (
                entry.rolling_window_seconds is None
                or entry.rolling_window_seconds <= 0
            ):
                raise ValueError(
                    f"rate capability {entry.key!r} needs a positive "
                    "rolling_window_seconds"
                )
        elif entry.rolling_window_seconds is not None:
            raise ValueError(
                f"capability {entry.key!r} sets rolling_window_seconds but "
                "is not a rate capability"
            )
        if entry.capability_type is CapabilityType.LEVEL:
            if not entry.ordered_values:
                raise ValueError(
                    f"level capability {entry.key!r} needs a nonempty "
                    "ordered_values ordering"
                )
            if len(entry.ordered_values) != len(set(entry.ordered_values)):
                raise ValueError(
                    f"level capability {entry.key!r} has duplicate ordered_values"
                )
        elif entry.ordered_values:
            raise ValueError(
                f"capability {entry.key!r} sets ordered_values but is not "
                "a level capability"
            )

    def __post_init__(self) -> None:
        keys = [entry.key for entry in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("capability registry contains duplicate keys")
        by_key: dict[str, CapabilityDefinition] = {}
        for entry in self.entries:
            self._validate_entry(entry)
            by_key[entry.key] = entry
        object.__setattr__(self, "_by_key", by_key)

    def get(self, key: str) -> CapabilityDefinition | None:
        return self._by_key.get(key)

    def require(self, key: str) -> CapabilityDefinition:
        definition = self.get(key)
        if definition is None:
            raise KeyError(f"unknown capability key: {key!r}")
        return definition

    def public_entries(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(entry for entry in self.entries if entry.public)


# Ordered public values for the level capabilities. The integer ordinal stored
# in a grant indexes into these tuples; index 0 is always the least privilege.
_LEVEL_UNSET: Final = "unset"
AUDIT_CADENCE_VALUES: Final[tuple[str, ...]] = (_LEVEL_UNSET, "weekly", "daily")
HISTORY_WINDOW_VALUES: Final[tuple[str, ...]] = (
    _LEVEL_UNSET,
    "90d",
    "12mo",
    "24mo",
)
# support_tier has an explicit config-owned ordering but NO plan grant until
# product supplies values; it resolves to the least privilege by default.
SUPPORT_TIER_VALUES: Final[tuple[str, ...]] = ("standard", "priority")


def _build_registry() -> CapabilityRegistry:
    return CapabilityRegistry(
        revision=CAPABILITY_REGISTRY_REVISION,
        entries=(
            CapabilityDefinition(
                key=KEY_AUDIT_CADENCE,
                capability_type=CapabilityType.LEVEL,
                resolution_rule=ResolutionRule.MAX,
                ordered_values=AUDIT_CADENCE_VALUES,
            ),
            CapabilityDefinition(
                key=KEY_HISTORY_WINDOW,
                capability_type=CapabilityType.LEVEL,
                resolution_rule=ResolutionRule.MAX,
                ordered_values=HISTORY_WINDOW_VALUES,
            ),
            CapabilityDefinition(
                key=KEY_SUPPORT_TIER,
                capability_type=CapabilityType.LEVEL,
                resolution_rule=ResolutionRule.MAX,
                ordered_values=SUPPORT_TIER_VALUES,
            ),
            CapabilityDefinition(
                key=KEY_AUDIT_CREDITS,
                capability_type=CapabilityType.COUNTER_CONSUMABLE,
                resolution_rule=ResolutionRule.SUM,
            ),
            CapabilityDefinition(
                key=KEY_PROJECT_SLOTS,
                capability_type=CapabilityType.COUNTER_OCCUPANCY,
                resolution_rule=ResolutionRule.SUM,
            ),
            CapabilityDefinition(
                key=KEY_PROMPT_SLOTS,
                capability_type=CapabilityType.COUNTER_OCCUPANCY,
                resolution_rule=ResolutionRule.SUM,
            ),
            CapabilityDefinition(
                key=KEY_MONITORED_URLS,
                capability_type=CapabilityType.COUNTER_OCCUPANCY,
                resolution_rule=ResolutionRule.SUM,
            ),
            CapabilityDefinition(
                key=KEY_FANOUT,
                capability_type=CapabilityType.FLAG,
                resolution_rule=ResolutionRule.ANY,
            ),
            CapabilityDefinition(
                key=KEY_PROVIDER_GROK,
                capability_type=CapabilityType.FLAG,
                resolution_rule=ResolutionRule.ANY,
            ),
            CapabilityDefinition(
                key=KEY_PROVIDER_PERPLEXITY,
                capability_type=CapabilityType.FLAG,
                resolution_rule=ResolutionRule.ANY,
            ),
            # Copilot resolves through the algebra but is NON-ISSUABLE: no
            # plan, operator, test, or dev grant may ever write it.
            CapabilityDefinition(
                key=KEY_PROVIDER_COPILOT,
                capability_type=CapabilityType.FLAG,
                resolution_rule=ResolutionRule.ANY,
                issuable=False,
            ),
            CapabilityDefinition(
                key=KEY_EXPORTS,
                capability_type=CapabilityType.FLAG,
                resolution_rule=ResolutionRule.ANY,
            ),
            CapabilityDefinition(
                key=KEY_MANUAL_RUNS_PER_DAY,
                capability_type=CapabilityType.COUNTER_RATE,
                resolution_rule=ResolutionRule.SUM,
                rolling_window_seconds=MANUAL_RUNS_ROLLING_WINDOW_SECONDS,
            ),
        ),
    )


# Bounded in-process entitlement cache knobs (domain/entitlements/cache.py).
# The cache is replica-safe only because every lookup first reads the persisted
# account ``entitlement_lifecycle_version`` and includes it in the key; these
# knobs bound memory and serve-staleness between version bumps.
ENTITLEMENT_CACHE_MAX_ENTRIES: Final = 1024
ENTITLEMENT_CACHE_MAX_TTL_SECONDS: Final = 300

# One config-owned registry revision for the whole v8 entitlement layer.
CAPABILITY_REGISTRY_REVISION: Final = "entitlements-v1"

CAPABILITY_REGISTRY: Final = _build_registry()

# Coming-soon provider flag keys. These resolve through the algebra, but no
# execution path may route them and commercial activation returns
# ``provider_unavailable``. Only Grok/Perplexity may exist in
# operator/dev/test grants.
COMING_SOON_PROVIDER_KEYS: Final[frozenset[str]] = frozenset(
    {KEY_PROVIDER_GROK, KEY_PROVIDER_PERPLEXITY, KEY_PROVIDER_COPILOT}
)
# Subset of coming-soon providers an operator/dev/test grant may actually write.
OPERATOR_GRANTABLE_PROVIDER_KEYS: Final[frozenset[str]] = frozenset(
    {KEY_PROVIDER_GROK, KEY_PROVIDER_PERPLEXITY}
)

# ---------------------------------------------------------------------------
# Grant / revocation / ledger vocabulary (config-owned, invariant 1)
# ---------------------------------------------------------------------------
# AccountGrant.source_kind. ``trial`` is in-scope grant algebra even though
# trial checkout and its abuse controls are deferred to PR3.
GRANT_SOURCE_PLAN: Final = "plan"
GRANT_SOURCE_ADDON: Final = "addon"
GRANT_SOURCE_TOPUP: Final = "topup"
GRANT_SOURCE_TRIAL: Final = "trial"
GRANT_SOURCE_OVERRIDE: Final = "override"
GRANT_SOURCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        GRANT_SOURCE_PLAN,
        GRANT_SOURCE_ADDON,
        GRANT_SOURCE_TOPUP,
        GRANT_SOURCE_TRIAL,
        GRANT_SOURCE_OVERRIDE,
    }
)

# GrantRevocation.actor_kind.
ACTOR_KIND_BILLING_OWNER: Final = "billing_owner"
ACTOR_KIND_OPERATOR: Final = "operator"
ACTOR_KIND_PROVIDER: Final = "provider"
ACTOR_KIND_SYSTEM: Final = "system"
ACTOR_KINDS: Final[frozenset[str]] = frozenset(
    {
        ACTOR_KIND_BILLING_OWNER,
        ACTOR_KIND_OPERATOR,
        ACTOR_KIND_PROVIDER,
        ACTOR_KIND_SYSTEM,
    }
)

# ConsumableLedger.entry_kind.
LEDGER_ENTRY_RESERVATION: Final = "reservation"
LEDGER_ENTRY_DEBIT: Final = "debit"
LEDGER_ENTRY_RELEASE: Final = "release"
LEDGER_ENTRY_KINDS: Final[frozenset[str]] = frozenset(
    {LEDGER_ENTRY_RESERVATION, LEDGER_ENTRY_DEBIT, LEDGER_ENTRY_RELEASE}
)

# Consumable draw-order tiebreak across source kinds (after effective expiry
# ascending, before UUID). Index in this tuple is the sort weight.
CONSUMABLE_DRAW_SOURCE_ORDER: Final[tuple[str, ...]] = (
    GRANT_SOURCE_TRIAL,
    GRANT_SOURCE_PLAN,
    GRANT_SOURCE_ADDON,
    GRANT_SOURCE_OVERRIDE,
    GRANT_SOURCE_TOPUP,
)

# IdempotencyRecord.state.
IDEMPOTENCY_STATE_STARTED: Final = "started"
IDEMPOTENCY_STATE_COMPLETED: Final = "completed"
IDEMPOTENCY_STATE_FAILED: Final = "failed"
IDEMPOTENCY_STATES: Final[frozenset[str]] = frozenset(
    {
        IDEMPOTENCY_STATE_STARTED,
        IDEMPOTENCY_STATE_COMPLETED,
        IDEMPOTENCY_STATE_FAILED,
    }
)

# PendingActivation.activation_kind / status. Trial checkout is deferred and
# creates no pending activation.
ACTIVATION_KIND_BASE: Final = "base"
ACTIVATION_KIND_ADDON: Final = "addon"
ACTIVATION_KIND_TOPUP: Final = "topup"
ACTIVATION_KINDS: Final[frozenset[str]] = frozenset(
    {ACTIVATION_KIND_BASE, ACTIVATION_KIND_ADDON, ACTIVATION_KIND_TOPUP}
)

PENDING_ACTIVATION_PENDING: Final = "pending"
PENDING_ACTIVATION_ACTIVATED: Final = "activated"
PENDING_ACTIVATION_FAILED: Final = "failed"
PENDING_ACTIVATION_ABANDONED: Final = "abandoned"
PENDING_ACTIVATION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        PENDING_ACTIVATION_PENDING,
        PENDING_ACTIVATION_ACTIVATED,
        PENDING_ACTIVATION_FAILED,
        PENDING_ACTIVATION_ABANDONED,
    }
)

# PendingActivation.credential_mode.
CREDENTIAL_MODE_BYOK: Final = "byok"
CREDENTIAL_MODE_FUNDED: Final = "funded"
CREDENTIAL_MODES: Final[frozenset[str]] = frozenset(
    {CREDENTIAL_MODE_BYOK, CREDENTIAL_MODE_FUNDED}
)

# ---------------------------------------------------------------------------
# Account occupancy enforcement (slice23 Task 4; config-owned, invariant 1)
# ---------------------------------------------------------------------------
# Namespace folded into the 64-bit ``pg_advisory_xact_lock`` key that
# serializes occupancy-checked mutations for one billing account
# (domain/entitlements/enforcement.py). Distinct from the prompts-domain
# lock namespaces so the lock families can never overlap.
OCCUPANCY_LOCK_NAMESPACE: Final = 0x43415041  # "CAPA"

CODE_OCCUPANCY_LIMIT_EXCEEDED: Final = "occupancy_limit_exceeded"
CODE_OCCUPANCY_UNRESOLVED: Final = "occupancy_unresolved"

# Structured-log event names. Safe fields only: account/workspace ids,
# capability keys, and integer counts — never user data (invariant 6).
EVENT_OCCUPANCY_LIMIT_EXCEEDED: Final = "billing.occupancy_limit_exceeded"
EVENT_OCCUPANCY_UNRESOLVED: Final = "billing.occupancy_unresolved"

# ---------------------------------------------------------------------------
# Funded + manual-rate admission (slice23 Task 4 Part B; config-owned)
# ---------------------------------------------------------------------------
# API error codes for the audit-admission refusals (api-error-contract section
# 5: codes live in config, raised via ``ApiException.coded``). The resolver
# status vocabulary owns ``entitlement_unresolved`` (see
# ``domain/entitlements/types.STATUS_ENTITLEMENT_UNRESOLVED``) — it is reused,
# never re-literalled here (invariant 2). The matching telemetry event names
# (``billing.funded_budget_exhausted`` etc.) live in ``config/billing_contracts.py``.
CODE_MANUAL_RUN_RATE_EXCEEDED: Final = "manual_run_rate_exceeded"
CODE_FUNDED_BUDGET_EXHAUSTED: Final = "funded_budget_exhausted"
CODE_FUNDED_CREDITS_EXHAUSTED: Final = "funded_credits_exhausted"
CODE_FUNDED_COST_UNRESOLVED: Final = "funded_cost_unresolved"
