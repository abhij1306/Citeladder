"""Workspace-authorized persisted link-graph read projections."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_link_graph import (
    LINK_GRAPH_ANALYZER_VERSION,
    LINK_GRAPH_LIST_DEFAULT_LIMIT,
    LINK_GRAPH_LIST_MAX_LIMIT,
    LINK_GRAPH_STATE_UNAVAILABLE,
)
from app.domain.site_health.normalization import (
    CursorScopeError,
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.domain.site_health.service.common import (
    InvalidCursorError,
    SiteHealthNotFoundError,
    _load_project,
)
from app.models.site_health import (
    SiteCrawl,
    SiteLinkGraphEdge,
    SiteLinkGraphNode,
    SiteLinkGraphSnapshot,
)

_NODE_SCOPE = "site-link-graph-nodes"
_EDGE_SCOPE = "site-link-graph-edges"


def _limit(value: int | None) -> int:
    if value is None:
        return LINK_GRAPH_LIST_DEFAULT_LIMIT
    return max(1, min(value, LINK_GRAPH_LIST_MAX_LIMIT))


async def _resolve_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None,
) -> SiteLinkGraphSnapshot | None:
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    if crawl_id is not None:
        crawl = await session.scalar(
            select(SiteCrawl.id).where(
                SiteCrawl.id == crawl_id,
                SiteCrawl.workspace_id == workspace_id,
                SiteCrawl.project_id == project_id,
            )
        )
        if crawl is None:
            raise SiteHealthNotFoundError("Crawl not found")
    statement = select(SiteLinkGraphSnapshot).where(
        SiteLinkGraphSnapshot.workspace_id == workspace_id,
        SiteLinkGraphSnapshot.project_id == project_id,
    )
    if crawl_id is not None:
        statement = statement.where(SiteLinkGraphSnapshot.crawl_id == crawl_id)
    return await session.scalar(
        statement.order_by(
            SiteLinkGraphSnapshot.created_at.desc(),
            SiteLinkGraphSnapshot.id.desc(),
        ).limit(1)
    )


def _unavailable() -> dict:
    return {
        "state": LINK_GRAPH_STATE_UNAVAILABLE,
        "snapshot_id": None,
        "crawl_id": None,
        "analyzer_version": LINK_GRAPH_ANALYZER_VERSION,
        "page_analyzer_version": "",
        "extractor_version": "",
        "source_analysis_ids": [],
        "coverage": {},
        "limitations": ["No persisted link graph is available for this selection."],
        "summary": {},
        "created_at": None,
    }


async def get_link_graph(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    snapshot = await _resolve_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if snapshot is None:
        return _unavailable()
    return {
        "state": snapshot.state,
        "snapshot_id": snapshot.id,
        "crawl_id": snapshot.crawl_id,
        "root_site_url_id": snapshot.root_site_url_id,
        "analyzer_version": snapshot.analyzer_version,
        "page_analyzer_version": snapshot.page_analyzer_version,
        "extractor_version": snapshot.extractor_version,
        "source_analysis_ids": snapshot.source_analysis_ids,
        "coverage": snapshot.coverage,
        "limitations": snapshot.limitations,
        "summary": snapshot.summary,
        "created_at": snapshot.created_at.isoformat(),
    }


def _decode(cursor: str, *, scope: str, filters: dict) -> tuple[str, uuid.UUID]:
    try:
        first, row_id = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        return first, uuid.UUID(row_id)
    except (CursorScopeError, ValueError) as exc:
        raise InvalidCursorError(str(exc)) from exc


def _empty_page(snapshot: SiteLinkGraphSnapshot | None) -> dict:
    return {
        "state": snapshot.state if snapshot else LINK_GRAPH_STATE_UNAVAILABLE,
        "snapshot_id": snapshot.id if snapshot else None,
        "crawl_id": snapshot.crawl_id if snapshot else None,
        "items": [],
        "next_cursor": None,
        "limitations": (
            snapshot.limitations
            if snapshot
            else ["No persisted link graph is available for this selection."]
        ),
    }


def _node_item(row: SiteLinkGraphNode) -> dict:
    return {
        "id": row.id,
        "site_url_id": row.site_url_id,
        "source_analysis_id": row.source_analysis_id,
        "normalized_url": row.normalized_url,
        "title": row.title,
        "indexable": row.indexable,
        "pagerank": row.pagerank,
        "click_depth": row.click_depth,
        "followed_inbound_count": row.followed_inbound_count,
        "followed_outbound_count": row.followed_outbound_count,
        "near_orphan": row.near_orphan,
        "weak_authority": row.weak_authority,
        "over_linked": row.over_linked,
        "hub": row.hub,
        "suggested_source_ids": row.suggested_source_ids,
    }


def _edge_item(row: SiteLinkGraphEdge) -> dict:
    return {
        "id": row.id,
        "source_site_url_id": row.source_site_url_id,
        "target_site_url_id": row.target_site_url_id,
        "target_url": row.target_url,
        "followed": row.followed,
        "occurrence_count": row.occurrence_count,
        "followed_occurrence_count": row.followed_occurrence_count,
        "nofollow_occurrence_count": row.nofollow_occurrence_count,
        "anchor_texts": row.anchor_texts,
    }


async def list_link_graph_nodes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    snapshot = await _resolve_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if snapshot is None:
        return _empty_page(None)
    filters = {"snapshot_id": str(snapshot.id)}
    statement = select(SiteLinkGraphNode).where(
        SiteLinkGraphNode.workspace_id == workspace_id,
        SiteLinkGraphNode.snapshot_id == snapshot.id,
    )
    if cursor:
        url, row_id = _decode(cursor, scope=_NODE_SCOPE, filters=filters)
        statement = statement.where(
            or_(
                SiteLinkGraphNode.normalized_url > url,
                and_(
                    SiteLinkGraphNode.normalized_url == url,
                    SiteLinkGraphNode.id > row_id,
                ),
            )
        )
    page_limit = _limit(limit)
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    SiteLinkGraphNode.normalized_url, SiteLinkGraphNode.id
                ).limit(page_limit + 1)
            )
        ).all()
    )
    items = rows[:page_limit]
    next_cursor = None
    if len(rows) > page_limit:
        last = items[-1]
        next_cursor = encode_keyset_cursor(
            scope=_NODE_SCOPE,
            filters=filters,
            sort_values=[last.normalized_url, last.id],
        )
    return {
        **_empty_page(snapshot),
        "items": [_node_item(row) for row in items],
        "next_cursor": next_cursor,
    }


async def list_link_graph_edges(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    snapshot = await _resolve_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if snapshot is None:
        return _empty_page(None)
    filters = {"snapshot_id": str(snapshot.id)}
    statement = select(SiteLinkGraphEdge).where(
        SiteLinkGraphEdge.workspace_id == workspace_id,
        SiteLinkGraphEdge.snapshot_id == snapshot.id,
    )
    if cursor:
        key, row_id = _decode(cursor, scope=_EDGE_SCOPE, filters=filters)
        statement = statement.where(
            or_(
                SiteLinkGraphEdge.target_key > key,
                and_(
                    SiteLinkGraphEdge.target_key == key,
                    SiteLinkGraphEdge.id > row_id,
                ),
            )
        )
    page_limit = _limit(limit)
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    SiteLinkGraphEdge.target_key, SiteLinkGraphEdge.id
                ).limit(page_limit + 1)
            )
        ).all()
    )
    items = rows[:page_limit]
    next_cursor = None
    if len(rows) > page_limit:
        last = items[-1]
        next_cursor = encode_keyset_cursor(
            scope=_EDGE_SCOPE,
            filters=filters,
            sort_values=[last.target_key, last.id],
        )
    return {
        **_empty_page(snapshot),
        "items": [_edge_item(row) for row in items],
        "next_cursor": next_cursor,
    }


__all__ = ["get_link_graph", "list_link_graph_edges", "list_link_graph_nodes"]
