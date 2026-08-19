"""Independent, resumable analysis phase control."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    CODE_ANALYSIS_LIMIT_EXCEEDED,
    CODE_PHASE_ALREADY_RUNNING,
    CRAWL_STATUS_QUEUED,
    CRAWL_TERMINAL_STATUSES,
    DISCOVERY_STATUS_COMPLETED,
    EVENT_ANALYSIS_STARTED,
    EVENT_ANALYSIS_STOPPED,
    OBSERVATION_SOURCE_ROOT,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    CORPUS_DISPOSITION_ANALYZE,
    INVENTORY_SOURCE_CRAWL_IDS_KEY,
    PHASE_ANALYSIS,
    PHASE_RUN_RUNNING,
    SELECTION_SOURCE_USER,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_QUEUED,
)
from app.domain.entitlements.service import refresh_site_health_runtime_for_workspace
from app.domain.site_health.entitlements import lock_runtime
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
    utcnow,
)
from app.domain.site_health.state_events import (
    apply_analysis_status,
    record_crawl_event,
)
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation


async def _reject_unusable_selection(
    session: AsyncSession,
    *,
    explicit_ids: list[uuid.UUID],
    admitted,
) -> None:
    """Fail an explicit selection that this crawl cannot analyze.

    Two separate reasons, reported separately because they are separate user
    errors. Admission alone is not enough: a document or an excluded URL sits in
    the inventory for coverage but carries no HTML the analyzer can read, so
    scheduling one spends a budget slot to produce a guaranteed failure. Both are
    REJECTED rather than silently dropped — a caller that named these specific
    URLs needs to be told which ones it cannot have.
    """
    wanted = set(explicit_ids)
    admitted_ids = set(
        (
            await session.scalars(
                select(SiteUrl.id).where(
                    SiteUrl.id.in_(explicit_ids),
                    SiteUrl.id.in_(select(admitted.c.site_url_id)),
                )
            )
        ).all()
    )
    if admitted_ids != wanted:
        raise PhaseControlError(
            "One or more selected URLs are not in this crawl",
            code="invalid_selection",
        )
    analyzable = set(
        (
            await session.scalars(
                select(SiteUrl.id).where(
                    SiteUrl.id.in_(explicit_ids),
                    SiteUrl.corpus_disposition == CORPUS_DISPOSITION_ANALYZE,
                )
            )
        ).all()
    )
    if analyzable != wanted:
        raise PhaseControlError(
            "One or more selected URLs cannot be analyzed as HTML",
            code="invalid_selection",
        )


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
        await _reject_unusable_selection(
            session, explicit_ids=explicit_ids, admitted=admitted
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
        # cannot read. Explicit selections are held to the same rule above,
        # where a non-analyzable pick is reported instead of silently dropped.
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
    if await running_phase(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS):
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
    generations = await max_task_generations(
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
    await refresh_site_health_runtime_for_workspace(
        session, workspace_id=workspace_id, at=utcnow()
    )
    runtime = await lock_runtime(session, workspace_id)
    profile = await _lock_analysis_profile(
        session,
        crawl=source_crawl,
        expected_selection_version=expected_selection_version,
    )
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
    mark_manual_phase_lifecycle(crawl)
    run = SiteCrawlPhaseRun(
        workspace_id=workspace_id,
        crawl_id=crawl.id,
        phase=PHASE_ANALYSIS,
        ordinal=await next_ordinal(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS),
        status=PHASE_RUN_RUNNING,
        requested_count=requested_url_count,
    )
    session.add(run)
    await session.flush()
    now = utcnow()
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
    resume_crawl(crawl)
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
    crawl = await lock_crawl(session, workspace_id=workspace_id, crawl_id=crawl_id)
    run = await running_phase(session, crawl_id=crawl.id, phase=PHASE_ANALYSIS)
    stopped_count = await stop_phase_tasks(
        session,
        crawl_id=crawl.id,
        task_kinds=(TASK_KIND_ANALYZE,),
    )
    mark_phase_run_stopped(run)
    if phase_stop_changed_state(
        stopped_count=stopped_count,
        phase_was_running=crawl.analysis_status == ANALYSIS_STATUS_RUNNING,
    ):
        if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
            apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_ANALYSIS_STOPPED,
            message="analysis stopped",
            count_disclosure=not crawl.sample_mode,
        )
    await pause_if_idle(session, crawl)
    await session.commit()
    await session.refresh(crawl)
    return PhaseMutationResult(crawl=crawl, phase_run=run)
