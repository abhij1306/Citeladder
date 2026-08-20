# Provider capacity acquisition (T4): Postgres-authoritative pool pacing.
#
# Every provider call start draws on a fixed set of shared pools
# (``ProviderCapacityBucket`` rows): the per-transport pool, the BYOK
# per-credential pool, or — for platform credentials — the funded-global and
# funded-account pools. ``acquire_provider_capacity`` locks those buckets in a
# STABLE canonical order (transport -> connection -> funded-global ->
# funded-account) inside one transaction, so concurrent workers across
# replicas can never deadlock on inverted lock order and can never overshoot a
# pool's concurrency ceiling (effective concurrency is the sum of non-expired,
# non-released lease units — expired leases recover capacity after crashes).
#
# The transport bucket additionally paces CALL STARTS with a token bucket
# whose rates come from the route-owned config
# (``route_capacity_policy``; route identity is ``(logical_engine,
# transport_provider)``). Unverified provider rates stay UNSET (None): funded
# acquisition then fails CLOSED (``capacity_unconfigured``) and BYOK runs
# concurrency-only until real rates are configured. Token starts are consumed
# at acquire time and are NEVER returned on release; only concurrency leases
# are released. A 429 outcome writes ``blocked_until`` on every pool the
# request drew from so sibling audits observe the shared cooldown.
#
# Insufficient capacity never raises: it returns a parked ``CapacityDecision``
# (``capacity_wait`` + ``available_at``, reusing the task's existing
# queued-state column) and emits ``audit.capacity.wait`` /
# ``audit.capacity.rate_limited`` telemetry carrying ONLY pool kind,
# transport, opaque task/account ids, and retry timing — never credentials,
# prompts, or provider bodies (invariant 6).
#
# Database decisions are authoritative across replicas. No process-local
# semaphore layer exists: it would add complexity without changing any
# decision the database already makes.
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    CAPACITY_CODE_CONCURRENCY,
    CAPACITY_CODE_RATE_LIMITED,
    CAPACITY_CODE_UNCONFIGURED,
    CAPACITY_OUTCOME_FAILED,
    CAPACITY_OUTCOME_RATE_LIMITED,
    CAPACITY_OUTCOME_SUCCEEDED,
    CAPACITY_POLICY_VERSION,
    CREDENTIAL_KIND_BYOK,
    CREDENTIAL_KIND_FUNDED,
    CREDENTIAL_KINDS,
    LEASE_KIND_CONCURRENCY,
    POOL_KIND_CONNECTION,
    POOL_KIND_FUNDED_ACCOUNT,
    POOL_KIND_FUNDED_GLOBAL,
    POOL_KIND_TRANSPORT,
    TELEMETRY_CAPACITY_RATE_LIMITED,
    TELEMETRY_CAPACITY_WAIT,
    audit_settings,
)
from app.core.config.provider_catalog import (
    RouteCapacityPolicy,
    route_capacity_policy,
)
from app.core.config.task_queue import TASK_STATUS_CAPACITY_WAIT
from app.models.audit import ProviderCapacityBucket, ProviderCapacityLease

logger = logging.getLogger("app.orchestration.provider_capacity")

_ONE = Decimal("1")
_ZERO = Decimal("0")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class CapacityRequest:
    """One task attempt's demand for provider capacity (frozen contract).

    ``credential_kind`` selects the pool set: BYOK draws transport +
    connection; funded draws transport + funded-global + funded-account.
    Carries opaque ids only — never a credential, prompt, or provider body.
    """

    task_id: uuid.UUID
    attempt_number: int
    logical_engine: str
    transport_provider: str
    credential_kind: str  # CREDENTIAL_KIND_* vocabulary
    connection_id: uuid.UUID | None = None
    billing_account_id: uuid.UUID | None = None
    units: Decimal = _ONE

    def __post_init__(self) -> None:
        if self.credential_kind not in CREDENTIAL_KINDS:
            raise ValueError(
                f"unknown credential_kind {self.credential_kind!r}; "
                f"expected one of {sorted(CREDENTIAL_KINDS)}"
            )
        if self.credential_kind == CREDENTIAL_KIND_FUNDED:
            if self.billing_account_id is None:
                raise ValueError("funded requests require billing_account_id")
        elif self.credential_kind == CREDENTIAL_KIND_BYOK:
            if self.connection_id is None:
                raise ValueError("BYOK requests require connection_id")
        if self.units <= 0:
            raise ValueError(f"units must be positive, got {self.units}")


