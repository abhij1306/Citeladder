# Analytics worker: claims AnalyticsTask queue rows and runs the per-kind
# executor registered in the kind dispatch table.
#
# A separate process (the ``analytics-worker`` compose service). It mirrors
# ``ContentWorker`` exactly on the queue mechanics — claim via the generic
# ``PostgresTaskQueue`` (``FOR UPDATE SKIP LOCKED``, claim committed BEFORE
# any work — invariant 8), sweep expired leases FIRST in every loop
# iteration, ``mark_running`` before dispatch, heartbeat the lease while the
# executor runs, and cooperative cancel at the task boundary. Terminal
# accounting goes through the worker-owned atomic ``_finalize``: one locked
# transaction per dispatch re-checks owner/status (a lost lease or an
# already-terminal row writes NOTHING — single-writer, invariant 3) and
# increments ``attempt_count`` exactly once.
#
# Catalog projection remains DB-only. Optional competitor discovery performs
# one bounded provider request after the queue claim has committed, and persists
# an immutable attempt before publishing candidates.
#
# DISPATCH TABLE: every declared kind routes to its real executor
# (``EXECUTORS`` below). A claimed kind outside the table is a config bug
# and fails loud: ``ExecutorNotWiredError`` is stamped as terminal
# ``executor_not_wired``, never retried.
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    ANALYTICS_QUEUE_SPEC,
    ANALYTICS_TASK_KIND_AI_REFERRALS_SNAPSHOT_REFRESH,
    ANALYTICS_TASK_KIND_CLASSIFY_REFERRALS,
    ANALYTICS_TASK_KIND_COMMERCE_CATALOG_PROJECTION,
    ANALYTICS_TASK_KIND_COMMERCE_COMPETITOR_DISCOVERY,
    ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
    ANALYTICS_TASK_KIND_INGEST_REFERRALS,
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
    ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION,
    ANALYTICS_TASK_KIND_REFERRAL_RETENTION_SWEEP,
    ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH,
    ERROR_EXECUTOR_NOT_WIRED,
    analytics_settings,
)
from app.core.config.provider_catalog import ERROR_UNKNOWN
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.analytics.ai_referrals_snapshot import refresh_ai_referrals_snapshot
from app.domain.analytics.ingest import ingest_referrals
from app.domain.analytics.tasks import (
    run_classify_referrals,
    run_referral_retention_sweep,
)
from app.domain.commerce.competitors import run_competitor_discovery
from app.domain.commerce.projector import project_catalog_analysis
from app.domain.demand.service import recompute_demand
from app.domain.opportunities.recompute import recompute as recompute_opportunities
from app.domain.opportunities.verification import verify_implementation_events
from app.domain.traffic.service import refresh_traffic_snapshot
from app.models.analytics import AnalyticsTask
from app.orchestration.executor_errors import TerminalExecutorError
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.drain import DrainableWorkerMixin

logger = logging.getLogger("app.workers.analytics_worker")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ExecutorNotWiredError(RuntimeError):
    """A claimed task kind has no registered executor (a config bug)."""


# Executor contract: one async callable per task kind. It receives the
# session factory + the claimed queue row and performs the kind's projection
# work (DB only — NO network I/O, invariant 7). The worker owns the queue
# lifecycle around it (mark_running / heartbeat / finalize).
type AnalyticsExecutor = Callable[
    [async_sessionmaker[AsyncSession], AnalyticsTask], Awaitable[None]
]


