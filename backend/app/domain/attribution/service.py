# Commerce attribution read service (WS-B): persisted projections only.
#
# ``get_commerce_attribution`` serves the persisted ``AttributionSnapshot``
# for the requested (window, granularity) — or the project's latest
# snapshot at the granularity when the window is omitted. NO provider is
# ever called and NOTHING is recomputed at read time (invariant 7): an
# absent snapshot yields the empty contract (empty method sections, the
# permanently ``not_offered`` statistical namespace), never a 404 and
# never a fabricated zero.
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.core.config.analytics import (
    AI_REFERRAL_RULE_VERSION,
    AI_SOURCES,
    ANALYTICS_DEFAULT_GRANULARITY,
    ANALYTICS_MAX_WINDOW_DAYS,
    ANALYTICS_SNAPSHOT_GRANULARITIES,
    ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
)
from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_FORMULA_VERSION,
    ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC,
    ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL,
    ATTRIBUTION_ORDER_STATE_ATTRIBUTED,
    ATTRIBUTION_ORDER_STATE_UNATTRIBUTED,
    ATTRIBUTION_ORDER_STATES,
    ATTRIBUTION_ORDERS_PAGE_SIZE,
    ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED,
)
from app.core.config.integrations_contracts import (
    MAPPING_STATUS_ACTIVE,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.analytics.enqueue import enqueue_attribution_recompute
from app.domain.attribution.schemas import (
    AttributionCoverage,
    AttributionDeterministic,
    AttributionMetrics,
    AttributionOrderLineItem,
    AttributionOrderRow,
    AttributionOrdersPage,
    AttributionRecomputeResponse,
    AttributionStatistical,
    CommerceAttributionResponse,
)
from app.domain.commerce.orders import order_fact_not_superseded
from app.domain.traffic.service import decode_keyset_cursor, encode_keyset_cursor
from app.models.analytics import AnalyticsTask
from app.models.attribution import AttributionLink, AttributionSnapshot
from app.models.commerce import OrderFact
from app.models.integrations import IntegrationPropertyMapping, IntegrationSyncRun


class AttributionQueryError(ValueError):
    """Raised for an invalid attribution query (bad granularity/window).

    The API layer maps this to HTTP 422; it is never a not-found
    condition. Mirrors the ``TrafficQueryError`` contract (one owner per
    surface).
    """


class AttributionCursorError(ValueError):
    """Raised when an order-page cursor is malformed or filter-mismatched."""


class AttributionRecomputeNotFoundError(LookupError):
    """Raised when a scoped recompute task does not exist."""


def _validate_granularity(granularity: str) -> str:
    granularity = granularity or ANALYTICS_DEFAULT_GRANULARITY
    if granularity not in ANALYTICS_SNAPSHOT_GRANULARITIES:
        raise AttributionQueryError(f"unknown granularity: {granularity!r}")
    return granularity


def _validate_window(from_date: date | None, to_date: date | None) -> None:
    """The from/to contract: both-or-neither, ordered, within the max span."""
    if (from_date is None) != (to_date is None):
        raise AttributionQueryError("'from' and 'to' must be supplied together")
    if from_date is None or to_date is None:
        return
    if to_date < from_date:
        raise AttributionQueryError("'to' must not be before 'from'")
    if (to_date - from_date).days + 1 > ANALYTICS_MAX_WINDOW_DAYS:
        raise AttributionQueryError(
            f"window exceeds ANALYTICS_MAX_WINDOW_DAYS ({ANALYTICS_MAX_WINDOW_DAYS})"
        )


async def _load_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> AttributionSnapshot | None:
    """The persisted snapshot serving the request, or ``None``.

    An explicit ``from``/``to`` selects the snapshot persisted for exactly
    that window (read endpoints serve persisted snapshot windows only —
    arbitrary custom windows are never recomputed). Without a window the
    project's LATEST persisted snapshot at the granularity is served (the
    A9/A10 precedent).
    """
    stmt = (
        select(AttributionSnapshot)
        .where(AttributionSnapshot.workspace_id == workspace_id)
        .where(AttributionSnapshot.project_id == project_id)
        .where(AttributionSnapshot.granularity == granularity)
    )
    if from_date is not None and to_date is not None:
        stmt = stmt.where(AttributionSnapshot.window_start == from_date)
        stmt = stmt.where(AttributionSnapshot.window_end == to_date)
    else:
        stmt = stmt.order_by(
            AttributionSnapshot.window_end.desc(),
            AttributionSnapshot.window_start.desc(),
        )
    return await session.scalar(stmt.limit(1))


def _empty_metrics() -> AttributionMetrics:
    """The metrics document of an absent snapshot: empty method sections."""
    return AttributionMetrics(
        deterministic=AttributionDeterministic(
            a1=[],
            a2=[],
            delta=[],
            unattributed=[],
            coverage=AttributionCoverage(
                total_latest_orders=0,
                orders_with_evidence=0,
                linked_ai_orders=0,
                unattributed_orders=0,
                evidence_coverage_rate=None,
                attributed_share=None,
                window_start="",
                window_end="",
            ),
        ),
        statistical=AttributionStatistical(
            state=ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED,
            sample_size=None,
            allocations=[],
        ),
    )


def _uuid_list(raw: object) -> list[uuid.UUID]:
    """Parse a persisted JSONB id array; malformed entries are skipped."""
    ids: list[uuid.UUID] = []
    for value in raw if isinstance(raw, list) else []:
        try:
            ids.append(uuid.UUID(str(value)))
        except ValueError:
            continue
    return ids


def _empty_attribution_response(
    *,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    granularity: str,
) -> CommerceAttributionResponse:
    return CommerceAttributionResponse(
        project_id=project_id,
        window_start=from_date.isoformat() if from_date is not None else "",
        window_end=to_date.isoformat() if to_date is not None else "",
        granularity=granularity,
        metrics=_empty_metrics(),
        source_link_ids=[],
        source_order_fact_ids=[],
        source_metric_row_ids=[],
        source_snapshot_ids=[],
        formula_version=ATTRIBUTION_FORMULA_VERSION,
        analyzer_version=ATTRIBUTION_ANALYZER_VERSION,
        created_at=None,
    )


def _snapshot_deterministic(snapshot: AttributionSnapshot) -> AttributionDeterministic:
    raw = (snapshot.metrics or {}).get(
        ATTRIBUTION_METRICS_NAMESPACE_DETERMINISTIC
    ) or {}
    return AttributionDeterministic(
        a1=raw.get("a1") or [],
        a2=raw.get("a2") or [],
        delta=raw.get("delta") or [],
        unattributed=raw.get("unattributed") or [],
        coverage=raw.get("coverage")
        or {
            "total_latest_orders": 0,
            "orders_with_evidence": 0,
            "linked_ai_orders": 0,
            "unattributed_orders": 0,
            "evidence_coverage_rate": None,
            "attributed_share": None,
            "window_start": snapshot.window_start.isoformat(),
            "window_end": snapshot.window_end.isoformat(),
        },
    )


def _snapshot_statistical(snapshot: AttributionSnapshot) -> AttributionStatistical:
    raw = (snapshot.metrics or {}).get(ATTRIBUTION_METRICS_NAMESPACE_STATISTICAL) or {}
    return AttributionStatistical(
        state=raw.get("state", ATTRIBUTION_STATISTICAL_STATE_NOT_OFFERED),
        sample_size=raw.get("sample_size"),
        allocations=raw.get("allocations") or [],
    )


def _snapshot_response(snapshot: AttributionSnapshot) -> CommerceAttributionResponse:
    return CommerceAttributionResponse(
        project_id=snapshot.project_id,
        window_start=snapshot.window_start.isoformat(),
        window_end=snapshot.window_end.isoformat(),
        granularity=snapshot.granularity,
        metrics=AttributionMetrics(
            deterministic=_snapshot_deterministic(snapshot),
            statistical=_snapshot_statistical(snapshot),
        ),
        source_link_ids=_uuid_list(snapshot.source_link_ids),
        source_order_fact_ids=_uuid_list(snapshot.source_order_fact_ids),
        source_metric_row_ids=_uuid_list(snapshot.source_metric_row_ids),
        source_snapshot_ids=_uuid_list(snapshot.source_snapshot_ids),
        formula_version=snapshot.formula_version,
        analyzer_version=snapshot.analyzer_version,
        created_at=(
            snapshot.created_at.isoformat() if snapshot.created_at is not None else None
        ),
    )


async def get_commerce_attribution(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    granularity: str = ANALYTICS_DEFAULT_GRANULARITY,
) -> CommerceAttributionResponse:
    """Serve the Commerce attribution projection from the persisted snapshot.

    The persisted ``metrics`` JSONB already carries the exact served
    document (the refresh executor writes it in the served shape); this
    validates it into the strict response model. An absent snapshot yields
    the empty contract (never a recomputation — invariant 7).
    """
    granularity = _validate_granularity(granularity)
    _validate_window(from_date, to_date)
    snapshot = await _load_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        granularity=granularity,
    )
    if snapshot is None:
        return _empty_attribution_response(
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
            granularity=granularity,
        )
    return _snapshot_response(snapshot)