@dataclass(frozen=True, slots=True)
class CapacityDecision:
    """The DB-authoritative outcome of one acquisition attempt (frozen).

    ``acquired=True`` carries the held ``lease_ids`` for correlation. A parked
    decision carries everything the worker needs to park the task:
    ``task_status`` (always ``capacity_wait``) + ``available_at`` (the
    existing queued-state column — no duplicate column), the safe ``code``,
    the blocking ``pool_kind``, and the retry timing.
    """

    acquired: bool
    task_status: str | None = None
    available_at: datetime | None = None
    retry_after_seconds: float | None = None
    code: str = ""  # CAPACITY_CODE_* when parked
    pool_kind: str = ""  # pool that blocked (telemetry only)
    lease_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class CapacityOutcome:
    """How one held acquisition finished (frozen contract).

    ``retry_after_seconds`` is the provider-advised ``Retry-After`` hint —
    UNTRUSTED input, always clamped to the route's configured max cooldown
    before it becomes a shared ``blocked_until``.
    """

    kind: str  # CAPACITY_OUTCOME_* vocabulary
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        known = {
            CAPACITY_OUTCOME_SUCCEEDED,
            CAPACITY_OUTCOME_FAILED,
            CAPACITY_OUTCOME_RATE_LIMITED,
        }
        if self.kind not in known:
            raise ValueError(
                f"unknown outcome kind {self.kind!r}; expected one of {sorted(known)}"
            )


@dataclass(frozen=True, slots=True)
class _BucketSpec:
    """Which pool row a request draws on (identity minus transport)."""

    pool_kind: str
    connection_id: uuid.UUID | None = None
    billing_account_id: uuid.UUID | None = None


def _bucket_specs(request: CapacityRequest) -> tuple[_BucketSpec, ...]:
    """The pools one request draws on, in THE canonical lock order.

    transport -> connection -> funded-global -> funded-account (BYOK stops
    after connection). Every acquirer locks in this exact order, so two
    workers can never hold inverted locks and deadlock.
    """
    transport = _BucketSpec(POOL_KIND_TRANSPORT)
    if request.credential_kind == CREDENTIAL_KIND_FUNDED:
        return (
            transport,
            _BucketSpec(POOL_KIND_FUNDED_GLOBAL),
            _BucketSpec(
                POOL_KIND_FUNDED_ACCOUNT,
                billing_account_id=request.billing_account_id,
            ),
        )
    return (
        transport,
        _BucketSpec(POOL_KIND_CONNECTION, connection_id=request.connection_id),
    )


def _concurrency_ceiling(pool_kind: str) -> Decimal:
    """Config-owned concurrency ceiling for one pool kind (invariant 1).

    The connection pool shares the transport envelope: one credential may not
    exceed the per-transport concurrency bound.
    """
    if pool_kind == POOL_KIND_FUNDED_GLOBAL:
        return Decimal(audit_settings.funded_pool_max_concurrency)
    if pool_kind == POOL_KIND_FUNDED_ACCOUNT:
        return Decimal(audit_settings.funded_pool_per_account)
    return Decimal(audit_settings.per_transport_concurrency)


def _configured_refill(route_policy: RouteCapacityPolicy) -> Decimal | None:
    """The configured token refill rate, or None while rates are unverified."""
    if route_policy.refill_tokens_per_second is None:
        return None
    return Decimal(str(route_policy.refill_tokens_per_second))


def _identity_filter(request: CapacityRequest, spec: _BucketSpec) -> tuple:
    """WHERE clauses matching one bucket's unique identity (NULL-safe)."""
    return (
        ProviderCapacityBucket.pool_kind == spec.pool_kind,
        ProviderCapacityBucket.transport_provider == request.transport_provider,
        ProviderCapacityBucket.connection_id.is_(None)
        if spec.connection_id is None
        else ProviderCapacityBucket.connection_id == spec.connection_id,
        ProviderCapacityBucket.billing_account_id.is_(None)
        if spec.billing_account_id is None
        else ProviderCapacityBucket.billing_account_id == spec.billing_account_id,
    )


