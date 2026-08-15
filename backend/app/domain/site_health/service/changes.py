"""Workspace-authorized reads of persisted crawl change projections."""

from __future__ import annotations

import uuid

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_change_intel import (
    CHANGE_ANALYZER_VERSION,
    CHANGE_DEFAULT_LIMIT,
    CHANGE_MAX_LIMIT,
    CHANGE_STATE_UNAVAILABLE,
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
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health import SiteCrawl

_CURSOR_SCOPE = "site-change-observations"


class InvalidChangeSelectionError(Exception):
    """An exact-pair request omitted one side of the pair."""


async def _validate_crawl(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID,
) -> None:
    exists = await session.scalar(
        select(SiteCrawl.id).where(
            SiteCrawl.id == crawl_id,
            SiteCrawl.workspace_id == workspace_id,
            SiteCrawl.project_id == project_id,
        )
    )
    if exists is None:
        raise SiteHealthNotFoundError("Crawl not found")


async def _resolve_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_a_id: uuid.UUID | None,
    crawl_b_id: uuid.UUID | None,
) -> SiteChangeSnapshot | None:
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    if (crawl_a_id is None) != (crawl_b_id is None):
        raise InvalidChangeSelectionError(
            "crawl_a_id and crawl_b_id must be supplied together"
        )
    statement = select(SiteChangeSnapshot).where(
        SiteChangeSnapshot.workspace_id == workspace_id,
        SiteChangeSnapshot.project_id == project_id,
    )
    if crawl_a_id is not None and crawl_b_id is not None:
        await _validate_crawl(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            crawl_id=crawl_a_id,
        )
        await _validate_crawl(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            crawl_id=crawl_b_id,
        )
        statement = statement.where(
            SiteChangeSnapshot.crawl_a_id == crawl_a_id,
            SiteChangeSnapshot.crawl_b_id == crawl_b_id,
        )
    return await session.scalar(
        statement.order_by(
            SiteChangeSnapshot.created_at.desc(), SiteChangeSnapshot.id.desc()
        ).limit(1)
    )


def _summary(snapshot: SiteChangeSnapshot | None) -> dict:
    if snapshot is None:
        return {
            "state": CHANGE_STATE_UNAVAILABLE,
            "reason_code": "no_persisted_change_snapshot",
            "snapshot_id": None,
            "crawl_a_id": None,
            "crawl_b_id": None,
            "complete_pair": False,
            "analyzer_version": CHANGE_ANALYZER_VERSION,
            "page_analyzer_version": "",
            "extractor_version": "",
            "source_analysis_ids": [],
            "coverage": {},
            "summary": {},
            "limitations": ["No persisted crawl comparison is available."],
            "created_at": None,
        }
    return {
        "state": snapshot.state,
        "reason_code": snapshot.reason_code,
        "snapshot_id": snapshot.id,
        "crawl_a_id": snapshot.crawl_a_id,
        "crawl_b_id": snapshot.crawl_b_id,
        "complete_pair": snapshot.complete_pair,
        "analyzer_version": snapshot.analyzer_version,
        "page_analyzer_version": snapshot.page_analyzer_version,
        "extractor_version": snapshot.extractor_version,
        "source_analysis_ids": snapshot.source_analysis_ids,
        "coverage": snapshot.coverage,
        "summary": snapshot.summary,
        "limitations": snapshot.limitations,
        "created_at": snapshot.created_at.isoformat(),
    }


async def get_changes_summary(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_a_id: uuid.UUID | None = None,
    crawl_b_id: uuid.UUID | None = None,
) -> dict:
    snapshot = await _resolve_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_a_id=crawl_a_id,
        crawl_b_id=crawl_b_id,
    )
    return _summary(snapshot)


def _item(row: SiteChangeObservation) -> dict:
    return {
        "id": row.id,
        "site_url_id": row.site_url_id,
        "normalized_url": row.normalized_url,
        "field": row.field,
        "change_class": row.change_class,
        "before_value": row.before_value,
        "after_value": row.after_value,
        "source_analysis_a_id": row.source_analysis_a_id,
        "source_analysis_b_id": row.source_analysis_b_id,
        "source_artifact_a_id": row.source_artifact_a_id,
        "source_artifact_b_id": row.source_artifact_b_id,
        "source_evaluation_a_id": row.source_evaluation_a_id,
        "source_evaluation_b_id": row.source_evaluation_b_id,
        "expected": row.expected,
        "implementation_event_id": row.implementation_event_id,
        "created_at": row.created_at.isoformat(),
    }


async def list_changes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_a_id: uuid.UUID | None = None,
    crawl_b_id: uuid.UUID | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    snapshot = await _resolve_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_a_id=crawl_a_id,
        crawl_b_id=crawl_b_id,
    )
    summary = _summary(snapshot)
    if snapshot is None:
        return {**summary, "items": [], "next_cursor": None}
    filters = {"snapshot_id": str(snapshot.id)}
    statement = select(SiteChangeObservation).where(
        SiteChangeObservation.workspace_id == workspace_id,
        SiteChangeObservation.snapshot_id == snapshot.id,
    )
    if cursor:
        try:
            url, field, row_id = decode_keyset_cursor(
                cursor, scope=_CURSOR_SCOPE, filters=filters
            )
            parsed_id = uuid.UUID(row_id)
        except (CursorScopeError, ValueError) as exc:
            raise InvalidCursorError(str(exc)) from exc
        statement = statement.where(
            or_(
                SiteChangeObservation.normalized_url > url,
                and_(
                    SiteChangeObservation.normalized_url == url,
                    SiteChangeObservation.field > field,
                ),
                and_(
                    SiteChangeObservation.normalized_url == url,
                    SiteChangeObservation.field == field,
                    SiteChangeObservation.id > parsed_id,
                ),
            )
        )
    page_limit = max(1, min(limit or CHANGE_DEFAULT_LIMIT, CHANGE_MAX_LIMIT))
    rows = list(
        (
            await session.scalars(
                statement.order_by(
                    SiteChangeObservation.normalized_url,
                    SiteChangeObservation.field,
                    SiteChangeObservation.id,
                ).limit(page_limit + 1)
            )
        ).all()
    )
    items = rows[:page_limit]
    next_cursor = None
    if len(rows) > page_limit:
        last = items[-1]
        next_cursor = encode_keyset_cursor(
            scope=_CURSOR_SCOPE,
            filters=filters,
            sort_values=[last.normalized_url, last.field, last.id],
        )
    return {
        **summary,
        "items": [_item(row) for row in items],
        "next_cursor": next_cursor,
    }


async def get_change(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    observation_id: uuid.UUID,
) -> dict:
    await _load_project(session, workspace_id=workspace_id, project_id=project_id)
    row = await session.scalar(
        select(SiteChangeObservation)
        .join(
            SiteChangeSnapshot,
            SiteChangeSnapshot.id == SiteChangeObservation.snapshot_id,
        )
        .where(
            SiteChangeObservation.id == observation_id,
            SiteChangeObservation.workspace_id == workspace_id,
            SiteChangeSnapshot.project_id == project_id,
        )
    )
    if row is None:
        raise SiteHealthNotFoundError("Change observation not found")
    return _item(row)


__all__ = [
    "InvalidChangeSelectionError",
    "get_change",
    "get_changes_summary",
    "list_changes",
]