def _order_filters(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source: str | None,
    attribution_state: str | None,
    from_date: date | None,
    to_date: date | None,
) -> dict[str, object]:
    return {
        "workspace_id": str(workspace_id),
        "project_id": str(project_id),
        "source": source,
        "attribution_state": attribution_state,
        "from": from_date.isoformat() if from_date else None,
        "to": to_date.isoformat() if to_date else None,
    }


def _validate_order_filters(source: str | None, attribution_state: str | None) -> None:
    if source is not None and source not in AI_SOURCES:
        raise AttributionQueryError(f"unknown source: {source!r}")
    if (
        attribution_state is not None
        and attribution_state not in ATTRIBUTION_ORDER_STATES
    ):
        raise AttributionQueryError(f"unknown attribution_state: {attribution_state!r}")
    if source is not None and attribution_state == ATTRIBUTION_ORDER_STATE_UNATTRIBUTED:
        raise AttributionQueryError("source cannot filter unattributed orders")


def _decode_order_cursor(
    cursor: str | None, *, filters: dict[str, object]
) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    try:
        occurred_raw, id_raw = decode_keyset_cursor(
            cursor, scope="commerce-attribution-orders", filters=filters
        )
        occurred_at = datetime.fromisoformat(occurred_raw)
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.replace(tzinfo=UTC)
        return occurred_at, uuid.UUID(id_raw)
    except (ValueError, TypeError) as exc:
        raise AttributionCursorError("invalid attribution orders cursor") from exc