def _sync_bucket_policy(
    bucket: ProviderCapacityBucket,
    *,
    spec: _BucketSpec,
    route_policy: RouteCapacityPolicy,
) -> None:
    """Converge a locked bucket onto the live config (policy_version drift).

    Bucket rows are created once but config is the owner of every knob
    (invariant 1): a stale row re-syncs its ceiling/refill at acquire time
    rather than pacing by forgotten numbers.
    """
    ceiling = _concurrency_ceiling(spec.pool_kind)
    if bucket.capacity != ceiling:
        bucket.capacity = ceiling
        bucket.policy_version = CAPACITY_POLICY_VERSION
    if spec.pool_kind == POOL_KIND_TRANSPORT:
        refill = _configured_refill(route_policy) or _ZERO
        if bucket.refill_tokens_per_second != refill:
            bucket.refill_tokens_per_second = refill
            bucket.policy_version = CAPACITY_POLICY_VERSION


async def _lock_buckets(
    session: AsyncSession,
    *,
    request: CapacityRequest,
    specs: tuple[_BucketSpec, ...],
    route_policy: RouteCapacityPolicy,
    now: datetime,
) -> list[ProviderCapacityBucket]:
    """Insert-if-missing, then lock every bucket row in canonical order.

    The ``FOR UPDATE`` row locks serialize acquirers per pool within this one
    transaction, which is what makes check+acquire atomic across replicas.
    """
    buckets: list[ProviderCapacityBucket] = []
    for spec in specs:
        await session.execute(
            pg_insert(ProviderCapacityBucket)
            .values(
                id=uuid.uuid4(),
                pool_kind=spec.pool_kind,
                transport_provider=request.transport_provider,
                connection_id=spec.connection_id,
                billing_account_id=spec.billing_account_id,
                capacity=_concurrency_ceiling(spec.pool_kind),
                tokens=Decimal(str(route_policy.capacity))
                if spec.pool_kind == POOL_KIND_TRANSPORT
                and route_policy.capacity is not None
                else _ZERO,
                refill_tokens_per_second=_configured_refill(route_policy) or _ZERO,
                refilled_at=now,
                policy_version=CAPACITY_POLICY_VERSION,
            )
            .on_conflict_do_nothing()
        )
        bucket = await session.scalar(
            select(ProviderCapacityBucket)
            .where(*_identity_filter(request, spec))
            .with_for_update()
        )
        assert bucket is not None  # just inserted-or-existed; same transaction
        _sync_bucket_policy(bucket, spec=spec, route_policy=route_policy)
        buckets.append(bucket)
    return buckets


async def _lock_existing_buckets(
    session: AsyncSession,
    *,
    request: CapacityRequest,
    specs: tuple[_BucketSpec, ...],
) -> list[ProviderCapacityBucket]:
    """Lock the request's existing bucket rows in canonical order (release)."""
    buckets: list[ProviderCapacityBucket] = []
    for spec in specs:
        bucket = await session.scalar(
            select(ProviderCapacityBucket)
            .where(*_identity_filter(request, spec))
            .with_for_update()
        )
        if bucket is not None:
            buckets.append(bucket)
    return buckets


async def _active_units(
    session: AsyncSession, bucket_id: uuid.UUID, now: datetime
) -> Decimal:
    """Effective concurrency: non-expired, non-released lease units.

    Expired leases simply stop counting — that is the crash-recovery path
    (a dead worker's slots free themselves at ``expires_at``).
    """
    total = await session.scalar(
        select(func.coalesce(func.sum(ProviderCapacityLease.units), 0)).where(
            ProviderCapacityLease.bucket_id == bucket_id,
            ProviderCapacityLease.released_at.is_(None),
            ProviderCapacityLease.expires_at > now,
        )
    )
    return _ZERO if total is None else Decimal(str(total))


def _parked(
    *, code: str, pool_kind: str, retry_at: datetime, now: datetime
) -> CapacityDecision:
    """A refusal decision that parks the task in ``capacity_wait``."""
    return CapacityDecision(
        acquired=False,
        task_status=TASK_STATUS_CAPACITY_WAIT,
        available_at=retry_at,
        retry_after_seconds=max(0.0, (retry_at - now).total_seconds()),
        code=code,
        pool_kind=pool_kind,
    )


def _refill_tokens(
    bucket: ProviderCapacityBucket, *, route_policy: RouteCapacityPolicy, now: datetime
) -> None:
    """Advance the transport bucket's token balance to ``now`` (lazy refill)."""
    cap = Decimal(str(route_policy.capacity))
    rate = _configured_refill(route_policy) or _ZERO
    elapsed = max(0.0, (now - bucket.refilled_at).total_seconds())
    bucket.tokens = min(cap, Decimal(str(bucket.tokens)) + Decimal(str(elapsed)) * rate)
    bucket.refilled_at = now


