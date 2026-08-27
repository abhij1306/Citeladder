"""Pure, bounded internal-link graph derivation over persisted page facts."""

from __future__ import annotations

import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

from app.connectors.web_evidence.url_policy import canonicalize
from app.domain.site_health.normalization import canonical_identity


@dataclass(frozen=True, slots=True)
class LinkPageInput:
    """One crawled page and the immutable anchor facts used by the graph."""

    site_url_id: uuid.UUID
    normalized_url: str
    final_url: str
    artifact_id: uuid.UUID
    facts: dict[str, Any]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageLinkMetricResult:
    site_url_id: uuid.UUID
    inbound_count: int
    outbound_count: int
    main_content_inbound_count: int
    main_content_outbound_count: int
    nofollow_inbound_count: int
    depth_from_home: int | None
    source_page_count: int
    top_inbound: list[dict[str, object]]
    top_outbound: list[dict[str, object]]
    source_artifact_ids: list[uuid.UUID]


@dataclass(slots=True)
class _Edge:
    source_id: uuid.UUID
    source_url: str
    target_id: uuid.UUID | None
    target_url: str
    anchor_count: int = 0
    main_content: bool = False
    has_nofollow: bool = False
    followable: bool = False
    rel_tokens: set[str] = field(default_factory=set)


def _canonical(raw: str, *, base_url: str | None = None) -> str | None:
    try:
        absolute = canonicalize(raw, base_url=base_url)
        return canonical_identity(absolute)[0]
    except (TypeError, ValueError):
        return None


def _canonical_values(values: set[str]) -> set[str]:
    return {
        canonical
        for value in values
        if value and (canonical := _canonical(value)) is not None
    }


def _alias_map(pages: list[LinkPageInput]) -> dict[str, uuid.UUID]:
    """Prefer exact SiteUrl identities over redirect aliases.

    A redirect source and its final URL can both be crawl nodes. In that case
    the exact normalized final-URL node owns links to the final URL; redirect
    aliases fill only identities that have no exact node.
    """
    resolved: dict[str, uuid.UUID] = {}
    for page in sorted(pages, key=lambda item: str(item.site_url_id)):
        direct = _canonical(page.normalized_url)
        if direct is not None:
            resolved[direct] = page.site_url_id

    redirect_claims: dict[str, set[uuid.UUID]] = defaultdict(set)
    for page in pages:
        for alias in _canonical_values({page.final_url, *page.aliases}):
            if alias not in resolved:
                redirect_claims[alias].add(page.site_url_id)
    for alias, claimants in redirect_claims.items():
        if len(claimants) == 1:
            resolved[alias] = next(iter(claimants))
    return resolved


def _rel_tokens(raw: object) -> set[str]:
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw or "").replace(",", " ").split()
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _page_anchors(page: LinkPageInput) -> list[dict[str, Any]]:
    links = page.facts.get("links") or {}
    if not isinstance(links, dict):
        return []
    anchors = links.get("anchors") or []
    if not isinstance(anchors, list):
        return []
    return [anchor for anchor in anchors if isinstance(anchor, dict)]


def _page_is_nofollow(page: LinkPageInput) -> bool:
    robots = page.facts.get("robots") or {}
    return bool(robots.get("nofollow")) if isinstance(robots, dict) else False


def _merge_anchor(
    by_target: dict[tuple[str, str], _Edge],
    *,
    page: LinkPageInput,
    anchor: dict[str, Any],
    aliases: dict[str, uuid.UUID],
    node_urls: dict[uuid.UUID, str],
    page_nofollow: bool,
) -> None:
    if not anchor.get("is_internal"):
        return
    target_url = _canonical(str(anchor.get("url") or ""), base_url=page.final_url)
    if target_url is None:
        return
    target_id = aliases.get(target_url)
    if target_id is not None:
        target_url = node_urls[target_id]
    target_key = str(target_id) if target_id is not None else target_url
    key = ("node" if target_id is not None else "url", target_key)
    edge = by_target.setdefault(
        key,
        _Edge(
            source_id=page.site_url_id,
            source_url=page.normalized_url,
            target_id=target_id,
            target_url=target_url,
        ),
    )
    tokens = _rel_tokens(anchor.get("rel"))
    nofollow = page_nofollow or "nofollow" in tokens
    edge.anchor_count += 1
    edge.main_content = edge.main_content or anchor.get("region") == "main"
    edge.has_nofollow = edge.has_nofollow or nofollow
    edge.followable = edge.followable or not nofollow
    edge.rel_tokens.update(tokens & {"nofollow", "sponsored", "ugc"})


