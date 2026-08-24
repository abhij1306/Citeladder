"""v8 entitlement shared contracts (PR1 commit 1): capability registry
integrity + construction validation, grant/ledger vocabulary consistency, and
the fail-closed resolver value types."""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.core.config.entitlements import (
    ACTOR_KINDS,
    AUDIT_CADENCE_VALUES,
    CAPABILITY_REGISTRY,
    CAPABILITY_REGISTRY_REVISION,
    COMING_SOON_PROVIDER_KEYS,
    CONSUMABLE_DRAW_SOURCE_ORDER,
    CREDENTIAL_MODES,
    GRANT_SOURCE_KINDS,
    HISTORY_WINDOW_VALUES,
    IDEMPOTENCY_STATES,
    KEY_PROVIDER_COPILOT,
    KEY_PROVIDER_GROK,
    KEY_PROVIDER_PERPLEXITY,
    LEDGER_ENTRY_KINDS,
    MANUAL_RUNS_ROLLING_WINDOW_SECONDS,
    OPERATOR_GRANTABLE_PROVIDER_KEYS,
    PENDING_ACTIVATION_STATUSES,
    SUPPORT_TIER_VALUES,
    CapabilityDefinition,
    CapabilityRegistry,
    CapabilityType,
    ResolutionRule,
)
from app.domain.entitlements.types import (
    STATUS_ENTITLEMENT_UNRESOLVED,
    STATUS_RESOLVED,
    ResolvedCapability,
    ResolvedEntitlement,
    no_capability_entitlement,
)

ALL_CAPABILITY_KEYS = (
    "audit_cadence",
    "history_window",
    "support_tier",
    "audit_credits",
    "project_slots",
    "prompt_slots",
    "monitored_urls",
    "fanout",
    "provider.grok",
    "provider.perplexity",
    "provider.copilot",
    "exports",
    "manual_runs_per_day",
)


def _definition(
    key: str = "k",
    capability_type: CapabilityType = CapabilityType.FLAG,
    resolution_rule: ResolutionRule = ResolutionRule.ANY,
    **kwargs,
) -> CapabilityDefinition:
    return CapabilityDefinition(
        key=key,
        capability_type=capability_type,
        resolution_rule=resolution_rule,
        **kwargs,
    )


class TestCapabilityRegistry:
    def test_registry_contains_exactly_the_frozen_keys(self) -> None:
        assert CAPABILITY_REGISTRY.revision == CAPABILITY_REGISTRY_REVISION
        assert tuple(entry.key for entry in CAPABILITY_REGISTRY.entries) == (
            ALL_CAPABILITY_KEYS
        )

    def test_every_entry_uses_the_type_canonical_rule(self) -> None:
        expected = {
            CapabilityType.FLAG: ResolutionRule.ANY,
            CapabilityType.COUNTER_OCCUPANCY: ResolutionRule.SUM,
            CapabilityType.COUNTER_CONSUMABLE: ResolutionRule.SUM,
            CapabilityType.COUNTER_RATE: ResolutionRule.SUM,
            CapabilityType.LEVEL: ResolutionRule.MAX,
        }
        for entry in CAPABILITY_REGISTRY.entries:
            assert entry.resolution_rule is expected[entry.capability_type]

    def test_level_orderings_start_at_least_privilege(self) -> None:
        assert AUDIT_CADENCE_VALUES[0] == "unset"
        assert AUDIT_CADENCE_VALUES[0] == "unset"
        assert HISTORY_WINDOW_VALUES[0] == "unset"
        assert SUPPORT_TIER_VALUES[0] == "standard"
        # Strictly increasing privilege, no duplicates.
        for values in (
            AUDIT_CADENCE_VALUES,
            AUDIT_CADENCE_VALUES,
            HISTORY_WINDOW_VALUES,
            SUPPORT_TIER_VALUES,
        ):
            assert len(values) == len(set(values))

    def test_copilot_is_non_issuable_and_never_operator_grantable(self) -> None:
        copilot = CAPABILITY_REGISTRY.require(KEY_PROVIDER_COPILOT)
        assert copilot.issuable is False
        assert KEY_PROVIDER_COPILOT in COMING_SOON_PROVIDER_KEYS
        assert KEY_PROVIDER_COPILOT not in OPERATOR_GRANTABLE_PROVIDER_KEYS
        assert OPERATOR_GRANTABLE_PROVIDER_KEYS == frozenset(
            {KEY_PROVIDER_GROK, KEY_PROVIDER_PERPLEXITY}
        )
        for key in OPERATOR_GRANTABLE_PROVIDER_KEYS:
            assert CAPABILITY_REGISTRY.require(key).issuable is True

    def test_rate_capability_carries_positive_rolling_window(self) -> None:
        rate = CAPABILITY_REGISTRY.require("manual_runs_per_day")
        assert rate.capability_type is CapabilityType.COUNTER_RATE
        assert rate.rolling_window_seconds == MANUAL_RUNS_ROLLING_WINDOW_SECONDS
        assert rate.rolling_window_seconds > 0

    def test_get_and_require_semantics(self) -> None:
        assert CAPABILITY_REGISTRY.get("no.such.key") is None
        with pytest.raises(KeyError):
            CAPABILITY_REGISTRY.require("no.such.key")

    def test_public_entries_excludes_non_public(self) -> None:
        registry = CapabilityRegistry(
            revision="r",
            entries=(
                _definition("a"),
                _definition("b", public=False),
            ),
        )
        assert tuple(e.key for e in registry.public_entries()) == ("a",)

    def test_duplicate_keys_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate keys"):
            CapabilityRegistry(
                revision="r",
                entries=(_definition("dup"), _definition("dup")),
            )

    def test_rule_must_match_type(self) -> None:
        with pytest.raises(ValueError, match="inconsistent with type"):
            CapabilityRegistry(
                revision="r",
                entries=(
                    _definition(
                        "bad",
                        capability_type=CapabilityType.FLAG,
                        resolution_rule=ResolutionRule.SUM,
                    ),
                ),
            )

    def test_rate_capability_requires_positive_window(self) -> None:
        for window in (None, 0, -5):
            with pytest.raises(ValueError, match="rolling_window_seconds"):
                CapabilityRegistry(
                    revision="r",
                    entries=(
                        _definition(
                            "rate",
                            capability_type=CapabilityType.COUNTER_RATE,
                            resolution_rule=ResolutionRule.SUM,
                            rolling_window_seconds=window,
                        ),
                    ),
                )

    def test_non_rate_capability_must_not_set_window(self) -> None:
        with pytest.raises(ValueError, match="not a rate capability"):
            CapabilityRegistry(
                revision="r",
                entries=(_definition("flag", rolling_window_seconds=60),),
            )

    def test_level_requires_nonempty_unique_ordering(self) -> None:
        with pytest.raises(ValueError, match="nonempty"):
            CapabilityRegistry(
                revision="r",
                entries=(
                    _definition(
                        "level",
                        capability_type=CapabilityType.LEVEL,
                        resolution_rule=ResolutionRule.MAX,
                    ),
                ),
            )
        with pytest.raises(ValueError, match="duplicate ordered_values"):
            CapabilityRegistry(
                revision="r",
                entries=(
                    _definition(
                        "level",
                        capability_type=CapabilityType.LEVEL,
                        resolution_rule=ResolutionRule.MAX,
                        ordered_values=("a", "a"),
                    ),
                ),
            )

    def test_non_level_must_not_set_ordered_values(self) -> None:
        with pytest.raises(ValueError, match="not a level capability"):
            CapabilityRegistry(
                revision="r",
                entries=(_definition("flag", ordered_values=("x",)),),
            )

    def test_registry_is_immutable(self) -> None:
        with pytest.raises(FrozenInstanceError):
            CAPABILITY_REGISTRY.revision = "mutated"  # type: ignore[misc]


