"""Crawl terminalization: the exactly-once lifecycle of a ``SiteCrawl``.

Extracted from ``SiteHealthWorker`` because this is the subsystem's most
load-bearing invariant and it was buried at the bottom of a 3,100-line class.

A crawl goes terminal HERE and nowhere else. ``reconcile`` is called from every
task's finalize, from the lease sweeper's terminal reclaims, and from the
stalled-crawl backstop, so it must be idempotent and safe to call
concurrently. It achieves that by holding the crawl row ``FOR UPDATE`` and
short-circuiting on an already-terminal crawl.

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
from typing import Any, Final

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.site_health.finalize import (
    evaluate_broken_internal_link,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
)
from app.analysis.site_health.rules import RuleEvaluation
from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_CANCELLED,
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    ANALYSIS_STATUS_STOPPED,
    ANALYZER_VERSION,
    APPLICABILITY_CRAWL_FINALIZE,
    CRAWL_ACTIVE_STATUSES,
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
    EXTRACTOR_VERSION,
    LINK_KIND_ANCHOR,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
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
from app.domain.site_health.failure import load_root_failure_summary
from app.domain.site_health.link_graph_queue import enqueue_link_graph_refresh
from app.domain.site_health.normalization import canonical_identity, canonical_or_empty
from app.domain.site_health.selection import crawl_is_active
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.domain.site_health.terminal_refresh import enqueue_terminal_analytics_refresh
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlPhaseRun,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
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
    link_remaining: int

    @classmethod
    def from_counts(cls, counts: dict[str, int]) -> _TaskSummary:
        return cls(
            discover_remaining=counts["discover_non_terminal"],
            discover_failed=counts["discover_failed"],
            analyze_remaining=counts["analyze_non_terminal"],
            analyze_total=counts["analyze_total"],
            analyze_succeeded=counts["analyze_succeeded"],
            analyze_cancelled=counts["analyze_cancelled"],
            link_remaining=counts["link_non_terminal"],
        )

    @property
    def analyze_applicable(self) -> int:
        return self.analyze_total - self.analyze_cancelled

    @property
    def all_drained(self) -> bool:
        return not (
            self.discover_remaining or self.analyze_remaining or self.link_remaining
        )


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


def crawl_root_identity(crawl: SiteCrawl) -> tuple[str, str]:
    """``(canonical, url_hash)`` of the crawl root, or ``("", "")``."""
    try:
        return canonical_identity(crawl.root_url)
    except UrlPolicyError:
        return "", ""


def _pass_through_hreflang_evaluation() -> RuleEvaluation:
    """An unchecked evaluation — the sentence all empty/self-only pages get."""
    return evaluate_hreflang_conflict(
        alternate_count=0,
        checked_count=0,
        unchecked_count=0,
        missing_return_tags=[],
    )


def _cross_check_hreflang_alternates(
    alternates: list[dict],
    source_canonical: str,
    alternates_by_page: dict[str, list[dict]],
) -> tuple[int, int, list[str]]:
    """Walk each alternate and check the reciprocal link back.

    A target with no analyzed artifact contributes to ``unchecked_count`` —
    we cannot verify it (spec §5.3). A self-referencing alternate is fine.
    Any checked target that fails to link back joins ``missing``.
    """
    checked_count = 0
    unchecked_count = 0
    missing: list[str] = []
    for alternate in alternates:
        target_url = str(alternate.get("url") or "")
        target_canonical = canonical_or_empty(target_url)
        if not target_canonical:
            unchecked_count += 1
            continue
        if target_canonical == source_canonical:
            continue
        target_alternates = alternates_by_page.get(target_canonical)
        if target_alternates is None:
            unchecked_count += 1
            continue
        checked_count += 1
        return_tag_found = any(
            canonical_or_empty(str(back.get("url") or "")) == source_canonical
            for back in target_alternates
        )
        if not return_tag_found and target_url not in missing:
            missing.append(target_url)
    return checked_count, unchecked_count, missing


def _evaluate_hreflang_for_page(
    alternates: list[dict],
    source_canonical: str | None,
    alternates_by_page: dict[str, list[dict]],
) -> RuleEvaluation:
    """Score one page's alternates against the crawl-wide alternates map."""
    if not alternates or not source_canonical:
        return _pass_through_hreflang_evaluation()
    checked, unchecked, missing = _cross_check_hreflang_alternates(
        alternates, source_canonical, alternates_by_page
    )
    return evaluate_hreflang_conflict(
        alternate_count=len(alternates),
        checked_count=checked,
        unchecked_count=unchecked,
        missing_return_tags=missing,
    )