def _page_edges(
    page: LinkPageInput,
    aliases: dict[str, uuid.UUID],
    node_urls: dict[uuid.UUID, str],
) -> list[_Edge]:
    by_target: dict[tuple[str, str], _Edge] = {}
    page_nofollow = _page_is_nofollow(page)
    for anchor in _page_anchors(page):
        _merge_anchor(
            by_target,
            page=page,
            anchor=anchor,
            aliases=aliases,
            node_urls=node_urls,
            page_nofollow=page_nofollow,
        )
    return sorted(by_target.values(), key=lambda item: item.target_url)


def _node_urls(pages: list[LinkPageInput]) -> dict[uuid.UUID, str]:
    representatives: dict[uuid.UUID, str] = {}
    for page in pages:
        normalized = _canonical(page.normalized_url)
        representatives[page.site_url_id] = normalized or page.normalized_url
    return representatives


def _depths(
    home_id: uuid.UUID | None,
    outgoing: dict[uuid.UUID, list[_Edge]],
) -> dict[uuid.UUID, int]:
    if home_id is None:
        return {}
    depths = {home_id: 0}
    queue: deque[uuid.UUID] = deque([home_id])
    while queue:
        source_id = queue.popleft()
        for edge in outgoing[source_id]:
            target_id = edge.target_id
            if not edge.followable or target_id is None or target_id in depths:
                continue
            depths[target_id] = depths[source_id] + 1
            queue.append(target_id)
    return depths


def _neighbour_row(edge: _Edge, *, inbound: bool) -> dict[str, object]:
    site_url_id: uuid.UUID | None
    if inbound:
        site_url_id = edge.source_id
        url = edge.source_url
    else:
        site_url_id = edge.target_id
        url = edge.target_url
    return {
        "site_url_id": str(site_url_id) if site_url_id is not None else None,
        "url": url,
        "anchor_count": edge.anchor_count,
        "main_content": edge.main_content,
        "nofollow": edge.has_nofollow,
        "rel": sorted(edge.rel_tokens),
    }


def _top_neighbours(
    edges: list[_Edge], *, inbound: bool, limit: int
) -> list[dict[str, object]]:
    ordered = sorted(
        edges,
        key=lambda edge: (
            -edge.anchor_count,
            -int(edge.main_content),
            edge.source_url if inbound else edge.target_url,
            str(edge.source_id if inbound else edge.target_id or ""),
        ),
    )
    return [_neighbour_row(edge, inbound=inbound) for edge in ordered[:limit]]


def build_link_metrics(
    pages: list[LinkPageInput], *, home_url: str, neighbour_limit: int
) -> list[PageLinkMetricResult]:
    """Collapse duplicate links, resolve crawl nodes, and derive page metrics."""
    ordered_pages = sorted(pages, key=lambda item: str(item.site_url_id))
    aliases = _alias_map(ordered_pages)
    node_urls = _node_urls(ordered_pages)
    outgoing = {
        page.site_url_id: _page_edges(page, aliases, node_urls)
        for page in ordered_pages
    }
    inbound: dict[uuid.UUID, list[_Edge]] = defaultdict(list)
    for edges in outgoing.values():
        for edge in edges:
            if edge.target_id is not None:
                inbound[edge.target_id].append(edge)

    canonical_home = _canonical(home_url)
    home_id = aliases.get(canonical_home) if canonical_home is not None else None
    depths = _depths(home_id, outgoing)
    source_artifact_ids = sorted({page.artifact_id for page in ordered_pages}, key=str)
    source_page_count = len(ordered_pages)
    limit = max(0, neighbour_limit)
    results: list[PageLinkMetricResult] = []
    for page in ordered_pages:
        page_outbound = outgoing[page.site_url_id]
        page_inbound = inbound[page.site_url_id]
        results.append(
            PageLinkMetricResult(
                site_url_id=page.site_url_id,
                inbound_count=len(page_inbound),
                outbound_count=len(page_outbound),
                main_content_inbound_count=sum(
                    edge.main_content for edge in page_inbound
                ),
                main_content_outbound_count=sum(
                    edge.main_content for edge in page_outbound
                ),
                nofollow_inbound_count=sum(edge.has_nofollow for edge in page_inbound),
                depth_from_home=depths.get(page.site_url_id),
                source_page_count=source_page_count,
                top_inbound=_top_neighbours(page_inbound, inbound=True, limit=limit),
                top_outbound=_top_neighbours(page_outbound, inbound=False, limit=limit),
                source_artifact_ids=source_artifact_ids,
            )
        )
    return results


__all__ = ["LinkPageInput", "PageLinkMetricResult", "build_link_metrics"]
