"""Independent, resumable discovery and analysis phase controls."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health import (
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    CANCELLED_DISCOVERY_TASK_CLONE_LIMIT,
    CODE_ANALYSIS_LIMIT_EXCEEDED,
    CODE_DISCOVERY_LIMIT_EXCEEDED,
    CODE_PHASE_ALREADY_RUNNING,
    CODE_PHASE_NOT_RESUMABLE,
    CORPUS_DISPOSITION_ANALYZE,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_QUEUED,
    CRAWL_STATUS_RUNNING,
    CRAWL_TERMINAL_STATUSES,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    EVENT_ANALYSIS_STARTED,
    EVENT_ANALYSIS_STOPPED,
    EVENT_DISCOVERY_STARTED,
    EVENT_DISCOVERY_STOPPED,
    INITIAL_TASK_GENERATION,
    INVENTORY_SOURCE_CRAWL_IDS_KEY,
    OBSERVATION_SOURCE_ROOT,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    PHASE_ANALYSIS,
    PHASE_DISCOVERY,
    PHASE_RUN_RUNNING,
    PHASE_RUN_STOPPED,
    SELECTION_SOURCE_USER,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_QUEUED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.entitlements.service import refresh_site_health_runtime_for_workspace
from app.domain.site_health.discovery import drain_discovery_frontier
from app.domain.site_health.entitlements import lock_runtime
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlPhaseRun,
    SiteCrawlTask,
    SiteHealthProfile,
    SitePageAnalysis,
    SiteUrl,
    SiteUrlObservation,
)


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


def _now() -> datetime:
    return datetime.now(UTC)


async def _lock_crawl(
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


async def _next_ordinal(
    session: AsyncSession, *, crawl_id: uuid.UUID, phase: str
) -> int:
    current = await session.scalar(
        select(func.max(SiteCrawlPhaseRun.ordinal)).where(
            SiteCrawlPhaseRun.crawl_id == crawl_id,
            SiteCrawlPhaseRun.phase == phase,
        )
    )
    return int(current or 0) + 1


async def _running_phase(
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


async def _max_task_generations(
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


def _resume_crawl(crawl: SiteCrawl) -> None:
    if crawl.status in {CRAWL_STATUS_PAUSED, CRAWL_STATUS_QUEUED}:
        apply_crawl_status(crawl, CRAWL_STATUS_RUNNING)


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
    generations = await _max_task_generations(
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


async def start_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    additional_url_count: int,
) -> PhaseMutationResult:
    crawl = await _lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    if await _running_phase(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY):
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
    run = SiteCrawlPhaseRun(
        workspace_id=workspace_id,
        crawl_id=crawl.id,
        phase=PHASE_DISCOVERY,
        ordinal=await _next_ordinal(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY),
        status=PHASE_RUN_RUNNING,
        requested_count=additional_url_count,
    )
    session.add(run)
    await session.flush()
    crawl.discovery_requested_count += additional_url_count
    if crawl.discovery_status == DISCOVERY_STATUS_STOPPED:
        apply_discovery_status(crawl, DISCOVERY_STATUS_RUNNING)
    _resume_crawl(crawl)
    admitted = await drain_discovery_frontier(session, crawl=crawl, phase_run_id=run.id)
    scheduled = admitted.admitted
    if scheduled == 0:
        scheduled = await _clone_cancelled_discovery_tasks(
            session,
            crawl=crawl,
            phase_run_id=run.id,
            requested_count=additional_url_count,
        )
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


async def _stop_phase_tasks(
    session: AsyncSession, *, run_id: uuid.UUID, task_kinds: tuple[str, ...]
) -> None:
    await session.execute(
        update(SiteCrawlTask)
        .where(
            SiteCrawlTask.phase_run_id == run_id,
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


async def _pause_if_idle(session: AsyncSession, crawl: SiteCrawl) -> None:
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


async def stop_discovery(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> PhaseMutationResult:
    crawl = await _lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    run = await _running_phase(session, crawl_id=crawl.id, phase=PHASE_DISCOVERY)
    if run is not None:
        await _stop_phase_tasks(
            session, run_id=run.id, task_kinds=(TASK_KIND_DISCOVER,)
        )
        run.status = PHASE_RUN_STOPPED
        run.stopped_at = _now()
        if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
            apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_DISCOVERY_STOPPED,
            message="discovery stopped",
            count_disclosure=not crawl.sample_mode,
        )
    await _pause_if_idle(session, crawl)
    await session.commit()
    await session.refresh(crawl)
    return PhaseMutationResult(crawl=crawl, phase_run=run)


async def _analysis_candidates(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    explicit_ids: list[uuid.UUID],
    requested_count: int,
    include_completed: bool = False,
) -> list[SiteUrl]:
    admitted = (
        select(SiteUrlObservation.site_url_id)
        .where(SiteUrlObservation.crawl_id == crawl.id)
        .subquery()
    )
    if explicit_ids:
        valid = set(
            (
                await session.scalars(
                    select(SiteUrl.id).where(
                        SiteUrl.id.in_(explicit_ids),
                        SiteUrl.id.in_(select(admitted.c.site_url_id)),
                    )
                )
            ).all()
        )
        if valid != set(explicit_ids):
            raise PhaseControlError(
                "One or more selected URLs are not in this crawl",
                code="invalid_selection",
            )
    completed = (
        select(SitePageAnalysis.site_url_id)
        .where(
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
        )
        .subquery()
    )
    explicit_order = {
        site_url_id: index for index, site_url_id in enumerate(explicit_ids)
    }
    explicit_rows = list(
        (
            await session.scalars(select(SiteUrl).where(SiteUrl.id.in_(explicit_ids)))
        ).all()
    )
    explicit_rows.sort(key=lambda row: explicit_order[row.id])
    remaining = requested_count - len(explicit_rows)
    if remaining <= 0:
        return explicit_rows
    ranked_where = [
        SiteUrlObservation.crawl_id == crawl.id,
        SiteUrl.id.not_in(explicit_ids),
        # Automatic selection only ever proposes analyzable items. A document or
        # an excluded URL stays in the inventory for coverage, but spending an
        # analysis budget slot on one would fetch evidence the HTML analyzer
        # cannot read. An explicit user selection is deliberately not filtered
        # here — that path validates admission separately.
        SiteUrl.corpus_disposition == CORPUS_DISPOSITION_ANALYZE,
    ]
    if not include_completed:
        ranked_where.append(SiteUrl.id.not_in(select(completed.c.site_url_id)))
    ranked = list(
        (
            await session.scalars(
                select(SiteUrl)
                .join(SiteUrlObservation, SiteUrlObservation.site_url_id == SiteUrl.id)
                .where(*ranked_where)
                .order_by(
                    SiteUrlObservation.value_priority.desc(),
                    SiteUrlObservation.depth.asc(),
                    SiteUrl.normalized_url.asc(),
                    SiteUrl.id.asc(),
                )
                .limit(remaining)
            )
        ).all()
    )
    return [*explicit_rows, *ranked]


async def _lock_analysis_source(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    requested_url_count: int,
    site_url_ids: list[uuid.UUID],
) -> tuple[SiteCrawl, bool]:
    crawl = await session.scalar(
        select(SiteCrawl)
        .where(SiteCrawl.id == crawl_id, SiteCrawl.workspace_id == workspace_id)
        .with_for_update()
    )
    if crawl is None:
        raise PhaseControlError("Site Health crawl not found", code="not_found")
    if await _running_phase(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS):
        raise PhaseControlError(
            "Analysis is already running", code=CODE_PHASE_ALREADY_RUNNING
        )
    ceiling = int(
        (crawl.configuration or {}).get("max_analysis_urls")
        or site_health_settings.max_analysis_urls
    )
    if requested_url_count <= 0 or requested_url_count > ceiling:
        raise PhaseControlError(
            "The requested analysis batch is too large for this environment",
            code=CODE_ANALYSIS_LIMIT_EXCEEDED,
        )
    if len(site_url_ids) > requested_url_count:
        raise PhaseControlError(
            "The analysis count must include every selected URL",
            code="invalid_selection",
        )
    return crawl, crawl.status in CRAWL_TERMINAL_STATUSES


async def _lock_analysis_profile(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    expected_selection_version: int,
) -> SiteHealthProfile:
    profile = await session.scalar(
        select(SiteHealthProfile)
        .where(SiteHealthProfile.id == crawl.profile_id)
        .with_for_update()
    )
    if profile is None:
        raise PhaseControlError("Site Health profile not found", code="not_found")
    if profile.selection_version != expected_selection_version:
        raise PhaseControlError(
            "The monitored selection changed", code="stale_selection_version"
        )
    return profile


async def _ensure_monitoring_capacity(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl: SiteCrawl,
    candidates: list[SiteUrl],
    monitored_url_limit: int,
) -> None:
    used = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.workspace_id == workspace_id,
                MonitoredSiteUrl.active.is_(True),
            )
        )
        or 0
    )
    candidate_ids = [row.id for row in candidates]
    existing = set(
        (
            await session.scalars(
                select(MonitoredSiteUrl.site_url_id).where(
                    MonitoredSiteUrl.project_id == crawl.project_id,
                    MonitoredSiteUrl.site_url_id.in_(candidate_ids),
                    MonitoredSiteUrl.active.is_(True),
                )
            )
        ).all()
    )
    additional = sum(row.id not in existing for row in candidates)
    if used + additional > monitored_url_limit:
        raise PhaseControlError(
            "The monitored URL quota would be exceeded",
            code="site_health_quota_exceeded",
        )


async def _analysis_target_crawl(
    session: AsyncSession, *, source: SiteCrawl, create_new: bool
) -> SiteCrawl:
    if not create_new:
        return source
    configuration = dict(source.configuration or {})
    lineage = list(configuration.get(INVENTORY_SOURCE_CRAWL_IDS_KEY) or [])
    configuration[INVENTORY_SOURCE_CRAWL_IDS_KEY] = [
        str(source.id),
        *[value for value in lineage if value != str(source.id)],
    ]
    crawl = SiteCrawl(
        workspace_id=source.workspace_id,
        project_id=source.project_id,
        profile_id=source.profile_id,
        status=CRAWL_STATUS_QUEUED,
        root_url=source.root_url,
        random_seed=source.random_seed,
        configuration=configuration,
        sample_mode=source.sample_mode,
        discovery_status=DISCOVERY_STATUS_COMPLETED,
        inventory_complete=True,
        discovery_requested_count=source.discovery_requested_count,
        discovered_url_count=source.discovered_url_count,
        admitted_url_count=source.admitted_url_count,
        extractor_version=source.extractor_version,
        analyzer_version=source.analyzer_version,
        rule_catalog_version=source.rule_catalog_version,
        scoring_version=source.scoring_version,
    )
    session.add(crawl)
    await session.flush()
    return crawl


def _record_analysis_inventory(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl: SiteCrawl,
    phase_run_id: uuid.UUID,
    candidates: list[SiteUrl],
) -> None:
    for row in candidates:
        value = classify_url_admission(row.normalized_url)
        session.add(
            SiteUrlObservation(
                workspace_id=workspace_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                site_url_id=row.id,
                phase_run_id=phase_run_id,
                source_kind=OBSERVATION_SOURCE_ROOT,
                value_kind=value.value_kind,
                value_priority=value.priority,
                depth=row.depth,
                observed_url=row.normalized_url,
                final_url=row.normalized_url,
                content_type="",
                title=row.latest_title or "",
            )
        )
    crawl.admitted_url_count = len(candidates)
    crawl.discovered_url_count = len(candidates)


async def _schedule_analysis_tasks(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl: SiteCrawl,
    phase_run_id: uuid.UUID,
    candidates: list[SiteUrl],
    now: datetime,
) -> None:
    await session.execute(
        pg_insert(MonitoredSiteUrl)
        .values(
            [
                {
                    "workspace_id": workspace_id,
                    "project_id": crawl.project_id,
                    "profile_id": crawl.profile_id,
                    "site_url_id": row.id,
                    "active": True,
                    "selection_source": SELECTION_SOURCE_USER,
                    "selected_at": now,
                }
                for row in candidates
            ]
        )
        .on_conflict_do_update(
            index_elements=["project_id", "site_url_id"],
            set_={
                "active": True,
                "selection_source": SELECTION_SOURCE_USER,
                "selected_at": now,
                "deselected_at": None,
            },
        )
    )
    generations = await _max_task_generations(
        session,
        crawl_id=crawl.id,
        task_kind=TASK_KIND_ANALYZE,
        url_hashes=(row.url_hash for row in candidates),
    )
    task_values = []
    for row in candidates:
        generation = generations.get(row.url_hash, -1) + 1
        task_values.append(
            {
                "crawl_id": crawl.id,
                "workspace_id": workspace_id,
                "phase_run_id": phase_run_id,
                "site_url_id": row.id,
                "task_kind": TASK_KIND_ANALYZE,
                "requested_url": row.normalized_url,
                "url_hash": row.url_hash,
                "depth": row.depth,
                "generation": generation,
                "idempotency_key": (
                    f"{crawl.id}:{TASK_KIND_ANALYZE}:{row.url_hash}:{generation}"
                ),
                "status": TASK_STATUS_QUEUED,
            }
        )
    await session.execute(
        pg_insert(SiteCrawlTask)
        .values(task_values)
        .on_conflict_do_nothing(
            index_elements=["crawl_id", "task_kind", "url_hash", "generation"]
        )
    )


async def start_analysis(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl_id: uuid.UUID,
    requested_url_count: int,
    site_url_ids: list[uuid.UUID],
    expected_selection_version: int,
) -> PhaseMutationResult:
    source_crawl, terminal_source = await _lock_analysis_source(
        session,
        workspace_id=workspace_id,
        crawl_id=crawl_id,
        requested_url_count=requested_url_count,
        site_url_ids=site_url_ids,
    )
    profile = await _lock_analysis_profile(
        session,
        crawl=source_crawl,
        expected_selection_version=expected_selection_version,
    )
    await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=_now()
    )
    runtime = await lock_runtime(session, workspace_id)
    candidates = await _analysis_candidates(
        session,
        crawl=source_crawl,
        explicit_ids=site_url_ids,
        requested_count=requested_url_count,
        include_completed=terminal_source,
    )
    if not candidates:
        raise PhaseControlError(
            "No eligible URLs are available for this analysis batch",
            code="invalid_selection",
        )
    await _ensure_monitoring_capacity(
        session,
        workspace_id=workspace_id,
        crawl=source_crawl,
        candidates=candidates,
        monitored_url_limit=runtime.monitored_url_limit,
    )
    crawl = await _analysis_target_crawl(
        session, source=source_crawl, create_new=terminal_source
    )
    run = SiteCrawlPhaseRun(
        workspace_id=workspace_id,
        crawl_id=crawl.id,
        phase=PHASE_ANALYSIS,
        ordinal=await _next_ordinal(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS),
        status=PHASE_RUN_RUNNING,
        requested_count=requested_url_count,
    )
    session.add(run)
    await session.flush()
    now = _now()
    if terminal_source:
        _record_analysis_inventory(
            session,
            workspace_id=workspace_id,
            crawl=crawl,
            phase_run_id=run.id,
            candidates=candidates,
        )
    await _schedule_analysis_tasks(
        session,
        workspace_id=workspace_id,
        crawl=crawl,
        phase_run_id=run.id,
        candidates=candidates,
        now=now,
    )
    profile.selection_version += 1
    crawl.analysis_requested_count += len(candidates)
    if crawl.analysis_status != ANALYSIS_STATUS_RUNNING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)
    _resume_crawl(crawl)
    record_crawl_event(
        session,
        crawl_id=crawl.id,
        event_type=EVENT_ANALYSIS_STARTED,
        message="analysis started",
        payload={"requested_count": requested_url_count},
        count_disclosure=not crawl.sample_mode,
    )
    await session.commit()
    await session.refresh(crawl)
    await session.refresh(run)
    return PhaseMutationResult(
        crawl=crawl,
        phase_run=run,
        created_new_crawl=terminal_source,
        selection_version=profile.selection_version,
        scheduled_count=len(candidates),
    )


async def stop_analysis(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl_id: uuid.UUID
) -> PhaseMutationResult:
    crawl = await _lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    run = await _running_phase(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS)
    if run is not None:
        await _stop_phase_tasks(
            session,
            run_id=run.id,
            task_kinds=(TASK_KIND_ANALYZE, TASK_KIND_LINK_CHECK),
        )
        run.status = PHASE_RUN_STOPPED
        run.stopped_at = _now()
        if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
            apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_ANALYSIS_STOPPED,
            message="analysis stopped",
            count_disclosure=not crawl.sample_mode,
        )
    await _pause_if_idle(session, crawl)
    await session.commit()
    await session.refresh(crawl)
    return PhaseMutationResult(crawl=crawl, phase_run=run)
