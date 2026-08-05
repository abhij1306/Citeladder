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
from app.core.config.site_health import (
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
    PHASE_ANALYSIS,
    PHASE_DISCOVERY,
    PHASE_RUN_COMPLETED,
    PHASE_RUN_RUNNING,
    RULE_OUTCOME_FAIL,
    SITE_HEALTH_RULES_BY_ID,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.opportunities.service import enqueue_opportunity_refresh
from app.domain.site_health.failure import load_root_failure_summary
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.selection import crawl_is_active
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
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


def _is_crawl_finalize_rule(rule_id: str) -> bool:
    """Whether a catalog rule is scoped ``crawl_finalize`` (finalize-owned)."""
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    return rule is not None and rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE


def _canonical_or_empty(url: str) -> str:
    """The canonical form of ``url``, or ``""`` when it fails normalization.

    The finalize pass canonicalizes persisted URLs (link targets, hreflang
    alternates, sitemap observations) that may no longer parse — an
    unnormalizable URL simply contributes nothing.

    Catches ``ValueError`` (the ``UrlPolicyError`` base) rather than the policy
    error alone: a malformed persisted URL can fail inside ``urlsplit`` itself
    (an unclosed IPv6 bracket, a junk port) before the policy checks run, and
    ``_run_crawl_finalize_pass`` must never die on one bad stored row.
    """
    try:
        return canonical_identity(url)[0]
    except ValueError:
        return ""


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
        target_canonical = _canonical_or_empty(target_url)
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
            _canonical_or_empty(str(back.get("url") or "")) == source_canonical
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
        canonical = _canonical_or_empty(str(final_url or ""))
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
          - terminalizes the OVERALL crawl ONLY when EVERY non-terminal task of
            ALL kinds is drained, classifying completed / partially_completed /
            failed and (on analysis terminalization) persisting the aggregate
            ``SiteHealthSnapshot`` + a ``crawl.completed`` event.

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
            discover_remaining = counts["discover_non_terminal"]
            analyze_remaining = counts["analyze_non_terminal"]
            link_remaining = counts["link_non_terminal"]
            analyze_total = counts["analyze_total"]
            analyze_succeeded = counts["analyze_succeeded"]
            analyze_cancelled = counts["analyze_cancelled"]
            analyze_applicable = analyze_total - analyze_cancelled
            discover_failed = counts["discover_failed"]

            # ``failed_url_count`` is DERIVED here, not accumulated by the
            # phases. It used to be a ``+= 1`` in the discover phase only, so a
            # terminally failed ANALYZE (robots-denied, retries exhausted) never
            # reached it: a crawl with 3 blocked pages reported 0 failed, and
            # the dashboard's "Queued = selected - completed - failed - running"
            # billed all 3 as still pending, forever. Recomputing from the task
            # table under the crawl's FOR UPDATE lock is both complete (every
            # kind, every route into a terminal status, including a sweeper
            # reclaim that never runs a phase finalize) and idempotent, so it
            # also self-heals a counter that has already drifted.
            crawl.failed_url_count = discover_failed + counts["analyze_failed"]
            # Same treatment for the analyzed counter: the analyze phase still
            # increments it live so the progress EVENT carries a fresh number,
            # but the succeeded-task count is the authority and repairs any
            # increment lost to a concurrent writer.
            crawl.analyzed_url_count = analyze_succeeded
            # ...and for admitted URLs, whose authority is the crawl's own
            # observation rows (unique per ``(crawl_id, site_url_id)``), so a
            # URL re-observed across discovery batches is counted once.
            crawl.admitted_url_count = int(
                await session.scalar(
                    select(func.count())
                    .select_from(SiteUrlObservation)
                    .where(SiteUrlObservation.crawl_id == crawl_id)
                )
                or 0
            )

            advanced_controls = bool(
                (crawl.configuration or {}).get("advanced_controls_enabled")
            )
            if advanced_controls:
                phase_runs = list(
                    (
                        await session.scalars(
                            select(SiteCrawlPhaseRun)
                            .where(
                                SiteCrawlPhaseRun.crawl_id == crawl_id,
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
                                    SiteUrlObservation.crawl_id == crawl_id,
                                    SiteUrlObservation.phase_run_id == phase_run.id,
                                )
                            )
                            or 0
                        )
                        drained = discover_remaining == 0
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
                                SiteCrawlTask.status.not_in(
                                    list(TASK_TERMINAL_STATUSES)
                                ),
                            )
                        )
                        drained = int(remaining_phase_tasks or 0) == 0
                    if drained:
                        phase_run.status = PHASE_RUN_COMPLETED
                        phase_run.completed_at = _utcnow()
                        if (
                            phase_run.phase == PHASE_DISCOVERY
                            and crawl.discovery_status == DISCOVERY_STATUS_RUNNING
                        ):
                            apply_discovery_status(crawl, DISCOVERY_STATUS_STOPPED)
                        elif (
                            phase_run.phase == PHASE_ANALYSIS
                            and crawl.analysis_status == ANALYSIS_STATUS_RUNNING
                        ):
                            apply_analysis_status(crawl, ANALYSIS_STATUS_STOPPED)

                if (
                    discover_remaining == 0
                    and analyze_remaining == 0
                    and link_remaining == 0
                ):
                    if crawl.status == CRAWL_STATUS_RUNNING:
                        apply_crawl_status(crawl, CRAWL_STATUS_PAUSED)
                    await session.commit()
                    return

            # Discovery sub-state: terminalize progressively once discover
            # tasks drain, independent of analyze/link_check work.
            fully_failed = crawl.discovered_url_count == 0
            # Scoped to DISCOVER failures on purpose: this decides whether
            # *discovery* was partial. Reading the combined counter would flip
            # it on any analyze failure, which is a different condition (and is
            # already handled by the analyze clause in the classification).
            discovery_partial = crawl.discovered_url_count > 0 and discover_failed > 0
            if discover_remaining == 0:
                if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
                    if fully_failed:
                        apply_discovery_status(crawl, DISCOVERY_STATUS_FAILED)
                    else:
                        apply_discovery_status(crawl, DISCOVERY_STATUS_COMPLETED)
                crawl.inventory_complete = not fully_failed

            # Analysis lifecycle: move pending -> running once any analyze task
            # exists (work has been admitted), so a later terminal transition
            # is legal.
            if analyze_total > 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
                apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)

            all_drained = (
                discover_remaining == 0
                and analyze_remaining == 0
                and link_remaining == 0
            )
            if not all_drained:
                await session.commit()
                return

            # Every task of every kind is terminal: terminalize analysis + the
            # overall crawl exactly once.
            analysis_terminalized = False
            if analyze_total == 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
                # An empty analysis plan is a successful, terminal lifecycle,
                # not a crawl left permanently "pending". Traverse the legal
                # state machine and persist the corresponding empty snapshot.
                apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)
            if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
                if analyze_total > 0 and analyze_applicable == 0:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_CANCELLED)
                elif fully_failed:
                    # SH-3: an empty analysis plan is only COMPLETED when the
                    # plan was legitimately empty (e.g. Starter with no
                    # monitored selection — discovery DID admit URLs). When
                    # discovery fully failed, ``0 == 0`` applicable would
                    # report analysis "completed" for a crawl that never
                    # fetched a single page; the analysis failed with it.
                    apply_analysis_status(crawl, ANALYSIS_STATUS_FAILED)
                elif analyze_succeeded == analyze_applicable:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_COMPLETED)
                elif analyze_succeeded > 0:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_PARTIALLY_COMPLETED)
                else:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_FAILED)
                analysis_terminalized = True

            if analysis_terminalized:
                # v2 P2 (spec §5.3): the crawl_finalize-scoped rules run as a
                # second evaluation pass here — after analysis terminalization
                # (all link_check evidence is terminal) and BEFORE the snapshot
                # so their issues land in the severity/category rollups.
                await self._run_crawl_finalize_pass(session, crawl=crawl)
                await self._persist_snapshot(session, crawl=crawl)

            # Every task is drained, so this crawl is finished whatever active
            # status it is parked in. Terminalizing only from RUNNING stranded
            # any crawl whose last task drained while it was still
            # draft/validating/queued (a crawl whose work all failed or was
            # swept before the worker ever flipped it to RUNNING): it stayed
            # ACTIVE forever, so the UI kept offering Cancel on a run that had
            # long since stopped, and the Opportunities refresh was never queued.
            # The transition table has no queued -> completed edge, so
            # walk the crawl through its legal intermediate states first.
            if crawl_is_active(crawl) and crawl.status != CRAWL_STATUS_RUNNING:
                for step in _RUNNING_PATH.get(crawl.status, ()):
                    apply_crawl_status(crawl, step)

            if crawl.status == CRAWL_STATUS_RUNNING:
                crawl.completed_at = _utcnow()
                failure_summary: dict | None = None
                if fully_failed:
                    apply_crawl_status(crawl, CRAWL_STATUS_FAILED)
                    # SH-2/SH-5 (B1): the failure summary is the single
                    # humanized source of truth — a stable code + sentence +
                    # status/attempts projected from the root task's terminal
                    # fetch attempts. Its message lands on the crawl row; its
                    # full shape rides the ``crawl.failed`` event payload.
                    failure_summary = await load_root_failure_summary(
                        session, crawl=crawl
                    )
                    if failure_summary is not None and not crawl.error_message:
                        crawl.error_message = failure_summary["message"]
                elif discovery_partial or (
                    analyze_applicable > 0 and analyze_succeeded < analyze_applicable
                ):
                    apply_crawl_status(crawl, CRAWL_STATUS_PARTIALLY_COMPLETED)
                else:
                    apply_crawl_status(crawl, CRAWL_STATUS_COMPLETED)
                if crawl.status == CRAWL_STATUS_FAILED:
                    # SH-2 (B1): a failed run is NOT a "completed" event — SSE
                    # and replay consumers get the failure summary instead.
                    record_crawl_event(
                        session,
                        crawl_id=crawl_id,
                        event_type=EVENT_CRAWL_FAILED,
                        message="crawl failed",
                        payload={"status": crawl.status, "failure": failure_summary},
                        count_disclosure=_count_disclosure(crawl),
                    )
                else:
                    record_crawl_event(
                        session,
                        crawl_id=crawl_id,
                        event_type=EVENT_CRAWL_COMPLETED,
                        message="crawl completed",
                        payload={"status": crawl.status},
                        count_disclosure=_count_disclosure(crawl),
                    )
                    await enqueue_opportunity_refresh(
                        session,
                        workspace_id=crawl.workspace_id,
                        project_id=crawl.project_id,
                        trigger_kind="site_crawl",
                        trigger_id=crawl.id,
                    )
            await session.commit()

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
            if (canonical := _canonical_or_empty(str(target_url)))
        }
        orphans: list[str] = []
        for _site_url_id, observed_url in sitemap_rows:
            observed = str(observed_url or "")
            observed_canonical = _canonical_or_empty(observed)
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
                        evidence=ev.evidence,
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