async def _refresh_opportunities(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    if task.project_id is None:
        raise ValueError("Opportunity refresh requires project_id")
    async with session_factory() as session:
        await recompute_opportunities(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            skip_if_current=True,
        )


# Kind dispatch table (invariant 2: one owner of kind -> executor routing).
EXECUTORS: dict[str, AnalyticsExecutor] = {
    ANALYTICS_TASK_KIND_INGEST_REFERRALS: ingest_referrals,
    ANALYTICS_TASK_KIND_CLASSIFY_REFERRALS: run_classify_referrals,
    ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH: refresh_traffic_snapshot,
    ANALYTICS_TASK_KIND_AI_REFERRALS_SNAPSHOT_REFRESH: refresh_ai_referrals_snapshot,
    ANALYTICS_TASK_KIND_REFERRAL_RETENTION_SWEEP: run_referral_retention_sweep,
    ANALYTICS_TASK_KIND_COMMERCE_CATALOG_PROJECTION: project_catalog_analysis,
    ANALYTICS_TASK_KIND_COMMERCE_COMPETITOR_DISCOVERY: run_competitor_discovery,
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH: _refresh_opportunities,
    ANALYTICS_TASK_KIND_OPPORTUNITY_VERIFICATION: verify_implementation_events,
    ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH: recompute_demand,
}


class AnalyticsWorker(DrainableWorkerMixin):
    """Claim/lease loop for ``AnalyticsTask`` rows.

    ``executors`` is the test seam: tests can replace provider-backed work with
    deterministic executors while production uses the module dispatch table.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
        executors: dict[str, AnalyticsExecutor] | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue = PostgresTaskQueue(self._session_factory, ANALYTICS_QUEUE_SPEC)
        self._executors = executors if executors is not None else EXECUTORS
        self.owner = owner or f"analytics-worker-{uuid.uuid4().hex[:12]}"

    # --- Loop --------------------------------------------------------------

    async def run_once(self) -> int:
        """Sweep expired leases, claim one row, run it. Returns count run."""
        await self._queue.release_expired()
        rows = await self._queue.claim(owner=self.owner, limit=1)
        for row in rows:
            await self._execute(row)
        return len(rows)

    async def run_forever(self) -> None:  # pragma: no cover - process loop
        logger.info("analytics worker started", extra={"owner": self.owner})
        while True:
            try:
                ran = await self.run_once()
            except Exception:  # defensive: a bad row must not kill the loop
                logger.exception("analytics worker loop iteration failed")
                ran = 0
            if ran == 0:
                await asyncio.sleep(max(0.05, analytics_settings.poll_interval_seconds))

    # --- One claimed row -----------------------------------------------------

    async def _execute(self, claimed: AnalyticsTask) -> None:
        task_id = claimed.id
        try:
            # Cooperative cancel at the boundary: if the row reached a
            # terminal status between enqueue and claim, never dispatch.
            async with self._session_factory() as session:
                row = await session.get(AnalyticsTask, task_id)
                if row is None or row.status in TASK_TERMINAL_STATUSES:
                    return

            if not await self._queue.mark_running(task_id=task_id, owner=self.owner):
                # Lease lost before dispatch; another worker retries.
                return

            await self._run_executor(claimed)
        except Exception as exc:  # defensive: never kill the loop
            logger.exception(
                "analytics task crashed",
                extra={"task_id": str(task_id)},
            )
            with contextlib.suppress(Exception):
                await self._finalize(task_id=task_id, owner=self.owner, error=exc)

    async def _run_executor(self, claimed: AnalyticsTask) -> None:
        executor = self._executors.get(claimed.task_kind)
        heartbeat = asyncio.create_task(self._heartbeat_loop(claimed.id))
        error: Exception | None = None
        try:
            if executor is None:
                # A kind outside the dispatch table is a config bug — fail
                # loud (terminal, without burning the retry budget).
                raise ExecutorNotWiredError(
                    f"analytics task kind {claimed.task_kind!r} has no "
                    "registered executor"
                )
            await executor(self._session_factory, claimed)
        except Exception as exc:
            error = exc
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        await self._finalize(task_id=claimed.id, owner=self.owner, error=error)

    async def _heartbeat_loop(self, task_id: uuid.UUID) -> None:
        interval = max(1.0, analytics_settings.heartbeat_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._queue.heartbeat(task_id=task_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dead heartbeat loop silently expires the lease and lets
                # the sweeper hand the task to another worker mid-run; keep
                # beating through transient failures instead.
                logger.exception(
                    "heartbeat failed; retrying",
                    extra={"task_id": str(task_id)},
                )

    # --- Atomic terminal accounting -------------------------------------------

    async def _finalize(
        self, *, task_id: uuid.UUID, owner: str, error: Exception | None
    ) -> bool:
        """ONE locked transaction per dispatch (the only terminal writer).

        Locks the row ``FOR UPDATE``, re-checks owner + status (a lost lease
        or an already-terminal row writes nothing), increments
        ``attempt_count`` exactly once, and writes the success / retry /
        terminal-failure fields together. A not-wired executor is a
        permanent-until-deploy condition: terminal failure WITHOUT consuming
        the retry budget on further attempts.
        """
        now = _utcnow()
        async with self._session_factory() as session:
            row = await session.get(AnalyticsTask, task_id, with_for_update=True)
            if row is None:
                await session.commit()
                return False
            if row.lease_owner != owner or row.status in TASK_TERMINAL_STATUSES:
                await session.commit()
                return False

            attempt_number = row.attempt_count + 1
            row.attempt_count = attempt_number
            if error is None:
                row.status = TASK_STATUS_SUCCEEDED
                row.completed_at = now
                row.error_code = ""
                row.error_detail = ""
            elif isinstance(error, ExecutorNotWiredError):
                row.status = TASK_STATUS_FAILED
                row.completed_at = now
                row.error_code = ERROR_EXECUTOR_NOT_WIRED
                row.error_detail = str(error)[:2000]
            elif isinstance(error, TerminalExecutorError):
                row.status = TASK_STATUS_FAILED
                row.completed_at = now
                row.error_code = error.error_code
                row.error_detail = str(error)[:2000]
            elif attempt_number < row.max_attempts:
                row.status = TASK_STATUS_RETRY_WAIT
                row.available_at = now + timedelta(
                    seconds=analytics_settings.retry_delay_seconds
                )
                row.error_code = ERROR_UNKNOWN
                row.error_detail = str(error)[:2000]
            else:
                row.status = TASK_STATUS_FAILED
                row.completed_at = now
                row.error_code = ANALYTICS_QUEUE_SPEC.max_attempts_error
                row.error_detail = str(error)[:2000]
            row.lease_owner = None
            row.lease_expires_at = None
            await session.commit()
            return True


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    instrument_worker("analytics-worker")
    worker = AnalyticsWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