def _pacing_refusal(
    *,
    request: CapacityRequest,
    bucket: ProviderCapacityBucket,
    route_policy: RouteCapacityPolicy,
    now: datetime,
) -> CapacityDecision | None:
    """Token-bucket pacing on the transport pool (fails closed when unset).

    Unverified route rates (None) park FUNDED work with
    ``capacity_unconfigured``; BYOK runs concurrency-only until configured.
    """
    if route_policy.capacity is None or route_policy.refill_tokens_per_second is None:
        if request.credential_kind == CREDENTIAL_KIND_FUNDED:
            return _parked(
                code=CAPACITY_CODE_UNCONFIGURED,
                pool_kind=POOL_KIND_TRANSPORT,
                retry_at=now + timedelta(seconds=route_policy.max_cooldown_seconds),
                now=now,
            )
        return None
    _refill_tokens(bucket, route_policy=route_policy, now=now)
    if Decimal(str(bucket.tokens)) >= request.units:
        return None
    rate = float(bucket.refill_tokens_per_second)
    shortfall = float(request.units - Decimal(str(bucket.tokens)))
    retry = shortfall / rate if rate > 0 else route_policy.max_cooldown_seconds
    return _parked(
        code=CAPACITY_CODE_RATE_LIMITED,
        pool_kind=POOL_KIND_TRANSPORT,
        retry_at=now + timedelta(seconds=retry),
        now=now,
    )


async def _first_refusal(
    session: AsyncSession,
    *,
    request: CapacityRequest,
    specs: tuple[_BucketSpec, ...],
    buckets: list[ProviderCapacityBucket],
    route_policy: RouteCapacityPolicy,
    now: datetime,
) -> CapacityDecision | None:
    """The first blocking pool's refusal, checking in canonical order."""
    for spec, bucket in zip(specs, buckets, strict=True):
        if bucket.blocked_until is not None and bucket.blocked_until > now:
            return _parked(
                code=CAPACITY_CODE_RATE_LIMITED,
                pool_kind=spec.pool_kind,
                retry_at=bucket.blocked_until,
                now=now,
            )
        active = await _active_units(session, bucket.id, now)
        if active + request.units > bucket.capacity:
            return _parked(
                code=CAPACITY_CODE_CONCURRENCY,
                pool_kind=spec.pool_kind,
                retry_at=now
                + timedelta(seconds=audit_settings.capacity_concurrency_retry_seconds),
                now=now,
            )
        if spec.pool_kind == POOL_KIND_TRANSPORT:
            refusal = _pacing_refusal(
                request=request, bucket=bucket, route_policy=route_policy, now=now
            )
            if refusal is not None:
                return refusal
    return None


async def _consume(
    session: AsyncSession,
    *,
    request: CapacityRequest,
    buckets: list[ProviderCapacityBucket],
    route_policy: RouteCapacityPolicy,
    now: datetime,
) -> tuple[uuid.UUID, ...]:
    """Take the concurrency leases + the (transport-only) token start.

    Lease insert is idempotent per (bucket, task, attempt, kind): a re-acquire
    of the same attempt refreshes the existing lease instead of
    double-counting. Token starts stay consumed — release never credits them.
    """
    expires = now + timedelta(seconds=audit_settings.capacity_lease_ttl_seconds)
    lease_ids: list[uuid.UUID] = []
    for bucket in buckets:
        lease = await session.scalar(
            select(ProviderCapacityLease).where(
                ProviderCapacityLease.bucket_id == bucket.id,
                ProviderCapacityLease.task_id == request.task_id,
                ProviderCapacityLease.attempt_number == request.attempt_number,
                ProviderCapacityLease.lease_kind == LEASE_KIND_CONCURRENCY,
            )
        )
        if lease is None:
            lease = ProviderCapacityLease(
                bucket_id=bucket.id,
                task_id=request.task_id,
                attempt_number=request.attempt_number,
                lease_kind=LEASE_KIND_CONCURRENCY,
                units=request.units,
                expires_at=expires,
            )
            session.add(lease)
            await session.flush()
        else:
            lease.released_at = None
            lease.units = request.units
            lease.expires_at = expires
        lease_ids.append(lease.id)
    configured = (
        route_policy.capacity is not None
        and route_policy.refill_tokens_per_second is not None
    )
    if configured and buckets:
        transport_bucket = buckets[0]
        transport_bucket.tokens = Decimal(str(transport_bucket.tokens)) - request.units
    return tuple(lease_ids)


