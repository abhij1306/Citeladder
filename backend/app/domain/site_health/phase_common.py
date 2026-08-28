"""Primitives shared by the discovery and analysis phase controls.

Both phase halves lock the same crawl row, allocate the same phase-run
ordinals, cancel the same task rows, and settle the same crawl sub-states. The
shared helpers live here so the two halves cannot drift apart (a duplicated
lock order is a deadlock waiting to happen).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    CODE_PHASE_NOT_RESUMABLE,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_QUEUED,
    CRAWL_STATUS_RUNNING,
    CRAWL_TERMINAL_STATUSES,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
)
from app.core.config.site_health_crawl_policy import (
    MANUAL_PHASE_LIFECYCLE_KEY,
    PHASE_RUN_RUNNING,
    PHASE_RUN_STOPPED,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
)
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask


class PhaseControlError(ValueError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PhaseMutationResult:
    crawl: SiteCrawl
    phase_run: SiteCrawlPhaseRun | None
    created_new_crawl: bool = False
    selection_version: int | None = None
    scheduled_count: int = 0


def utcnow() -> datetime:
    return datetime.now(UTC)


def mark_manual_phase_lifecycle(crawl: SiteCrawl) -> None:
    configuration = dict(crawl.configuration or {})
    configuration[MANUAL_PHASE_LIFECYCLE_KEY] = True
    crawl.configuration = configuration


async def lock_crawl(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl:
    crawl = await session.scalar(
        select(SiteCrawl)
        .where(SiteCrawl.id == crawl_id, SiteCrawl.workspace_id == workspace_id)
        .with_for_update()
    )
    if crawl is None:
        raise PhaseControlError("Site Health crawl not found", code="not_found")
    if crawl.status in CRAWL_TERMINAL_STATUSES:
        raise PhaseControlError(
            "This crawl is complete; start a new crawl to analyze it again",
            code=CODE_PHASE_NOT_RESUMABLE,
        )
    return crawl


async def lock_crawl_for_evidence_commit(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> SiteCrawl | None:
    """Refresh and lock a crawl without conflicting with child FK inserts.

    Evidence transactions already hold KEY SHARE through artifact/task foreign
    keys. ``FOR NO KEY UPDATE`` serializes status and counters while remaining
    compatible with sibling inserts; ``FOR UPDATE`` creates a deadlock cycle.
    """
    return await session.scalar(
        select(SiteCrawl)
        .where(SiteCrawl.id == crawl_id, SiteCrawl.workspace_id == workspace_id)
        .execution_options(populate_existing=True)
        .with_for_update(key_share=True)
    )


async def next_ordinal(
    session: AsyncSession, *, crawl_id: uuid.UUID, phase: str
) -> int:
    current = await session.scalar(
        select(func.max(SiteCrawlPhaseRun.ordinal)).where(
            SiteCrawlPhaseRun.crawl_id == crawl_id,
            SiteCrawlPhaseRun.phase == phase,
        )
    )
    return int(current or 0) + 1


async def running_phase(
    session: AsyncSession, *, crawl_id: uuid.UUID, phase: str
) -> SiteCrawlPhaseRun | None:
    return await session.scalar(
        select(SiteCrawlPhaseRun)
        .where(
            SiteCrawlPhaseRun.crawl_id == crawl_id,
            SiteCrawlPhaseRun.phase == phase,
            SiteCrawlPhaseRun.status == PHASE_RUN_RUNNING,
        )
        .order_by(SiteCrawlPhaseRun.ordinal.desc())
        .limit(1)
        .with_for_update()
    )


async def max_task_generations(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    task_kind: str,
    url_hashes: Iterable[str],
) -> dict[str, int]:
    hashes = set(url_hashes)
    if not hashes:
        return {}
    return {
        url_hash: int(generation)
        for url_hash, generation in (
            await session.execute(
                select(
                    SiteCrawlTask.url_hash,
                    func.max(SiteCrawlTask.generation),
                )
                .where(
                    SiteCrawlTask.crawl_id == crawl_id,
                    SiteCrawlTask.task_kind == task_kind,
                    SiteCrawlTask.url_hash.in_(hashes),
                )
                .group_by(SiteCrawlTask.url_hash)
            )
        ).all()
    }


def resume_crawl(crawl: SiteCrawl) -> None:
    if crawl.status in {CRAWL_STATUS_PAUSED, CRAWL_STATUS_QUEUED}:
        apply_crawl_status(crawl, CRAWL_STATUS_RUNNING)


async def stop_phase_tasks(
    session: AsyncSession, *, crawl_id: uuid.UUID, task_kinds: tuple[str, ...]
) -> int:
    result = await session.execute(
        update(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl_id,
            SiteCrawlTask.task_kind.in_(task_kinds),
            SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)),
        )
        .values(
            status=TASK_STATUS_CANCELLED,
            lease_owner=None,
            lease_expires_at=None,
            completed_at=func.now(),
            error_code="stopped",
        )
    )
    return _affected_row_count(result)


def _affected_row_count(result: Any) -> int:
    return int(cast(CursorResult[Any], result).rowcount or 0)


def mark_phase_run_stopped(run: SiteCrawlPhaseRun | None) -> None:
    if run is None:
        return
    run.status = PHASE_RUN_STOPPED
    run.stopped_at = utcnow()


def phase_stop_changed_state(*, stopped_count: int, phase_was_running: bool) -> bool:
    return stopped_count > 0 or phase_was_running


async def pause_if_idle(session: AsyncSession, crawl: SiteCrawl) -> None:
    """Settle crawl + phase state once no non-terminal task remains.

    A stop with no RUNNING phase-run row (the phase already drained, or a
    second Stop click) still has to leave truthful state behind: a RUNNING
    discovery/analysis sub-state that no non-terminal task backs renders as a
    live phase the user cannot stop. Deriving both sub-states from the
    outstanding-task count here makes Stop idempotent for every caller instead
    of depending on which rows a particular stop path happened to find.
    """
    outstanding = await session.scalar(
        select(func.count())
        .select_from(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)),
        )
    )
    if int(outstanding or 0) != 0:
        return
    if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
        apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
    if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)
    if crawl.status == CRAWL_STATUS_RUNNING:
        apply_crawl_status(crawl, CRAWL_STATUS_PAUSED)