async def _crawl_hreflang_indexes(
    session: AsyncSession,
    artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
) -> tuple[
    list[tuple[uuid.UUID, str, list[dict]]],
    dict[str, list[dict]],
    dict[uuid.UUID, str],
]:
    """One query → per-artifact alternates + the canonical->alternates index."""
    artifacts = (
        await session.execute(
            select(
                SiteFetchArtifact.id,
                SiteFetchArtifact.final_url,
                SiteFetchArtifact.normalized_facts,
            )
            .where(SiteFetchArtifact.id.in_(artifact_by_analysis.values()))
            .order_by(SiteFetchArtifact.id)
        )
    ).all()
    alternates_by_page: dict[str, list[dict]] = {}
    canonical_by_artifact: dict[uuid.UUID, str] = {}
    per_artifact: list[tuple[uuid.UUID, str, list[dict]]] = []
    for artifact_id, final_url, facts in artifacts:
        canonical = canonical_or_empty(str(final_url or ""))
        alternates = list((facts or {}).get("hreflang_alternates") or [])
        if canonical:
            canonical_by_artifact[artifact_id] = canonical
            alternates_by_page.setdefault(canonical, alternates)
        per_artifact.append((artifact_id, canonical, alternates))
    return per_artifact, alternates_by_page, canonical_by_artifact


