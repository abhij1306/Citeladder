"""Validation and scalar projection helpers for persisted traffic reads."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.traffic import (
    TRAFFIC_DEFAULT_GRANULARITY,
    TRAFFIC_DEFAULT_SORT,
    TRAFFIC_FORMULA_VERSION,
    TRAFFIC_MAX_WINDOW_DAYS,
    TRAFFIC_NORMALIZATION_VERSION,
    TRAFFIC_SNAPSHOT_GRANULARITIES,
)
from app.domain.site_health.normalization import decode_keyset_cursor
from app.domain.traffic.schemas import (
    TrafficDashboardResponse,
    TrafficSeries,
    TrafficTotals,
)
from app.models.traffic import TrafficSnapshot


class TrafficQueryError(ValueError):
    """An invalid traffic granularity, window, or sort."""


class TrafficCursorError(ValueError):
    """A traffic table cursor failed decode or scope verification."""


def validate_window(from_date: date | None, to_date: date | None) -> None:
    if (from_date is None) != (to_date is None):
        raise TrafficQueryError("'from' and 'to' must be supplied together")
    if from_date is None or to_date is None:
        return
    if to_date < from_date:
        raise TrafficQueryError("'to' must not be before 'from'")
    if (to_date - from_date).days + 1 > TRAFFIC_MAX_WINDOW_DAYS:
        raise TrafficQueryError(
            f"window exceeds TRAFFIC_MAX_WINDOW_DAYS ({TRAFFIC_MAX_WINDOW_DAYS})"
        )


def validate_granularity(granularity: str) -> str:
    effective = granularity or TRAFFIC_DEFAULT_GRANULARITY
    if effective not in TRAFFIC_SNAPSHOT_GRANULARITIES:
        raise TrafficQueryError(f"unknown granularity: {effective!r}")
    return effective


def parse_sort(sort: str | None, *, whitelist: frozenset[str]) -> tuple[str, bool]:
    effective = sort if sort else TRAFFIC_DEFAULT_SORT
    descending = effective.startswith("-")
    key = effective[1:] if descending else effective
    if key not in whitelist:
        raise TrafficQueryError(f"unknown traffic sort: {sort!r}")
    return key, descending


def int_or_zero(value: object) -> int:
    return int(value) if isinstance(value, (int, float)) else 0


def int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, (int, float)) else None


def float_or_none(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def totals(raw: object) -> TrafficTotals:
    metrics = raw if isinstance(raw, dict) else {}
    return TrafficTotals(
        impressions=int_or_zero(metrics.get("impressions")),
        clicks=int_or_zero(metrics.get("clicks")),
        ctr=float_or_none(metrics.get("ctr")),
        position=float_or_none(metrics.get("position")),
        sessions=int_or_none(metrics.get("sessions")),
        conversions=int_or_none(metrics.get("conversions")),
    )


def empty_dashboard(
    *,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> TrafficDashboardResponse:
    return TrafficDashboardResponse(
        project_id=project_id,
        evidence_state="not_run",
        window_start=from_date.isoformat() if from_date is not None else "",
        window_end=to_date.isoformat() if to_date is not None else "",
        granularity=granularity,
        totals=TrafficTotals(
            impressions=0,
            clicks=0,
            ctr=None,
            position=None,
            sessions=None,
            conversions=None,
        ),
        series=TrafficSeries(
            impressions=[],
            clicks=[],
            ctr=[],
            position=[],
            sessions=[],
            conversions=[],
        ),
        formula_version=TRAFFIC_FORMULA_VERSION,
        normalization_version=TRAFFIC_NORMALIZATION_VERSION,
    )


def table_filters(
    *,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    sort: str,
) -> dict[str, object]:
    return {
        "project_id": str(project_id),
        "from": from_date.isoformat() if from_date is not None else "",
        "to": to_date.isoformat() if to_date is not None else "",
        "sort": sort,
    }


def decode_table_cursor(
    cursor: str, *, scope: str, filters: dict[str, object]
) -> tuple[float | None, uuid.UUID]:
    try:
        value_raw, id_raw = decode_keyset_cursor(cursor, scope=scope, filters=filters)
        return (None if value_raw == "" else float(value_raw)), uuid.UUID(id_raw)
    except ValueError as exc:
        raise TrafficCursorError(str(exc)) from exc


async def load_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> TrafficSnapshot | None:
    stmt = (
        select(TrafficSnapshot)
        .where(TrafficSnapshot.workspace_id == workspace_id)
        .where(TrafficSnapshot.project_id == project_id)
        .where(TrafficSnapshot.granularity == granularity)
    )
    if from_date is not None and to_date is not None:
        stmt = stmt.where(
            TrafficSnapshot.window_start == from_date,
            TrafficSnapshot.window_end == to_date,
        )
    else:
        stmt = stmt.order_by(
            TrafficSnapshot.window_end.desc(),
            TrafficSnapshot.window_start.desc(),
            TrafficSnapshot.id.desc(),
        )
    return await session.scalar(stmt.limit(1))
