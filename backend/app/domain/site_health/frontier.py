"""Conflict-safe progressive Site Health frontier admission."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from itertools import batched

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import classify_url_admission
from app.core.config.site_health_contracts import (
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    FRONTIER_ADMITTED,
    FRONTIER_PENDING,
    SELECTION_SOURCE_BOOTSTRAP,
    SELECTION_SOURCE_FREE_SAMPLE,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.domain.site_health.frontier_support import (
    _add_free_sample,
    _AdmissionProgress,
    _automatic_remaining,
    _candidate_allowed,
    _enqueue_task,
    _frontier_full,
    _frontier_limit,
    _ordered_unique_candidates,
    _requested_budget_exhausted,
    _requested_discovery_target,
    _upsert_site_url,
    _utcnow,
)
from app.domain.site_health.schemas import AdmissionResult, FrontierCandidate
from app.models.site_health.crawl import SiteCrawl, SiteDiscoveryFrontier
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime


async def _record_sample_admission(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidate: FrontierCandidate,
    site_url_id: uuid.UUID,
    progress: _AdmissionProgress,
    phase_run_id: uuid.UUID | None,
) -> None:
    # A non-analyzable candidate (a document) is still inventoried and observed
    # so it stays in coverage, but the HTML analyzer never receives it: the
    # extractors differ, and handing a PDF to the HTML parser would produce
    # empty facts that read as a thin, failing page rather than a document.
    analyze = (
        candidate.analyzable
        and progress.remaining is not None
        and progress.remaining > 0
    )
    automatic_limit = int(
        (crawl.configuration or {}).get(AUTOMATIC_MONITOR_LIMIT_KEY) or 0
    )
    selection_source = (
        SELECTION_SOURCE_BOOTSTRAP
        if automatic_limit > 0
        else SELECTION_SOURCE_FREE_SAMPLE
    )
    newly_activated, newly_observed = await _add_free_sample(
        session,
        crawl=crawl,
        site_url_id=site_url_id,
        url=candidate.url,
        url_hash_value=candidate.url_hash,
        depth=candidate.depth,
        source_kind=candidate.source_kind,
        analyze=analyze,
        selection_source=selection_source,
        phase_run_id=phase_run_id,
        value_kind=candidate.value_kind,
        value_priority=candidate.value_priority,
        rewrite_reason=candidate.rewrite_reason,
        rewrite_version=candidate.rewrite_version,
    )
    if newly_activated and progress.remaining is not None:
        progress.remaining -= 1
    if newly_observed:
        progress.admitted += 1


async def _record_admission(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidate: FrontierCandidate,
    position: int,
    enqueue_children: bool,
    progress: _AdmissionProgress,
    phase_run_id: uuid.UUID | None,
) -> None:
    site_url_id, _created = await _upsert_site_url(
        session, crawl=crawl, candidate=candidate
    )
    progress.site_url_ids[candidate.url_hash] = str(site_url_id)
    progress.observed += 1

    if crawl.sample_mode:
        await _record_sample_admission(
            session,
            crawl=crawl,
            candidate=candidate,
            site_url_id=site_url_id,
            progress=progress,
            phase_run_id=phase_run_id,
        )
        return
    if (
        candidate.analyzable
        and progress.remaining is not None
        and progress.remaining > 0
    ):
        newly_activated, _newly_observed = await _add_free_sample(
            session,
            crawl=crawl,
            site_url_id=site_url_id,
            url=candidate.url,
            url_hash_value=candidate.url_hash,
            depth=candidate.depth,
            source_kind=candidate.source_kind,
            selection_source=SELECTION_SOURCE_BOOTSTRAP,
            phase_run_id=phase_run_id,
            value_kind=candidate.value_kind,
            value_priority=candidate.value_priority,
            rewrite_reason=candidate.rewrite_reason,
            rewrite_version=candidate.rewrite_version,
            # This URL is about to be queued for discovery just below, so its
            # analyze task is handed over by that fetch instead of racing it.
            analyze_after_discovery=enqueue_children,
        )
        if newly_activated:
            progress.remaining -= 1
    if enqueue_children:
        task_id = await _enqueue_task(
            session,
            crawl=crawl,
            site_url_id=site_url_id,
            url=candidate.url,
            url_hash_value=candidate.url_hash,
            task_kind=TASK_KIND_DISCOVER,
            depth=candidate.depth,
            randomized_position=position,
            parent_site_url_id=None,
            priority=candidate.value_priority,
            phase_run_id=phase_run_id,
        )
        if task_id is not None:
            progress.admitted += 1
        return
    progress.admitted += 1


async def _store_frontier_candidates(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidates: list[FrontierCandidate],
    configuration: dict,
) -> None:
    """Persist admissible candidates before applying the current batch budget."""
    eligible = _eligible_frontier_candidates(crawl, candidates, configuration)
    if not eligible:
        return
    existing_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SiteDiscoveryFrontier)
            .where(SiteDiscoveryFrontier.crawl_id == crawl.id)
        )
        or 0
    )
    remaining_capacity = max(_frontier_limit(crawl, configuration) - existing_count, 0)
    if remaining_capacity == 0:
        return
    # asyncpg rejects statements with more than 32,767 bind parameters. A
    # sitemap can legitimately contribute the configured 5,000 URLs at once;
    # one ten-column multi-row INSERT for that set already exceeds the driver
    # limit. Keep both the duplicate lookup and INSERT bounded by the existing
    # admission batch policy so large sitemap inventories remain progressive.
    batch_size = max(int(site_health_settings.admission_batch_size), 1)
    existing_hashes = await _existing_frontier_hashes(
        session, crawl_id=crawl.id, candidates=eligible, batch_size=batch_size
    )
    admitted_candidates = [
        candidate for candidate in eligible if candidate.url_hash not in existing_hashes
    ][:remaining_capacity]
    if not admitted_candidates:
        return
    await _insert_frontier_candidates(
        session, crawl=crawl, candidates=admitted_candidates, batch_size=batch_size
    )


def _eligible_frontier_candidates(
    crawl: SiteCrawl, candidates: list[FrontierCandidate], configuration: dict
) -> list[FrontierCandidate]:
    return [
        candidate
        for candidate in _ordered_unique_candidates(candidates)
        if _candidate_allowed(crawl, candidate, configuration)
    ]


async def _existing_frontier_hashes(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    candidates: list[FrontierCandidate],
    batch_size: int,
) -> set[str]:
    hashes: set[str] = set()
    for candidate_batch in batched(candidates, batch_size):
        existing = await session.scalars(
            select(SiteDiscoveryFrontier.url_hash).where(
                SiteDiscoveryFrontier.crawl_id == crawl_id,
                SiteDiscoveryFrontier.url_hash.in_(
                    [candidate.url_hash for candidate in candidate_batch]
                ),
            )
        )
        hashes.update(existing.all())
    return hashes


async def _insert_frontier_candidates(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidates: list[FrontierCandidate],
    batch_size: int,
) -> None:
    for candidate_batch in batched(candidates, batch_size):
        values = [
            {
                "workspace_id": crawl.workspace_id,
                "crawl_id": crawl.id,
                "normalized_url": candidate.url,
                "url_hash": candidate.url_hash,
                "depth": candidate.depth,
                "source_kind": candidate.source_kind,
                "value_kind": candidate.value_kind,
                "value_priority": candidate.value_priority,
                "parent_position": candidate.parent_position,
                "link_ordinal": candidate.link_ordinal,
                "rewrite_reason": candidate.rewrite_reason,
                "rewrite_version": candidate.rewrite_version,
                "status": FRONTIER_PENDING,
            }
            for candidate in candidate_batch
        ]
        await session.execute(
            pg_insert(SiteDiscoveryFrontier)
            .values(values)
            .on_conflict_do_nothing(index_elements=["crawl_id", "url_hash"])
        )


async def _pending_frontier(
    session: AsyncSession, *, crawl: SiteCrawl
) -> list[tuple[SiteDiscoveryFrontier, FrontierCandidate]]:
    remaining = max(_requested_discovery_target(crawl) - crawl.admitted_url_count, 0)
    if remaining == 0:
        return []
    rows = list(
        (
            await session.scalars(
                select(SiteDiscoveryFrontier)
                .where(
                    SiteDiscoveryFrontier.crawl_id == crawl.id,
                    SiteDiscoveryFrontier.status == FRONTIER_PENDING,
                )
                .order_by(
                    SiteDiscoveryFrontier.value_priority.desc(),
                    SiteDiscoveryFrontier.parent_position.asc(),
                    SiteDiscoveryFrontier.link_ordinal.asc(),
                    SiteDiscoveryFrontier.url_hash.asc(),
                )
                .limit(min(remaining, site_health_settings.admission_batch_size))
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    return [(row, _candidate_from_frontier_row(row)) for row in rows]


def _candidate_from_frontier_row(row: SiteDiscoveryFrontier) -> FrontierCandidate:
    """Rebuild a candidate from its persisted frontier row.

    The frontier persists the ordering key and the admitted ``value_kind``, but
    not the corpus disposition. Rebuilding with the dataclass defaults would
    silently relabel every deferred candidate as an analyzable HTML page — so a
    PDF admitted into the frontier came back as a page for the HTML analyzer.

    Disposition is a pure function of the URL path (the extension), so it is
    re-derived exactly here rather than widening the frontier table.
    ``value_kind`` is read back from the row because THAT verdict was made
    under the crawl's scope, which a bare re-classification here would not have.
    """
    admission = classify_url_admission(row.normalized_url)
    return FrontierCandidate(
        url=row.normalized_url,
        url_hash=row.url_hash,
        depth=row.depth,
        source_kind=row.source_kind,
        value_priority=row.value_priority,
        parent_position=row.parent_position,
        link_ordinal=row.link_ordinal,
        rewrite_reason=row.rewrite_reason,
        rewrite_version=row.rewrite_version,
        value_kind=row.value_kind,
        disposition=admission.disposition,
        disposition_reason=admission.disposition_reason,
        disposition_version=admission.disposition_version,
        item_kind=admission.item_kind,
    )


async def _admission_batch(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidates: list[FrontierCandidate],
    configuration: dict,
) -> Sequence[tuple[SiteDiscoveryFrontier | None, FrontierCandidate]]:
    if crawl.sample_mode:
        eligible = (
            candidate
            for candidate in _ordered_unique_candidates(candidates)
            if _candidate_allowed(crawl, candidate, configuration)
        )
        return [
            (None, candidate)
            for candidate in list(eligible)[: site_health_settings.admission_batch_size]
        ]
    await _store_frontier_candidates(
        session, crawl=crawl, candidates=candidates, configuration=configuration
    )
    return await _pending_frontier(session, crawl=crawl)


def _mark_frontier_admitted(frontier: SiteDiscoveryFrontier | None) -> None:
    if frontier is not None:
        frontier.status = FRONTIER_ADMITTED
        frontier.admitted_at = _utcnow()


async def admit_candidates(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidates: list[FrontierCandidate],
    enqueue_children: bool = True,
    phase_run_id: uuid.UUID | None = None,
    runtime: WorkspaceSiteHealthRuntime | None = None,
) -> AdmissionResult:
    """Admit a deterministically-ordered batch of candidates.

    Full inventory: insert every new ``SiteUrl`` (conflict-safe), bump the
    crawl's admitted counter, and (when ``enqueue_children``) queue a child
    discover task per NEW URL under the depth/frontier ceilings.

    Sample mode: lock the workspace runtime row ``FOR UPDATE``, compute the
    remaining workspace-wide allowance out of the frozen sample limit, admit
    only up to that allowance, add each admitted URL to the ``free_sample``
    monitored set with an auto-queued analyze task, and stop
    (``sample_capped=True``) the moment the allowance is exhausted — never
    computing a hidden total.

    Caller owns the commit (progressive batches commit per admission call).

    ``runtime`` lets a caller that has ALREADY locked the workspace runtime row
    hand it in. The canonical lock hierarchy is
    ``workspace entitlement -> monitored membership -> crawl -> task``, and a
    caller inside a crawl-locked transaction that let this function take the
    entitlement lock for itself inverted the first and third rungs — a discover
    holding the crawl and waiting on the runtime, against an analyze holding
    the runtime and waiting on the crawl. That ABBA pair produced 27 deadlocks
    across two ordinary crawls, each one rolling a whole task back into a
    two-second retry.
    """
    configuration = dict(crawl.configuration or {})
    progress = _AdmissionProgress(
        remaining=await _automatic_remaining(session, crawl, runtime=runtime)
    )
    for position, (frontier, candidate) in enumerate(
        await _admission_batch(
            session,
            crawl=crawl,
            candidates=candidates,
            configuration=configuration,
        )
    ):
        if _requested_budget_exhausted(crawl, progress.admitted):
            break
        if _frontier_full(crawl, progress.admitted):
            break
        await _record_admission(
            session,
            crawl=crawl,
            candidate=candidate,
            position=position,
            enqueue_children=enqueue_children,
            progress=progress,
            phase_run_id=phase_run_id,
        )
        _mark_frontier_admitted(frontier)

    # Live delta so the frontier ceiling above and the progress event advance
    # within a task. ``CrawlLifecycle.reconcile`` then re-derives this counter
    # from the crawl's ``SiteUrlObservation`` rows — the exact, deduplicated
    # "URLs this crawl admitted". Feeding it the UNIQUE count (not every
    # observation) is what keeps the live value and the re-derived one in
    # agreement, so the ceiling stops the crawl at the real frontier size
    # instead of counting a twice-seen URL twice.
    crawl.admitted_url_count += progress.admitted
    sample_capped = bool(
        crawl.sample_mode and progress.remaining is not None and progress.remaining <= 0
    )
    return AdmissionResult(
        admitted=progress.admitted,
        sample_capped=sample_capped,
        site_url_ids=progress.site_url_ids,
        observed=progress.observed,
    )


async def drain_discovery_frontier(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    phase_run_id: uuid.UUID,
) -> AdmissionResult:
    """Activate persisted frontier rows for a resumed discovery batch."""
    return await admit_candidates(
        session,
        crawl=crawl,
        candidates=[],
        enqueue_children=True,
        phase_run_id=phase_run_id,
    )
