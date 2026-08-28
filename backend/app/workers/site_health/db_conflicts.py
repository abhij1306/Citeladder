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

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_runtime import site_health_settings
from app.models.site_health.queue import SiteCrawlTask

# Postgres SQLSTATEs that mean "this transaction lost a race, run it again":
# 40001 serialization_failure, 40P01 deadlock_detected, 55P03 lock_not_available.
# None says anything about the page being crawled, so none is a terminal task
# failure.
#
# 55P03 is what `lock_timeout` raises, and it was missing: a sibling holding a
# contended row just long enough killed the waiter outright, with
# `attempt_count` and `conflict_count` both still 0 because the crash never
# reached the retry path at all. Three tasks died that way in one measured
# crawl and finalized it `partially_completed` -- a lock this worker would have
# got on a second try, reported as pages that could not be analyzed.
_TRANSIENT_DB_SQLSTATES = frozenset({"40001", "40P01", "55P03"})


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


def is_transient_db_conflict(exc: BaseException) -> bool:
    """Whether the database rolled this transaction back over a lock race.

    The SQLSTATE is the authority whenever the driver exposes one — a message
    match would read "deadlock detected" out of an unrelated error's own text.
    The message check is the fallback for a driver that carries no code.
    """
    coded = False
    for error in (exc, getattr(exc, "orig", None), getattr(exc, "__cause__", None)):
        if error is None:
            continue
        code = getattr(error, "sqlstate", None) or getattr(error, "pgcode", None)
        if code is None:
            continue
        coded = True
        if code in _TRANSIENT_DB_SQLSTATES:
            return True
    if coded:
        return False
    return isinstance(exc, DBAPIError) and any(
        token in str(exc)
        for token in (
            "deadlock detected",
            "could not serialize",
            "canceling statement due to lock timeout",
        )
    )


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
