"""Capacity-sharing lane policy for the Site Health worker.

The queue remains one durable PostgreSQL owner. Lanes only control which task
kinds an in-process worker slot prefers to claim, preventing a large analysis
burst from consuming every slot while discovery still has frontier work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core.config.site_health_contracts import (
    SITE_ACQUISITION_TASK_KINDS,
    SITE_PROCESSING_TASK_KINDS,
)
from app.core.config.site_health_runtime import site_health_settings
from app.models.site_health.queue import SiteCrawlTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue

logger = logging.getLogger("app.workers.site_health.scheduling")

_ACQUISITION_KINDS = tuple(sorted(SITE_ACQUISITION_TASK_KINDS))
_PROCESSING_KINDS = tuple(sorted(SITE_PROCESSING_TASK_KINDS))


@dataclass(frozen=True, slots=True)
class WorkerLane:
    """One worker slot's preferred and borrowable queue task kinds."""

    preferred_kinds: tuple[str, ...]
    borrow_kinds: tuple[str, ...]


async def claim_for_lane(
    queue: PostgresTaskQueue[SiteCrawlTask], *, owner: str, lane: WorkerLane
) -> SiteCrawlTask | None:
    """Claim preferred work, borrowing the other lane only while idle."""
    try:
        claimed = await queue.claim(owner=owner, limit=1, kinds=lane.preferred_kinds)
        if claimed:
            return claimed[0]
        borrowed = await queue.claim(owner=owner, limit=1, kinds=lane.borrow_kinds)
        return borrowed[0] if borrowed else None
    except Exception:  # a DB blip must not kill the slot
        logger.exception("site health lane claim failed")
        return None


def build_lane_plan(
    *, concurrency: int, acquisition_reserve: int
) -> tuple[WorkerLane, ...]:
    """Reserve both lane preferences while allowing idle capacity to borrow.

    With more than one slot, processing always retains at least one preferred
    slot. A single-slot worker cannot reserve concurrent capacity, so it keeps
    the queue's existing processing-first order and borrows discovery work.
    """
    if concurrency <= 1:
        return (
            WorkerLane(
                preferred_kinds=_PROCESSING_KINDS,
                borrow_kinds=_ACQUISITION_KINDS,
            ),
        )

    acquisition_slots = min(acquisition_reserve, concurrency - 1)
    acquisition_lane = WorkerLane(
        preferred_kinds=_ACQUISITION_KINDS,
        borrow_kinds=_PROCESSING_KINDS,
    )
    processing_lane = WorkerLane(
        preferred_kinds=_PROCESSING_KINDS,
        borrow_kinds=_ACQUISITION_KINDS,
    )
    return (acquisition_lane,) * acquisition_slots + (processing_lane,) * (
        concurrency - acquisition_slots
    )


def configured_lane_plan() -> tuple[WorkerLane, ...]:
    """Build the live worker plan under the shared concurrency ceiling."""
    concurrency = max(
        1,
        min(
            site_health_settings.worker_concurrency,
            site_health_settings.global_concurrency,
        ),
    )
    return build_lane_plan(
        concurrency=concurrency,
        acquisition_reserve=site_health_settings.acquisition_lane_reserve,
    )
