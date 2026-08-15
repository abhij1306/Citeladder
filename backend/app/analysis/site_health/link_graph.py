"""Pure deterministic crawl-scoped internal-link graph analysis."""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.config.site_health import (
    LINK_GRAPH_HUB_MAX_DEPTH,
    LINK_GRAPH_HUB_MIN_TARGETS,
    LINK_GRAPH_MAX_ANCHOR_DISTRIBUTION,
    LINK_GRAPH_MAX_ANCHOR_TEXTS_PER_EDGE,
    LINK_GRAPH_MAX_SUGGESTIONS,
    LINK_GRAPH_NEAR_ORPHAN_MAX_INBOUND,
    LINK_GRAPH_OVER_LINKED_MIN_TARGETS,
    LINK_GRAPH_PAGERANK_DAMPING,
    LINK_GRAPH_PAGERANK_MAX_ITERATIONS,
    LINK_GRAPH_PAGERANK_TOLERANCE,
    LINK_GRAPH_STATE_AVAILABLE,
    LINK_GRAPH_STATE_INCOMPLETE,
    LINK_GRAPH_SUGGESTION_MIN_JACCARD,
    LINK_GRAPH_WEAK_AUTHORITY_MIN_NODES,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class LinkGraphNodeInput:
    site_url_id: uuid.UUID
    source_analysis_id: uuid.UUID
    normalized_url: str
    title: str
    indexable: bool
    page_nofollow: bool = False


@dataclass(frozen=True)
class LinkGraphReferenceInput:
    source_site_url_id: uuid.UUID
    target_site_url_id: uuid.UUID | None
    target_url: str
    rel: str = ""
    anchor_text: str = ""


@dataclass(frozen=True)
class LinkGraphEdge:
    source_site_url_id: uuid.UUID
    target_site_url_id: uuid.UUID | None
    target_url: str
    followed: bool
    occurrence_count: int
    followed_occurrence_count: int
    nofollow_occurrence_count: int
    anchor_texts: tuple[str, ...]


@dataclass(frozen=True)
class LinkGraphNode:
    site_url_id: uuid.UUID
    source_analysis_id: uuid.UUID
    normalized_url: str
    title: str
    indexable: bool
    pagerank: float
    click_depth: int | None
    followed_inbound_count: int
    followed_outbound_count: int
    near_orphan: bool
    weak_authority: bool
    over_linked: bool
    hub: bool
    suggested_source_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class LinkGraphResult:
    state: str
    nodes: tuple[LinkGraphNode, ...]
    edges: tuple[LinkGraphEdge, ...]
    root_site_url_id: uuid.UUID | None
    pagerank_iterations: int
    pagerank_converged: bool
    authority_concentrated: bool
    anchor_text_distribution: tuple[tuple[str, int], ...]
    limitations: tuple[str, ...]


@dataclass
class _EdgeAccumulator:
    source_id: uuid.UUID
    target_id: uuid.UUID | None
    target_url: str
    occurrence_count: int = 0
    followed_count: int = 0
    nofollow_count: int = 0
    anchor_texts: set[str] | None = None

    def __post_init__(self) -> None:
        self.anchor_texts = set()


def _is_nofollow(rel: str) -> bool:
    return "nofollow" in {token.lower() for token in rel.split()}


def _collapse_edges(
    nodes: dict[uuid.UUID, LinkGraphNodeInput],
    references: list[LinkGraphReferenceInput],
) -> tuple[LinkGraphEdge, ...]:
    grouped: dict[tuple[uuid.UUID, str], _EdgeAccumulator] = {}
    for ref in references:
        source = nodes.get(ref.source_site_url_id)
        if source is None:
            continue
        target_key = (
            str(ref.target_site_url_id) if ref.target_site_url_id else ref.target_url
        )
        key = (ref.source_site_url_id, target_key)
        edge = grouped.setdefault(
            key,
            _EdgeAccumulator(
                source_id=ref.source_site_url_id,
                target_id=ref.target_site_url_id,
                target_url=ref.target_url,
            ),
        )
        edge.occurrence_count += 1
        followed = ref.target_site_url_id is not None and not (
            source.page_nofollow or _is_nofollow(ref.rel)
        )
        if followed:
            edge.followed_count += 1
        else:
            edge.nofollow_count += 1
        text = " ".join(ref.anchor_text.split())
        if text and edge.anchor_texts is not None:
            edge.anchor_texts.add(text[:256])
    return tuple(
        LinkGraphEdge(
            source_site_url_id=item.source_id,
            target_site_url_id=item.target_id,
            target_url=item.target_url,
            followed=item.followed_count > 0,
            occurrence_count=item.occurrence_count,
            followed_occurrence_count=item.followed_count,
            nofollow_occurrence_count=item.nofollow_count,
            anchor_texts=tuple(sorted(item.anchor_texts or ()))[
                :LINK_GRAPH_MAX_ANCHOR_TEXTS_PER_EDGE
            ],
        )
        for _key, item in sorted(grouped.items(), key=lambda pair: pair[0])
    )


def _topology(
    node_ids: tuple[uuid.UUID, ...], edges: tuple[LinkGraphEdge, ...]
) -> tuple[dict[uuid.UUID, set[uuid.UUID]], dict[uuid.UUID, set[uuid.UUID]]]:
    outbound: dict[uuid.UUID, set[uuid.UUID]] = {node_id: set() for node_id in node_ids}
    inbound: dict[uuid.UUID, set[uuid.UUID]] = {node_id: set() for node_id in node_ids}
    for edge in edges:
        if not edge.followed or edge.target_site_url_id not in inbound:
            continue
        outbound[edge.source_site_url_id].add(edge.target_site_url_id)
        inbound[edge.target_site_url_id].add(edge.source_site_url_id)
    return outbound, inbound


def _pagerank(
    node_ids: tuple[uuid.UUID, ...], outbound: dict[uuid.UUID, set[uuid.UUID]]
) -> tuple[dict[uuid.UUID, float], int, bool]:
    count = len(node_ids)
    if count == 0:
        return {}, 0, True
    ranks = {node_id: 1.0 / count for node_id in node_ids}
    base = (1.0 - LINK_GRAPH_PAGERANK_DAMPING) / count
    for iteration in range(1, LINK_GRAPH_PAGERANK_MAX_ITERATIONS + 1):
        dangling = sum(ranks[node_id] for node_id in node_ids if not outbound[node_id])
        updated = {
            node_id: base + LINK_GRAPH_PAGERANK_DAMPING * dangling / count
            for node_id in node_ids
        }
        for source_id in node_ids:
            targets = outbound[source_id]
            if not targets:
                continue
            share = LINK_GRAPH_PAGERANK_DAMPING * ranks[source_id] / len(targets)
            for target_id in targets:
                updated[target_id] += share
        delta = sum(abs(updated[node_id] - ranks[node_id]) for node_id in node_ids)
        ranks = updated
        if delta <= LINK_GRAPH_PAGERANK_TOLERANCE:
            return ranks, iteration, True
    return ranks, LINK_GRAPH_PAGERANK_MAX_ITERATIONS, False


def _depths(
    root_id: uuid.UUID | None, outbound: dict[uuid.UUID, set[uuid.UUID]]
) -> dict[uuid.UUID, int]:
    if root_id is None or root_id not in outbound:
        return {}
    depths = {root_id: 0}
    queue = deque([root_id])
    while queue:
        source_id = queue.popleft()
        for target_id in sorted(outbound[source_id], key=str):
            if target_id in depths:
                continue
            depths[target_id] = depths[source_id] + 1
            queue.append(target_id)
    return depths


def _quartile_cutoff(ranks: dict[uuid.UUID, float]) -> float | None:
    values = sorted(ranks.values())
    if len(values) < LINK_GRAPH_WEAK_AUTHORITY_MIN_NODES:
        return None
    return values[max(0, math.ceil(len(values) * 0.25) - 1)]


def _hub_cutoff(outbound: dict[uuid.UUID, set[uuid.UUID]]) -> int:
    values = sorted((len(targets) for targets in outbound.values()), reverse=True)
    if not values:
        return LINK_GRAPH_HUB_MIN_TARGETS
    top_decile_count = max(1, math.ceil(len(values) * 0.10))
    return max(LINK_GRAPH_HUB_MIN_TARGETS, values[top_decile_count - 1])


def _tokens(node: LinkGraphNodeInput) -> set[str]:
    path = urlsplit(node.normalized_url).path.replace("-", " ").replace("_", " ")
    return set(_TOKEN_RE.findall(f"{path} {node.title}".lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _suggest_sources(
    target_id: uuid.UUID,
    *,
    nodes: dict[uuid.UUID, LinkGraphNodeInput],
    ranks: dict[uuid.UUID, float],
    outbound: dict[uuid.UUID, set[uuid.UUID]],
) -> tuple[uuid.UUID, ...]:
    target_tokens = _tokens(nodes[target_id])
    candidates: list[tuple[float, float, str, uuid.UUID]] = []
    for source_id, source in nodes.items():
        if source_id == target_id or target_id in outbound[source_id]:
            continue
        similarity = _jaccard(target_tokens, _tokens(source))
        if similarity < LINK_GRAPH_SUGGESTION_MIN_JACCARD:
            continue
        candidates.append((ranks[source_id], similarity, str(source_id), source_id))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return tuple(item[3] for item in candidates[:LINK_GRAPH_MAX_SUGGESTIONS])


def _node_metric(
    node_id: uuid.UUID,
    *,
    nodes: dict[uuid.UUID, LinkGraphNodeInput],
    ranks: dict[uuid.UUID, float],
    inbound: dict[uuid.UUID, set[uuid.UUID]],
    outbound: dict[uuid.UUID, set[uuid.UUID]],
    depths: dict[uuid.UUID, int],
    root_site_url_id: uuid.UUID | None,
    weak_cutoff: float | None,
    hub_cutoff: int,
    complete_coverage: bool,
) -> LinkGraphNode:
    source = nodes[node_id]
    near_orphan = (
        source.indexable
        and node_id != root_site_url_id
        and len(inbound[node_id]) <= LINK_GRAPH_NEAR_ORPHAN_MAX_INBOUND
    )
    weak = (
        weak_cutoff is not None
        and bool(inbound[node_id])
        and ranks[node_id] <= weak_cutoff
    )
    suggestions: tuple[uuid.UUID, ...] = ()
    if complete_coverage and (near_orphan or weak):
        suggestions = _suggest_sources(
            node_id, nodes=nodes, ranks=ranks, outbound=outbound
        )
    return LinkGraphNode(
        site_url_id=node_id,
        source_analysis_id=source.source_analysis_id,
        normalized_url=source.normalized_url,
        title=source.title,
        indexable=source.indexable,
        pagerank=ranks[node_id],
        click_depth=depths.get(node_id),
        followed_inbound_count=len(inbound[node_id]),
        followed_outbound_count=len(outbound[node_id]),
        near_orphan=near_orphan,
        weak_authority=weak,
        over_linked=len(outbound[node_id]) >= LINK_GRAPH_OVER_LINKED_MIN_TARGETS,
        hub=(
            len(outbound[node_id]) >= hub_cutoff
            and depths.get(node_id, LINK_GRAPH_HUB_MAX_DEPTH + 1)
            <= LINK_GRAPH_HUB_MAX_DEPTH
        ),
        suggested_source_ids=suggestions,
    )


def analyze_link_graph(
    nodes: list[LinkGraphNodeInput],
    references: list[LinkGraphReferenceInput],
    *,
    root_site_url_id: uuid.UUID | None,
    complete_coverage: bool,
    limitations: tuple[str, ...] = (),
) -> LinkGraphResult:
    """Return a stable graph over one crawl's selected successful analyses."""
    by_id = {node.site_url_id: node for node in nodes}
    node_ids = tuple(sorted(by_id, key=str))
    edges = _collapse_edges(by_id, references)
    outbound, inbound = _topology(node_ids, edges)
    ranks, iterations, converged = _pagerank(node_ids, outbound)
    depths = _depths(root_site_url_id, outbound)
    weak_cutoff = _quartile_cutoff(ranks)
    hub_cutoff = _hub_cutoff(outbound)
    metrics = [
        _node_metric(
            node_id,
            nodes=by_id,
            ranks=ranks,
            inbound=inbound,
            outbound=outbound,
            depths=depths,
            root_site_url_id=root_site_url_id,
            weak_cutoff=weak_cutoff,
            hub_cutoff=hub_cutoff,
            complete_coverage=complete_coverage,
        )
        for node_id in node_ids
    ]
    top_count = max(1, math.ceil(len(node_ids) * 0.10)) if node_ids else 0
    top_share = sum(sorted(ranks.values(), reverse=True)[:top_count])
    anchor_counts = Counter(
        text.lower() for edge in edges for text in edge.anchor_texts if text.strip()
    )
    distribution = tuple(
        sorted(anchor_counts.items(), key=lambda item: (-item[1], item[0]))[
            :LINK_GRAPH_MAX_ANCHOR_DISTRIBUTION
        ]
    )
    return LinkGraphResult(
        state=LINK_GRAPH_STATE_AVAILABLE
        if complete_coverage
        else LINK_GRAPH_STATE_INCOMPLETE,
        nodes=tuple(metrics),
        edges=edges,
        root_site_url_id=root_site_url_id,
        pagerank_iterations=iterations,
        pagerank_converged=converged,
        authority_concentrated=top_share > 0.50,
        anchor_text_distribution=distribution,
        limitations=limitations,
    )
