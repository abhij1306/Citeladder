# Progressive URL discovery: parsing, conflict-safe admission, Free stop-at-10.
#
# The heart of Task 3's inventory pipeline. Three concerns, all deterministic
# and bounded:
#
#   1. ``extract_discovery_links`` — an incremental ``lxml`` parse of a fetched
#      HTML body in DISCOVERY mode only: the page ``<title>`` plus canonical,
#      in-scope, narrowed, de-duplicated anchor links in document order. Bounded
#      by ``max_links_per_page``. (Full page-fact extraction is Task 5.)
#
#   2. ``admit_candidates`` — conflict-safe frontier admission. New ``SiteUrl``
#      identities are inserted with PostgreSQL ``INSERT ... ON CONFLICT DO
#      NOTHING`` on the unique ``(project_id, url_hash)`` so two concurrent
#      workers can never create duplicate inventory rows. Starter admits every
#      in-scope URL up to the frontier ceiling and enqueues child discover
#      tasks. Rows are emitted progressively (committed per batch) so the
#      inventory is queryable while discovery runs.
#
#   3. Free workspace-wide stop-at-10 — for a sample crawl, admission locks the
#      workspace runtime row ``FOR UPDATE`` and counts active
#      ``free_sample`` monitored rows ACROSS THE WHOLE WORKSPACE. Once the
#      10-URL allowance is filled, admission and all further discovery stop
#      transactionally; each admitted sample URL is added to the system-managed
#      monitored set (``selection_source=free_sample``) and gets an ``analyze``
#      task queued automatically. No total/frontier/overflow count is computed
#      or persisted — the pipeline simply terminalizes at the cap.
from __future__ import annotations

import codecs
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import batched

from lxml import etree
from lxml import html as lxml_html
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    classify_url_admission,
    split_host_port,
)
from app.core.config.site_health import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    CRAWL_ACTIVE_STATUSES,
    DISCOVERY_STATUS_RUNNING,
    FRONTIER_ADMITTED,
    FRONTIER_PENDING,
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
    SELECTION_SOURCE_BOOTSTRAP,
    SELECTION_SOURCE_FREE_SAMPLE,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import (
    AdmissionResult,
    DiscoveredLink,
    DiscoveryOutput,
    FrontierCandidate,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SiteDiscoveryFrontier,
    SiteUrl,
    SiteUrlObservation,
    WorkspaceSiteHealthRuntime,
)


def _safe_parser_encoding(charset: str) -> str | None:
    """Return a codec-valid encoding name, or ``None`` to auto-detect.

    A response's declared charset is arbitrary attacker-influenced input. Handed
    straight to ``lxml``'s ``HTMLParser(encoding=...)`` an unknown value raises
    ``LookupError`` at parser-construction time — outside the ``try`` guarding
    the actual parse — which would crash discovery instead of degrading. Validate
    with ``codecs.lookup``; on an empty/unknown value return ``None`` so lxml
    auto-detects rather than raising.
    """
    normalized = str(charset or "").strip()
    if not normalized:
        return None
    try:
        codecs.lookup(normalized)
    except LookupError:
        return None
    return normalized.lower()


def _utcnow() -> datetime:
    return datetime.now(UTC)


def extract_discovery_links(
    body: bytes,
    *,
    base_url: str,
    root_registrable_domain: str,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    max_links: int | None = None,
    charset: str = "",
) -> tuple[str, list[DiscoveredLink]]:
    """Parse HTML into (title, in-scope canonical links) — discovery mode only.

    Deterministic + bounded: anchors are resolved against ``base_url``,
    canonicalized, scope+narrowing checked, de-duplicated by hash, and returned
    in document order up to ``max_links``. Malformed HTML never raises — lxml's
    recovering parser tolerates it and we skip un-canonicalizable hrefs.
    """
    limit = max_links or site_health_settings.max_links_per_page
    title = ""
    links: list[DiscoveredLink] = []
    if not body:
        return title, links

    # Honor the response's declared charset when present; otherwise let lxml
    # auto-detect rather than hard-coding UTF-8 (a mismatched hard-coded
    # charset can mangle a non-UTF-8 page's anchors/title). A bogus/unknown
    # charset is validated away to None (auto-detect) so parser construction
    # never raises LookupError.
    declared_charset = _safe_parser_encoding(charset)
    parser = lxml_html.HTMLParser(
        recover=True, encoding=declared_charset, no_network=True
    )
    try:
        root = lxml_html.document_fromstring(body, parser=parser)
    except (etree.ParserError, ValueError):
        return title, links
    if root is None:
        return title, links

    title_node = next(root.iter("title"), None)
    if title_node is not None:
        title_text = "".join(
            t if isinstance(t, str) else t.decode("utf-8", "replace")
            for t in title_node.itertext()
        )
        title = title_text.strip()[:1024]

    seen: set[str] = set()
    ordinal = 0
    for anchor in root.iter("a"):
        href = anchor.get("href")
        if not href:
            continue
        href = href.strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        admission = classify_url_admission(
            href,
            base_url=base_url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        )
        if not admission.accepted or not admission.canonical_url:
            continue
        canonical, h = canonical_identity(admission.canonical_url)
        if h in seen:
            continue
        seen.add(h)
        links.append(DiscoveredLink(url=canonical, url_hash=h, ordinal=ordinal))
        ordinal += 1
        if len(links) >= limit:
            break
    return title, links


