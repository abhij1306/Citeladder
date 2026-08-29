# Transient database lock conflicts, and what the worker does about them.
#
# Discovery admits child URLs while analyze finalizes a sibling, so the two
# routinely want the same rows. Postgres resolves that by rolling one
# transaction back — a statement about ordering, never about the page — so the
# task has to be re-queued rather than failed terminally.
from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_runtime import site_health_settings
from app.models.site_health.queue import SiteCrawlTask


class _RetryableQueue(Protocol):
    """The one queue operation this module needs, kept narrow for testing."""

    async def retry(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        delay_seconds: float,
        error_code: str,
        error_detail: str,
        mutate: Callable[[Any], None] | None = ...,
    ) -> bool: ...


async def requeue_conflicted_task(
    queue: _RetryableQueue,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    owner: str,
    task_id: uuid.UUID,
    detail: str,
) -> bool:
    """Re-queue a lock-conflicted task without spending a fetch attempt."""
    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        conflict_count = int(getattr(task, "conflict_count", 0)) + 1
    if task is None or conflict_count > site_health_settings.db_conflict_max_requeues:
        return False
    return await queue.retry(
        task_id=task_id,
        owner=owner,
        delay_seconds=site_health_settings.db_conflict_retry_delay(conflict_count),
        error_code="crawl_task_lock_conflict",
        error_detail=detail,
        mutate=lambda row: setattr(row, "conflict_count", conflict_count),
    )
