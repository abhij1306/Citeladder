"""Approved complete-coverage link-graph signals for Opportunities."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.opportunities import SITE_GAP_FACTOR, SITE_VALUE_FACTOR
from app.core.config.site_health import (
    LINK_GRAPH_ANALYZER_VERSION,
    LINK_GRAPH_MAX_NODES,
    LINK_GRAPH_STATE_AVAILABLE,
)
from app.models.site_health import (
    SiteCrawl,
    SiteLinkGraphNode,
    SiteLinkGraphSnapshot,
)

_RULE_FLAGS = (
    ("site_link_near_orphan", "near_orphan"),
    ("site_link_weak_authority", "weak_authority"),
)


async def _current_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl: SiteCrawl
) -> SiteLinkGraphSnapshot | None:
    return await session.scalar(
        select(SiteLinkGraphSnapshot)
        .where(
            SiteLinkGraphSnapshot.workspace_id == workspace_id,
            SiteLinkGraphSnapshot.project_id == crawl.project_id,
            SiteLinkGraphSnapshot.crawl_id == crawl.id,
            SiteLinkGraphSnapshot.state == LINK_GRAPH_STATE_AVAILABLE,
            SiteLinkGraphSnapshot.analyzer_version == LINK_GRAPH_ANALYZER_VERSION,
            SiteLinkGraphSnapshot.page_analyzer_version == crawl.analyzer_version,
            SiteLinkGraphSnapshot.extractor_version == crawl.extractor_version,
        )
        .order_by(
            SiteLinkGraphSnapshot.created_at.desc(), SiteLinkGraphSnapshot.id.desc()
        )
        .limit(1)
    )


def _hit(
    *,
    snapshot: SiteLinkGraphSnapshot,
    node: SiteLinkGraphNode,
    rule_id: str,
    suggestions: list[SiteLinkGraphNode],
) -> DetectorHit:
    source_ids = tuple(
        sorted(
            {
                str(node.source_analysis_id),
                *(str(row.source_analysis_id) for row in suggestions),
            }
        )
    )
    return DetectorHit(
        rule_id=rule_id,
        target_key=f"site-url:{node.site_url_id}",
        target_prompt_id=None,
        target_url=node.normalized_url,
        target_theme=None,
        evidence={
            "link_graph_snapshot_id": str(snapshot.id),
            "link_graph_node_id": str(node.id),
            "crawl_id": str(snapshot.crawl_id),
            "coverage": dict(snapshot.coverage or {}),
            "metric": {
                "pagerank": node.pagerank,
                "followed_inbound_count": node.followed_inbound_count,
            },
            "suggested_sources": [
                {
                    "site_url_id": str(source.site_url_id),
                    "url": source.normalized_url,
                    "title": source.title,
                }
                for source in suggestions
            ],
        },
        source_analysis_ids=source_ids,
        source_issue_ids=(),
        source_metric_ids=(str(snapshot.id), str(node.id)),
        value_factor=SITE_VALUE_FACTOR,
        gap_factor=SITE_GAP_FACTOR,
    )


def _hits_for_nodes(
    snapshot: SiteLinkGraphSnapshot,
    signal_nodes: list[SiteLinkGraphNode],
    sources: dict[uuid.UUID, SiteLinkGraphNode],
) -> list[DetectorHit]:
    hits: list[DetectorHit] = []
    for node in signal_nodes:
        suggestions = [
            sources[source_id]
            for source_id in node.suggested_source_ids
            if source_id in sources
        ]
        if not suggestions:
            continue
        for rule_id, flag in _RULE_FLAGS:
            if getattr(node, flag):
                hits.append(
                    _hit(
                        snapshot=snapshot,
                        node=node,
                        rule_id=rule_id,
                        suggestions=suggestions,
                    )
                )
    return hits


async def load_link_graph_hits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl: SiteCrawl,
) -> list[DetectorHit]:
    """Return only approved signals from one exact complete graph snapshot."""
    snapshot = await _current_snapshot(session, workspace_id=workspace_id, crawl=crawl)
    if snapshot is None or not bool((snapshot.coverage or {}).get("complete")):
        return []
    signal_nodes = list(
        (
            await session.scalars(
                select(SiteLinkGraphNode)
                .where(
                    SiteLinkGraphNode.workspace_id == workspace_id,
                    SiteLinkGraphNode.snapshot_id == snapshot.id,
                    or_(
                        SiteLinkGraphNode.near_orphan.is_(True),
                        SiteLinkGraphNode.weak_authority.is_(True),
                    ),
                    SiteLinkGraphNode.indexable.is_(True),
                )
                .order_by(SiteLinkGraphNode.normalized_url, SiteLinkGraphNode.id)
                .limit(LINK_GRAPH_MAX_NODES)
            )
        ).all()
    )
    source_ids = sorted(
        {source_id for node in signal_nodes for source_id in node.suggested_source_ids},
        key=str,
    )
    sources = {
        row.site_url_id: row
        for row in (
            await session.scalars(
                select(SiteLinkGraphNode).where(
                    SiteLinkGraphNode.workspace_id == workspace_id,
                    SiteLinkGraphNode.snapshot_id == snapshot.id,
                    SiteLinkGraphNode.site_url_id.in_(source_ids),
                )
            )
        ).all()
    }
    return _hits_for_nodes(snapshot, signal_nodes, sources)


__all__ = ["load_link_graph_hits"]
