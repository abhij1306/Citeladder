"""Deterministic canonical-alias disposition for one Site Health crawl."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    is_in_scope,
    registrable_domain,
)
from app.core.config.site_health_crawl_policy import (
    CORPUS_DISPOSITION_EXCLUDE,
    CORPUS_DISPOSITION_VERSION,
    SELECTION_SOURCE_USER,
    URL_EXCLUSION_DUPLICATE,
)
from app.domain.site_health.normalization import canonical_identity
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation


@dataclass
class _AliasGraph:
    site_url_ids: dict[str, uuid.UUID]
    active_hashes: set[str]
    protected_hashes: set[str]
    candidate_hashes: set[str]
    known_hashes: set[str]
    edges: dict[str, str]


def _canonical_target_hash(
    crawl: SiteCrawl,
    *,
    url_hash_value: str,
    declared_canonical: str,
    base_url: str,
) -> str:
    declared = str(declared_canonical or "").strip()
    if not declared:
        return ""
    root = str((crawl.configuration or {}).get("root_registrable_domain") or "")
    if not root:
        root = registrable_domain(crawl.root_url)
    try:
        canonical, canonical_hash = canonical_identity(declared, base_url=base_url)
    except UrlPolicyError:
        return ""
    if canonical_hash == url_hash_value:
        return ""
    if not root or not is_in_scope(canonical, root):
        return ""
    return canonical_hash


async def _admitted_rows(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    url_hashes: set[str] | None = None,
) -> list[tuple[uuid.UUID, str, bool, str]]:
    query = (
        select(
            SiteUrl.id,
            SiteUrl.url_hash,
            MonitoredSiteUrl.active,
            MonitoredSiteUrl.selection_source,
        )
        .join(
            SiteUrlObservation,
            (SiteUrlObservation.site_url_id == SiteUrl.id)
            & (SiteUrlObservation.workspace_id == crawl.workspace_id)
            & (SiteUrlObservation.project_id == crawl.project_id)
            & (SiteUrlObservation.crawl_id == crawl.id),
        )
        .join(
            MonitoredSiteUrl,
            (MonitoredSiteUrl.site_url_id == SiteUrl.id)
            & (MonitoredSiteUrl.workspace_id == crawl.workspace_id)
            & (MonitoredSiteUrl.project_id == crawl.project_id),
        )
        .where(
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
        )
        .distinct()
    )
    if url_hashes is not None:
        query = query.where(SiteUrl.url_hash.in_(url_hashes))
    rows = await session.execute(query)
    return [
        (site_url_id, str(url_hash), bool(active), str(selection_source))
        for site_url_id, url_hash, active, selection_source in rows
    ]


def _graph_for_admitted(
    admitted: list[tuple[uuid.UUID, str, bool, str]],
) -> _AliasGraph:
    site_url_ids = {url_hash: site_url_id for site_url_id, url_hash, *_ in admitted}
    active_hashes = {url_hash for _, url_hash, active, _ in admitted if active}
    protected_hashes = {
        url_hash
        for _, url_hash, active, source in admitted
        if active and source == SELECTION_SOURCE_USER
    }
    return _AliasGraph(
        site_url_ids=site_url_ids,
        active_hashes=active_hashes,
        protected_hashes=protected_hashes,
        candidate_hashes=active_hashes - protected_hashes,
        known_hashes=set(),
        edges={},
    )


async def _load_alias_graph(session: AsyncSession, *, crawl: SiteCrawl) -> _AliasGraph:
    graph = _graph_for_admitted(await _admitted_rows(session, crawl=crawl))
    site_url_ids = graph.site_url_ids
    if not site_url_ids:
        return graph
    rows = await session.execute(
        select(
            SiteCrawlTask.url_hash,
            SiteFetchArtifact.final_url,
            SiteFetchArtifact.normalized_facts,
        )
        .join(SiteFetchArtifact, SiteFetchArtifact.task_id == SiteCrawlTask.id)
        .where(
            SiteCrawlTask.workspace_id == crawl.workspace_id,
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.url_hash.in_(site_url_ids),
            SiteFetchArtifact.workspace_id == crawl.workspace_id,
            SiteFetchArtifact.crawl_id == crawl.id,
        )
        .order_by(SiteFetchArtifact.fetched_at, SiteFetchArtifact.id)
    )
    for url_hash, final_url, facts in rows:
        _observe_alias_edge(
            graph,
            crawl=crawl,
            url_hash_value=str(url_hash or ""),
            declared_canonical=str((facts or {}).get("canonical_url") or ""),
            base_url=str(final_url or ""),
        )
    return graph


def _observe_alias_edge(
    graph: _AliasGraph,
    *,
    crawl: SiteCrawl,
    url_hash_value: str,
    declared_canonical: str,
    base_url: str,
) -> None:
    graph.known_hashes.add(url_hash_value)
    target_hash = _canonical_target_hash(
        crawl,
        url_hash_value=url_hash_value,
        declared_canonical=declared_canonical,
        base_url=base_url,
    )
    if target_hash in graph.site_url_ids:
        graph.edges[url_hash_value] = target_hash
    else:
        graph.edges.pop(url_hash_value, None)


def _resolved_representative(graph: _AliasGraph, source_hash: str) -> str:
    path: list[str] = []
    positions: dict[str, int] = {}
    current = source_hash
    while True:
        if current != source_hash and current in graph.protected_hashes:
            return current
        if current in positions:
            cycle = set(path[positions[current] :])
            retained = sorted(cycle & graph.protected_hashes) or sorted(
                cycle & graph.active_hashes
            )
            return retained[0] if retained else ""
        if current not in graph.known_hashes:
            return ""
        positions[current] = len(path)
        path.append(current)
        target = graph.edges.get(current)
        if not target:
            return current if current in graph.active_hashes else ""
        current = target


def _resolved_duplicate_targets(graph: _AliasGraph) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for source_hash in sorted(graph.candidate_hashes):
        representative = _resolved_representative(graph, source_hash)
        if representative in graph.active_hashes and representative != source_hash:
            resolved[source_hash] = representative
    selected = set(resolved)
    return {
        source_hash: target_hash
        for source_hash, target_hash in resolved.items()
        if target_hash not in selected
    }


async def _exclude_duplicate_site_urls(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_ids: set[uuid.UUID],
) -> None:
    if not site_url_ids:
        return
    await session.execute(
        update(SiteUrl)
        .where(
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.id.in_(site_url_ids),
        )
        .values(
            corpus_disposition=CORPUS_DISPOSITION_EXCLUDE,
            disposition_reason=URL_EXCLUSION_DUPLICATE,
            disposition_version=CORPUS_DISPOSITION_VERSION,
        )
    )
    await session.execute(
        update(MonitoredSiteUrl)
        .where(
            MonitoredSiteUrl.workspace_id == crawl.workspace_id,
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.site_url_id.in_(site_url_ids),
            MonitoredSiteUrl.selection_source != SELECTION_SOURCE_USER,
        )
        .values(active=False)
    )
    await session.execute(
        update(SitePageAnalysis)
        .where(
            SitePageAnalysis.workspace_id == crawl.workspace_id,
            SitePageAnalysis.project_id == crawl.project_id,
            SitePageAnalysis.crawl_id == crawl.id,
            SitePageAnalysis.site_url_id.in_(site_url_ids),
            SitePageAnalysis.is_current.is_(True),
        )
        .values(is_current=False)
    )


async def resolve_duplicate_of_admitted_page(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    url_hash_value: str,
    declared_canonical: str,
    base_url: str,
) -> str:
    """Return the active admitted target of one system-managed alias edge."""
    target_hash = _canonical_target_hash(
        crawl=crawl,
        url_hash_value=url_hash_value,
        declared_canonical=declared_canonical,
        base_url=base_url,
    )
    if not target_hash:
        return ""
    graph = _graph_for_admitted(
        await _admitted_rows(
            session,
            crawl=crawl,
            url_hashes={url_hash_value, target_hash},
        )
    )
    if url_hash_value not in graph.candidate_hashes:
        return ""
    return target_hash if target_hash in graph.active_hashes else ""


async def mark_duplicate_url(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    url_hash_value: str,
) -> None:
    """Exclude one fetched system-managed alias and supersede its analysis."""
    site_url_id = await session.scalar(
        select(SiteUrl.id).where(
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
            SiteUrl.url_hash == url_hash_value,
        )
    )
    if site_url_id is not None:
        await _exclude_duplicate_site_urls(
            session, crawl=crawl, site_url_ids={site_url_id}
        )


async def reconcile_crawl_duplicate_aliases(
    session: AsyncSession, *, crawl: SiteCrawl
) -> int:
    """Resolve alias clusters before excluding their non-representatives."""
    graph = await _load_alias_graph(session, crawl=crawl)
    duplicate_targets = _resolved_duplicate_targets(graph)
    duplicate_ids = {
        graph.site_url_ids[source_hash] for source_hash in duplicate_targets
    }
    await _exclude_duplicate_site_urls(session, crawl=crawl, site_url_ids=duplicate_ids)
    return len(duplicate_ids)


__all__ = [
    "mark_duplicate_url",
    "reconcile_crawl_duplicate_aliases",
    "resolve_duplicate_of_admitted_page",
]
