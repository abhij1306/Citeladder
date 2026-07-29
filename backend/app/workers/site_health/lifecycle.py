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
    ANALYZER_VERSION,
    APPLICABILITY_CRAWL_FINALIZE,
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_RUNNING,
    EVENT_CRAWL_COMPLETED,
    EXTRACTOR_VERSION,
    LINK_KIND_ANCHOR,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
    SITE_HEALTH_RULES_BY_ID,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
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
    """
    try:
        return canonical_identity(url)[0]
    except UrlPolicyError:
        return ""


def crawl_root_identity(crawl: SiteCrawl) -> tuple[str, str]:
    """``(canonical, url_hash)`` of the crawl root, or ``("", "")``."""
    try:
        return canonical_identity(crawl.root_url)
    except UrlPolicyError:
        return "", ""


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

            # Discovery sub-state: terminalize progressively once discover
            # tasks drain, independent of analyze/link_check work.
            fully_failed = crawl.discovered_url_count == 0
            discovery_partial = (
                crawl.discovered_url_count > 0 and crawl.failed_url_count > 0
            )
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

            if crawl.status == CRAWL_STATUS_RUNNING:
                crawl.completed_at = _utcnow()
                if fully_failed:
                    apply_crawl_status(crawl, CRAWL_STATUS_FAILED)
                elif discovery_partial or (
                    analyze_applicable > 0 and analyze_succeeded < analyze_applicable
                ):
                    apply_crawl_status(crawl, CRAWL_STATUS_PARTIALLY_COMPLETED)
                else:
                    apply_crawl_status(crawl, CRAWL_STATUS_COMPLETED)
                record_crawl_event(
                    session,
                    crawl_id=crawl_id,
                    event_type=EVENT_CRAWL_COMPLETED,
                    message="crawl completed",
                    payload={"status": crawl.status},
                    count_disclosure=_count_disclosure(crawl),
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
        """Aggregate per-kind terminal/non-terminal task counts for a crawl."""

        async def _non_terminal(kind: str) -> int:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(SiteCrawlTask)
                    .where(SiteCrawlTask.crawl_id == crawl_id)
                    .where(SiteCrawlTask.task_kind == kind)
                    .where(SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
                )
                or 0
            )

        analyze_total = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
            )
            or 0
        )
        analyze_succeeded = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
                .where(SiteCrawlTask.status == TASK_STATUS_SUCCEEDED)
            )
            or 0
        )
        analyze_cancelled = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
                .where(SiteCrawlTask.status == TASK_STATUS_CANCELLED)
            )
            or 0
        )
        return {
            "discover_non_terminal": await _non_terminal(TASK_KIND_DISCOVER),
            "analyze_non_terminal": await _non_terminal(TASK_KIND_ANALYZE),
            "link_non_terminal": await _non_terminal(TASK_KIND_LINK_CHECK),
            "analyze_total": analyze_total,
            "analyze_succeeded": analyze_succeeded,
            "analyze_cancelled": analyze_cancelled,
        }

    # --- v2 P2: crawl_finalize evaluation pass -----------------------------

    async def _run_crawl_finalize_pass(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        """Evaluate the crawl_finalize-scoped rules from cross-page evidence.

        Runs under the crawl ``FOR UPDATE`` lock that already guarantees
        exactly-once terminalization (spec §5.3). Writes NEW
        ``SiteRuleEvaluation`` rows — one per (analysis, crawl_finalize rule),
        ``ON CONFLICT DO NOTHING`` on the unique slot — plus one ``SiteIssue``
        per fail. Never mutates existing rows (invariant 3); this writer is
        the sole owner of crawl_finalize-scope rows (the analyze writer
        filtered them out, so the unique slots are free). Anchors:

          - ``technical.broken_internal_link`` / ``technical.hreflang_conflict``:
            every latest-completed analysis in this crawl (their evidence is
            per-page: link probes / hreflang alternates).
          - ``technical.sitemap_orphan``: the crawl ROOT's latest completed
            analysis only (a site-wide condition, like the site_root rules);
            simply absent when the root has no completed analysis.

        All URL normalization happens here via ``canonical_identity`` — the
        pure evaluators in ``analysis/site_health/finalize.py`` only receive
        pre-normalized, bounded inputs.
        """
        # Latest completed analysis per URL in this crawl (the same ranking
        # rule the snapshot aggregator uses, minus its active-membership join:
        # finalize evidence attaches to the URL's own latest analysis).
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
        rows = (
            await session.execute(
                select(ranked.c.id, ranked.c.site_url_id, ranked.c.artifact_id).where(
                    ranked.c.latest_rank == 1
                )
            )
        ).all()
        if not rows:
            return
        analysis_ids = [row.id for row in rows]
        artifact_by_analysis = {row.id: row.artifact_id for row in rows}
        site_url_by_analysis = {row.id: row.site_url_id for row in rows}

        evaluations: list[tuple[uuid.UUID, RuleEvaluation]] = []

        # --- broken_internal_link: per analysis, from its link probes. -----
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
        for analysis_id in analysis_ids:
            evaluations.append(
                (
                    analysis_id,
                    evaluate_broken_internal_link(
                        checked_count=checked.get(analysis_id, 0),
                        broken_urls=broken.get(analysis_id, []),
                    ),
                )
            )

        # --- hreflang_conflict: per analysis, from artifact facts. ----------
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
        analysis_by_artifact = {row.artifact_id: row.id for row in rows}
        # canonical identity of each analyzed page's final URL -> alternates.
        alternates_by_page: dict[str, list[dict]] = {}
        canonical_by_artifact: dict[uuid.UUID, str] = {}
        for artifact_id, final_url, facts in artifacts:
            canonical = _canonical_or_empty(str(final_url or ""))
            if not canonical:
                continue
            canonical_by_artifact[artifact_id] = canonical
            alternates_by_page.setdefault(
                canonical,
                list((facts or {}).get("hreflang_alternates") or []),
            )
        for artifact_id, _final_url, facts in artifacts:
            analysis_id = analysis_by_artifact[artifact_id]
            alternates = list((facts or {}).get("hreflang_alternates") or [])
            source_canonical = canonical_by_artifact.get(artifact_id)
            if not alternates or not source_canonical:
                evaluations.append(
                    (
                        analysis_id,
                        evaluate_hreflang_conflict(
                            alternate_count=0,
                            checked_count=0,
                            unchecked_count=0,
                            missing_return_tags=[],
                        ),
                    )
                )
                continue
            checked_count = 0
            unchecked_count = 0
            missing: list[str] = []
            for alternate in alternates:
                target_url = str(alternate.get("url") or "")
                target_canonical = _canonical_or_empty(target_url)
                if not target_canonical:
                    unchecked_count += 1
                    continue
                # A self-referencing alternate is always fine.
                if target_canonical == source_canonical:
                    continue
                target_alternates = alternates_by_page.get(target_canonical)
                if target_alternates is None:
                    # The target was not analyzed in this crawl: it cannot be
                    # verified, so it neither passes nor fails (spec §5.3).
                    unchecked_count += 1
                    continue
                checked_count += 1
                return_tag_found = any(
                    _canonical_or_empty(str(back.get("url") or "")) == source_canonical
                    for back in target_alternates
                )
                if not return_tag_found and target_url not in missing:
                    missing.append(target_url)
            evaluations.append(
                (
                    analysis_id,
                    evaluate_hreflang_conflict(
                        alternate_count=len(alternates),
                        checked_count=checked_count,
                        unchecked_count=unchecked_count,
                        missing_return_tags=missing,
                    ),
                )
            )

        # --- sitemap_orphan: crawl-wide, anchored on the root analysis. -----
        root_canonical, root_hash = crawl_root_identity(crawl)
        if root_hash:
            site_url_rows = (
                await session.execute(
                    select(SiteUrl.id, SiteUrl.url_hash).where(
                        SiteUrl.id.in_(site_url_by_analysis.values())
                    )
                )
            ).all()
            # Built by index rather than dict(rows): a SQLAlchemy Row is not a
            # 2-tuple to the type checker, so dict() infers dict[Never, Never].
            hash_by_site_url: dict[uuid.UUID, str] = {
                row[0]: row[1] for row in site_url_rows
            }
            root_analysis_id = next(
                (
                    row.id
                    for row in rows
                    if hash_by_site_url.get(row.site_url_id) == root_hash
                ),
                None,
            )
            if root_analysis_id is not None:
                sitemap_rows = (
                    await session.execute(
                        select(
                            SiteUrlObservation.site_url_id,
                            SiteUrlObservation.observed_url,
                        ).where(
                            SiteUrlObservation.crawl_id == crawl.id,
                            SiteUrlObservation.source_kind
                            == OBSERVATION_SOURCE_SITEMAP,
                        )
                    )
                ).all()
                # Internal anchor targets observed anywhere in this crawl: a
                # sitemap URL that no analyzed page links to is an orphan.
                anchor_rows = (
                    await session.execute(
                        select(SiteLinkReference.target_url).where(
                            SiteLinkReference.source_analysis_id.in_(analysis_ids),
                            SiteLinkReference.is_internal.is_(True),
                            SiteLinkReference.kind == LINK_KIND_ANCHOR,
                        )
                    )
                ).all()
                linked_targets: set[str] = set()
                for (target_url,) in anchor_rows:
                    target_canonical = _canonical_or_empty(str(target_url))
                    if target_canonical:
                        linked_targets.add(target_canonical)
                orphans: list[str] = []
                for _site_url_id, observed_url in sitemap_rows:
                    observed = str(observed_url or "")
                    observed_canonical = _canonical_or_empty(observed)
                    if not observed_canonical:
                        continue
                    # The crawl root is definitionally reachable (it seeds the
                    # crawl), never an orphan.
                    if observed_canonical == root_canonical:
                        continue
                    if observed_canonical not in linked_targets:
                        if observed not in orphans:
                            orphans.append(observed)
                evaluations.append(
                    (
                        root_analysis_id,
                        evaluate_sitemap_orphan(
                            sitemap_url_count=len(sitemap_rows),
                            orphan_urls=orphans,
                        ),
                    )
                )

        # Persist: new rows only, conflict-safe on the unique
        # (analysis_id, rule_id) slot; one issue per fail.
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