class TestVocabulary:
    def test_draw_order_covers_every_grant_source_exactly_once(self) -> None:
        assert frozenset(CONSUMABLE_DRAW_SOURCE_ORDER) == GRANT_SOURCE_KINDS
        assert len(CONSUMABLE_DRAW_SOURCE_ORDER) == len(
            set(CONSUMABLE_DRAW_SOURCE_ORDER)
        )
        # Trial burns before plan-bought credits; top-ups last.
        assert CONSUMABLE_DRAW_SOURCE_ORDER[0] == "trial"
        assert CONSUMABLE_DRAW_SOURCE_ORDER[-1] == "topup"

    def test_controlled_vocabularies_are_nonempty_frozensets(self) -> None:
        for vocabulary in (
            GRANT_SOURCE_KINDS,
            ACTOR_KINDS,
            LEDGER_ENTRY_KINDS,
            IDEMPOTENCY_STATES,
            PENDING_ACTIVATION_STATUSES,
            CREDENTIAL_MODES,
        ):
            assert isinstance(vocabulary, frozenset)
            assert vocabulary
        assert LEDGER_ENTRY_KINDS == frozenset({"reservation", "debit", "release"})
        assert CREDENTIAL_MODES == frozenset({"byok", "funded"})


class TestResolvedEntitlementTypes:
    def _resolved(self) -> ResolvedEntitlement:
        return ResolvedEntitlement(
            account_id=uuid.uuid4(),
            registry_revision=CAPABILITY_REGISTRY_REVISION,
            entitlement_lifecycle_version=3,
            resolved_at=datetime.now(UTC),
            valid_until=None,
            status=STATUS_RESOLVED,
            capabilities=(
                ResolvedCapability(
                    key="fanout",
                    capability_type=CapabilityType.FLAG,
                    value=1,
                ),
                ResolvedCapability(
                    key="project_slots",
                    capability_type=CapabilityType.COUNTER_OCCUPANCY,
                    value=5,
                ),
            ),
        )

    def test_capability_helpers(self) -> None:
        entitlement = self._resolved()
        assert entitlement.capability("fanout") is not None
        assert entitlement.capability("missing") is None
        assert entitlement.capability_value("project_slots") == 5
        assert entitlement.capability_value("missing") == 0
        assert entitlement.has_flag("fanout") is True
        assert entitlement.has_flag("project_slots") is False

    def test_no_capability_entitlement_fails_closed(self) -> None:
        account_id = uuid.uuid4()
        at = datetime.now(UTC)
        entitlement = no_capability_entitlement(
            account_id=account_id,
            registry_revision=CAPABILITY_REGISTRY_REVISION,
            entitlement_lifecycle_version=0,
            at=at,
            errors=("grant rows corrupt",),
        )
        assert entitlement.status == STATUS_ENTITLEMENT_UNRESOLVED
        assert entitlement.capabilities == ()
        assert entitlement.valid_until is None
        assert entitlement.errors == ("grant rows corrupt",)
        # A fail-closed entitlement grants nothing, not even defaults.
        assert entitlement.capability_value("fanout") == 0
        assert entitlement.has_flag("fanout") is False