def build_frontier_candidates(
    output: DiscoveryOutput,
    *,
    parent_position: int,
    depth: int,
) -> list[FrontierCandidate]:
    """Turn a discover task's links into deterministically-ordered candidates.

    The order key ``(parent_position, link_ordinal, url_hash)`` makes the
    frontier admission order reproducible under the crawl seed (invariant 9).
    """
    return [
        FrontierCandidate.from_admission(
            classify_url_admission(link.url),
            url=link.url,
            url_hash=link.url_hash,
            depth=depth + 1,
            source_kind=OBSERVATION_SOURCE_LINK,
            parent_position=parent_position,
            link_ordinal=link.ordinal,
        )
        for link in output.links
    ]


async def _active_free_sample_count(
    session: AsyncSession, workspace_id: uuid.UUID
) -> int:
    """Count active ``free_sample`` monitored rows across the workspace."""
    result = await session.scalar(
        select(func.count())
        .select_from(MonitoredSiteUrl)
        .where(MonitoredSiteUrl.workspace_id == workspace_id)
        .where(MonitoredSiteUrl.active.is_(True))
        .where(MonitoredSiteUrl.selection_source == SELECTION_SOURCE_FREE_SAMPLE)
    )
    return int(result or 0)


async def _upsert_site_url(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    candidate: FrontierCandidate,
) -> tuple[uuid.UUID, bool]:
    """Insert a ``SiteUrl`` conflict-safely; return ``(id, created)``.

    Uses ``INSERT ... ON CONFLICT (project_id, url_hash) DO NOTHING`` so two
    workers admitting the same URL never create duplicate identities; on
    conflict we read the existing row's id.

    ``created`` reports whether a NEW project-level identity was inserted. It
    deliberately does NOT drive admission or the sample allowance: those are
    per-CRAWL, and every URL of a recrawled site already has an identity, so
    gating on it counted nothing on any run after the first.
    """
    now = _utcnow()
    try:
        host, _port = split_host_port(candidate.url)
    # urlsplit port parsing raises ValueError on a malformed-but-admitted URL;
    # host is display metadata only, so degrade to "" (same catch as
    # is_in_scope). Anything else is a systemic bug and must propagate.
    except ValueError:
        host = ""
    stmt = (
        pg_insert(SiteUrl)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            normalized_url=candidate.url,
            url_hash=candidate.url_hash,
            display_url=candidate.url,
            host=host[:255],
            depth=candidate.depth,
            corpus_disposition=candidate.disposition,
            disposition_reason=candidate.disposition_reason,
            disposition_version=candidate.disposition_version,
            item_kind=candidate.item_kind,
            discovery_status=DISCOVERY_STATUS_RUNNING,
            latest_source_kind=candidate.source_kind,
            first_seen_crawl_id=crawl.id,
            last_seen_crawl_id=crawl.id,
            first_seen_at=now,
            last_seen_at=now,
        )
        .on_conflict_do_nothing(index_elements=["project_id", "url_hash"])
        .returning(SiteUrl.id)
    )
    inserted_id = await session.scalar(stmt)
    if inserted_id is not None:
        return inserted_id, True
    existing = await session.scalar(
        select(SiteUrl.id).where(
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.url_hash == candidate.url_hash,
        )
    )
    if existing is None:
        # Unreachable barring a concurrent hard-delete between the conflicting
        # insert and this read — surface loudly rather than return a bogus id.
        raise RuntimeError(f"SiteUrl row vanished for url_hash={candidate.url_hash!r}")
    return existing, False


