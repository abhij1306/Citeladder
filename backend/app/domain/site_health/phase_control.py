"""Independent, resumable discovery phase control.

The analysis half lives in ``phase_analysis``; the primitives both halves share
(crawl locking, phase-run ordinals, task cancellation, idle settling) live in
``phase_common``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    CANCELLED_DISCOVERY_TASK_CLONE_LIMIT,
    CODE_DISCOVERY_LIMIT_EXCEEDED,
    CODE_PHASE_ALREADY_RUNNING,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    EVENT_DISCOVERY_STARTED,
    EVENT_DISCOVERY_STOPPED,
    INITIAL_TASK_GENERATION,
    SITE_ACQUISITION_TASK_KINDS,
    TASK_KIND_DISCOVER,
    TASK_KIND_SITE_SETUP,
)
from app.core.config.site_health_crawl_policy import (
    PHASE_DISCOVERY,
    PHASE_RUN_RUNNING,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_QUEUED,
)
from app.domain.site_health.discovery import drain_discovery_frontier
from app.domain.site_health.phase_common import (
    PhaseControlError,
    PhaseMutationResult,
    lock_crawl,
    mark_manual_phase_lifecycle,
    mark_phase_run_stopped,
    max_task_generations,
    next_ordinal,
    pause_if_idle,
    phase_stop_changed_state,
    resume_crawl,
    running_phase,
    stop_phase_tasks,
)
from app.domain.site_health.state_events import (
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask


async def _clone_cancelled_discovery_tasks(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    phase_run_id: uuid.UUID,
    requested_count: int,
) -> int:
    rows = list(
        (
            await session.scalars(
                select(SiteCrawlTask)
                .where(
                    SiteCrawlTask.crawl_id == crawl.id,
                    SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                    SiteCrawlTask.status == TASK_STATUS_CANCELLED,
                )
                .order_by(SiteCrawlTask.updated_at.desc(), SiteCrawlTask.id.desc())
                .limit(min(requested_count, CANCELLED_DISCOVERY_TASK_CLONE_LIMIT))
            )
        ).all()
    )
    generations = await max_task_generations(
        session,
        crawl_id=crawl.id,
        task_kind=TASK_KIND_DISCOVER,
        url_hashes=(row.url_hash for row in rows),
    )
    created = 0
    for source in rows:
        generation = generations.get(source.url_hash, INITIAL_TASK_GENERATION) + 1
        task_id = await session.scalar(
            pg_insert(SiteCrawlTask)
            .values(
                crawl_id=crawl.id,
                workspace_id=crawl.workspace_id,
                phase_run_id=phase_run_id,
                site_url_id=source.site_url_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=source.requested_url,
                url_hash=source.url_hash,
                parent_site_url_id=source.parent_site_url_id,
                depth=source.depth,
                generation=generation,
                idempotency_key=f"{crawl.id}:{TASK_KIND_DISCOVER}:{source.url_hash}:{generation}",
                status=TASK_STATUS_QUEUED,
                priority=source.priority,
                randomized_position=source.randomized_position,
                max_attempts=source.max_attempts,
            )
            .on_conflict_do_nothing(
                index_elements=["crawl_id", "task_kind", "url_hash", "generation"]
            )
            .returning(SiteCrawlTask.id)
        )
        created += int(task_id is not None)
    return created


async def _resume_cancelled_site_setup(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    phase_run_id: uuid.UUID,
) -> None:
    """Restore the one-shot setup prerequisite when a stopped crawl resumes."""
    if crawl.site_facts is not None:
        return
    source = await session.scalar(
        select(SiteCrawlTask)
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.task_kind == TASK_KIND_SITE_SETUP,
            SiteCrawlTask.status == TASK_STATUS_CANCELLED,
        )
        .order_by(SiteCrawlTask.generation.desc(), SiteCrawlTask.id.desc())
        .limit(1)
    )
    if source is None:
        return
    generations = await max_task_generations(
        session,
        crawl_id=crawl.id,
        task_kind=TASK_KIND_SITE_SETUP,
        url_hashes=(source.url_hash,),
    )
    generation = generations.get(source.url_hash, INITIAL_TASK_GENERATION) + 1
    await session.execute(
        pg_insert(SiteCrawlTask)
        .values(
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            phase_run_id=phase_run_id,
            task_kind=TASK_KIND_SITE_SETUP,
            requested_url=source.requested_url,
            url_hash=source.url_hash,
            depth=0,
            generation=generation,
            idempotency_key=(
                f"{crawl.id}:{TASK_KIND_SITE_SETUP}:{source.url_hash}:{generation}"
            ),
            status=TASK_STATUS_QUEUED,
            priority=source.priority,
            randomized_position=source.randomized_position,
            max_attempts=source.max_attempts,
        )
        .on_conflict_do_nothing(
            index_elements=["crawl_id", "task_kind", "url_hash", "generation"]
        )
    )


async def start_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    additional_url_count: int,
) -> PhaseMutationResult:
    crawl = await lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    if await running_phase(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY):
        raise PhaseControlError(
            "Discovery is already running", code=CODE_PHASE_ALREADY_RUNNING
        )
    ceiling = int(
        (crawl.configuration or {}).get("max_discovery_urls")
        or site_health_settings.max_discovery_urls
    )
    if (
        additional_url_count <= 0
        or crawl.admitted_url_count + additional_url_count > ceiling
    ):
        raise PhaseControlError(
            "The requested discovery batch is too large for this environment",
            code=CODE_DISCOVERY_LIMIT_EXCEEDED,
        )
    mark_manual_phase_lifecycle(crawl)
    run = SiteCrawlPhaseRun(
        workspace_id=workspace_id,
        crawl_id=crawl.id,
        phase=PHASE_DISCOVERY,
        ordinal=await next_ordinal(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY),
        status=PHASE_RUN_RUNNING,
        requested_count=additional_url_count,
    )
    session.add(run)
    await session.flush()
    crawl.discovery_requested_count += additional_url_count
    if crawl.discovery_status == DISCOVERY_STATUS_STOPPED:
        apply_discovery_status(crawl, DISCOVERY_STATUS_RUNNING)
    resume_crawl(crawl)
    admitted = await drain_discovery_frontier(session, crawl=crawl, phase_run_id=run.id)
    scheduled = admitted.admitted
    if scheduled == 0:
        scheduled = await _clone_cancelled_discovery_tasks(
            session,
            crawl=crawl,
            phase_run_id=run.id,
            requested_count=additional_url_count,
        )
    await _resume_cancelled_site_setup(session, crawl=crawl, phase_run_id=run.id)
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_DISCOVERY_STARTED,
        message="discovery started",
        payload={"requested_count": additional_url_count},
        count_disclosure=not crawl.sample_mode,
    )
    await session.commit()
    await session.refresh(crawl)
    await session.refresh(run)
    return PhaseMutationResult(crawl=crawl, phase_run=run, scheduled_count=scheduled)


async def stop_discovery(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> PhaseMutationResult:
    crawl = await lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    run = await running_phase(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY)
    stopped_count = await stop_phase_tasks(
        session,
        crawl_id=crawl.id,
        task_kinds=tuple(sorted(SITE_ACQUISITION_TASK_KINDS)),
    )
    mark_phase_run_stopped(run)
    if phase_stop_changed_state(
        stopped_count=stopped_count,
        phase_was_running=crawl.discovery_status == DISCOVERY_STATUS_RUNNING,
    ):
        if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
            apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_DISCOVERY_STOPPED,
            message="discovery stopped",
            count_disclosure=not crawl.sample_mode,
        )
    await pause_if_idle(session, crawl)
    await session.commit()
    await session.refresh(crawl)
    return PhaseMutationResult(crawl=crawl, phase_run=run)