def _orders_statement(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source: str | None,
    attribution_state: str | None,
    from_date: date | None,
    to_date: date | None,
    keyset: tuple[datetime, uuid.UUID] | None,
) -> Select:
    current_link = and_(
        AttributionLink.order_fact_id == OrderFact.id,
        AttributionLink.workspace_id == workspace_id,
        AttributionLink.rule_version == AI_REFERRAL_RULE_VERSION,
        AttributionLink.analyzer_version == ATTRIBUTION_ANALYZER_VERSION,
    )
    stmt = (
        select(OrderFact, AttributionLink)
        .outerjoin(AttributionLink, current_link)
        .where(OrderFact.workspace_id == workspace_id)
        .where(OrderFact.project_id == project_id)
        .where(order_fact_not_superseded())
    )
    if from_date is not None and to_date is not None:
        start = datetime.combine(from_date, time.min, tzinfo=UTC)
        end = datetime.combine(to_date + timedelta(days=1), time.min, tzinfo=UTC)
        stmt = stmt.where(OrderFact.occurred_at >= start, OrderFact.occurred_at < end)
    if source is not None:
        stmt = stmt.where(AttributionLink.evidence_refs["ai_source"].astext == source)
    if attribution_state == ATTRIBUTION_ORDER_STATE_ATTRIBUTED:
        stmt = stmt.where(AttributionLink.id.is_not(None))
    elif attribution_state == ATTRIBUTION_ORDER_STATE_UNATTRIBUTED:
        stmt = stmt.where(AttributionLink.id.is_(None))
    if keyset is not None:
        occurred_at, fact_id = keyset
        stmt = stmt.where(
            or_(
                OrderFact.occurred_at < occurred_at,
                and_(OrderFact.occurred_at == occurred_at, OrderFact.id < fact_id),
            )
        )
    return stmt


def _order_row(fact: OrderFact, link: AttributionLink | None) -> AttributionOrderRow:
    evidence = link.evidence_refs if link is not None else {}
    return AttributionOrderRow(
        fact_id=fact.id,
        occurred_at=fact.occurred_at.isoformat(),
        line_items=[
            AttributionOrderLineItem.model_validate(item)
            for item in (fact.line_items or [])
        ],
        amount=float(fact.total_amount),
        currency=fact.currency,
        attribution_state=(
            ATTRIBUTION_ORDER_STATE_ATTRIBUTED
            if link is not None
            else ATTRIBUTION_ORDER_STATE_UNATTRIBUTED
        ),
        method=link.method if link is not None else None,
        ai_source=str(evidence.get("ai_source")) if link is not None else None,
        confidence=link.confidence if link is not None else None,
        rule_version=link.rule_version if link is not None else None,
    )


