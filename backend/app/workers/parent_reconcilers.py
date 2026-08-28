"""Parent reconciliation for a terminal lease reclaim, shared by the sweeper.

A queue whose spec names a ``parent_id_attr`` owns a RUN, not just rows: when a
reclaim fails the last outstanding task at max attempts, the owning discovery
or crawl has to be terminalized in the same pass. Nothing else observes that
transition -- a task the sweeper fails never runs a worker's ``finally`` -- so
without this the task is ``failed`` while its parent sits ``running`` forever.

These live here rather than inside each worker so the cross-queue sweeper can
reclaim those queues when their domain worker is the process that died, which
is the exact case the sweeper exists for. Each worker keeps calling its own
sweep too; whichever runs first wins and the other finds nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.brand_discovery import (
    BRAND_DISCOVERY_QUEUE_SPEC,
    DISCOVERY_STATUS_COMPLETING,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_PROJECT_CREATED,
    DISCOVERY_STATUS_READY,
    ERROR_BRAND_COMPLETION,
    ERROR_BRAND_DISCOVERY,
    TASK_KIND_BRAND_COMPLETION,
    WARNING_BRAND_COMPLETION_FAILED,
)
from app.core.config.site_health_runtime import SITE_CRAWL_QUEUE_SPEC
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.models.discovery import BrandDiscovery, BrandDiscoveryTask

Reconciler = Callable[
    [async_sessionmaker[AsyncSession], list[uuid.UUID]], Awaitable[None]
]


async def reconcile_brand_discoveries(
    session_factory: async_sessionmaker[AsyncSession],
    parent_ids: list[uuid.UUID],
) -> None:
    """Fail discoveries whose active job exhausted its attempt budget."""
    if not parent_ids:
        return
    async with session_factory() as session:
        rows = list(
            (
                await session.scalars(
                    select(BrandDiscovery).where(BrandDiscovery.id.in_(parent_ids))
                )
            ).all()
        )
        failed_kinds: dict[uuid.UUID, set[str]] = {}
        for discovery_id, task_kind in (
            await session.execute(
                select(
                    BrandDiscoveryTask.discovery_id,
                    BrandDiscoveryTask.task_kind,
                ).where(
                    BrandDiscoveryTask.discovery_id.in_(parent_ids),
                    BrandDiscoveryTask.status == TASK_STATUS_FAILED,
                )
            )
        ).all():
            failed_kinds.setdefault(discovery_id, set()).add(task_kind)
        for row in rows:
            kinds = failed_kinds.get(row.id, set())
            if (
                TASK_KIND_BRAND_COMPLETION in kinds
                and row.status == DISCOVERY_STATUS_COMPLETING
            ):
                row.status = DISCOVERY_STATUS_FAILED
                row.stage = "failed"
                row.error_code = ERROR_BRAND_COMPLETION
                row.warnings = list(
                    dict.fromkeys([*row.warnings, WARNING_BRAND_COMPLETION_FAILED])
                )
                row.error_detail = BRAND_DISCOVERY_QUEUE_SPEC.max_attempts_error
                continue
            if row.status in {DISCOVERY_STATUS_READY, DISCOVERY_STATUS_PROJECT_CREATED}:
                continue
            row.status = DISCOVERY_STATUS_FAILED
            row.stage = "failed"
            row.error_code = ERROR_BRAND_DISCOVERY
            row.warnings = list(dict.fromkeys([*row.warnings, "research_degraded"]))
            row.error_detail = BRAND_DISCOVERY_QUEUE_SPEC.max_attempts_error
        await session.commit()


async def reconcile_site_crawls(
    session_factory: async_sessionmaker[AsyncSession],
    parent_ids: list[uuid.UUID],
) -> None:
    """Re-derive each affected crawl's status through its own lifecycle owner."""
    if not parent_ids:
        return
    # Imported here: the lifecycle module pulls in the Site Health analysis
    # stack, and the sweeper process should not pay for it unless a crawl
    # actually needs reconciling.
    from app.workers.site_health.lifecycle import CrawlLifecycle

    lifecycle = CrawlLifecycle(session_factory)
    for crawl_id in parent_ids:
        await lifecycle.reconcile(crawl_id)


# Keyed by the queue's table name, which is the one stable identity the sweeper
# already uses for logging. A parented queue MISSING from this map is a bug the
# sweeper reports rather than silently stranding, because its parents would go
# unreconciled.
PARENT_RECONCILERS: dict[str, Reconciler] = {
    BRAND_DISCOVERY_QUEUE_SPEC.model.__tablename__: reconcile_brand_discoveries,
    SITE_CRAWL_QUEUE_SPEC.model.__tablename__: reconcile_site_crawls,
}