def _emit_capacity_event(
    *, request: CapacityRequest, decision: CapacityDecision
) -> None:
    """Structured capacity telemetry: pool/ids/retry timing ONLY (invariant 6)."""
    event = (
        TELEMETRY_CAPACITY_RATE_LIMITED
        if decision.code in (CAPACITY_CODE_RATE_LIMITED, CAPACITY_CODE_UNCONFIGURED)
        else TELEMETRY_CAPACITY_WAIT
    )
    logger.info(
        event + " pool_kind=%s transport_provider=%s task_id=%s account_id=%s "
        "retry_after_seconds=%.3f",
        decision.pool_kind,
        request.transport_provider,
        request.task_id,
        request.billing_account_id or "",
        decision.retry_after_seconds or 0.0,
    )


async def acquire_provider_capacity(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request: CapacityRequest,
    at: datetime | None = None,
) -> CapacityDecision:
    """Atomically acquire provider capacity for one task attempt.

    Locks the request's buckets in canonical order inside one transaction and
    either takes concurrency leases (plus a token start on the transport pool
    when the route is configured) or returns a parked decision carrying
    ``capacity_wait`` + ``available_at``. Never raises for insufficient
    capacity — only for invalid requests (unknown route/kind).
    """
    now = at or _utcnow()
    route_policy = route_capacity_policy(
        request.logical_engine, request.transport_provider
    )
    specs = _bucket_specs(request)
    async with session_factory() as session:
        buckets = await _lock_buckets(
            session,
            request=request,
            specs=specs,
            route_policy=route_policy,
            now=now,
        )
        refusal = await _first_refusal(
            session,
            request=request,
            specs=specs,
            buckets=buckets,
            route_policy=route_policy,
            now=now,
        )
        if refusal is not None:
            await session.commit()
            _emit_capacity_event(request=request, decision=refusal)
            return refusal
        lease_ids = await _consume(
            session,
            request=request,
            buckets=buckets,
            route_policy=route_policy,
            now=now,
        )
        await session.commit()
        return CapacityDecision(acquired=True, lease_ids=lease_ids)


def _safe_cooldown_seconds(
    *, request: CapacityRequest, outcome: CapacityOutcome
) -> float:
    """429 cooldown: provider Retry-After clamped to the route's max cooldown.

    With no provider guidance the route's configured max cooldown applies
    (the fail-safe configured backoff).
    """
    cap = route_capacity_policy(
        request.logical_engine, request.transport_provider
    ).max_cooldown_seconds
    if outcome.retry_after_seconds is None:
        return cap
    return min(max(outcome.retry_after_seconds, 0.0), cap)


async def release_provider_capacity(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    request: CapacityRequest,
    outcome: CapacityOutcome,
    at: datetime | None = None,
) -> None:
    """Release one attempt's concurrency leases; token starts stay consumed.

    On a 429 outcome, every pool the request drew from gets its
    ``blocked_until`` raised to the safe cooldown horizon (never lowered, so a
    later 429 cannot shorten a sibling's longer cooldown), making the
    cooldown visible to every sibling acquisition. Idempotent: already
    released leases are left untouched.
    """
    now = at or _utcnow()
    specs = _bucket_specs(request)
    async with session_factory() as session:
        buckets = await _lock_existing_buckets(session, request=request, specs=specs)
        leases = list(
            (
                await session.scalars(
                    select(ProviderCapacityLease).where(
                        ProviderCapacityLease.task_id == request.task_id,
                        ProviderCapacityLease.attempt_number == request.attempt_number,
                        ProviderCapacityLease.lease_kind == LEASE_KIND_CONCURRENCY,
                        ProviderCapacityLease.released_at.is_(None),
                        ProviderCapacityLease.bucket_id.in_([b.id for b in buckets]),
                    )
                )
            ).all()
        )
        for lease in leases:
            lease.released_at = now
        if outcome.kind == CAPACITY_OUTCOME_RATE_LIMITED and buckets:
            cooldown = _safe_cooldown_seconds(request=request, outcome=outcome)
            until = now + timedelta(seconds=cooldown)
            for bucket in buckets:
                if bucket.blocked_until is None or bucket.blocked_until < until:
                    bucket.blocked_until = until
            logger.info(
                TELEMETRY_CAPACITY_RATE_LIMITED
                + " transport_provider=%s task_id=%s account_id=%s "
                "retry_after_seconds=%.3f",
                request.transport_provider,
                request.task_id,
                request.billing_account_id or "",
                cooldown,
            )
        await session.commit()