class CrawlLifecycle:
    """Owns crawl status reconciliation, the finalize pass, and the snapshot."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reconcile(self, crawl_id: uuid.UUID) -> None:
        """Reconcile the crawl's overall status from discovery AND analysis.

        The single shared finalize for every task kind. It:
          - terminalizes the DISCOVERY sub-state once discover tasks drain
            (progressively, even while analyze/link_check work remains);
          - drives the independent ANALYSIS lifecycle (pending -> running ->
            completed/partially_completed/failed) from the analyze task
            outcomes;
          - terminalizes analysis as soon as discovery and analyze work drain,
            while link checks may continue under the still-active crawl;
          - terminalizes the OVERALL crawl ONLY when EVERY non-terminal task of
            ALL kinds is drained, classifying completed / partially_completed /
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
            # drained only when BOTH kinds are done. Link checks are a later
            # evidence phase: keeping analysis RUNNING until they finish made
            # 150/150 analyzed pages look stuck and hid the UI's explicit
            # "checking links" state.
            if summary.discover_remaining == 0 and summary.analyze_remaining == 0:
                _terminalize_analysis_state(
                    crawl, summary=summary, fully_failed=fully_failed
                )
            if not summary.all_drained:
                await session.commit()
                return

            # Crawl-finalize rules wait for link evidence, then run before the
            # snapshot so their issues enter its rollups. Analysis may already
            # have terminalized on an earlier reconciliation.
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
        elif discovery_partial or (
            summary.analyze_applicable > 0
            and summary.analyze_succeeded < summary.analyze_applicable
        ):
            apply_crawl_status(crawl, CRAWL_STATUS_PARTIALLY_COMPLETED)
        else:
            apply_crawl_status(crawl, CRAWL_STATUS_COMPLETED)

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
        await enqueue_link_graph_refresh(
            session,
            crawl=crawl,
            usable_evidence=summary.analyze_succeeded > 0,
        )
        if summary.analyze_succeeded == 0:
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
                        SiteCrawlTask.task_kind.in_(
                            [TASK_KIND_ANALYZE, TASK_KIND_LINK_CHECK]
                        ),
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
                "link_non_terminal",
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
            outstanding = (
                select(SiteCrawlTask.id)
                .where(SiteCrawlTask.crawl_id == SiteCrawl.id)
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
        """Distinct URLs with at least one terminally failed task, any kind.

        ``link_check`` is excluded: a broken outbound link is page EVIDENCE (it
        becomes an issue on the page that links to it), not a failure to acquire
        the URL being crawled, and counting it here would report a healthy page
        as a failed one.
        """
        return int(
            await session.scalar(
                select(func.count(func.distinct(SiteCrawlTask.url_hash))).where(
                    SiteCrawlTask.crawl_id == crawl_id,
                    SiteCrawlTask.status == TASK_STATUS_FAILED,
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
            "link_non_terminal": count(TASK_KIND_LINK_CHECK, "non_terminal"),
            "analyze_total": count(TASK_KIND_ANALYZE, "total"),
            "analyze_succeeded": count(TASK_KIND_ANALYZE, "succeeded"),
            "analyze_cancelled": count(TASK_KIND_ANALYZE, "cancelled"),
            "analyze_failed": count(TASK_KIND_ANALYZE, "failed"),
            "discover_failed": count(TASK_KIND_DISCOVER, "failed"),
        }

    # --- v2 P2: crawl_finalize evaluation pass -----------------------------

    async def _run_crawl_finalize_pass(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        """Orchestrate cross-page crawl-finalize rules under the crawl lock."""
        rows = await self._load_latest_analyses(session, crawl=crawl)
        if not rows:
            return
        analysis_ids = [row.id for row in rows]
        artifact_by_analysis = {row.id: row.artifact_id for row in rows}
        site_url_by_analysis = {row.id: row.site_url_id for row in rows}
        evaluations = await self._evaluate_broken_internal_links(
            session, analysis_ids=analysis_ids
        )
        evaluations.extend(
            await self._evaluate_hreflang_conflicts(
                session,
                rows=rows,
                artifact_by_analysis=artifact_by_analysis,
            )
        )
        evaluations.extend(
            await self._evaluate_sitemap_orphans(
                session,
                crawl=crawl,
                rows=rows,
                analysis_ids=analysis_ids,
                site_url_by_analysis=site_url_by_analysis,
            )
        )
        await self._persist_evaluations(
            session,
            crawl=crawl,
            evaluations=evaluations,
            artifact_by_analysis=artifact_by_analysis,
            site_url_by_analysis=site_url_by_analysis,
        )

    async def _load_latest_analyses(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> list[Any]:
        """Load the latest completed analysis for every URL in this crawl."""
        ranked = (
            select(
                SitePageAnalysis.id.label("id"),
                SitePageAnalysis.site_url_id.label("site_url_id"),
                SitePageAnalysis.artifact_id.label("artifact_id"),
                func.row_number()
                .over(
                    partition_by=SitePageAnalysis.site_url_id,
                    order_by=(
                        SitePageAnalysis.created_at.desc(),
                        SitePageAnalysis.id.desc(),
                    ),
                )
                .label("latest_rank"),
            )
            .where(
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            )
            .subquery()
        )
        return list(
            (
                await session.execute(
                    select(
                        ranked.c.id, ranked.c.site_url_id, ranked.c.artifact_id
                    ).where(ranked.c.latest_rank == 1)
                )
            ).all()
        )

    async def _evaluate_broken_internal_links(
        self, session: AsyncSession, *, analysis_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        """Evaluate per-analysis internal-link reachability evidence."""
        # Reachability rides the evidence_fingerprint prefix written by
        # ``_write_link_reference`` ("reachable:" / "unreachable:"); ALL link
        # kinds count as internal targets. ``policy_skipped:`` rows (a
        # robots-denied target that was never probed) are excluded: no
        # reachability was observed, so they are neither checked nor broken.
        link_rows = (
            await session.execute(
                select(
                    SiteLinkReference.source_analysis_id,
                    SiteLinkReference.target_url,
                    SiteLinkReference.evidence_fingerprint,
                ).where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.is_internal.is_(True),
                )
            )
        ).all()
        checked: dict[uuid.UUID, int] = {}
        broken: dict[uuid.UUID, list[str]] = {}
        for source_analysis_id, target_url, fingerprint in link_rows:
            fp = str(fingerprint or "")
            if fp.startswith("policy_skipped:"):
                continue
            checked[source_analysis_id] = checked.get(source_analysis_id, 0) + 1
            if fp.startswith("unreachable:"):
                bucket = broken.setdefault(source_analysis_id, [])
                if target_url not in bucket:
                    bucket.append(target_url)
        return [
            (
                analysis_id,
                evaluate_broken_internal_link(
                    checked_count=checked.get(analysis_id, 0),
                    broken_urls=broken.get(analysis_id, []),
                ),
            )
            for analysis_id in analysis_ids
        ]

    async def _evaluate_hreflang_conflicts(
        self,
        session: AsyncSession,
        *,
        rows: list[Any],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        """Evaluate reciprocal hreflang tags from persisted artifact facts."""
        (
            per_artifact,
            alternates_by_page,
            canonical_by_artifact,
        ) = await _crawl_hreflang_indexes(session, artifact_by_analysis)
        analysis_by_artifact = {row.artifact_id: row.id for row in rows}
        return [
            (
                analysis_by_artifact[artifact_id],
                _evaluate_hreflang_for_page(
                    alternates,
                    canonical_by_artifact.get(artifact_id),
                    alternates_by_page,
                ),
            )
            for artifact_id, _canonical, alternates in per_artifact
        ]

    async def _evaluate_sitemap_orphans(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        rows: list[Any],
        analysis_ids: list[uuid.UUID],
        site_url_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        """Evaluate the crawl-wide sitemap-orphan rule on the root analysis."""
        root_canonical, root_hash = crawl_root_identity(crawl)
        if not root_hash:
            return []
        site_url_rows = (
            await session.execute(
                select(SiteUrl.id, SiteUrl.url_hash).where(
                    SiteUrl.id.in_(site_url_by_analysis.values())
                )
            )
        ).all()
        hash_by_site_url = {row[0]: row[1] for row in site_url_rows}
        root_analysis_id = next(
            (
                row.id
                for row in rows
                if hash_by_site_url.get(row.site_url_id) == root_hash
            ),
            None,
        )
        if root_analysis_id is None:
            return []
        sitemap_rows = (
            await session.execute(
                select(
                    SiteUrlObservation.site_url_id,
                    SiteUrlObservation.observed_url,
                ).where(
                    SiteUrlObservation.crawl_id == crawl.id,
                    SiteUrlObservation.source_kind == OBSERVATION_SOURCE_SITEMAP,
                )
            )
        ).all()
        anchor_rows = (
            await session.execute(
                select(SiteLinkReference.target_url).where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.is_internal.is_(True),
                    SiteLinkReference.kind == LINK_KIND_ANCHOR,
                )
            )
        ).all()
        linked_targets = {
            canonical
            for (target_url,) in anchor_rows
            if (canonical := canonical_or_empty(str(target_url)))
        }
        orphans: list[str] = []
        for _site_url_id, observed_url in sitemap_rows:
            observed = str(observed_url or "")
            observed_canonical = canonical_or_empty(observed)
            if (
                observed_canonical
                and observed_canonical != root_canonical
                and observed_canonical not in linked_targets
                and observed not in orphans
            ):
                orphans.append(observed)
        return [
            (
                root_analysis_id,
                evaluate_sitemap_orphan(
                    sitemap_url_count=len(sitemap_rows), orphan_urls=orphans
                ),
            )
        ]

    async def _persist_evaluations(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        evaluations: list[tuple[uuid.UUID, RuleEvaluation]],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
        site_url_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> None:
        """Persist conflict-safe finalize evaluations and their failed issues."""
        for analysis_id, ev in evaluations:
            artifact_id = artifact_by_analysis[analysis_id]
            inserted_id = await session.scalar(
                pg_insert(SiteRuleEvaluation)
                .values(
                    workspace_id=crawl.workspace_id,
                    analysis_id=analysis_id,
                    source_artifact_id=artifact_id,
                    rule_id=ev.rule_id,
                    dimension=ev.dimension,
                    category=ev.category,
                    severity=ev.severity,
                    finding_class=ev.finding_class,
                    weight=ev.weight,
                    outcome=ev.outcome,
                    evidence=ev.evidence,
                    supporting_artifact_ids=[artifact_id],
                    extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                    analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                    rule_version=ev.rule_version,
                )
                .on_conflict_do_nothing(index_elements=["analysis_id", "rule_id"])
                .returning(SiteRuleEvaluation.id)
            )
            if inserted_id is None:
                continue
            if ev.outcome == RULE_OUTCOME_FAIL:
                session.add(
                    SiteIssue(
                        workspace_id=crawl.workspace_id,
                        project_id=crawl.project_id,
                        crawl_id=crawl.id,
                        site_url_id=site_url_by_analysis[analysis_id],
                        analysis_id=analysis_id,
                        evaluation_id=inserted_id,
                        source_artifact_id=artifact_id,
                        rule_id=ev.rule_id,
                        dimension=ev.dimension,
                        category=ev.category,
                        severity=ev.severity,
                        finding_class=ev.finding_class,
                        evidence=ev.evidence,
                        description=ev.description,
                        remediation=ev.remediation,
                        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                        rule_version=ev.rule_version,
                    )
                )

        # SessionLocal disables autoflush; the snapshot query immediately after
        # this pass must see the newly added issues.
        await session.flush()

    async def _persist_snapshot(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        """Compute + persist the crawl aggregate snapshot (unique per crawl).

        Delegates to the canonical ``persist_crawl_snapshot`` domain helper so
        the worker and ``service.cancel_crawl`` share ONE aggregation algorithm
        (no duplicate scoring/rollup logic). ``persist_empty=True`` because a
        clean terminalization (including an empty analysis plan) must always
        write a canonical snapshot — an empty/null-score one when nothing was
        aggregated — unlike a cancel, which leaves ``score_summary`` null.
        """
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)
