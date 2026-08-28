"""Shared persistence and policy helpers for Site Health frontier admission."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    classify_url_admission,
    is_in_scope,
    registrable_domain,
    split_host_port,
)
from app.core.config.site_health_contracts import (
    CRAWL_ACTIVE_STATUSES,
    DISCOVERY_STATUS_RUNNING,
    OBSERVATION_SOURCE_LINK,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    CORPUS_DISPOSITION_EXCLUDE,
    CORPUS_DISPOSITION_INVENTORY_ONLY,
    CORPUS_DISPOSITION_VERSION,
    DISPOSITION_REASON_DOCUMENT,
    ITEM_KIND_DOCUMENT,
    SELECTION_SOURCE_FREE_SAMPLE,
    SELECTION_SOURCE_USER,
    URL_EXCLUSION_DUPLICATE,
)
from app.core.config.site_health_runtime import (
    ANALYZE_PRIORITY_BOOST,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import FrontierCandidate
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation


def _utcnow() -> datetime:
    return datetime.now(UTC)


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
    """Insert a ``SiteUrl`` conflict-safely; return ``(id, created)``."""
    now = _utcnow()
    try:
        host, _port = split_host_port(candidate.url)
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
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.url_hash == candidate.url_hash,
        )
    )
    if existing is None:
        raise RuntimeError(f"SiteUrl row vanished for url_hash={candidate.url_hash!r}")
    # SiteUrl is the mutable latest-seen projection. A previous crawl may have
    # identified this identity as a document or canonical alias; seeing it in a
    # new crawl resets that disposition until the new evidence confirms it.
    await session.execute(
        update(SiteUrl)
        .where(
            SiteUrl.id == existing,
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
        )
        .values(
            display_url=candidate.url,
            host=host[:255],
            depth=candidate.depth,
            corpus_disposition=candidate.disposition,
            disposition_reason=candidate.disposition_reason,
            disposition_version=candidate.disposition_version,
            item_kind=candidate.item_kind,
            discovery_status=DISCOVERY_STATUS_RUNNING,
            latest_source_kind=candidate.source_kind,
            last_seen_crawl_id=crawl.id,
            last_seen_at=now,
        )
    )
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
    """Enqueue one active-crawl task conflict-safely."""
    still_active = await session.scalar(
        select(SiteCrawl.id).where(
            SiteCrawl.id == crawl.id,
            SiteCrawl.status.in_(list(CRAWL_ACTIVE_STATUSES)),
        )
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
            index_elements=["crawl_id", "task_kind", "url_hash", "generation"]
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
    """Insert or reactivate a system-managed monitored membership."""
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
    analyze_after_discovery: bool = False,
    selection_source: str = SELECTION_SOURCE_FREE_SAMPLE,
    phase_run_id: uuid.UUID | None = None,
    value_kind: str = "other",
    value_priority: int = 0,
    rewrite_reason: str = "",
    rewrite_version: str = "",
) -> tuple[bool, bool]:
    """Admit a URL into inventory and optionally monitor and analyze it."""
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
            rewrite_reason=rewrite_reason,
            rewrite_version=rewrite_version,
            depth=depth,
            observed_url=url,
            final_url=url,
        )
        .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
        .returning(SiteUrlObservation.id)
    )
    # A URL that is about to be DISCOVERED gets its analyze task later, from
    # the transaction that writes its discover artifact (see
    # ``enqueue_analysis_for_discovered_url``). Enqueuing it here instead meant
    # the analyze task existed long before the page had been fetched, so it
    # woke, found the discover task still in flight, and deferred -- pushing
    # its own ``available_at`` further back every time and sending it behind
    # everything queued since. A cold crawl therefore drained its whole
    # discovery tree before analyzing anything.
    #
    # Handed over after the fetch, the artifact is already committed, so the
    # task is claimed once and reuses it rather than burning a claim to learn
    # it must wait.
    if analyze and not analyze_after_discovery:
        await _enqueue_task(
            session,
            crawl=crawl,
            site_url_id=site_url_id,
            url=url,
            url_hash_value=url_hash_value,
            task_kind=TASK_KIND_ANALYZE,
            depth=depth,
            priority=value_priority + ANALYZE_PRIORITY_BOOST,
            phase_run_id=phase_run_id,
        )
    return activated_id is not None, observation_id is not None


async def resolve_duplicate_of_admitted_page(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    url_hash_value: str,
    declared_canonical: str,
) -> str:
    """The url_hash this page says it really is, when that page is already ours.

    A storefront serves one product at every collection path that lists it, and
    each alias declares the same ``rel=canonical``. Crawled as distinct pages
    they cost a fetch, an analysis and a catalog row each: one 427-page crawl
    covered only 306 distinct canonicals, so 27% of the budget bought nothing.

    Returns the canonical's hash only when that URL was observed by this crawl
    and is already active, while the alias is system-managed. Collapsing onto
    an unobserved target or overriding a user's explicit selection could
    silently drop content. Returns "" when there is nothing safe to collapse.
    """
    declared = str(declared_canonical or "").strip()
    if not declared:
        return ""
    root = str((crawl.configuration or {}).get("root_registrable_domain") or "")
    if not root:
        root = registrable_domain(crawl.root_url)
    try:
        canonical, canonical_hash = canonical_identity(declared)
    except UrlPolicyError:
        return ""
    if canonical_hash == url_hash_value:
        return ""
    # `rel=canonical` is markup the crawled page controls; honoring an
    # off-domain value would let one site redirect our identity onto another's.
    if not root or not is_in_scope(canonical, root):
        return ""
    admitted = await session.scalar(
        select(MonitoredSiteUrl.id)
        .join(SiteUrl, SiteUrl.id == MonitoredSiteUrl.site_url_id)
        .join(
            SiteUrlObservation,
            SiteUrlObservation.site_url_id == SiteUrl.id,
        )
        .where(
            MonitoredSiteUrl.workspace_id == crawl.workspace_id,
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.active.is_(True),
            SiteUrl.url_hash == canonical_hash,
            SiteUrlObservation.crawl_id == crawl.id,
        )
    )
    alias_is_system_managed = await session.scalar(
        select(MonitoredSiteUrl.id)
        .join(SiteUrl, SiteUrl.id == MonitoredSiteUrl.site_url_id)
        .where(
            MonitoredSiteUrl.workspace_id == crawl.workspace_id,
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.active.is_(True),
            MonitoredSiteUrl.selection_source != SELECTION_SOURCE_USER,
            SiteUrl.url_hash == url_hash_value,
        )
    )
    return canonical_hash if admitted is not None and alias_is_system_managed else ""


async def mark_duplicate_url(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    url_hash_value: str,
) -> None:
    """Record a crawled alias as an exclusion, not as a page of the corpus.

    Uses the existing disposition vocabulary rather than a new one, so the
    dashboard can already say WHY the page left the set.
    """
    site_url = await session.scalar(
        select(SiteUrl).where(
            SiteUrl.workspace_id == workspace_id,
            SiteUrl.project_id == project_id,
            SiteUrl.url_hash == url_hash_value,
        )
    )
    if site_url is None:
        return
    site_url.corpus_disposition = CORPUS_DISPOSITION_EXCLUDE
    site_url.disposition_reason = URL_EXCLUSION_DUPLICATE
    site_url.disposition_version = CORPUS_DISPOSITION_VERSION
    await session.execute(
        update(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.site_url_id == site_url.id,
            MonitoredSiteUrl.selection_source != SELECTION_SOURCE_USER,
        )
        .values(active=False)
    )


async def mark_inventory_document(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    url_hash_value: str,
) -> None:
    """Project a fetched document as inventory-only and free auto quota."""
    site_url = await session.scalar(
        select(SiteUrl).where(
            SiteUrl.workspace_id == workspace_id,
            SiteUrl.project_id == project_id,
            SiteUrl.url_hash == url_hash_value,
        )
    )
    if site_url is None:
        return
    site_url.corpus_disposition = CORPUS_DISPOSITION_INVENTORY_ONLY
    site_url.disposition_reason = DISPOSITION_REASON_DOCUMENT
    site_url.disposition_version = CORPUS_DISPOSITION_VERSION
    site_url.item_kind = ITEM_KIND_DOCUMENT
    await session.execute(
        update(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == workspace_id,
            MonitoredSiteUrl.project_id == project_id,
            MonitoredSiteUrl.site_url_id == site_url.id,
            MonitoredSiteUrl.selection_source != SELECTION_SOURCE_USER,
        )
        .values(active=False)
    )


async def enqueue_analysis_for_discovered_url(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID | None,
    url: str,
    url_hash_value: str,
    depth: int,
    value_priority: int,
    phase_run_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Queue the analyze task for a URL whose discover artifact now exists.

    Called from the discover task's own persistence transaction, so the
    artifact this analysis will reuse is committed alongside it. Only a URL
    that is an active member of the monitored set is analyzed; admission
    decided that already, and re-checking here keeps a deselected URL from
    being analyzed on the strength of having been fetched.
    """
    if site_url_id is None:
        site_url_id = await session.scalar(
            select(SiteUrl.id).where(
                SiteUrl.project_id == crawl.project_id,
                SiteUrl.url_hash == url_hash_value,
            )
        )
    if site_url_id is None:
        return None
    member = await session.scalar(
        select(MonitoredSiteUrl.id).where(
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.site_url_id == site_url_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    if member is None:
        return None
    return await _enqueue_task(
        session,
        crawl=crawl,
        site_url_id=site_url_id,
        url=url,
        url_hash_value=url_hash_value,
        task_kind=TASK_KIND_ANALYZE,
        depth=depth,
        priority=value_priority + ANALYZE_PRIORITY_BOOST,
        phase_run_id=phase_run_id,
    )


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


async def _sample_remaining(
    session: AsyncSession,
    crawl: SiteCrawl,
    *,
    runtime: WorkspaceSiteHealthRuntime | None = None,
) -> int | None:
    if not crawl.sample_mode:
        return None
    if runtime is None:
        runtime = await session.scalar(
            select(WorkspaceSiteHealthRuntime)
            .where(WorkspaceSiteHealthRuntime.workspace_id == crawl.workspace_id)
            .with_for_update()
        )
    sample_limit = runtime.sample_url_limit if runtime is not None else 0
    used = await _active_free_sample_count(session, crawl.workspace_id)
    return max(0, int(sample_limit) - used)


async def _automatic_remaining(
    session: AsyncSession,
    crawl: SiteCrawl,
    *,
    runtime: WorkspaceSiteHealthRuntime | None = None,
) -> int | None:
    requested = int((crawl.configuration or {}).get(AUTOMATIC_MONITOR_LIMIT_KEY) or 0)
    if requested <= 0:
        return (
            await _sample_remaining(session, crawl, runtime=runtime)
            if crawl.sample_mode
            else None
        )
    if runtime is None:
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
    # What this crawl has SELECTED for analysis, counted from the membership
    # admission writes -- not from the analyze tasks that follow it. A URL that
    # is also being discovered gets its analyze task later, from the fetch that
    # hands the artifact over, so counting tasks here read the budget as
    # untouched and admitted straight past the frozen limit.
    used_by_crawl = await session.scalar(
        select(func.count(func.distinct(SiteUrlObservation.site_url_id)))
        .select_from(SiteUrlObservation)
        .join(
            MonitoredSiteUrl,
            MonitoredSiteUrl.site_url_id == SiteUrlObservation.site_url_id,
        )
        .where(
            SiteUrlObservation.crawl_id == crawl.id,
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.active.is_(True),
        )
    )
    return max(
        0,
        min(
            requested - int(used_by_crawl or 0),
            entitlement_limit - int(active_memberships or 0),
        ),
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
    return crawl.admitted_url_count + admitted >= _frontier_limit(crawl)
