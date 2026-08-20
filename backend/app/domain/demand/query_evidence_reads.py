"""Workspace-scoped persisted reads for query evidence."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.demand import (
    ERROR_QUERY_EVIDENCE_CURSOR_INVALID,
    QUERY_EVIDENCE_MAX_LIMIT,
)
from app.domain.demand.query_classification import normalize_query
from app.models.demand import QueryEvidenceRow, QueryEvidenceSnapshot


class QueryEvidenceCursorError(ValueError):
    """The cursor is malformed or does not match the stable row key."""


@dataclass(frozen=True)
class QueryEvidencePage:
    rows: list[QueryEvidenceRow]
    next_cursor: str | None


async def latest_query_evidence_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> QueryEvidenceSnapshot | None:
    return await session.scalar(
        select(QueryEvidenceSnapshot)
        .where(
            QueryEvidenceSnapshot.workspace_id == workspace_id,
            QueryEvidenceSnapshot.project_id == project_id,
            QueryEvidenceSnapshot.window_start == window_start,
            QueryEvidenceSnapshot.window_end == window_end,
        )
        .order_by(
            QueryEvidenceSnapshot.created_at.desc(), QueryEvidenceSnapshot.id.desc()
        )
        .limit(1)
    )


def _encode_cursor(row: QueryEvidenceRow, snapshot_id: uuid.UUID) -> str:
    raw = json.dumps(
        [str(snapshot_id), row.date.isoformat(), str(row.id)], separators=(",", ":")
    )
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(value: str) -> tuple[uuid.UUID, date, uuid.UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError
        return (
            uuid.UUID(str(raw[0])),
            date.fromisoformat(str(raw[1])),
            uuid.UUID(str(raw[2])),
        )
    except (ValueError, TypeError, json.JSONDecodeError, binascii.Error) as exc:
        raise QueryEvidenceCursorError(ERROR_QUERY_EVIDENCE_CURSOR_INVALID) from exc


async def list_query_evidence(
    session: AsyncSession,
    *,
    snapshot: QueryEvidenceSnapshot,
    limit: int,
    cursor: str | None = None,
    query: str | None = None,
    site_url_id: uuid.UUID | None = None,
    resolution_outcome: str | None = None,
) -> QueryEvidencePage:
    capped = min(max(limit, 1), QUERY_EVIDENCE_MAX_LIMIT)
    statement = select(QueryEvidenceRow).where(
        QueryEvidenceRow.workspace_id == snapshot.workspace_id,
        QueryEvidenceRow.project_id == snapshot.project_id,
        QueryEvidenceRow.snapshot_id == snapshot.id,
    )
    if query:
        statement = statement.where(
            QueryEvidenceRow.normalized_query == normalize_query(query)
        )
    if site_url_id:
        statement = statement.where(QueryEvidenceRow.site_url_id == site_url_id)
    if resolution_outcome:
        statement = statement.where(
            QueryEvidenceRow.resolution_outcome == resolution_outcome
        )
    if cursor:
        cursor_snapshot_id, cursor_date, cursor_id = _decode_cursor(cursor)
        if cursor_snapshot_id != snapshot.id:
            raise QueryEvidenceCursorError(ERROR_QUERY_EVIDENCE_CURSOR_INVALID)
        statement = statement.where(
            or_(
                QueryEvidenceRow.date > cursor_date,
                and_(
                    QueryEvidenceRow.date == cursor_date,
                    QueryEvidenceRow.id > cursor_id,
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                statement.order_by(QueryEvidenceRow.date, QueryEvidenceRow.id).limit(
                    capped + 1
                )
            )
        ).all()
    )
    return QueryEvidencePage(
        rows=rows[:capped],
        next_cursor=(
            _encode_cursor(rows[capped - 1], snapshot.id)
            if len(rows) > capped
            else None
        ),
    )


async def query_evidence_resolution_counts(
    session: AsyncSession, *, snapshot: QueryEvidenceSnapshot
) -> dict[str, int]:
    rows = await session.execute(
        select(QueryEvidenceRow.resolution_outcome, func.count())
        .where(
            QueryEvidenceRow.workspace_id == snapshot.workspace_id,
            QueryEvidenceRow.project_id == snapshot.project_id,
            QueryEvidenceRow.snapshot_id == snapshot.id,
        )
        .group_by(QueryEvidenceRow.resolution_outcome)
    )
    return {str(outcome): int(count) for outcome, count in rows.all()}
