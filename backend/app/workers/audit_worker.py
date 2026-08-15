# Audit worker: the Postgres-queue claim/lease execution loop (invariant 8).
#
# A separate process (the ``worker`` compose service). It claims ``AuditTask``
# rows via ``PostgresTaskQueue`` (``FOR UPDATE SKIP LOCKED``, lease committed
# BEFORE any network I/O), resolves the decrypted BYOK key from the task's
# ``ProviderConnection`` at execution time (never env, never logged — invariant
# 6), builds the answer-engine adapter, and calls it with request pacing and a
# hard per-call ceiling. ONE queue attempt makes ONE external call
# (``call_provider_once``): the queue's retry/backoff is the SOLE retry loop,
# bounded by the task's frozen ``max_attempts``. Before the call it acquires
# provider capacity (``app.orchestration.provider_capacity``) — a refusal
# parks the task in ``capacity_wait`` without spending an attempt — and after
# the call it releases capacity with the outcome (a provider 429 writes the
# shared cooldown). Each actual call appends one immutable ``ProviderAttempt``
# and, for a FUNDED task (frozen reservation in the task's route snapshot),
# bills exactly one ledger unit — a timed-out call bills too — with the
# task's unused reservation released at terminalization. A successful call
# persists an immutable ``RawResponseArtifact`` plus the task's execution
# fields (single writer = the claiming worker — invariant 3). It heartbeats
# the lease while a call runs, drives the audit lifecycle (QUEUED -> RUNNING,
# then RUNNING -> ANALYZING / FAILED at the execution boundary), and honors
# cooperative cancel + the per-run wall-clock deadline at each task boundary
# (invariant 9).
#
# Scoring/analysis is B6's job: this worker persists the raw answer + citations
# and hands a finished-execution audit off at ``analyzing``.
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.product_service import (
    analyze_task_products,
    build_product_scoring_config,
    finalize_audit_product_analysis,
)
from app.analysis.service import (
    analyze_task,
    build_scoring_config,
    finalize_audit_analysis,
)
from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
)
from app.connectors.answer_engines.errors import ProviderError
from app.connectors.answer_engines.factory import build_adapter
from app.connectors.answer_engines.http_client import aclose_shared_clients
from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCEEDED,
    AUDIT_QUEUE_SPEC,
    AUDIT_STATUS_ANALYZING,
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_FAILED,
    AUDIT_STATUS_QUEUED,
    AUDIT_STATUS_RUNNING,
    AUDIT_TERMINAL_STATUSES,
    CAPACITY_OUTCOME_FAILED,
    ERROR_RUN_DEADLINE,
    EVENT_AUDIT_RUNNING,
    EVENT_TASK_CAPACITY_WAIT,
    EVENT_TASK_FAILED,
    EVENT_TASK_RETRY,
    EVENT_TASK_SUCCEEDED,
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
    audit_settings,
    max_run_seconds_from_configuration,
    measurement_policy_from_configuration,
)
from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.core.config.costs import (
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    RouteIdentity,
    route_pricing_for,
)
from app.core.config.provider_catalog import (
    ERROR_AUTH,
    ERROR_PARSE,
    RETRYABLE_ERRORS,
)
from app.core.config.task_queue import DEFAULT_MAX_DRAIN_BATCHES
from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.core.telemetry import configure_logging
from app.domain.audits.cost_projection import build_execution_cost_projection
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.entitlements.ledger import (
    record_billable_attempt,
    release_terminal_funded_task,
)
from app.domain.opportunities.verification import enqueue_audit_opportunity_tasks
from app.domain.providers.credentials import pause_connection_after_key_failure
from app.models.audit import (
    Audit,
    AuditEvent,
    AuditTask,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.models.provider import ProviderConnection
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.orchestration.provider_capacity import (
    CapacityDecision,
    CapacityOutcome,
    CapacityRequest,
    acquire_provider_capacity,
    release_provider_capacity,
)
from app.workers import audit_worker_support as _support
from app.workers.drain import DrainableWorkerMixin

logger = logging.getLogger("app.workers.audit_worker")

# Compatibility re-exports for worker-level tests and existing private callers.
CallAttempt = _support.CallAttempt
_ExecutionContext = _support.ExecutionContext
_FrozenFunding = _support.FrozenFunding
_apply_response_to_task = _support.apply_response_to_task
_build_artifact = _support.build_artifact
_build_call_request = _support.build_call_request
_build_request = _support.build_request
_build_request_snapshot = _support.build_request_snapshot
_capacity_outcome = _support.capacity_outcome
_capacity_request = _support.capacity_request
_capacity_wait_payload = _support.capacity_wait_payload
_drain_horizon_seconds = _support.drain_horizon_seconds
_frozen_connection_id_from = _support.frozen_connection_id_from
_frozen_funding_from = _support.frozen_funding_from
_raw_finish_reason = _support.raw_finish_reason
_serialize_citations = _support.serialize_citations
_serialize_search_events = _support.serialize_search_events
_terminal_rejection = _support.terminal_rejection
_utcnow = _support.utcnow
_warn_if_provider_pacing_unbounded = _support.warn_if_provider_pacing_unbounded
assert_worker_pool_capacity = _support.assert_worker_pool_capacity
pace_provider_request = _support.pace_provider_request

__all__ = [
    "AuditWorker",
    "CallAttempt",
    "_ExecutionContext",
    "_FrozenFunding",
    "_apply_response_to_task",
    "_build_artifact",
    "_build_call_request",
    "_build_request",
    "_build_request_snapshot",
    "_capacity_outcome",
    "_capacity_request",
    "_capacity_wait_payload",
    "_drain_horizon_seconds",
    "_frozen_connection_id_from",
    "_frozen_funding_from",
    "_raw_finish_reason",
    "_serialize_citations",
    "_serialize_search_events",
    "_terminal_rejection",
    "_utcnow",
    "_warn_if_provider_pacing_unbounded",
    "assert_worker_pool_capacity",
    "call_provider_once",
    "pace_provider_request",
]

# Statuses a task may hold while the PRE-CALL writers act on it. The row is
# still `leased` (not `running`) until provider capacity is held, so the
# terminal-rejection / adapter-failure / capacity-park paths must accept it;
# `running` stays accepted because a retry re-enters those paths.
TASK_PRE_CALL_STATUSES = frozenset({TASK_STATUS_LEASED, TASK_STATUS_RUNNING})


async def call_provider_once(
    adapter, request: AnswerEngineRequest, *, timeout_seconds: float
) -> CallAttempt:
    """Compatibility seam that keeps worker-level pacing monkeypatchable."""
    return await _support.call_provider_once(
        adapter,
        request,
        timeout_seconds=timeout_seconds,
        pace_request=pace_provider_request,
    )


class AuditWorker(DrainableWorkerMixin):
    """Owns a claim/lease loop against ``PostgresTaskQueue``.

    A single worker claims up to ``worker_concurrency`` tasks per poll and runs
    them CONCURRENTLY (``asyncio.gather``), each task inside its own short-lived
    sessions — a session is never shared across tasks (sharing an async session
    across concurrent tasks corrupts session state) and never held open across a
    provider call. Cross-task coordination happens in the database:
    ``_lock_owned_running_task`` row-locks before any evidence write and
    ``_finalize_audit`` is ``FOR UPDATE``-guarded, both already built for
    multi-worker races.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue = PostgresTaskQueue(self._session_factory, AUDIT_QUEUE_SPEC)
        self.owner = owner or f"worker-{uuid.uuid4().hex[:12]}"
        # Shared across this worker's concurrency slots — see _sweep_expired_leases.
        self._sweep_lock = asyncio.Lock()
        self._last_sweep_at: float | None = None

    async def _sweep_expired_leases(self) -> None:
        """Release expired leases, at most once per poll interval per worker.

        Every slot sweeps before every claim, so at concurrency N an unthrottled
        sweep means N UPDATEs across the leased rows per claim cycle — and a fast
        task makes that cycle tight. The lease TTL is measured in minutes, so
        sweeping more often than the poll interval buys nothing.

        The gate is shared worker state rather than per-slot: the point is one
        sweep for the whole pool, not one per slot. The timestamp is advanced
        before the await so concurrent slots queued on the lock skip their turn,
        and a failed sweep simply waits out the interval (the caller logs it, and
        the lease TTL is orders of magnitude longer).
        """
        interval = max(0.05, audit_settings.poll_interval_seconds)
        async with self._sweep_lock:
            now = time.monotonic()
            if self._last_sweep_at is not None and now - self._last_sweep_at < interval:
                return
            self._last_sweep_at = now
            await self._sweep_queue()

    async def _sweep_queue(self) -> None:
        """Release expired leases and reconcile swept funded reservations.

        The queue sweeper is billing-agnostic BY DESIGN: a task it
        terminalizes at max attempts (a crash-looping worker) never gets a
        funded release from any worker path, so the sweep only REPORTS those
        ids. The audit worker — the sweep's caller and the billing-aware
        owner on this path — releases each terminalized funded task's unused
        reservation here so a crash loop can never leak credits.
        """
        sweep = await self._queue.release_expired_detailed()
        await self._release_swept_funded_tasks(sweep.failed_task_ids)

    async def _release_swept_funded_tasks(
        self, failed_task_ids: tuple[uuid.UUID, ...]
    ) -> None:
        """Funded-ledger janitor for sweeper-terminalized tasks."""
        for task_id in failed_task_ids:
            await self._release_terminalized_funded_task(task_id, trigger="sweep")

    async def _release_terminalized_funded_task(
        self, task_id: uuid.UUID, *, trigger: str
    ) -> None:
        """Best-effort release of one terminalized task's funded reservation.

        The task is already terminal, so nothing will bill its still-reserved
        units again; a BYOK task has no frozen funding block and is skipped.
        Idempotent per deterministic trigger key: a same-key IntegrityError
        is the ledger's designed race guard (a concurrent releaser won) and
        is logged, never raised — terminalization never depends on this.
        """
        try:
            async with self._session_factory() as session:
                task = await session.get(AuditTask, task_id)
                funding = _frozen_funding_from(
                    task.provider_route_snapshot if task is not None else None
                )
                if task is not None and funding is not None:
                    await release_terminal_funded_task(
                        session,
                        reservation_id=funding.reservation_id,
                        audit_id=task.audit_id,
                        task_id=task.id,
                        trigger=trigger,
                        at=_utcnow(),
                    )
                await session.commit()
        except IntegrityError:
            logger.info(
                "funded release already settled by a concurrent releaser",
                extra={"task_id": str(task_id), "trigger": trigger},
            )
        except Exception:
            logger.exception(
                "funded release for a terminalized task failed",
                extra={"task_id": str(task_id), "trigger": trigger},
            )

    async def run_once(self) -> int:
        """Sweep expired leases, claim a batch, execute it. Returns count run.

        The claimed batch executes concurrently — per-prompt provider calls
        take tens of seconds, so serial execution would make a run's wall-clock
        time scale linearly with its task count. ``_execute_task`` catches and
        records its own crashes, but its cleanup (crash recording / audit
        finalization) can itself raise (e.g. DB connection loss) — gather with
        ``return_exceptions=True`` so one task's cleanup failure never abandons
        the rest of the batch mid-flight; every claimed task completes before
        this method returns.
        """
        await self._sweep_queue()
        tasks = await self._queue.claim(
            owner=self.owner,
            limit=max(1, audit_settings.worker_concurrency),
        )
        if tasks:
            results = await asyncio.gather(
                *(self._execute_task(task) for task in tasks),
                return_exceptions=True,
            )
            for task, result in zip(tasks, results, strict=True):
                if isinstance(result, BaseException):
                    logger.error(
                        "audit task cleanup failed",
                        exc_info=result,
                        extra={"task_id": str(task.id)},
                    )
        return len(tasks)

    async def run_pipelined(self, *, drain: bool) -> int:
        """Keep ``worker_concurrency`` calls in flight, refilling as each lands.

        This is the throughput path, and it exists because ``run_once``'s
        lock-step batching has a convoy problem. Claiming N tasks, gathering ALL
        of them, then claiming the next N means a batch takes as long as its
        SLOWEST member while its finished slots sit idle. Provider latency is
        wildly uneven — measured Claude calls on one run ranged 3.4s to 46.3s,
        because latency tracks the answer's output-token count — so the spread
        within a batch is the common case, not the exception.

        A free-tier run is 10 prompts x 3 providers = 30 calls. Over that many
        tasks the difference is large: with the batch loop the run costs
        ``sum(slowest per batch)``, with a refilling pool it approaches
        ``sum(all) / concurrency``.

        Each slot claims exactly one task, so in-flight work never exceeds the
        configured concurrency. Per-task crashes stay isolated the same way
        ``run_once`` isolates them: ``_execute_task`` records its own failures,
        and a raising cleanup path is logged rather than allowed to cancel the
        sibling tasks still talking to providers.

        With ``drain=True`` every slot stops as soon as a claim comes back empty
        (one-shot / test mode). With ``drain=False`` slots keep polling, which is
        the long-running worker.
        """
        concurrency = max(1, audit_settings.worker_concurrency)
        completed = 0

        async def slot() -> None:
            # Each slot decides for ITSELF when to stop. Deliberately no shared
            # idle flag: one slot seeing an empty queue must not make its
            # siblings skip their next claim, or work that arrived a moment
            # later is left sitting while the pool winds down.
            nonlocal completed
            while True:
                claimed = await self._claim_for_slot(drain=drain)
                if claimed is None:
                    return
                if not claimed:
                    continue
                ran, parked = await self._run_claimed(claimed)
                completed += ran
                if parked and not drain:
                    # The pool this slot drew on is FULL. Claiming again
                    # immediately just parks the next pending task too — the
                    # slot spins, each turn re-parking a different row, and a
                    # run with more tasks than transport capacity burns claim
                    # cycles for its whole duration. Wait out the same horizon
                    # the refusal parked the task for, then try again.
                    await asyncio.sleep(
                        max(0.05, audit_settings.capacity_concurrency_retry_seconds)
                    )

        await asyncio.gather(
            *(slot() for _ in range(concurrency)), return_exceptions=True
        )
        return completed

    async def _claim_for_slot(self, *, drain: bool) -> list[AuditTask] | None:
        """One pipeline slot's claim, with its own stop/backoff decision.

        Returns the claimed rows, an EMPTY list when the slot should simply go
        round again after backing off, or ``None`` when the slot's own exit
        condition fired. A claim failure (DB blip) is treated exactly like an
        empty queue apart from the log: it must not kill the slot.
        """
        try:
            await self._sweep_expired_leases()
            claimed = await self._queue.claim(owner=self.owner, limit=1)
        except Exception:
            logger.exception("audit worker claim failed")
            claimed = []
        if claimed:
            return claimed
        if drain:
            return None
        await asyncio.sleep(max(0.05, audit_settings.poll_interval_seconds))
        return []

    async def _run_claimed(self, claimed: Sequence[AuditTask]) -> tuple[int, bool]:
        """Execute one slot's claim; returns ``(completed, parked)``.

        Per-task crashes stay isolated the same way ``run_once`` isolates
        them: ``_execute_task`` records its own failures, and a raising
        cleanup path is logged rather than allowed to cancel the sibling
        tasks still talking to providers.
        """
        completed = 0
        parked = False
        for task in claimed:
            try:
                parked = await self._execute_task(task) or parked
            except BaseException as exc:  # noqa: BLE001 - see run_pipelined docstring
                if isinstance(exc, asyncio.CancelledError):
                    raise
                logger.error(
                    "audit task cleanup failed",
                    exc_info=exc,
                    extra={"task_id": str(task.id)},
                )
            completed += 1
        return completed, parked

    async def run_until_idle(
        self, *, max_batches: int = DEFAULT_MAX_DRAIN_BATCHES
    ) -> int:
        """Drain via the PIPELINED pump, overriding the shared mixin loop.

        Same contract as ``DrainableWorkerMixin.run_until_idle`` (drain until a
        pass does no work, bounded by ``max_batches``), but driven by
        ``run_pipelined`` — this worker's pump drains in one pass rather than
        one claim batch at a time. One refinement: an empty pass is only
        "idle" when no pending row becomes claimable within the short drain
        horizon. A capacity park (or a short retry backoff) makes the queue
        LOOK empty for a moment; abandoning work the drain itself just
        re-parked would strand it until the next invocation.
        """
        total = 0
        idle_budget = _drain_horizon_seconds()
        for _ in range(max(1, max_batches)):
            ran = await self.run_pipelined(drain=True)
            total += ran
            keep_waiting, idle_budget = await self._wait_out_idle_pass(ran, idle_budget)
            if not keep_waiting:
                break
        return total

    async def _wait_out_idle_pass(
        self, ran: int, idle_budget: float
    ) -> tuple[bool, float]:
        """Bounded patience for transient unavailability after an empty pass.

        Once the queue looks empty the drain waits out at most ONE park
        horizon for pending rows to become claimable again (a capacity park
        or short retry backoff makes the queue LOOK empty for a moment).
        A row that stays unavailable past the horizon — a misconfigured
        zero-ceiling pool, a permanent funded fail-closed — ends the drain
        instead of looping forever; the next invocation resumes it.
        """
        if ran > 0:
            return True, idle_budget
        if idle_budget <= 0 or not await self._has_soon_claimable_tasks():
            return False, idle_budget
        sleep = max(0.05, audit_settings.poll_interval_seconds)
        await asyncio.sleep(sleep)
        return True, idle_budget - sleep

    async def _has_soon_claimable_tasks(self) -> bool:
        """True while a pending row becomes claimable within the drain horizon.

        The horizon covers the transient states a drain itself creates — the
        concurrency capacity park (``capacity_concurrency_retry_seconds``)
        plus one poll interval of slack. Longer horizons are NOT drained: a
        shared 429 cooldown or an unconfigured funded route cannot proceed on
        this invocation, exactly like a long provider Retry-After retry.
        """
        horizon = _utcnow() + timedelta(seconds=_drain_horizon_seconds())
        async with self._session_factory() as session:
            soon = await session.scalar(
                select(func.count())
                .select_from(AuditTask)
                .where(AuditTask.status.in_(sorted(TASK_CLAIMABLE_STATUSES)))
                .where(AuditTask.available_at <= horizon)
            )
            return bool(soon)

    async def run_forever(self) -> None:  # pragma: no cover - long-running loop
        logger.info("audit worker started", extra={"owner": self.owner})
        assert_worker_pool_capacity()
        _warn_if_provider_pacing_unbounded()
        try:
            while True:
                try:
                    # Never returns while work keeps arriving; the slots poll.
                    await self.run_pipelined(drain=False)
                except Exception:  # defensive: a bad task must not kill the loop
                    logger.exception("audit worker loop iteration failed")
                    await asyncio.sleep(max(0.05, audit_settings.poll_interval_seconds))
        finally:
            # Release the pooled provider connections on shutdown (SIGTERM /
            # cancellation) rather than dropping sockets on process exit.
            await aclose_shared_clients()

    # --- per-task execution ------------------------------------------------

    async def _execute_task(self, claimed: AuditTask) -> bool:
        """Run one claimed task end to end inside its own session.

        Honors cooperative cancel + the per-run wall-clock deadline at the
        boundary (before touching the provider). Persists the immutable artifact
        + attempt and finalizes the task through the queue so the lease is always
        released. Never raises — a crash is caught and recorded as a failure.

        Returns True when the task was PARKED on a capacity refusal rather
        than executed, so the caller's slot can wait out the pool instead of
        immediately claiming another task that would park for the same reason.
        """
        task_id = claimed.id
        audit_id = claimed.audit_id
        parked = False
        try:
            async with self._session_factory() as session:
                task = await session.get(AuditTask, task_id)
                if task is None:
                    return False
                # Row-lock the audit: concurrent tasks of the same audit must
                # serialize the QUEUED -> RUNNING transition (and the cancel /
                # deadline checks) or both would record it. Held only across
                # in-memory checks — no network I/O before the commit below.
                audit = await session.get(Audit, audit_id, with_for_update=True)
                if audit is None:
                    return False

                # Cooperative cancel: stop at this boundary if the audit was
                # killed since the claim, rather than hitting the provider.
                if audit.status == AUDIT_STATUS_CANCELLED:
                    # Terminal without a provider call: no billable unit, but
                    # the task's unused funded reservation is released (BYOK
                    # no-op) so cancelled runs never strand credits.
                    await self._apply_funded_ledger(
                        session, task=task, billable=False, terminal=True
                    )
                    await session.commit()
                    await self._queue.cancel(task_id=task_id)
                    return False

                # Per-run wall-clock deadline: once the audit has been running
                # longer than max_run_seconds, terminalize remaining tasks
                # instead of starting another provider call. The audit itself
                # is finalized once by this method's finally block. The FROZEN
                # value written at creation governs (invariant 9): a live
                # settings change mid-run must never extend or shorten an
                # in-flight audit.
                deadline_seconds = max_run_seconds_from_configuration(
                    audit.configuration
                )
                if self._deadline_passed(audit, deadline_seconds):
                    # Same terminal release as the cancel path above.
                    await self._apply_funded_ledger(
                        session, task=task, billable=False, terminal=True
                    )
                    await session.commit()
                    await self._queue.fail(
                        task_id=task_id,
                        owner=self.owner,
                        error_code=ERROR_RUN_DEADLINE,
                        error_detail=(
                            f"audit exceeded max_run_seconds ({deadline_seconds}s)"
                        ),
                    )
                    return False

                # First task moves the audit QUEUED -> RUNNING.
                self._ensure_running(session, audit)
                await session.commit()

            # The row stays `leased` here and is marked `running` only once
            # capacity is actually held (see _run_provider_call): a task that
            # is about to park waiting for a slot must never be published as
            # running, or the run screen shows more rows running than the
            # transport ceiling allows and each one visibly bounces back to
            # `Capacity Wait`.
            parked = await self._run_provider_call(task_id, audit_id)
        except Exception as exc:  # defensive: never let one task kill the loop
            logger.exception("audit task crashed", extra={"task_id": str(task_id)})
            await self._record_crash(task_id, exc)
        finally:
            await self._finalize_audit(audit_id)
        return parked

    def _deadline_passed(self, audit: Audit, deadline_seconds: float) -> bool:
        started = audit.started_at
        if started is None:
            return False
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = (_utcnow() - started).total_seconds()
        return elapsed >= deadline_seconds

    def _ensure_running(self, session: AsyncSession, audit: Audit) -> None:
        if audit.status == AUDIT_STATUS_QUEUED:
            audit.started_at = _utcnow()
            apply_transition(
                session,
                audit=audit,
                target=AUDIT_STATUS_RUNNING,
                message="audit running",
            )
            record_event(
                session,
                audit_id=audit.id,
                event_type=EVENT_AUDIT_RUNNING,
                message="audit running",
            )

    async def _run_provider_call(self, task_id: uuid.UUID, audit_id: uuid.UUID) -> bool:
        """Orchestrate ONE queue attempt: load -> validate -> capacity -> call.

        A thin shell over the helpers below — each owns one concern (frozen
        context, terminal validation, adapter build, capacity, the single
        call, outcome persistence) so no function carries the old CC-17 lump.

        Returns True when the attempt PARKED on a capacity refusal (no
        provider call was made and the task is back in the claimable set).
        """
        context = await self._load_execution_context(task_id, audit_id)
        if context is None:
            return False
        rejection = _terminal_rejection(context)
        if rejection is not None:
            await self._fail_terminal(
                task_id=task_id,
                audit_id=audit_id,
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                transport_model=context.transport_model,
                error_code=rejection[0],
                error_detail=rejection[1],
            )
            return False
        request, request_snapshot = _build_call_request(context)
        adapter = await self._build_adapter_or_fail(context, request_snapshot)
        if adapter is None:
            return False
        # Capacity I/O happens only AFTER the claim committed (invariant 8).
        capacity = _capacity_request(context)
        decision = await acquire_provider_capacity(
            self._session_factory, request=capacity
        )
        if not decision.acquired:
            # Parked: NO provider call happens, so no attempt budget is spent
            # and no ledger unit is billed. The task re-enters the claimable
            # set once the decision's available_at passes.
            await self._park_capacity_wait(
                task_id=task_id, audit_id=audit_id, decision=decision
            )
            return True
        # Capacity is held: NOW the row is genuinely running. Losing the lease
        # here means the sweeper handed the task to another worker, so this
        # attempt must hand the slot straight back rather than call out.
        if not await self._queue.mark_running(task_id=task_id, owner=self.owner):
            await release_provider_capacity(
                self._session_factory,
                request=capacity,
                outcome=CapacityOutcome(kind=CAPACITY_OUTCOME_FAILED),
            )
            return False
        attempt = await self._execute_with_capacity(context, capacity, adapter, request)
        await self._persist_attempt_outcome(context, attempt, request_snapshot)
        return False

    async def _persist_attempt_outcome(
        self,
        context: _ExecutionContext,
        attempt: CallAttempt,
        request_snapshot: dict,
    ) -> None:
        """Route ONE finished call to the success or failure persistence path.

        Both sides take the same identity block, so the only real decision
        here is which one runs — kept out of ``_run_provider_call`` so that
        function stays the load/validate/capacity/call shell it documents.
        """
        persist = self._persist_success if attempt.succeeded else self._handle_failure
        await persist(
            task_id=context.task_id,
            audit_id=context.audit_id,
            attempts=[attempt],
            logical_engine=context.logical_engine,
            transport_provider=context.transport_provider,
            transport_model=context.transport_model,
            request_snapshot=request_snapshot,
        )

    async def _load_execution_context(
        self, task_id: uuid.UUID, audit_id: uuid.UUID
    ) -> _ExecutionContext | None:
        """Load everything the call needs in one short session, then close it.

        The session ends before any capacity/provider I/O so no transaction is
        ever held across a network call (invariant 8). The measurement policy
        comes from the FROZEN configuration, never the live settings: an env
        change must not alter an in-flight run (invariant 9).

        The credential is the FROZEN identity from the task's route snapshot
        (T11): the worker loads exactly the connection the planner froze —
        tenant BYOK or the platform row in the system workspace — by id only.
        The frozen identity IS the authorization, so the lookup deliberately
        does NOT apply tenant-workspace scoping, and the worker never
        re-resolves or falls back to another credential.
        """
        async with self._session_factory() as session:
            task = await session.get(AuditTask, task_id)
            audit = await session.get(Audit, audit_id)
            if task is None or audit is None:
                return None
            route_snapshot = task.provider_route_snapshot or {}
            connection_id = _frozen_connection_id_from(route_snapshot)
            connection: ProviderConnection | None = None
            if connection_id is not None:
                connection = await session.get(ProviderConnection, connection_id)
            configuration = dict(audit.configuration or {})
            return _ExecutionContext(
                task_id=task_id,
                audit_id=audit_id,
                logical_engine=task.logical_engine,
                transport_provider=task.transport_provider,
                transport_model=task.transport_model,
                prompt_text=task.prompt_text or "",
                system_instruction=audit.system_instruction or "",
                configuration=configuration,
                policy=measurement_policy_from_configuration(configuration),
                base_url=str(route_snapshot.get("base_url") or ""),
                attempt_number=task.attempt_count + 1,
                connection_id=connection_id,
                connection_active=(
                    bool(connection.active) if connection is not None else False
                ),
                api_key_encrypted=(
                    connection.api_key_encrypted if connection is not None else ""
                ),
                funding=_frozen_funding_from(task.provider_route_snapshot),
            )

    async def _build_adapter_or_fail(
        self, context: _ExecutionContext, request_snapshot: dict
    ):
        """Build the adapter from the execution-time decrypted BYOK key.

        The key is resolved at execution time only — never logged, persisted,
        or placed in a snapshot (invariant 6). A build failure is a terminal
        misconfiguration, not a retryable provider error.
        """
        api_key = decrypt_secret(context.api_key_encrypted)
        try:
            return build_adapter(
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                api_key=api_key,
                country_code=str(context.configuration.get("country_code", "")),
                base_url=context.base_url,
            )
        except ProviderError as exc:
            await self._fail_terminal(
                task_id=context.task_id,
                audit_id=context.audit_id,
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                transport_model=context.transport_model,
                error_code=exc.error_code,
                error_detail=str(exc),
                request_snapshot=request_snapshot,
            )
            return None

    async def _execute_with_capacity(
        self,
        context: _ExecutionContext,
        capacity: CapacityRequest,
        adapter,
        request: AnswerEngineRequest,
    ) -> CallAttempt:
        """Run the single provider call under held capacity; ALWAYS release.

        The release carries the call's outcome so a provider 429 writes the
        shared pool cooldown (``rate_limited``) while any other result simply
        returns the concurrency leases. Token starts stay consumed either
        way; an abandoned call (crash/cancellation) releases as ``failed``.
        """
        attempt: CallAttempt | None = None
        try:
            attempt = await self._execute_one_attempt(context, adapter, request)
            return attempt
        finally:
            await release_provider_capacity(
                self._session_factory,
                request=capacity,
                outcome=(
                    _capacity_outcome(attempt)
                    if attempt is not None
                    else CapacityOutcome(kind=CAPACITY_OUTCOME_FAILED)
                ),
            )

    async def _execute_one_attempt(
        self, context: _ExecutionContext, adapter, request: AnswerEngineRequest
    ) -> CallAttempt:
        """Make this queue attempt's ONE provider call, heartbeating the lease.

        The per-call ceiling is the FROZEN mode timeout from the task's
        configuration — never the live settings (invariant 9).
        """
        heartbeat = asyncio.create_task(self._heartbeat_loop(context.task_id))
        try:
            return await call_provider_once(
                adapter,
                request,
                timeout_seconds=context.policy.timeout_seconds,
            )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _park_capacity_wait(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        decision: CapacityDecision,
    ) -> None:
        """Park the task on a capacity refusal; the attempt budget is untouched.

        Records ``EVENT_TASK_CAPACITY_WAIT`` (opaque ids + retry timing only —
        invariant 6) under the owner/liveness lock, then hands the row to the
        queue, which re-parks it claimable once ``available_at`` passes.

        The event is recorded AT MOST ONCE per (task, attempt, refusal code).
        A task that cannot get capacity re-parks every
        ``capacity_concurrency_retry_seconds`` for as long as the pool is
        full, and recording each one turned the event log into park churn — a
        measured 10-prompt run logged 132 ``task.capacity_wait`` events
        against 10 real task events. Since every event is an SSE frame that
        invalidates the run screen's queries, that churn cost a refetch storm
        to report a state that had not changed. One event per distinct wait
        carries the same information.
        """
        async with self._session_factory() as session:
            locked = await self._lock_owned_running_task(
                session,
                task_id=task_id,
                audit_id=audit_id,
                allowed_statuses=TASK_PRE_CALL_STATUSES,
            )
            if locked is None:
                await session.rollback()
                return
            task, _audit = locked
            attempt_number = task.attempt_count + 1
            if await self._capacity_wait_already_recorded(
                session,
                audit_id=audit_id,
                task_id=task_id,
                attempt_number=attempt_number,
                code=decision.code,
            ):
                await session.rollback()
            else:
                record_event(
                    session,
                    audit_id=audit_id,
                    event_type=EVENT_TASK_CAPACITY_WAIT,
                    message="task waiting on provider capacity",
                    payload=_capacity_wait_payload(
                        task_id=task_id,
                        attempt_number=attempt_number,
                        decision=decision,
                    ),
                )
                await session.commit()
        await self._queue.park_capacity_wait(
            task_id=task_id,
            owner=self.owner,
            available_at=decision.available_at or _utcnow(),
        )

    async def _capacity_wait_already_recorded(
        self,
        session: AsyncSession,
        *,
        audit_id: uuid.UUID,
        task_id: uuid.UUID,
        attempt_number: int,
        code: str,
    ) -> bool:
        """True when THIS wait was already recorded for this task attempt.

        Keyed on (task, attempt, refusal code) so a task that parks, waits
        out a full pool, and then parks again for a DIFFERENT reason (a
        provider 429 rather than local concurrency) still records the new
        condition — only the identical repeat is suppressed. Runs under the
        caller's row lock on the task, so two workers cannot both decide the
        event is missing.
        """
        existing = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.audit_id == audit_id)
            .where(AuditEvent.event_type == EVENT_TASK_CAPACITY_WAIT)
            .where(
                AuditEvent.payload.contains(
                    {"task_id": str(task_id), "attempt": attempt_number, "code": code}
                )
            )
        )
        return bool(existing)

    async def _apply_funded_ledger(
        self,
        session: AsyncSession,
        *,
        task: AuditTask,
        billable: bool,
        terminal: bool,
    ) -> None:
        """The funded-ledger call sites for one task (no-op for BYOK).

        ``billable`` converts one reserved unit into a billable attempt — one
        per ACTUAL provider call, including timeouts (a timed-out call is
        billable), keyed on the just-persisted 1-based ``attempt_count`` with
        a deterministic idempotency key so a replay never double-debits.
        ``terminal`` releases the task's unused reservation exactly once at
        terminalization (idempotent on the ledger side). Caller owns the
        commit so the ledger rows land atomically with the attempt row.
        """
        funding = _frozen_funding_from(task.provider_route_snapshot)
        if funding is None:
            return
        if billable:
            await record_billable_attempt(
                session,
                reservation_id=funding.reservation_id,
                task_id=task.id,
                attempt=task.attempt_count,
                idempotency_key=f"{task.id}:{task.attempt_count}:funded-billable",
                at=_utcnow(),
            )
        if terminal:
            await release_terminal_funded_task(
                session,
                reservation_id=funding.reservation_id,
                audit_id=task.audit_id,
                task_id=task.id,
                trigger="unused",
                at=_utcnow(),
            )

    async def _heartbeat_loop(
        self, task_id: uuid.UUID
    ) -> None:  # pragma: no cover - timing loop
        interval = max(1.0, audit_settings.heartbeat_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._queue.heartbeat(task_id=task_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dead heartbeat loop silently expires the lease and lets the
                # sweeper hand the task to another worker mid-call; keep beating
                # through transient failures instead.
                logger.exception(
                    "heartbeat failed; retrying", extra={"task_id": str(task_id)}
                )

    async def _lock_owned_running_task(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        allowed_statuses: frozenset[str] = frozenset({TASK_STATUS_RUNNING}),
    ) -> tuple[AuditTask, Audit] | None:
        """Lock the task FOR UPDATE and verify we still own it before writing.

        Guards invariant 3/8 (single writer / no double-claim). Between the
        provider call finishing and this write, the lease could have expired
        (sweeper -> another worker claimed it) or the audit could have been
        cancelled. Returns ``(task, audit)`` only when the task is still leased
        to THIS worker, in one of ``allowed_statuses``, and the audit is not
        cancelled or terminal; otherwise ``None`` and the stale provider
        result is discarded.

        ``allowed_statuses`` defaults to ``running`` — the post-call evidence
        writers. The pre-call writers (terminal rejection, adapter build
        failure, capacity park) pass ``TASK_PRE_CALL_STATUSES`` instead,
        because the row is deliberately still ``leased`` until capacity is
        held. Each call site declares what it expects rather than the gate
        blanket-accepting both, so a post-call write can still never land on
        a task that never started.
        """
        task = await session.get(AuditTask, task_id, with_for_update=True)
        if task is None:
            return None
        if task.lease_owner != self.owner or task.status not in allowed_statuses:
            return None
        audit = await session.get(Audit, audit_id)
        if (
            audit is None
            or audit.status == AUDIT_STATUS_CANCELLED
            or (audit.status in AUDIT_TERMINAL_STATUSES)
        ):
            return None
        return task, audit

    def _record_attempts(
        self,
        session: AsyncSession,
        *,
        task: AuditTask,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        artifact_id: uuid.UUID | None,
    ) -> None:
        """Append one immutable ProviderAttempt per actual provider call.

        ProviderAttempt is append-only "one row per attempt" (invariant 3):
        one queue attempt makes one call, so each persistence pass appends
        exactly one row — a task that failed twice through queue retries and
        then succeeded ends with three rows (two failed + one succeeded), not
        a single collapsed row. Advances ``attempt_count`` by the number of
        calls made and stamps each row's ``attempt_number``.
        """
        base = task.attempt_count
        for offset, attempt in enumerate(attempts, start=1):
            attempt_number = base + offset
            response = attempt.response
            if response is not None:
                session.add(
                    ProviderAttempt(
                        task_id=task.id,
                        audit_id=audit_id,
                        attempt_number=attempt_number,
                        logical_engine=response.logical_engine,
                        transport_provider=response.transport_provider,
                        transport_model=response.transport_model,
                        status=ATTEMPT_STATUS_SUCCEEDED,
                        latency_ms=response.latency_ms,
                        artifact_id=artifact_id,
                    )
                )
            else:
                error = attempt.error
                error_code = error.error_code if error else ERROR_PARSE
                error_detail = str(error) if error else "unknown provider error"
                session.add(
                    ProviderAttempt(
                        task_id=task.id,
                        audit_id=audit_id,
                        attempt_number=attempt_number,
                        logical_engine=logical_engine,
                        transport_provider=transport_provider,
                        transport_model=transport_model,
                        status=ATTEMPT_STATUS_FAILED,
                        error_code=error_code,
                        error_detail=error_detail[:2000],
                    )
                )
        task.attempt_count = base + len(attempts)

    def _record_cost_projection(
        self,
        session: AsyncSession,
        *,
        artifact: RawResponseArtifact,
        attempt_count: int,
    ) -> None:
        """Price one persisted artifact into an append-only projection row.

        Reads the artifact's own persisted route identity for the pricing
        lookup (never the request snapshot) and stamps the persisted ACTUAL
        attempt count — ProviderAttempt rows are written before this runs.
        The row is analytics-only: a pricing-catalog miss logs a safe warning
        and SKIPS the projection — unknown pricing never blocks evidence (the
        assert this replaced rolled the whole success transaction back,
        losing the artifact, the attempts, and the funded bill+release to a
        post-call crash).
        """

        pricing = route_pricing_for(
            RouteIdentity(
                logical_engine=artifact.logical_engine,
                transport_provider=artifact.transport_provider,
                transport_model=artifact.transport_model,
            ),
            PRICING_CATALOG_VERSION,
        )
        if pricing is None:
            logger.warning(
                "execution cost projection skipped: no pricing for route",
                extra={
                    "logical_engine": artifact.logical_engine,
                    "transport_provider": artifact.transport_provider,
                    "transport_model": artifact.transport_model,
                },
            )
            return
        session.add(
            build_execution_cost_projection(
                artifact,
                pricing=pricing,
                formula_version=EXECUTION_COST_FORMULA_VERSION,
                attempt_count=attempt_count,
            )
        )

    async def _persist_success(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        request_snapshot: dict,
    ) -> None:
        response = attempts[-1].response
        assert response is not None  # caller only invokes on a success
        search_events = _serialize_search_events(response)
        citations = _serialize_citations(response)
        artifact_id: uuid.UUID | None = None
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock BEFORE writing any evidence
            # (invariant 3/8). If the lease was lost or the audit cancelled, the
            # provider response is discarded — no artifact/attempt/analysis.
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, audit_id=audit_id
            )
            if locked is None:
                await session.rollback()
                return
            task, audit = locked
            # Immutable raw artifact (invariant 3): written once, never mutated.
            artifact = _build_artifact(
                audit_id=audit_id,
                task_id=task_id,
                response=response,
                search_events=search_events,
                citations=citations,
            )
            session.add(artifact)
            await session.flush()
            artifact_id = artifact.id
            _apply_response_to_task(
                task,
                response=response,
                request_snapshot=request_snapshot,
                search_events=search_events,
                citations=citations,
                artifact_id=artifact_id,
            )

            # Score on persist (invariants 4/9): the deterministic analyzer runs
            # against the just-persisted answer + citations (no provider call)
            # and writes the derived ResponseAnalysis + mention/citation rows,
            # each stamped with the raw-artifact provenance + analyzer_version.
            # Brand analysis is MEASUREMENT-ONLY (§7.1): a shopping-surface
            # probe task skips it entirely so brand metrics stay isolated.
            if task.shopping_surface == SHOPPING_SURFACE_MEASUREMENT:
                config = build_scoring_config(audit.configuration)
                analysis = await analyze_task(session, task=task, config=config)
                if analysis is not None:
                    task.score = analysis.score

            # Sibling deterministic PRODUCT pass (Agentic Commerce): scores
            # the frozen catalog against the same persisted answer and writes
            # ProductResponseAnalysis/ProductMention/MerchantMention rows
            # (no-op on an empty frozen catalog). Runs for EVERY surface so
            # product probe evidence remains eligible. Never touches the
            # brand-level rows above.
            product_config = build_product_scoring_config(audit.configuration)
            await analyze_task_products(session, task=task, config=product_config)

            # One ProviderAttempt per actual call (retries + final success).
            self._record_attempts(
                session,
                task=task,
                audit_id=audit_id,
                attempts=attempts,
                logical_engine=logical_engine,
                transport_provider=transport_provider,
                transport_model=transport_model,
                artifact_id=artifact_id,
            )
            # Funded ledger (no-op BYOK): bill the just-persisted call and
            # release the task's unused reservation at this terminalization.
            await self._apply_funded_ledger(
                session, task=task, billable=True, terminal=True
            )
            # Append-only cost projection (invariant 3): built AFTER the
            # ProviderAttempt rows so attempt_count is the persisted actual
            # call count. Unknown usage/rates stay null — never zero, and an
            # unknown pricing catalog skips the row instead of blocking the
            # success path.
            self._record_cost_projection(
                session, artifact=artifact, attempt_count=task.attempt_count
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_SUCCEEDED,
                message="task succeeded",
                payload={"task_id": str(task_id)},
            )
            await session.commit()

        await self._queue.succeed(
            task_id=task_id, owner=self.owner, result_artifact_id=artifact_id
        )

    async def _pause_frozen_credential_on_auth_failure(
        self, session: AsyncSession, *, task: AuditTask, error_code: str
    ) -> None:
        """Pause the task's FROZEN credential after an auth-classified failure.

        Tenant BYOK row or platform row alike — the pause writer keys the
        telemetry event off the row's own ``credential_source``. Runs inside
        the failure-path's owner-locked transaction so the pause lands
        atomically with the attempt evidence (invariant 3/8). A missing
        frozen id (or a row deleted mid-run) is a no-op: the task's failure
        handling must never crash on credential bookkeeping.
        """
        if error_code != ERROR_AUTH:
            return
        connection_id = _frozen_connection_id_from(task.provider_route_snapshot)
        if connection_id is None:
            return
        await pause_connection_after_key_failure(session, connection_id, _utcnow())

    async def _handle_failure(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        request_snapshot: dict,
    ) -> None:
        error = attempts[-1].error
        error_code = error.error_code if error else ERROR_PARSE
        error_detail = str(error) if error else "unknown provider error"
        retryable = bool(error and error.retryable and error_code in RETRYABLE_ERRORS)
        retry_after = getattr(error, "retry_after_seconds", None)

        will_retry = False
        attempt_number = 0
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock before writing evidence
            # (invariant 3/8): a stale/cancelled worker must not touch the task.
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, audit_id=audit_id
            )
            if locked is None:
                await session.rollback()
                return
            task, _audit = locked
            task.request_snapshot = request_snapshot
            # One ProviderAttempt per actual call (all failed on this path).
            self._record_attempts(
                session,
                task=task,
                audit_id=audit_id,
                attempts=attempts,
                logical_engine=logical_engine,
                transport_provider=transport_provider,
                transport_model=transport_model,
                artifact_id=None,
            )
            attempt_number = task.attempt_count
            exhausted = task.attempt_count >= task.max_attempts
            will_retry = retryable and not exhausted
            # Funded ledger (no-op BYOK): bill this actual call — a timed-out
            # call bills too — and release the unused reservation only when
            # the task terminalizes (a queue retry keeps it for the next call).
            await self._apply_funded_ledger(
                session, task=task, billable=True, terminal=not will_retry
            )
            # T11 auth pause (details on the helper): pauses the FROZEN
            # credential so no NEW task resolves it until the grace deadline;
            # this task still fails through current finalization below and
            # there is NO silent platform fallback.
            await self._pause_frozen_credential_on_auth_failure(
                session, task=task, error_code=error_code
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_RETRY if will_retry else EVENT_TASK_FAILED,
                message="task retry" if will_retry else "task failed",
                payload={"task_id": str(task_id), "error_code": error_code},
            )
            await session.commit()

        if will_retry:
            await self._queue.retry(
                task_id=task_id,
                owner=self.owner,
                delay_seconds=audit_settings.retry_delay(attempt_number, retry_after),
                error_code=error_code,
                error_detail=error_detail,
            )
        else:
            await self._queue.fail(
                task_id=task_id,
                owner=self.owner,
                error_code=error_code,
                error_detail=error_detail,
            )

    async def _fail_terminal(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        error_code: str,
        error_detail: str,
        request_snapshot: dict | None = None,
    ) -> None:
        """Terminally fail a task (non-retryable misconfiguration)."""
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock before writing evidence
            # (invariant 3/8): even a terminal fail must not touch a task this
            # worker no longer owns or an audit that was cancelled meanwhile.
            # Pre-call path: both rejection sites (retired transport / missing
            # connection, and an adapter build failure) run before capacity is
            # held, so the row is still `leased`.
            locked = await self._lock_owned_running_task(
                session,
                task_id=task_id,
                audit_id=audit_id,
                allowed_statuses=TASK_PRE_CALL_STATUSES,
            )
            if locked is None:
                await session.rollback()
                return
            task, _audit = locked
            task.attempt_count += 1
            if request_snapshot is not None:
                task.request_snapshot = request_snapshot
            session.add(
                ProviderAttempt(
                    task_id=task_id,
                    audit_id=audit_id,
                    attempt_number=task.attempt_count,
                    logical_engine=logical_engine,
                    transport_provider=transport_provider,
                    transport_model=transport_model,
                    status=ATTEMPT_STATUS_FAILED,
                    error_code=error_code,
                    error_detail=error_detail[:2000],
                )
            )
            # No provider call happened (terminal misconfiguration): nothing
            # to bill, but the task's unused funded reservation is released
            # (BYOK no-op) so a rejected funded task never strands credits.
            await self._apply_funded_ledger(
                session, task=task, billable=False, terminal=True
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_FAILED,
                message="task failed",
                payload={"task_id": str(task_id), "error_code": error_code},
            )
            await session.commit()
        await self._queue.fail(
            task_id=task_id,
            owner=self.owner,
            error_code=error_code,
            error_detail=error_detail,
        )

    async def _record_crash(self, task_id: uuid.UUID, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        failed = await self._queue.fail(
            task_id=task_id,
            owner=self.owner,
            error_code=ERROR_PARSE,
            error_detail=detail,
        )
        await self._release_crashed_funded_task(task_id, terminalized=failed)

    async def _release_crashed_funded_task(
        self, task_id: uuid.UUID, *, terminalized: bool
    ) -> None:
        """Release a crashed task's unused funded reservation (best-effort).

        A crash escaping ``_run_provider_call`` ran none of the evidence
        paths, so unlike cancel/deadline/fail-terminal it had no
        funded-ledger terminalization: the reservation — or its unbilled
        remainder — leaked. ``queue.fail`` owns the terminalization and is
        owner-guarded, so a lost lease (the sweeper handed the task to
        another worker, which will bill against the reservation) skips the
        release entirely. A provider call that DID happen was billed by the
        success/failure path before the crash — the ledger releases only
        still-reserved units, so the call stays billed exactly once and the
        remainder is released exactly once.
        """
        if not terminalized:
            return
        await self._release_terminalized_funded_task(task_id, trigger="crash")

    async def _progress_counts(
        self, session: AsyncSession, audit_id: uuid.UUID
    ) -> tuple[int, int, int]:
        """``(succeeded, failed, remaining)`` over an audit's MEASUREMENT rows.

        Progress/completion denominators are MEASUREMENT-ONLY (§7.1):
        shopping-surface probe rows never move audit counts.

        ``failed`` is terminal-but-not-succeeded rather than ``total -
        succeeded``: mid-run the difference matters, because a still-queued or
        in-flight task is not a failure and must never be published as one.
        The two definitions converge once ``remaining`` is 0, so the counts
        this publishes DURING a run land on exactly the terminal figures.
        """
        measurement = (
            select(func.count())
            .select_from(AuditTask)
            .where(AuditTask.audit_id == audit_id)
            .where(AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT)
        )
        total = int(await session.scalar(measurement) or 0)
        succeeded = int(
            await session.scalar(
                measurement.where(AuditTask.status == TASK_STATUS_SUCCEEDED)
            )
            or 0
        )
        terminal = int(
            await session.scalar(
                measurement.where(AuditTask.status.in_(list(TASK_TERMINAL_STATUSES)))
            )
            or 0
        )
        return succeeded, terminal - succeeded, total - terminal

    async def _finalize_audit(self, audit_id: uuid.UUID) -> None:
        """Publish live progress, and terminalize once execution is done.

        Runs after EVERY task boundary, and does two things:

        1. Publishes the audit's running ``completed_count`` /
           ``failed_count``. This happens on every pass, not just the last
           one, because those counters ARE the run screen's progress
           indicator: gating them on "no task remains" pinned them at 0 for
           the whole run and then flipped them to the final figures, which
           reads as a hung run rather than a working one.
        2. When no non-terminal task remains, transitions RUNNING ->
           ANALYZING (>=1 success) or RUNNING -> FAILED (0 successes). On
           ANALYZING it hands straight to the analysis stage (aggregate +
           terminal).

        A cancelled audit keeps its status. Guarded with ``FOR UPDATE`` so
        concurrent workers don't double-finalize or interleave counts.
        """
        reached_analyzing = False
        async with self._session_factory() as session:
            audit = await session.get(Audit, audit_id, with_for_update=True)
            if audit is None or audit.status in AUDIT_TERMINAL_STATUSES:
                if audit is not None:
                    await session.rollback()
                return
            succeeded, failed, remaining = await self._progress_counts(
                session, audit_id
            )
            # Only dirty the row when a count actually moved: this method runs
            # at every task boundary INCLUDING capacity parks, and an
            # unconditional write would churn `updated_at` on passes that
            # observed no progress at all.
            if audit.completed_count != succeeded or audit.failed_count != failed:
                audit.completed_count = succeeded
                audit.failed_count = failed
            if remaining > 0:
                # Execution still in flight: the counts above are this pass's
                # only contribution; the transition waits for the last task.
                await session.commit()
                return
            if audit.status == AUDIT_STATUS_RUNNING:
                if succeeded == 0:
                    audit.completed_at = _utcnow()
                    apply_transition(
                        session,
                        audit=audit,
                        target=AUDIT_STATUS_FAILED,
                        message="audit failed: no successful executions",
                    )
                    audit.error_message = "no successful executions"
                else:
                    # Execution done; hand to the deterministic analysis stage.
                    apply_transition(
                        session,
                        audit=audit,
                        target=AUDIT_STATUS_ANALYZING,
                        message="execution complete; ready for analysis",
                        payload={"completed": succeeded, "failed": failed},
                    )
                    reached_analyzing = True
            await session.commit()

        if reached_analyzing:
            await self._finalize_analysis(audit_id)

    async def _finalize_analysis(self, audit_id: uuid.UUID) -> None:
        """Aggregate the MetricSnapshot + resolve the terminal status (B6).

        Runs once an audit reaches ANALYZING. Aggregates from persisted analyses
        only (invariant 7 — no provider call) and drives ANALYZING -> REPORTING
        -> COMPLETED / PARTIALLY_COMPLETED. Guarded with ``FOR UPDATE`` so
        concurrent workers don't double-finalize. After the terminal commit it
        best-effort queues the project's Opportunities refresh — this is the
        ONLY audit-side hook: ``_finalize_audit`` never fires it (execution
        boundary, no snapshots yet) and failed audits never reach ANALYZING.
        """
        async with self._session_factory() as session:
            audit = await session.get(Audit, audit_id, with_for_update=True)
            if audit is None or audit.status != AUDIT_STATUS_ANALYZING:
                if audit is not None:
                    await session.rollback()
                return
            # Product finalize first (same session/commit): upserts the
            # per-product ProductMetricSnapshot rows from the persisted
            # product analyses; the brand finalize below stays untouched.
            await finalize_audit_product_analysis(session, audit=audit)
            await finalize_audit_analysis(session, audit=audit)
            workspace_id = audit.workspace_id
            project_id = audit.project_id
            await session.commit()

        await self._enqueue_opportunity_refresh(
            audit_id=audit_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )

    async def _enqueue_opportunity_refresh(
        self,
        *,
        audit_id: uuid.UUID,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        """Queue downstream work without reopening the terminal audit write."""

        # Queue work only after the source audit is durably terminal. A queue
        # outage must never roll back the evidence and snapshot above.
        try:
            async with self._session_factory() as session:
                await enqueue_audit_opportunity_tasks(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    audit_id=audit_id,
                )
                await session.commit()
        except Exception:
            logger.exception(
                "opportunity refresh enqueue failed",
                extra={"audit_id": str(audit_id)},
            )


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    worker = AuditWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
