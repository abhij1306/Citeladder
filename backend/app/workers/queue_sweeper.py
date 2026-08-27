"""Cross-queue lease sweeper: the reclaimer that survives a dead worker.

Every worker sweeps its OWN queue at the top of its loop, which is enough
while that worker is alive. It is exactly the case where it is not alive that
strands rows: a worker killed after ``mark_running`` leaves its row at
``running`` with an expired lease, and the only process that would reclaim it
is the one that just died. Commerce competitor discovery showed this as a
workspace polling "Discovery for this category is running" indefinitely.

So this process sweeps EVERY queue, owns none of them, and runs no executors.
Its reclaim path is bounded, ``SKIP LOCKED`` (so it never contends with a live
worker holding its row), and already the single writer of the reclaim
transition. Running it alongside the real workers is therefore safe rather
than redundant -- whichever sweeps first wins, and the other finds nothing.

A queue whose spec names a ``parent_id_attr`` needs one thing more. Reclaiming
its row at max attempts terminalizes the task, and terminalizing the LAST
outstanding task of a run leaves the owning discovery or crawl ``running``
forever unless it is reconciled in the same pass. Excluding those queues was
not a fix either -- it stranded exactly the rows the sweeper exists to clear,
in exactly the case (their worker is gone) it exists for. So the sweep uses
``release_expired_detailed`` and hands the reported parents to the domain
reconciler registered in ``parent_reconcilers``.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import ANALYTICS_QUEUE_SPEC
from app.core.config.audits import AUDIT_QUEUE_SPEC
from app.core.config.brand_discovery import BRAND_DISCOVERY_QUEUE_SPEC
from app.core.config.content import CONTENT_QUEUE_SPEC
from app.core.config.integrations_clients import INTEGRATION_QUEUE_SPEC
from app.core.config.site_health_runtime import SITE_CRAWL_QUEUE_SPEC
from app.core.config.task_queue import PostgresQueueSpec
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging, instrument_worker
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.parent_reconcilers import PARENT_RECONCILERS

logger = logging.getLogger("app.workers.queue_sweeper")

# Every durable queue in the system. A queue missing from this list keeps the
# old behaviour (reclaimed only by its own live worker), so the cost of
# forgetting one is a stranded row, not a crash -- hence the list is explicit
# rather than discovered by reflection.
_CANDIDATE_QUEUES: tuple[PostgresQueueSpec, ...] = (
    ANALYTICS_QUEUE_SPEC,
    AUDIT_QUEUE_SPEC,
    BRAND_DISCOVERY_QUEUE_SPEC,
    CONTENT_QUEUE_SPEC,
    INTEGRATION_QUEUE_SPEC,
    SITE_CRAWL_QUEUE_SPEC,
)

SWEPT_QUEUES: tuple[PostgresQueueSpec, ...] = _CANDIDATE_QUEUES

# Slower than any worker's own poll: this is the backstop for a process that
# is gone, not the primary path, and a lease has to expire before there is
# anything to reclaim at all.
SWEEP_INTERVAL_SECONDS = 30.0


class QueueSweeper:
    """Reclaims expired leases across every queue. Runs no executors."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        specs: tuple[PostgresQueueSpec, ...] = SWEPT_QUEUES,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queues = [
            (spec, PostgresTaskQueue(self._session_factory, spec)) for spec in specs
        ]

    async def run_once(self) -> int:
        """One pass over every queue. Returns the total rows reclaimed."""
        reclaimed = 0
        for spec, queue in self._queues:
            name = spec.model.__tablename__
            try:
                reclaimed += await self._sweep(spec, queue)
            except Exception:  # one bad queue must not stop the others
                logger.exception("queue sweep failed", extra={"queue": name})
        if reclaimed:
            logger.info(
                "queue sweeper reclaimed leases", extra={"reclaimed": reclaimed}
            )
        return reclaimed

    async def _sweep(self, spec: PostgresQueueSpec, queue: PostgresTaskQueue) -> int:
        """Reclaim one queue, reconciling any run a terminal reclaim orphaned."""
        sweep = await queue.release_expired_detailed()
        name = spec.model.__tablename__
        if spec.parent_id_attr is None or not sweep.failed_parent_ids:
            return sweep.reclaimed
        reconcile = PARENT_RECONCILERS.get(name)
        if reconcile is None:
            # Never silent: an unregistered parented queue means those runs are
            # now terminal-with-a-live-parent, which is the state this whole
            # path exists to prevent.
            logger.error(
                "no parent reconciler for a parented queue",
                extra={"queue": name, "parents": len(sweep.failed_parent_ids)},
            )
            return sweep.reclaimed
        await reconcile(self._session_factory, list(sweep.failed_parent_ids))
        logger.info(
            "queue sweeper reconciled orphaned parents",
            extra={"queue": name, "parents": len(sweep.failed_parent_ids)},
        )
        return sweep.reclaimed

    async def run_forever(self) -> None:  # pragma: no cover - process loop
        logger.info("queue sweeper started", extra={"queues": len(self._queues)})
        while True:
            try:
                await self.run_once()
            except Exception:  # defensive: the loop outlives any one pass
                logger.exception("queue sweeper loop iteration failed")
            await asyncio.sleep(SWEEP_INTERVAL_SECONDS)


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    instrument_worker("queue-sweeper")
    asyncio.run(QueueSweeper().run_forever())


if __name__ == "__main__":  # pragma: no cover - process entrypoint
    main()
