"""Crawl terminalization: the exactly-once lifecycle of a ``SiteCrawl``.

Extracted from ``SiteHealthWorker`` because this is the subsystem's most
load-bearing invariant and it was buried at the bottom of a 3,100-line class.

A crawl goes terminal HERE and nowhere else. ``reconcile_after_task`` filters
only intermediate, successful analysis work through a read-only durable-state
check; every other task finalize, the lease sweeper's terminal reclaims, and
the stalled-crawl backstop reach ``reconcile``. It must therefore remain
idempotent and safe to call concurrently. It achieves that by holding the
crawl row ``FOR UPDATE`` and short-circuiting on an already-terminal crawl.

Note what is deliberately INSIDE that lock: the crawl_finalize evaluation pass
and the aggregate snapshot. Their atomicity with the status transition IS the
exactly-once guarantee — moving them to a follow-up transaction would open a
crash window leaving a terminal crawl with no snapshot and no finalize-scoped
issues, a state no retry can repair (the snapshot writer is ``ON CONFLICT DO
NOTHING`` and reconcile short-circuits on terminal crawls).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from app.core.config.site_health_acquisition import (
    CORPUS_EXCLUSION_ERROR_CODES,
)
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_CANCELLED,
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    APPLICABILITY_CRAWL_FINALIZE,
    CRAWL_ACTIVE_STATUSES,
    CRAWL_PARTIAL_REASON_ANALYSIS,
    CRAWL_PARTIAL_REASON_BOTH,
    CRAWL_PARTIAL_REASON_DISCOVERY,
    CRAWL_PARTIAL_REASON_NONE,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_DRAFT,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_PAUSED,
    CRAWL_STATUS_QUEUED,
    CRAWL_STATUS_RUNNING,
    CRAWL_STATUS_VALIDATING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_STOPPED,
    EVENT_CRAWL_COMPLETED,
    EVENT_CRAWL_FAILED,
    SITE_TASK_KINDS,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    MANUAL_PHASE_LIFECYCLE_KEY,
    PHASE_ANALYSIS,
    PHASE_DISCOVERY,
    PHASE_RUN_COMPLETED,
    PHASE_RUN_RUNNING,
)
from app.core.config.site_health_rules import (
    SITE_HEALTH_RULES_BY_ID,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.site_health.change_queue import enqueue_change_refresh
from app.domain.site_health.failure import load_root_failure_summary
from app.domain.site_health.link_queue import enqueue_link_metric_refresh
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.domain.site_health.task_guards import crawl_is_active
from app.domain.site_health.terminal_refresh import enqueue_terminal_analytics_refresh
from app.models.site_health.crawl import SiteCrawl, SiteCrawlPhaseRun
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrlObservation
from app.workers.site_health.lifecycle_finalize import (
    CrawlFinalizeMixin,
)

logger = logging.getLogger("app.workers.site_health.lifecycle")


def _utcnow() -> datetime:
    return datetime.now(UTC)


# The legal intermediate hops from each non-running ACTIVE status up to
# ``running`` (``_CRAWL_TRANSITIONS`` has no direct edge from queued/draft to a
# terminal state). Used only by the drained-crawl terminalization below, so a
# crawl whose work finished before it was ever marked running can still reach
# its terminal state instead of staying active forever.
_RUNNING_PATH: Final[dict[str, tuple[str, ...]]] = {
    CRAWL_STATUS_DRAFT: (
        CRAWL_STATUS_VALIDATING,
        CRAWL_STATUS_QUEUED,
        CRAWL_STATUS_RUNNING,
    ),
    CRAWL_STATUS_VALIDATING: (CRAWL_STATUS_QUEUED, CRAWL_STATUS_RUNNING),
    CRAWL_STATUS_QUEUED: (CRAWL_STATUS_RUNNING,),
}


def _count_disclosure(crawl: SiteCrawl) -> bool:
    """Free crawls never disclose absolute counts in event payloads."""
    return not crawl.sample_mode


def _start_planned_analysis(crawl: SiteCrawl, *, analyze_total: int) -> None:
    """Enter the analysis lifecycle once its first task has been admitted."""
    if analyze_total > 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)


@dataclass(frozen=True, slots=True)
class _TaskSummary:
    """The task counts that drive one locked lifecycle reconciliation."""

    discover_remaining: int
    discover_failed: int
    analyze_remaining: int
    analyze_total: int
    analyze_succeeded: int
    analyze_cancelled: int
    analyze_excluded: int

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> _TaskSummary:
        return cls(
            discover_remaining=counts["discover_non_terminal"],
            discover_failed=counts["discover_failed"],
            analyze_remaining=counts["analyze_non_terminal"],
            analyze_total=counts["analyze_total"],
            analyze_succeeded=counts["analyze_succeeded"],
            analyze_cancelled=counts["analyze_cancelled"],
            analyze_excluded=counts["analyze_excluded"],
        )

    @property
    def analyze_applicable(self) -> int:
        """Pages this crawl was ever going to be able to analyze.

        Excludes cancelled tasks and every page that left the corpus by policy
        (``CORPUS_EXCLUSION_ERROR_CODES``): a redirect onto a customer-account
        host, or a URL robots told us not to fetch. Those are pages the crawl
        decided not to analyze, not pages it failed to analyze, so counting
        them as failures made a crawl that reached everything it could report
        itself ``partially_completed``.
        """
        return self.analyze_total - self.analyze_cancelled - self.analyze_excluded

    @property
    def all_drained(self) -> bool:
        return not (self.discover_remaining or self.analyze_remaining)


def _reconcile_discovery_state(
    crawl: SiteCrawl, summary: _TaskSummary
) -> tuple[bool, bool]:
    """Progressively terminalize discovery and return failure classifications."""
    discovery_failed = crawl.discovered_url_count == 0
    # A recrawl can still produce fresh analyses from the persistent monitored
    # set when its root discovery request is blocked. That is useful partial
    # evidence, not a fully failed crawl. Classifying it as FAILED discarded
    # the downstream Opportunities refresh even after every selected page was
    # analyzed successfully.
    fully_failed = discovery_failed and summary.analyze_succeeded == 0
    discovery_partial = summary.discover_failed > 0 and not fully_failed
    if summary.discover_remaining == 0:
        if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
            status = (
                DISCOVERY_STATUS_FAILED
                if discovery_failed
                else DISCOVERY_STATUS_COMPLETED
            )
            apply_discovery_status(crawl, status)
        crawl.inventory_complete = not discovery_failed
    return fully_failed, discovery_partial


def _partial_reason(*, discovery_partial: bool, analysis_partial: bool) -> str:
    """Name what actually fell short, so the UI never has to guess.

    A crawl that met one dead link and analyzed every page it DID fetch is a
    normal outcome on a real site; saying "pages could not be analyzed" there
    is simply false, and it fired on effectively every crawl.
    """
    if discovery_partial and analysis_partial:
        return CRAWL_PARTIAL_REASON_BOTH
    if discovery_partial:
        return CRAWL_PARTIAL_REASON_DISCOVERY
    if analysis_partial:
        return CRAWL_PARTIAL_REASON_ANALYSIS
    return CRAWL_PARTIAL_REASON_NONE


def _terminalize_analysis_state(
    crawl: SiteCrawl, *, summary: _TaskSummary, fully_failed: bool
) -> bool:
    """Drive the drained analysis sub-state and report whether it changed."""
    if summary.analyze_total == 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)
    if crawl.analysis_status != ANALYSIS_STATUS_RUNNING:
        return False

    if summary.analyze_total > 0 and summary.analyze_applicable == 0:
        status = ANALYSIS_STATUS_CANCELLED
    elif fully_failed:
        status = ANALYSIS_STATUS_FAILED
    elif summary.analyze_succeeded == summary.analyze_applicable:
        status = ANALYSIS_STATUS_COMPLETED
    elif summary.analyze_succeeded > 0:
        status = ANALYSIS_STATUS_PARTIALLY_COMPLETED
    else:
        status = ANALYSIS_STATUS_FAILED
    apply_analysis_status(crawl, status)
    return True


def _advance_drained_crawl_to_running(crawl: SiteCrawl) -> None:
    """Walk a drained active crawl through the legal pre-terminal states."""
    if not crawl_is_active(crawl) or crawl.status == CRAWL_STATUS_RUNNING:
        return
    for step in _RUNNING_PATH.get(crawl.status, ()):
        apply_crawl_status(crawl, step)


def _stop_drained_phases(crawl: SiteCrawl) -> None:
    """Stop phase sub-states left RUNNING once every task has drained.

    An advanced-control crawl is parked between user-started phases, so its
    phases terminalize to STOPPED (resumable) rather than COMPLETED. Callers
    must only reach this once no non-terminal task of any kind remains: a
    RUNNING sub-state with no work behind it is not a live phase, it is a lie
    the dashboard renders as an in-flight run.
    """
    if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
        apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
    if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)


def _pause_running_crawl(crawl: SiteCrawl) -> None:
    """Park a drained advanced-control crawl until another phase is started."""
    if crawl.status == CRAWL_STATUS_RUNNING:
        apply_crawl_status(crawl, CRAWL_STATUS_PAUSED)


def _stop_completed_manual_phase(crawl: SiteCrawl, phase: str) -> None:
    """Stop a drained user-controlled phase without parking sample crawls."""
    if crawl.sample_mode:
        return
    if phase == PHASE_DISCOVERY and crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
        apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
    elif phase == PHASE_ANALYSIS and crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
        apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)


def _uses_phase_lifecycle(crawl: SiteCrawl) -> bool:
    """Whether persisted phase-run bookkeeping participates in reconciliation."""
    return crawl.sample_mode or bool(
        (crawl.configuration or {}).get(MANUAL_PHASE_LIFECYCLE_KEY)
    )


def _is_crawl_finalize_rule(rule_id: str) -> bool:
    """Whether a catalog rule is scoped ``crawl_finalize`` (finalize-owned)."""
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    return rule is not None and rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE


class CrawlLifecycle(CrawlFinalizeMixin):
    """Owns crawl status reconciliation, the finalize pass, and the snapshot."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reconcile_after_task(
        self,
        task: SiteCrawlTask,
    ) -> None:
        """Reconcile a task finalize unless it is safely intermediate analysis.

        Successful analysis pages dominate crawl volume. While sibling discover
        or analyze work remains, their persisted evidence cannot change any
        lifecycle boundary, so taking the crawl lock and recomputing all
        aggregates is pure overhead. The single query below is deliberately
        strict: unknown rows and workspace mismatches touch nothing, and every
        known state outside the narrow standard-crawl case falls through to the
        authoritative locked reconciliation.
        """
        can_skip = await self._can_skip_intermediate_analyze_reconcile(
            crawl_id=task.crawl_id,
            task_id=task.id,
            workspace_id=task.workspace_id,
        )
        if can_skip is None or can_skip:
            return
        await self.reconcile(task.crawl_id)

    async def _can_skip_intermediate_analyze_reconcile(
        self,
        *,
        crawl_id: uuid.UUID,
        task_id: uuid.UUID,
        workspace_id: uuid.UUID,
    ) -> bool | None:
        """Return true only for a durable, non-boundary analyze success.

        ``None`` means the task/crawl pair was not found in the supplied
        workspace. It is not safe to reconcile an unscoped crawl id in that
        case, so the caller intentionally performs no mutation.
        """
        remaining_task = aliased(SiteCrawlTask)
        has_outstanding_work = (
            select(remaining_task.id)
            .where(
                remaining_task.crawl_id == crawl_id,
                remaining_task.workspace_id == workspace_id,
                remaining_task.task_kind.in_([TASK_KIND_DISCOVER, TASK_KIND_ANALYZE]),
                remaining_task.status.not_in(list(TASK_TERMINAL_STATUSES)),
            )
            .exists()
        )
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(
                        SiteCrawlTask.task_kind.label("task_kind"),
                        SiteCrawlTask.status.label("task_status"),
                        SiteCrawlTask.result_artifact_id.label("artifact_id"),
                        SiteCrawl.status.label("crawl_status"),
                        SiteCrawl.analysis_status.label("analysis_status"),
                        SiteCrawl.sample_mode.label("sample_mode"),
                        SiteCrawl.configuration.label("crawl_configuration"),
                        has_outstanding_work.label("has_outstanding_work"),
                    )
                    .join(SiteCrawl, SiteCrawl.id == SiteCrawlTask.crawl_id)
                    .where(
                        SiteCrawlTask.id == task_id,
                        SiteCrawlTask.crawl_id == crawl_id,
                        SiteCrawlTask.workspace_id == workspace_id,
                        SiteCrawl.workspace_id == workspace_id,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        configuration = (
            row.crawl_configuration if isinstance(row.crawl_configuration, dict) else {}
        )
        return bool(
            row.task_kind == TASK_KIND_ANALYZE
            and row.task_status == TASK_STATUS_SUCCEEDED
            and row.artifact_id is not None
            and row.crawl_status == CRAWL_STATUS_RUNNING
            and row.analysis_status == ANALYSIS_STATUS_RUNNING
            and not row.sample_mode
            and not configuration.get(MANUAL_PHASE_LIFECYCLE_KEY)
            and row.has_outstanding_work
        )

    async def reconcile(self, crawl_id: uuid.UUID) -> None:
        """Reconcile the crawl's overall status from discovery AND analysis.

        The single shared finalize for every task kind. It:
          - terminalizes the DISCOVERY sub-state once discover tasks drain
            (progressively, even while analysis work remains);
          - drives the independent ANALYSIS lifecycle (pending -> running ->
            completed/partially_completed/failed) from the analyze task
            outcomes;
          - terminalizes analysis as soon as discovery and analyze work drain;
          - terminalizes the OVERALL crawl once crawl work drains, classifying
            completed / partially_completed /
            failed and then persisting the aggregate ``SiteHealthSnapshot`` +
            a ``crawl.completed`` event.

        Keeping the crawl row ``FOR UPDATE`` and terminalizing exactly once (a
        completed crawl short-circuits) is what prevents a late analyze finalize
        from calling ``apply_crawl_status`` out of a terminal state (which would
        raise ``InvalidSiteCrawlTransition`` — all terminal states are empty
        sets in the transition tables).

        On the call that actually drives the crawl terminal, a durable analytics
        task is queued to refresh the project's Opportunities from fresh evidence.
        """
        async with self._session_factory() as session:
            crawl = await session.get(SiteCrawl, crawl_id, with_for_update=True)
            if crawl is None or not crawl_is_active(crawl):
                if crawl is not None:
                    await session.rollback()
                return

            counts = await self._task_counts(session, crawl_id)
            summary = _TaskSummary.from_counts(counts)
            await self._refresh_derived_counters(session, crawl=crawl, summary=summary)

            if await self._reconcile_advanced_phase_runs(
                session, crawl=crawl, counts=counts
            ):
                await session.commit()
                return

            fully_failed, discovery_partial = _reconcile_discovery_state(crawl, summary)
            _start_planned_analysis(crawl, analyze_total=summary.analyze_total)
            # Discovery can still admit fresh analyze tasks, so analysis is
            # drained only when both kinds are done.
            if summary.discover_remaining == 0 and summary.analyze_remaining == 0:
                _terminalize_analysis_state(
                    crawl, summary=summary, fully_failed=fully_failed
                )
            if not summary.all_drained:
                await session.commit()
                return

            # Crawl-finalize rules use persisted page facts and run before the
            # snapshot so their issues enter its rollups.
            await self._run_crawl_finalize_pass(session, crawl=crawl)
            await self._persist_snapshot(session, crawl=crawl)

            _advance_drained_crawl_to_running(crawl)
            await self._terminalize_crawl(
                session,
                crawl=crawl,
                summary=summary,
                fully_failed=fully_failed,
                discovery_partial=discovery_partial,
            )
            await session.commit()

    async def _refresh_derived_counters(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        summary: _TaskSummary,
    ) -> None:
        """Repair counters from their durable task and observation authorities."""
        crawl.failed_url_count = await self._failed_url_count(session, crawl.id)
        crawl.analyzed_url_count = summary.analyze_succeeded
        observed_url_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteUrlObservation)
                .where(SiteUrlObservation.crawl_id == crawl.id)
            )
            or 0
        )
        # Admission is ahead of observation for full crawls: a parent page
        # reserves and queues child identities before those children are
        # fetched. Replacing the live admission counter with the smaller
        # observation count reopened the requested budget after every task,
        # allowing each sibling to enqueue another full batch. The persisted
        # counter is monotonic; observations can repair it upward, never down.
        crawl.admitted_url_count = max(crawl.admitted_url_count, observed_url_count)

    async def _terminalize_crawl(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        summary: _TaskSummary,
        fully_failed: bool,
        discovery_partial: bool,
    ) -> None:
        """Persist the final crawl status, event, and successful refresh task."""
        if crawl.status != CRAWL_STATUS_RUNNING:
            return
        crawl.completed_at = _utcnow()
        failure_summary: dict | None = None
        if fully_failed:
            apply_crawl_status(crawl, CRAWL_STATUS_FAILED)
            failure_summary = await load_root_failure_summary(session, crawl=crawl)
            if failure_summary is not None and not crawl.error_message:
                crawl.error_message = failure_summary["message"]
        else:
            analysis_partial = (
                summary.analyze_applicable > 0
                and summary.analyze_succeeded < summary.analyze_applicable
            )
            crawl.partial_reason = _partial_reason(
                discovery_partial=discovery_partial, analysis_partial=analysis_partial
            )
            apply_crawl_status(
                crawl,
                CRAWL_STATUS_PARTIALLY_COMPLETED
                if crawl.partial_reason
                else CRAWL_STATUS_COMPLETED,
            )

        if crawl.status == CRAWL_STATUS_FAILED:
            record_crawl_event(
                session,
                crawl_id=crawl.id,
                event_type=EVENT_CRAWL_FAILED,
                message="crawl failed",
                payload={"status": crawl.status, "failure": failure_summary},
                count_disclosure=_count_disclosure(crawl),
            )
            return
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_CRAWL_COMPLETED,
            message="crawl completed",
            payload={"status": crawl.status},
            count_disclosure=_count_disclosure(crawl),
        )
        if summary.analyze_succeeded > 0:
            await enqueue_change_refresh(session, crawl=crawl)
            await enqueue_link_metric_refresh(session, crawl=crawl)
        else:
            await enqueue_terminal_analytics_refresh(
                session, crawl=crawl, change_snapshot_id=None
            )

    async def _reconcile_advanced_phase_runs(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        counts: dict[str, int],
    ) -> bool:
        if not _uses_phase_lifecycle(crawl):
            return False
        phase_runs = list(
            (
                await session.scalars(
                    select(SiteCrawlPhaseRun)
                    .where(
                        SiteCrawlPhaseRun.crawl_id == crawl.id,
                        SiteCrawlPhaseRun.status == PHASE_RUN_RUNNING,
                    )
                    .order_by(SiteCrawlPhaseRun.ordinal.desc())
                    .with_for_update()
                )
            ).all()
        )
        for phase_run in phase_runs:
            if phase_run.phase == PHASE_DISCOVERY:
                phase_run.processed_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(SiteUrlObservation)
                        .where(
                            SiteUrlObservation.crawl_id == crawl.id,
                            SiteUrlObservation.phase_run_id == phase_run.id,
                        )
                    )
                    or 0
                )
                drained = counts["discover_non_terminal"] == 0
            else:
                phase_run.processed_count = int(
                    await session.scalar(
                        select(func.count())
                        .select_from(SiteCrawlTask)
                        .where(
                            SiteCrawlTask.phase_run_id == phase_run.id,
                            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                            SiteCrawlTask.status.in_(
                                [TASK_STATUS_SUCCEEDED, TASK_STATUS_FAILED]
                            ),
                        )
                    )
                    or 0
                )
                remaining_phase_tasks = await session.scalar(
                    select(func.count())
                    .select_from(SiteCrawlTask)
                    .where(
                        SiteCrawlTask.phase_run_id == phase_run.id,
                        SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                        SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)),
                    )
                )
                drained = int(remaining_phase_tasks or 0) == 0
            if drained:
                phase_run.status = PHASE_RUN_COMPLETED
                phase_run.completed_at = _utcnow()
                _stop_completed_manual_phase(crawl, phase_run.phase)

        outstanding = sum(
            counts[key]
            for key in (
                "discover_non_terminal",
                "analyze_non_terminal",
            )
        )
        if outstanding:
            return False
        # Sample crawls are an automatic bounded run, even when the local
        # development controls are enabled. Their initial discovery phase-run
        # is bookkeeping for progress; it must not turn a fully successful
        # sample into PAUSED/STOPPED before the normal lifecycle persists its
        # snapshot and completed event. Manual full-inventory phase batches
        # still park below so the user can explicitly continue them.
        if crawl.sample_mode:
            return False
        # The loop above only sees phase runs still marked RUNNING. Once an
        # earlier reconcile completed them, a later drained reconcile finds no
        # rows, skips the loop, and used to park the crawl PAUSED with the phase
        # sub-states left exactly as they were — so a crawl whose work had fully
        # drained kept reporting ``analysis_status=running`` forever, and the UI
        # kept rendering a live run with no non-terminal task behind it. The
        # phase sub-states are derived from the drained task counts, not from
        # the presence of a RUNNING phase-run row.
        _stop_drained_phases(crawl)
        _pause_running_crawl(crawl)
        return True

    async def reconcile_stalled(self) -> int:
        """Force-reconcile active crawls that have no outstanding work left.

        The backstop for the whole terminalization path. ``_reconcile_crawl_status``
        is normally reached from a task's ``finally``, so ANY route that drains a
        crawl's last non-terminal task without running a worker's finalize
        (sweeper reclaim, an out-of-band status write, a process killed between
        the queue ack and the finalize) strands the crawl in an active status
        forever: no snapshot, no ``crawl.completed`` event, and clients polling
        it indefinitely.

        Rather than enumerate those routes, this asks the terminal question
        directly — active crawl, zero non-terminal tasks, untouched for longer
        than the stall threshold — and reconciles. Idempotent and safe to run
        every loop: reconcile short-circuits on terminal crawls, and requiring
        BOTH an empty queue and a quiet period keeps it clear of live crawls
        that are merely between tasks.
        """
        threshold = site_health_settings.stalled_crawl_reconcile_seconds
        if threshold <= 0:  # disabled
            return 0
        cutoff = _utcnow() - timedelta(seconds=threshold)
        async with self._session_factory() as session:
            # Retired task kinds can remain in a pre-upgrade local database.
            # No current worker will claim them, so treating them as work would
            # permanently prevent the crawl from reaching its terminal state.
            outstanding = (
                select(SiteCrawlTask.id)
                .where(SiteCrawlTask.crawl_id == SiteCrawl.id)
                .where(SiteCrawlTask.task_kind.in_(SITE_TASK_KINDS))
                .where(SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
            )
            stalled = list(
                (
                    await session.scalars(
                        select(SiteCrawl.id)
                        .where(SiteCrawl.status.in_(list(CRAWL_ACTIVE_STATUSES)))
                        .where(SiteCrawl.status != CRAWL_STATUS_PAUSED)
                        .where(SiteCrawl.updated_at < cutoff)
                        .where(~outstanding.exists())
                        .order_by(SiteCrawl.updated_at.asc())
                        .limit(site_health_settings.stalled_crawl_reconcile_batch)
                    )
                ).all()
            )
        for crawl_id in stalled:
            logger.warning(
                "reconciling stalled crawl with no outstanding tasks",
                extra={"crawl_id": str(crawl_id)},
            )
            await self.reconcile(crawl_id)
        return len(stalled)

    async def _failed_url_count(
        self, session: AsyncSession, crawl_id: uuid.UUID
    ) -> int:
        """Distinct URLs with a terminally failed acquisition or analysis task."""
        return int(
            await session.scalar(
                select(func.count(func.distinct(SiteCrawlTask.url_hash))).where(
                    SiteCrawlTask.crawl_id == crawl_id,
                    SiteCrawlTask.status == TASK_STATUS_FAILED,
                    # A page that left the corpus by policy is an exclusion,
                    # not a failure: our admission rejected the resolved URL,
                    # robots told us not to fetch it. Nothing went wrong in
                    # either case.
                    SiteCrawlTask.error_code.not_in(
                        sorted(CORPUS_EXCLUSION_ERROR_CODES)
                    ),
                    SiteCrawlTask.task_kind.in_(
                        [TASK_KIND_DISCOVER, TASK_KIND_ANALYZE]
                    ),
                    # A blank hash is not a URL. Counting it would report one
                    # phantom failed page for every task that failed before its
                    # URL was canonicalized.
                    SiteCrawlTask.url_hash != "",
                )
            )
            or 0
        )

    async def _task_counts(
        self, session: AsyncSession, crawl_id: uuid.UUID
    ) -> dict[str, int]:
        """Aggregate per-kind terminal/non-terminal task counts for a crawl.

        ONE grouped scan with conditional (``FILTER``) counts rather than six
        serial ``COUNT(*)`` round trips over the same rows: this runs inside
        the crawl's ``FOR UPDATE`` window on every task's finalize, so the five
        extra round trips were five extra chances for a sibling task to queue
        behind the lock.
        """
        rows = (
            await session.execute(
                select(
                    SiteCrawlTask.task_kind,
                    func.count().label("total"),
                    func.count()
                    .filter(SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
                    .label("non_terminal"),
                    func.count()
                    .filter(SiteCrawlTask.status == TASK_STATUS_SUCCEEDED)
                    .label("succeeded"),
                    func.count()
                    .filter(SiteCrawlTask.status == TASK_STATUS_CANCELLED)
                    .label("cancelled"),
                    func.count()
                    .filter(SiteCrawlTask.status == TASK_STATUS_FAILED)
                    .label("failed"),
                    func.count()
                    .filter(
                        SiteCrawlTask.status == TASK_STATUS_FAILED,
                        SiteCrawlTask.error_code.in_(
                            sorted(CORPUS_EXCLUSION_ERROR_CODES)
                        ),
                    )
                    .label("excluded"),
                )
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .group_by(SiteCrawlTask.task_kind)
            )
        ).all()
        # A kind with no rows simply has no group; every count defaults to 0.
        by_kind = {row.task_kind: row for row in rows}

        def count(kind: str, field: str) -> int:
            row = by_kind.get(kind)
            return int(getattr(row, field)) if row is not None else 0

        return {
            "discover_non_terminal": count(TASK_KIND_DISCOVER, "non_terminal"),
            "analyze_non_terminal": count(TASK_KIND_ANALYZE, "non_terminal"),
            "analyze_total": count(TASK_KIND_ANALYZE, "total"),
            "analyze_succeeded": count(TASK_KIND_ANALYZE, "succeeded"),
            "analyze_cancelled": count(TASK_KIND_ANALYZE, "cancelled"),
            "analyze_excluded": count(TASK_KIND_ANALYZE, "excluded"),
            "analyze_failed": count(TASK_KIND_ANALYZE, "failed"),
            "discover_failed": max(
                count(TASK_KIND_DISCOVER, "failed")
                - count(TASK_KIND_DISCOVER, "excluded"),
                0,
            ),
        }