async def get_attribution_orders(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source: str | None = None,
    attribution_state: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    cursor: str | None = None,
) -> AttributionOrdersPage:
    """Keyset-page latest safe order facts joined to current-version links."""
    _validate_window(from_date, to_date)
    _validate_order_filters(source, attribution_state)
    filters = _order_filters(
        workspace_id=workspace_id,
        project_id=project_id,
        source=source,
        attribution_state=attribution_state,
        from_date=from_date,
        to_date=to_date,
    )
    stmt = _orders_statement(
        workspace_id=workspace_id,
        project_id=project_id,
        source=source,
        attribution_state=attribution_state,
        from_date=from_date,
        to_date=to_date,
        keyset=_decode_order_cursor(cursor, filters=filters),
    )
    rows = (
        await session.execute(
            stmt.order_by(OrderFact.occurred_at.desc(), OrderFact.id.desc()).limit(
                ATTRIBUTION_ORDERS_PAGE_SIZE + 1
            )
        )
    ).all()
    next_cursor = None
    if len(rows) > ATTRIBUTION_ORDERS_PAGE_SIZE:
        rows = rows[:ATTRIBUTION_ORDERS_PAGE_SIZE]
        last_fact = rows[-1][0]
        next_cursor = encode_keyset_cursor(
            scope="commerce-attribution-orders",
            filters=filters,
            sort_values=[last_fact.occurred_at.isoformat(), str(last_fact.id)],
        )

    items = [_order_row(fact, link) for fact, link in rows]
    return AttributionOrdersPage(items=items, next_cursor=next_cursor)


def _recompute_response(task: AnalyticsTask) -> AttributionRecomputeResponse:
    if task.project_id is None:
        raise ValueError("an attribution snapshot task must be project-scoped")
    return AttributionRecomputeResponse(
        task_id=task.id,
        project_id=task.project_id,
        status=task.status,
        error_code=task.error_code,
        updated_at=task.updated_at.isoformat(),
        completed_at=(
            task.completed_at.isoformat() if task.completed_at is not None else None
        ),
    )


async def enqueue_commerce_attribution_recompute(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
) -> AttributionRecomputeResponse:
    """Enqueue a persisted-only snapshot rebuild and commit its queue row."""
    _validate_window(from_date, to_date)
    if from_date is None or to_date is None:
        latest_window = (
            await session.execute(
                select(
                    IntegrationSyncRun.window_start,
                    IntegrationSyncRun.window_end,
                )
                .join(
                    IntegrationPropertyMapping,
                    IntegrationPropertyMapping.connection_id
                    == IntegrationSyncRun.connection_id,
                )
                .where(IntegrationPropertyMapping.workspace_id == workspace_id)
                .where(IntegrationPropertyMapping.project_id == project_id)
                .where(IntegrationPropertyMapping.status == MAPPING_STATUS_ACTIVE)
                .where(IntegrationSyncRun.workspace_id == workspace_id)
                .where(IntegrationSyncRun.status == TASK_STATUS_SUCCEEDED)
                .order_by(
                    IntegrationSyncRun.window_end.desc(),
                    IntegrationSyncRun.window_start.desc(),
                    IntegrationSyncRun.created_at.desc(),
                )
                .limit(1)
            )
        ).one_or_none()
        if latest_window is None:
            raise AttributionQueryError("no completed sync window is available")
        from_date, to_date = latest_window

    task_id = await enqueue_attribution_recompute(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=from_date,
        window_end=to_date,
    )
    await session.commit()
    task = await session.get(AnalyticsTask, task_id)
    if task is None:
        raise RuntimeError("attribution recompute task disappeared after commit")
    return _recompute_response(task)


async def get_attribution_recompute(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    task_id: uuid.UUID,
) -> AttributionRecomputeResponse:
    task = await session.scalar(
        select(AnalyticsTask)
        .where(AnalyticsTask.id == task_id)
        .where(AnalyticsTask.workspace_id == workspace_id)
        .where(AnalyticsTask.project_id == project_id)
        .where(AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT)
    )
    if task is None:
        raise AttributionRecomputeNotFoundError(str(task_id))
    return _recompute_response(task)