def _task_idempotency_key(
    crawl_id: uuid.UUID, task_kind: str, url_hash_value: str, generation: int
) -> str:
    return f"{crawl_id}:{task_kind}:{url_hash_value}:{generation}"


async def _enqueue_task(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID | None,
    url: str,
    url_hash_value: str,
    task_kind: str,
    depth: int,
    generation: int = 0,
    randomized_position: int = 0,
    parent_site_url_id: uuid.UUID | None = None,
    priority: int = 0,
    phase_run_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Enqueue one queue row conflict-safely (returns id, or None if it existed).

    The unique ``(crawl_id, task_kind, url_hash, generation)`` slot plus the
    unique ``idempotency_key`` mean a re-admitted URL never double-enqueues in
    the same generation; the insert is ``ON CONFLICT DO NOTHING``.

    Serialized against terminalization by taking ``FOR NO KEY UPDATE`` on the
    crawl row FIRST. ``CrawlLifecycle.reconcile`` holds the same row ``FOR
    UPDATE`` while it counts non-terminal tasks and decides to terminalize, but
    it could only ever count what was COMMITTED when its query ran: an enqueue
    that committed after that count and before reconcile's commit produced a
    live task on an already-terminal crawl — its result discarded, its crawl
    unable to advance. The two lock modes conflict, so one waits for the other:
    reconcile either sees the new task, or this call sees the terminal status
    and declines. Concurrent enqueues do NOT block each other (``FOR NO KEY
    UPDATE`` is self-compatible), so the fast path is unaffected.

    Returns ``None`` when the crawl is no longer active — an enqueue onto a
    terminal crawl is dropped rather than stranded.
    """
    still_active = await session.scalar(
        select(SiteCrawl.id)
        .where(
            SiteCrawl.id == crawl.id,
            SiteCrawl.status.in_(list(CRAWL_ACTIVE_STATUSES)),
        )
        .with_for_update(key_share=True)
    )
    if still_active is None:
        return None

    stmt = (
        pg_insert(SiteCrawlTask)
        .values(
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            phase_run_id=phase_run_id,
            site_url_id=site_url_id,
            task_kind=task_kind,
            requested_url=url,
            url_hash=url_hash_value,
            depth=depth,
            generation=generation,
            idempotency_key=_task_idempotency_key(
                crawl.id, task_kind, url_hash_value, generation
            ),
            status=TASK_STATUS_QUEUED,
            priority=priority,
            randomized_position=randomized_position,
            parent_site_url_id=parent_site_url_id,
            max_attempts=site_health_settings.max_attempts,
        )
        .on_conflict_do_nothing(
            index_elements=[
                "crawl_id",
                "task_kind",
                "url_hash",
                "generation",
            ]
        )
        .returning(SiteCrawlTask.id)
    )
    return await session.scalar(stmt)


async def _upsert_system_membership(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID,
    now: datetime,
    selection_source: str,
) -> uuid.UUID | None:
    """Insert/reactivate the system-managed sample membership for a URL.

    Returns the row id when THIS call created or reactivated the membership
    (the caller's signal to consume one unit of the workspace sample
    allowance), or ``None`` when it was already active — the conflict guard
    below makes that case a no-op.
    """
    return await session.scalar(
        pg_insert(MonitoredSiteUrl)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            profile_id=crawl.profile_id,
            site_url_id=site_url_id,
            active=True,
            selection_source=selection_source,
            selected_at=now,
        )
        .on_conflict_do_update(
            index_elements=["project_id", "site_url_id"],
            set_={
                "active": True,
                "selection_source": selection_source,
                "selected_at": now,
                "deselected_at": None,
            },
            where=(MonitoredSiteUrl.active.is_(False)),
        )
        .returning(MonitoredSiteUrl.id)
    )


async def _add_free_sample(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID,
    url: str,
    url_hash_value: str,
    depth: int,
    source_kind: str = OBSERVATION_SOURCE_LINK,
    analyze: bool = True,
    selection_source: str = SELECTION_SOURCE_FREE_SAMPLE,
    phase_run_id: uuid.UUID | None = None,
    value_kind: str = "other",
    value_priority: int = 0,
) -> tuple[bool, bool]:
    """Admit a Free URL into the inventory; optionally monitor + analyze it.

    ``analyze`` splits the two budgets this function used to conflate. With
    ``analyze=False`` (the workspace sample allowance is spent) the URL is still
    given its identity and its per-crawl ``SiteUrlObservation`` — it appears in
    the inventory like any other discovered URL — but gets NO monitored
    membership and NO analyze task, so it costs a row rather than a fetch. That
    is what lets a Free crawl map up to the discovery cap while deep-analyzing
    only ``sample_url_limit`` pages.

    Conflict-safe on ``(project_id, site_url_id)`` so re-admission never
    duplicates the membership. Three cases on conflict:

    - No existing row: a fresh ``INSERT`` creates a new active membership.
    - An existing row that is currently INACTIVE (e.g. deactivated by a
      selection replacement, or deselected then rediscovered): it is
      reactivated in place (``active=True``, ``selected_at`` refreshed,
      ``deselected_at`` cleared) rather than silently doing nothing, so a
      recrawl can genuinely bring a previously-sampled URL back into the
      monitored set.
    - An existing row that is ALREADY active: the conflict update's ``WHERE``
      guard means nothing changes and the statement is a no-op (equivalent to
      ``DO NOTHING``), so re-observing an already-sampled URL never appears
      to "activate" it again.

    The analyze task is what deep-analyzes the Free sample automatically,
    subject to the locked workspace allowance.

    Returns ``(newly_activated, newly_observed)`` — two independent facts:

    - ``newly_activated``: this call inserted a brand-new membership row or
      reactivated an inactive one, i.e. exactly when the caller should decrement
      the remaining workspace-wide sample allowance. ``False`` when the
      membership was already active (re-observing an already-counted sample
      must not consume a second unit of the allowance).
    - ``newly_observed``: the per-CRAWL ``SiteUrlObservation`` was created by
      this call, which is the crawl's unique-admission signal (the number
      ``reconcile`` re-derives). A URL reached twice within one crawl activates
      at most once but is observed once — the two are not interchangeable.
    """
    now = _utcnow()
    activated_id = (
        await _upsert_system_membership(
            session,
            crawl=crawl,
            site_url_id=site_url_id,
            now=now,
            selection_source=selection_source,
        )
        if analyze
        else None
    )
    newly_activated = activated_id is not None
    # Record per-crawl admission provenance for the sampled URL. The pages /
    # inventory read paths scope strictly through ``SiteUrlObservation``
    # (see ``_admitted_site_url_subquery``), and a Free crawl fetches most of
    # its sample via analyze-only tasks (no per-URL discover task ever runs),
    # so without this row 9 of 10 sampled URLs would be invisible in the UI.
    # Conflict-safe on the unique ``(crawl_id, site_url_id)`` pair; the richer
    # discover-path observation (status/title/artifact) wins if it ran first,
    # and this sparse admission row is enriched later by the analyze result.
    observation_id = await session.scalar(
        pg_insert(SiteUrlObservation)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            site_url_id=site_url_id,
            source_kind=source_kind,
            phase_run_id=phase_run_id,
            value_kind=value_kind,
            value_priority=value_priority,
            depth=depth,
            observed_url=url,
            final_url=url,
        )
        .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
        .returning(SiteUrlObservation.id)
    )
    # Inventory-only admissions stop here: no analyze task, so an over-cap URL
    # costs two rows and zero network I/O.
    if analyze:
        await _enqueue_task(
            session,
            crawl=crawl,
            site_url_id=site_url_id,
            url=url,
            url_hash_value=url_hash_value,
            task_kind=TASK_KIND_ANALYZE,
            depth=depth,
            priority=1,
            phase_run_id=phase_run_id,
        )
    return newly_activated, observation_id is not None


@dataclass
class _AdmissionProgress:
    admitted: int = 0
    observed: int = 0
    remaining: int | None = None
    site_url_ids: dict[str, str] = field(default_factory=dict)


def _ordered_unique_candidates(
    candidates: list[FrontierCandidate],
) -> list[FrontierCandidate]:
    by_hash: dict[str, FrontierCandidate] = {}
    for candidate in sorted(candidates, key=lambda item: item.order_key):
        by_hash.setdefault(candidate.url_hash, candidate)
    return list(by_hash.values())


async def _sample_remaining(session: AsyncSession, crawl: SiteCrawl) -> int | None:
    if not crawl.sample_mode:
        return None
    runtime = await session.scalar(
        select(WorkspaceSiteHealthRuntime)
        .where(WorkspaceSiteHealthRuntime.workspace_id == crawl.workspace_id)
        .with_for_update()
    )
    sample_limit = runtime.sample_url_limit if runtime is not None else 0
    used = await _active_free_sample_count(session, crawl.workspace_id)
    return max(0, int(sample_limit) - used)


async def _automatic_remaining(session: AsyncSession, crawl: SiteCrawl) -> int | None:
    requested = int((crawl.configuration or {}).get(AUTOMATIC_MONITOR_LIMIT_KEY) or 0)
    if requested <= 0:
        return await _sample_remaining(session, crawl) if crawl.sample_mode else None
    runtime = await session.scalar(
        select(WorkspaceSiteHealthRuntime)
        .where(WorkspaceSiteHealthRuntime.workspace_id == crawl.workspace_id)
        .with_for_update()
    )
    if runtime is None:
        return 0
    entitlement_limit = int(
        runtime.sample_url_limit if crawl.sample_mode else runtime.monitored_url_limit
    )
    active_memberships = await session.scalar(
        select(func.count(MonitoredSiteUrl.id)).where(
            MonitoredSiteUrl.workspace_id == crawl.workspace_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    used_by_crawl = await session.scalar(
        select(func.count(func.distinct(SiteCrawlTask.url_hash))).where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
        )
    )
    return max(
        0,
        min(
            requested - int(used_by_crawl or 0),
            entitlement_limit - int(active_memberships or 0),
        ),
    )


async def add_automatic_root(session: AsyncSession, crawl: SiteCrawl) -> None:
    """Persist and queue analysis for a user-initiated automatic crawl root."""
    remaining = await _automatic_remaining(session, crawl)
    if remaining is None or remaining <= 0:
        return
    canonical_url, url_hash_value = canonical_identity(crawl.root_url)
    candidate = FrontierCandidate(
        url=canonical_url,
        url_hash=url_hash_value,
        depth=0,
        source_kind=OBSERVATION_SOURCE_ROOT,
        value_priority=0,
        parent_position=0,
        link_ordinal=0,
    )
    site_url_id, _created = await _upsert_site_url(
        session, crawl=crawl, candidate=candidate
    )
    await _add_free_sample(
        session,
        crawl=crawl,
        site_url_id=site_url_id,
        url=canonical_url,
        url_hash_value=url_hash_value,
        depth=0,
        source_kind=OBSERVATION_SOURCE_ROOT,
        selection_source=SELECTION_SOURCE_BOOTSTRAP,
    )


def _candidate_allowed(
    crawl: SiteCrawl,
    candidate: FrontierCandidate,
    configuration: dict,
) -> bool:
    decision = classify_url_admission(
        candidate.url,
        root_registrable_domain=configuration.get("root_registrable_domain") or None,
        include_globs=configuration.get("include_globs"),
        exclude_globs=configuration.get("exclude_globs"),
    )
    if not decision.accepted or candidate.depth > site_health_settings.max_crawl_depth:
        return False
    # The re-admission above is scoped (root domain + globs) and is what decides
    # ADMISSIBILITY here. The value kind, though, comes from the candidate's own
    # admission verdict so the filter, the frontier row, and the observation row
    # all agree on one classification of the URL.
    selected_page_kinds = set(configuration.get("page_kinds") or [])
    return not selected_page_kinds or candidate.value_kind in {
        "root",
        "other",
        *selected_page_kinds,
    }


def _requested_discovery_target(crawl: SiteCrawl) -> int:
    configured = int((crawl.configuration or {}).get("requested_page_limit") or 0)
    return int(
        crawl.discovery_requested_count
        or configured
        or site_health_settings.automatic_page_limit
    )


def _requested_budget_exhausted(crawl: SiteCrawl, admitted: int) -> bool:
    return crawl.admitted_url_count + admitted >= _requested_discovery_target(crawl)


def _frontier_limit(crawl: SiteCrawl, configuration: dict | None = None) -> int:
    if crawl.sample_mode:
        return site_health_settings.sample_discovery_url_cap
    frozen = configuration if configuration is not None else (crawl.configuration or {})
    return int(
        frozen.get("max_frontier_urls") or site_health_settings.max_frontier_urls
    )


def _frontier_full(crawl: SiteCrawl, admitted: int) -> bool:
    current = crawl.admitted_url_count + admitted
    return current >= _frontier_limit(crawl)


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
    """
    configuration = dict(crawl.configuration or {})
    progress = _AdmissionProgress(remaining=await _automatic_remaining(session, crawl))
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
