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
import logging
import time
import uuid
from collections.abc import Sequence
from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.answer_engines.http_client import aclose_shared_clients
from app.core.config.audits import (
    AUDIT_QUEUE_SPEC,
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_QUEUED,
    AUDIT_STATUS_RUNNING,
    ERROR_RUN_DEADLINE,
    EVENT_AUDIT_RUNNING,
    audit_settings,
    max_run_seconds_from_configuration,
)
from app.core.config.task_queue import (
    DEFAULT_MAX_DRAIN_BATCHES,
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
)
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.entitlements.ledger import (
    release_terminal_funded_task,
)
from app.models.audit import (
    Audit,
    AuditTask,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.audit.execution import AuditExecutionMixin
from app.workers.audit.terminalization import AuditTerminalizationMixin
from app.workers.audit_worker_support import (
    assert_worker_pool_capacity,
)
from app.workers.audit_worker_support import (
    drain_horizon_seconds as _drain_horizon_seconds,
)
from app.workers.audit_worker_support import (
    frozen_funding_from as _frozen_funding_from,
)
from app.workers.audit_worker_support import (
    utcnow as _utcnow,
)
from app.workers.audit_worker_support import (
    warn_if_provider_pacing_unbounded as _warn_if_provider_pacing_unbounded,
)
from app.workers.drain import DrainableWorkerMixin

logger = logging.getLogger("app.workers.audit_worker")

__all__ = ["AuditWorker"]

# Statuses a task may hold while the PRE-CALL writers act on it. The row is
# still `leased` (not `running`) until provider capacity is held, so the
# terminal-rejection / adapter-failure / capacity-park paths must accept it;
# `running` stays accepted because a retry re-enters those paths.
TASK_PRE_CALL_STATUSES = frozenset({TASK_STATUS_LEASED, TASK_STATUS_RUNNING})


class AuditWorker(AuditExecutionMixin, AuditTerminalizationMixin, DrainableWorkerMixin):
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
            except BaseException as exc:
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


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    instrument_worker("audit-worker")
    worker = AuditWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
