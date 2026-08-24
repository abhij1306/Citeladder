"""Unit tests for the pure entitlement fold and the bounded resolver cache.

The fold (``app.domain.entitlements.resolver``) is a pure function over frozen
value types at a caller-supplied ``at`` — no clock, no DB, no provider. These
tests pin the resolution algebra (flags OR / counters SUM / levels MAX), the
boundary exclusions, the total consumable draw order, top-up expiry coupling
to the base subscription end, input-validation failures, and the cache's
version/revision/TTL semantics. DB-backed resolution (version bumps, runtime
refresh, same-transaction revocation visibility) lives in
``tests/component/test_entitlements.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    ENTITLEMENT_CACHE_MAX_TTL_SECONDS,
    GRANT_SOURCE_ADDON,
    GRANT_SOURCE_OVERRIDE,
    GRANT_SOURCE_PLAN,
    GRANT_SOURCE_TOPUP,
    GRANT_SOURCE_TRIAL,
    KEY_AUDIT_CREDITS,
    KEY_EXPORTS,
    KEY_HISTORY_WINDOW,
    KEY_MONITORED_URLS,
)
from app.domain.entitlements import cache as entitlement_cache
from app.domain.entitlements.resolver import (
    ResolverInputError,
    effective_grant_expiry,
    fold_entitlement,
    ordered_consumable_grants,
)
from app.domain.entitlements.types import (
    STATUS_ENTITLEMENT_UNRESOLVED,
    STATUS_RESOLVED,
    GrantInput,
    ResolvedEntitlement,
    RevocationInput,
    no_capability_entitlement,
)

_AT = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)
_ACCOUNT = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _grant(
    key: str,
    value: int,
    *,
    source_kind: str = GRANT_SOURCE_PLAN,
    valid_from: datetime = _AT - timedelta(hours=1),
    valid_until: datetime | None = None,
    grant_id: uuid.UUID | None = None,
) -> GrantInput:
    return GrantInput(
        id=grant_id or uuid.uuid4(),
        key=key,
        value=value,
        source_kind=source_kind,
        valid_from=valid_from,
        valid_until=valid_until,
        period_start=valid_from,
        period_end=valid_until,
    )


def _fold(
    grants: tuple[GrantInput, ...],
    revocations: tuple[RevocationInput, ...] = (),
    *,
    subscription_end: datetime | None = None,
    at: datetime = _AT,
) -> ResolvedEntitlement:
    return fold_entitlement(
        account_id=_ACCOUNT,
        grants=grants,
        revocations=revocations,
        registry=CAPABILITY_REGISTRY,
        subscription_end=subscription_end,
        entitlement_lifecycle_version=0,
        at=at,
    )


# =========================================================================
# Empty fold + validation failures (never a partial fold)
# =========================================================================
def test_no_grants_resolves_to_empty_capabilities() -> None:
    out = _fold(())
    assert out.status == STATUS_RESOLVED
    assert out.capabilities == ()
    assert out.capability_value(KEY_MONITORED_URLS) == 0
    assert out.has_flag(KEY_EXPORTS) is False
    assert out.valid_until is None
    assert out.registry_revision == CAPABILITY_REGISTRY.revision


def test_unknown_capability_key_fails_the_whole_fold() -> None:
    good = _grant(KEY_MONITORED_URLS, 50)
    bad = _grant("not_a_capability", 1)
    with pytest.raises(ResolverInputError, match="unknown capability key"):
        _fold((good, bad))


def test_unknown_source_kind_fails_the_fold() -> None:
    bad = _grant(KEY_MONITORED_URLS, 50, source_kind="gift")
    with pytest.raises(ResolverInputError, match="unknown grant source kind"):
        _fold((bad,))


def test_flag_grant_value_must_be_zero_or_one() -> None:
    bad = _grant(KEY_EXPORTS, 2)
    with pytest.raises(ResolverInputError, match="flag grant value not 0/1"):
        _fold((bad,))


def test_level_grant_ordinal_must_be_in_range() -> None:
    # HISTORY_WINDOW has 4 ordered values: ordinals 0..3 only.
    bad = _grant(KEY_HISTORY_WINDOW, 4)
    with pytest.raises(ResolverInputError, match="level grant ordinal out of range"):
        _fold((bad,))


def test_counter_grant_value_must_be_nonnegative() -> None:
    bad = _grant(KEY_MONITORED_URLS, -1)
    with pytest.raises(ResolverInputError, match="counter grant value negative"):
        _fold((bad,))


def test_no_capability_entitlement_is_the_fail_closed_shape() -> None:
    out = no_capability_entitlement(
        account_id=_ACCOUNT,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=3,
        at=_AT,
        errors=("billing_account_missing",),
    )
    assert out.status == STATUS_ENTITLEMENT_UNRESOLVED
    assert out.capabilities == ()
    assert out.capability_value(KEY_MONITORED_URLS) == 0
    assert out.valid_until is None
    assert out.errors == ("billing_account_missing",)


# =========================================================================
# Resolution algebra: flags OR / counters SUM / levels MAX
# =========================================================================
def test_flags_resolve_with_or() -> None:
    off = _grant(KEY_EXPORTS, 0)
    on = _grant(KEY_EXPORTS, 1, source_kind=GRANT_SOURCE_TRIAL)
    assert _fold((off, on)).capability_value(KEY_EXPORTS) == 1
    assert _fold((off,)).capability_value(KEY_EXPORTS) == 0


def test_counters_resolve_with_sum() -> None:
    a = _grant(KEY_MONITORED_URLS, 30)
    b = _grant(KEY_MONITORED_URLS, 20, source_kind=GRANT_SOURCE_ADDON)
    resolved = _fold((a, b)).capability(KEY_MONITORED_URLS)
    assert resolved is not None
    assert resolved.value == 50
    assert set(resolved.contributing_grant_ids) == {a.id, b.id}


def test_levels_resolve_with_max_never_sum() -> None:
    # HISTORY_WINDOW ordinals: unset=0, 90d=1, 12mo=2, 24mo=3.
    low = _grant(KEY_HISTORY_WINDOW, 1)
    high = _grant(KEY_HISTORY_WINDOW, 3, source_kind=GRANT_SOURCE_OVERRIDE)
    resolved = _fold((low, high)).capability(KEY_HISTORY_WINDOW)
    assert resolved is not None
    assert resolved.value == 3


# =========================================================================
# Boundary exclusion at the exact ``at``
# =========================================================================
def test_grant_starting_exactly_at_is_active_future_is_not() -> None:
    starts_now = _grant(KEY_MONITORED_URLS, 10, valid_from=_AT)
    starts_later = _grant(KEY_MONITORED_URLS, 20, valid_from=_AT + timedelta(seconds=1))
    assert _fold((starts_now,)).capability_value(KEY_MONITORED_URLS) == 10
    assert _fold((starts_later,)).capability_value(KEY_MONITORED_URLS) == 0


def test_grant_expiring_exactly_at_is_inactive() -> None:
    expires_now = _grant(KEY_MONITORED_URLS, 10, valid_until=_AT)
    expires_later = _grant(
        KEY_MONITORED_URLS, 20, valid_until=_AT + timedelta(seconds=1)
    )
    assert _fold((expires_now,)).capability_value(KEY_MONITORED_URLS) == 0
    assert _fold((expires_later,)).capability_value(KEY_MONITORED_URLS) == 20


def test_revocation_effective_exactly_at_excludes_the_grant() -> None:
    grant = _grant(KEY_MONITORED_URLS, 50)
    revoked_now = RevocationInput(grant_id=grant.id, effective_from=_AT)
    revoked_later = RevocationInput(
        grant_id=grant.id, effective_from=_AT + timedelta(seconds=1)
    )
    assert _fold((grant,), (revoked_now,)).capability_value(KEY_MONITORED_URLS) == 0
    assert _fold((grant,), (revoked_later,)).capability_value(KEY_MONITORED_URLS) == 50


def test_earliest_revocation_wins() -> None:
    grant = _grant(KEY_MONITORED_URLS, 50)
    later = RevocationInput(grant_id=grant.id, effective_from=_AT + timedelta(days=1))
    earlier = RevocationInput(grant_id=grant.id, effective_from=_AT - timedelta(days=1))
    assert _fold((grant,), (later, earlier)).capability_value(KEY_MONITORED_URLS) == 0


def test_valid_until_tracks_the_earliest_future_boundary() -> None:
    expiring = _grant(KEY_MONITORED_URLS, 10, valid_until=_AT + timedelta(days=7))
    open_ended = _grant(KEY_EXPORTS, 1)
    out = _fold((expiring, open_ended))
    assert out.valid_until == _AT + timedelta(days=7)
    capability = out.capability(KEY_MONITORED_URLS)
    assert capability is not None
    assert capability.next_change_at == _AT + timedelta(days=7)


# =========================================================================
# Total consumable draw order (expiry, source order, UUID tie-break)
# =========================================================================
def test_draw_order_is_expiry_then_source_order_then_uuid() -> None:
    expiry = _AT + timedelta(days=30)
    subscription_end = _AT + timedelta(days=60)
    trial = _grant(
        KEY_AUDIT_CREDITS, 1, source_kind=GRANT_SOURCE_TRIAL, valid_until=expiry
    )
    plan = _grant(
        KEY_AUDIT_CREDITS,
        2,
        source_kind=GRANT_SOURCE_PLAN,
        valid_until=expiry,
        grant_id=uuid.UUID("88888888-8888-4888-8888-888888888888"),
    )
    addon = _grant(
        KEY_AUDIT_CREDITS, 3, source_kind=GRANT_SOURCE_ADDON, valid_until=expiry
    )
    override = _grant(
        KEY_AUDIT_CREDITS, 4, source_kind=GRANT_SOURCE_OVERRIDE, valid_until=expiry
    )
    topup = _grant(
        KEY_AUDIT_CREDITS, 5, source_kind=GRANT_SOURCE_TOPUP, valid_until=expiry
    )
    # A non-expiring grant draws after every expiring grant.
    eternal = _grant(KEY_AUDIT_CREDITS, 6, source_kind=GRANT_SOURCE_PLAN)
    # Same source + same expiry: the UUID bytes break the tie.
    tie_high = _grant(
        KEY_AUDIT_CREDITS,
        7,
        source_kind=GRANT_SOURCE_PLAN,
        valid_until=expiry,
        grant_id=uuid.UUID("ffffffff-ffff-4fff-bfff-ffffffffffff"),
    )
    tie_low = _grant(
        KEY_AUDIT_CREDITS,
        8,
        source_kind=GRANT_SOURCE_PLAN,
        valid_until=expiry,
        grant_id=uuid.UUID("00000000-0000-4000-8000-000000000000"),
    )
    shuffled = (topup, eternal, override, tie_high, addon, plan, tie_low, trial)
    order = ordered_consumable_grants(shuffled, subscription_end)
    assert order == (
        trial.id,
        tie_low.id,
        plan.id,
        tie_high.id,
        addon.id,
        override.id,
        topup.id,
        eternal.id,
    )


def test_consumable_resolution_carries_the_draw_order() -> None:
    expiry = _AT + timedelta(days=30)
    subscription_end = _AT + timedelta(days=60)
    plan = _grant(
        KEY_AUDIT_CREDITS, 5, source_kind=GRANT_SOURCE_PLAN, valid_until=expiry
    )
    topup = _grant(
        KEY_AUDIT_CREDITS, 5, source_kind=GRANT_SOURCE_TOPUP, valid_until=expiry
    )
    resolved = _fold((topup, plan), subscription_end=subscription_end).capability(
        KEY_AUDIT_CREDITS
    )
    assert resolved is not None
    assert resolved.value == 10
    assert resolved.ordered_draw_grant_ids == (plan.id, topup.id)


# =========================================================================
# Top-up expiry is coupled to the readable base subscription end
# =========================================================================
def test_topup_without_a_subscription_end_is_never_active() -> None:
    topup = _grant(KEY_AUDIT_CREDITS, 100, source_kind=GRANT_SOURCE_TOPUP)
    assert effective_grant_expiry(topup, None) == datetime.min.replace(tzinfo=UTC)
    assert (
        _fold((topup,), subscription_end=None).capability_value(KEY_AUDIT_CREDITS) == 0
    )


def test_topup_expiry_is_the_min_of_valid_until_and_subscription_end() -> None:
    topup = _grant(
        KEY_AUDIT_CREDITS,
        100,
        source_kind=GRANT_SOURCE_TOPUP,
        valid_until=_AT + timedelta(days=30),
    )
    sooner = _AT + timedelta(days=10)
    later = _AT + timedelta(days=60)
    assert effective_grant_expiry(topup, sooner) == sooner
    assert effective_grant_expiry(topup, later) == _AT + timedelta(days=30)


def test_topup_expiry_moves_with_renewal_and_cancellation() -> None:
    topup = _grant(
        KEY_AUDIT_CREDITS,
        100,
        source_kind=GRANT_SOURCE_TOPUP,
        valid_until=_AT + timedelta(days=30),
    )
    # Active while the base subscription runs past ``at``.
    renewed = _AT + timedelta(days=15)
    assert (
        _fold((topup,), subscription_end=renewed).capability_value(KEY_AUDIT_CREDITS)
        == 100
    )
    # A cancellation removes the readable end: the top-up resolves unavailable.
    assert (
        _fold((topup,), subscription_end=None).capability_value(KEY_AUDIT_CREDITS) == 0
    )
    # A base end BEFORE ``at`` likewise leaves the top-up expired.
    lapsed = _AT - timedelta(days=1)
    assert (
        _fold((topup,), subscription_end=lapsed).capability_value(KEY_AUDIT_CREDITS)
        == 0
    )


# =========================================================================
# Purity: the fold never reads the clock or a provider
# =========================================================================
def test_fold_is_deterministic_and_clock_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grants = (_grant(KEY_MONITORED_URLS, 50), _grant(KEY_EXPORTS, 1))

    class _Boom:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"fold touched clock/global: {name}")

    # Any runtime clock/date access inside the fold explodes.
    monkeypatch.setattr("app.domain.entitlements.resolver.datetime", _Boom())
    first = _fold(grants)
    second = _fold(grants)
    assert first == second
    assert first.capability_value(KEY_MONITORED_URLS) == 50


# =========================================================================
# Bounded resolver cache
# =========================================================================
@pytest.fixture(autouse=True)
def _clear_entitlement_cache():
    entitlement_cache.clear_cache()
    yield
    entitlement_cache.clear_cache()


def _resolved(
    version: int,
    *,
    resolved_at: datetime = _AT,
    account_id: uuid.UUID = _ACCOUNT,
    valid_until: datetime | None = None,
) -> ResolvedEntitlement:
    return ResolvedEntitlement(
        account_id=account_id,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=version,
        resolved_at=resolved_at,
        valid_until=valid_until,
        status=STATUS_RESOLVED,
        capabilities=(),
        errors=(),
    )


def test_cache_hit_then_version_miss_then_revision_miss() -> None:
    entitlement_cache.put_cached(_resolved(version=1))
    hit = entitlement_cache.get_cached(
        account_id=_ACCOUNT,
        registry_revision=CAPABILITY_REGISTRY.revision,
        entitlement_lifecycle_version=1,
        at=_AT,
    )
    assert hit is not None
    # A grant/revocation/lifecycle write bumps the version: natural miss.
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=2,
            at=_AT,
        )
        is None
    )
    # A registry revision change also misses naturally.
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision="entitlements-v2",
            entitlement_lifecycle_version=1,
            at=_AT,
        )
        is None
    )


def test_cache_entry_older_than_the_max_ttl_is_not_served() -> None:
    old = _resolved(version=1, resolved_at=_AT)
    entitlement_cache.put_cached(old)
    later = _AT + timedelta(seconds=ENTITLEMENT_CACHE_MAX_TTL_SECONDS)
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=later,
        )
        is None
    )
    just_inside = _AT + timedelta(seconds=ENTITLEMENT_CACHE_MAX_TTL_SECONDS - 1)
    entitlement_cache.put_cached(old)
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=just_inside,
        )
        is not None
    )


def test_cache_entry_past_its_valid_until_is_not_served() -> None:
    boundary = _AT + timedelta(minutes=5)
    entry = _resolved(version=1, valid_until=boundary)
    entitlement_cache.put_cached(entry)
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=boundary,
        )
        is None
    )


def test_cache_lru_eviction_bounds_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(entitlement_cache, "ENTITLEMENT_CACHE_MAX_ENTRIES", 2)
    other_account = uuid.uuid4()
    entitlement_cache.put_cached(_resolved(version=1))
    entitlement_cache.put_cached(_resolved(version=1, account_id=other_account))
    entitlement_cache.put_cached(_resolved(version=2))
    # The first account's v1 entry was evicted (LRU), the newer two remain.
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=_AT,
        )
        is None
    )
    assert (
        entitlement_cache.get_cached(
            account_id=other_account,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=_AT,
        )
        is not None
    )


def test_invalidate_account_and_registry() -> None:
    entitlement_cache.put_cached(_resolved(version=1))
    entitlement_cache.invalidate_account(_ACCOUNT)
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=_AT,
        )
        is None
    )
    entitlement_cache.put_cached(_resolved(version=1))
    entitlement_cache.invalidate_registry(CAPABILITY_REGISTRY.revision)
    assert (
        entitlement_cache.get_cached(
            account_id=_ACCOUNT,
            registry_revision=CAPABILITY_REGISTRY.revision,
            entitlement_lifecycle_version=1,
            at=_AT,
        )
        is None
    )
