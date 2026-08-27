"""Cross-queue lease sweeper: the reclaimer that survives a dead worker.

Every worker sweeps its OWN queue at the top of its loop, which is enough
while that worker is alive. It is exactly the case where it is not alive that
strands rows: a worker killed after ``mark_running`` leaves its row at
``running`` with an expired lease, and the only process that would reclaim it
is the one that just died. Commerce competitor discovery showed this as a
workspace polling "Discovery for this category is running" indefinitely.

So this process sweeps the parentless queues, owns none of them, and runs no
executors. (A queue whose reclaim must also reconcile an owning run is left to
that run's own worker -- see ``SWEPT_QUEUES`` below.)
It is deliberately the least privileged worker in the system: it only calls
``release_expired``, whose reclaim path is bounded, ``SKIP LOCKED`` (so it
never contends with a live worker holding its row), and already the
single writer of the reclaim transition. Running it alongside the real
workers is therefore safe rather than redundant -- whichever sweeps first
wins, and the other finds nothing.
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

# A queue whose spec names a `parent_id_attr` is deliberately NOT swept here.
# Reclaiming such a row at max attempts terminalizes it, and terminalizing the
# LAST outstanding task of a run means the owning discovery or crawl has to be
# reconciled in the same breath -- otherwise the task is `failed` while its
# parent sits `running` forever, which is a worse state than the stranded lease
# this process exists to clear. That reconciliation is domain logic owned by
# `brand_discovery_worker._reap_expired` and `site_health_worker`, both of
# which already sweep their own queue with `release_expired_detailed`. This
# process stays the least privileged one in the system: it reclaims only the
# queues where a reclaim needs no owner to be told.
SWEPT_QUEUES: tuple[PostgresQueueSpec, ...] = tuple(
    spec for spec in _CANDIDATE_QUEUES if spec.parent_id_attr is None
)

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
            (spec.model.__tablename__, PostgresTaskQueue(self._session_factory, spec))
            for spec in specs
        ]

    async def run_once(self) -> int:
        """One pass over every queue. Returns the total rows reclaimed."""
        reclaimed = 0
        for name, queue in self._queues:
            try:
                reclaimed += await queue.release_expired()
            except Exception:  # one bad queue must not stop the others
                logger.exception("queue sweep failed", extra={"queue": name})
        if reclaimed:
            logger.info(
                "queue sweeper reclaimed leases", extra={"reclaimed": reclaimed}
            )
        return reclaimed

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
