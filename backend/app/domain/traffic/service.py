"""Persist and read deterministic traffic projections.

Refreshes fold persisted integration metrics in bounded batches and replace
each snapshot's page/query rows atomically. Reads remain workspace-scoped and
serve only persisted projections; synchronization stays with integrations.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Float, and_, cast, delete, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.integrations_contracts import (
    GRANT_STATUS_CONNECTED,
    MAPPING_STATUS_ACTIVE,
)
from app.core.config.traffic import (
    TRAFFIC_CONSUMED_DATASETS,
    TRAFFIC_DEFAULT_GRANULARITY,
    TRAFFIC_FORMULA_VERSION,
    TRAFFIC_NORMALIZATION_VERSION,
    TRAFFIC_PAGE_SORT_WHITELIST,
    TRAFFIC_QUERY_SORT_WHITELIST,
    TRAFFIC_SNAPSHOT_GRANULARITIES,
    TRAFFIC_SYNC_PROVIDERS,
    TRAFFIC_TABLE_PAGE_SIZE,
)
from app.domain.analytics.enqueue import enqueue_demand_snapshot_refresh
from app.domain.analytics.schemas import metric_series_points
from app.domain.analytics.tasks import payload_window, raise_if_task_terminal
from app.domain.demand.projection import stable_hash
from app.domain.site_health.normalization import (
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.domain.traffic.projection import (
    TRAFFIC_SERIES_NAMES,
    SnapshotProjection,
    TrafficMetricRowInput,
    build_traffic_projection,
)
from app.domain.traffic.query_support import (
    TrafficCursorError,
    TrafficQueryError,
)
from app.domain.traffic.query_support import (
    decode_table_cursor as _decode_table_cursor,
)
from app.domain.traffic.query_support import (
    empty_dashboard as _empty_dashboard,
)
from app.domain.traffic.query_support import (
    float_or_none as _float_or_none,
)
from app.domain.traffic.query_support import (
    int_or_none as _int_or_none,
)
from app.domain.traffic.query_support import (
    int_or_zero as _int_or_zero,
)
from app.domain.traffic.query_support import load_snapshot as _load_snapshot
from app.domain.traffic.query_support import (
    parse_sort as _parse_sort,
)
from app.domain.traffic.query_support import (
    table_filters as _table_filters,
)
from app.domain.traffic.query_support import (
    totals as _totals,
)
from app.domain.traffic.query_support import (
    validate_granularity as _validate_granularity,
)
from app.domain.traffic.query_support import (
    validate_window as _validate_window,
)
from app.domain.traffic.schemas import (
    TrafficDashboardResponse,
    TrafficPageRow,
    TrafficPagesPage,
    TrafficQueriesPage,
    TrafficQueryRow,
    TrafficSeries,
)
from app.models.analytics import AnalyticsTask
from app.models.integrations import (
    IntegrationConnection,
    IntegrationMetricRow,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
)
from app.models.site_health import SiteHealthProfile, SiteUrl
from app.models.traffic import TrafficPageStat, TrafficQueryStat, TrafficSnapshot

# Bounded work per read batch: each batch is one cooperative-cancel boundary
# (the WRITE phase is a single transaction). Module constant (not config) —
# the same precedent as A6's ``_CLASSIFY_BATCH_SIZE``; tests monkeypatch it
# down to 1 to exercise the boundary per row.
_METRIC_ROW_BATCH_SIZE = 1000

__all__ = [
    "TrafficCursorError",
    "TrafficQueryError",
    "decode_keyset_cursor",
]


async def _raise_if_task_terminal(
    session_factory: async_sessionmaker[AsyncSession], task_id: uuid.UUID | None
) -> None:
    """Cooperative-cancel boundary check (invariant 9).

    Thin label adapter over the single owner (``domain/analytics/tasks.py``)
    so this executor's message names its own batch boundary and tests keep
    a module-local patch point. The refresh writes nothing before its
    single write transaction, so stopping here leaves no partial
    projection behind.
    """
    await raise_if_task_terminal(session_factory, task_id, boundary="metric-row batch")


async def _metric_row_batch(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    after_id: uuid.UUID | None,
    limit: int,
) -> list[IntegrationMetricRow]:
    """One keyset batch of the window's consumed-dataset metric rows.

    Workspace + project scoped (invariant 5); the id-keyset order keeps the
    scan stable across batches. Latest-``resync_seq`` selection is applied
    by the pure projection (one owner of the rule), not here.
    """
    stmt = (
        select(IntegrationMetricRow)
        .where(IntegrationMetricRow.workspace_id == workspace_id)
        .where(IntegrationMetricRow.project_id == project_id)
        .where(IntegrationMetricRow.dataset.in_(sorted(TRAFFIC_CONSUMED_DATASETS)))
        .where(IntegrationMetricRow.date >= window_start)
        .where(IntegrationMetricRow.date <= window_end)
        .order_by(IntegrationMetricRow.id.asc())
        .limit(limit)
    )
    if after_id is not None:
        stmt = stmt.where(IntegrationMetricRow.id > after_id)
    return list((await session.scalars(stmt)).all())


def _to_input(row: IntegrationMetricRow) -> TrafficMetricRowInput:
    return TrafficMetricRowInput(
        id=row.id,
        property_ref=row.property_ref,
        provider=row.provider,
        dataset=row.dataset,
        date=row.date,
        dimension_key=row.dimension_key,
        metrics=row.metrics,
        source_artifact_id=row.source_artifact_id,
        resync_seq=row.resync_seq,
        importer_version=row.importer_version,
    )


async def _upsert_snapshot(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    window_start: date,
    window_end: date,
    granularity: str,
    projection: SnapshotProjection,
) -> uuid.UUID:
    """The transactional upsert of the one current snapshot row.

    ``INSERT ... ON CONFLICT (project_id, window_start, window_end,
    granularity) DO UPDATE`` — concurrent refreshes serialize on the unique
    row and can never create a duplicate "current" snapshot (traffic.md
    section 3). The conflict target's workspace cannot drift (one project
    lives in one workspace), so only the projection payload + provenance +
    version stamps are updated.
    """
    stmt = (
        pg_insert(TrafficSnapshot)
        .values(
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
            granularity=granularity,
            metrics=projection.metrics,
            source_metric_row_ids=projection.source_metric_row_ids,
            source_artifact_ids=projection.source_artifact_ids,
            formula_version=TRAFFIC_FORMULA_VERSION,
            normalization_version=TRAFFIC_NORMALIZATION_VERSION,
        )
        .on_conflict_do_update(
            index_elements=[
                "project_id",
                "window_start",
                "window_end",
                "granularity",
            ],
            set_={
                "metrics": projection.metrics,
                "source_metric_row_ids": projection.source_metric_row_ids,
                "source_artifact_ids": projection.source_artifact_ids,
                "formula_version": TRAFFIC_FORMULA_VERSION,
                "normalization_version": TRAFFIC_NORMALIZATION_VERSION,
                "created_at": func.now(),
            },
        )
        .returning(TrafficSnapshot.id)
    )
    snapshot_id = await session.scalar(stmt)
    if snapshot_id is None:  # RETURNING always yields the upserted row's id
        raise RuntimeError("traffic snapshot upsert returned no id")
    return snapshot_id


async def _resolve_site_url_ids(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    url_hashes: list[str],
) -> dict[str, uuid.UUID]:
    """Map page url_hashes to crawled ``SiteUrl`` ids (unmatched -> absent).

    The page join resolves by ``(project_id, url_hash)`` —
    ``uq_site_url_project_hash`` (traffic.md section 5); an unmatched page
    keeps ``site_url_id NULL`` and stays a valid measured page.
    """
    if not url_hashes:
        return {}
    stmt = (
        select(SiteUrl.url_hash, SiteUrl.id)
        .where(SiteUrl.workspace_id == task.workspace_id)
        .where(SiteUrl.project_id == task.project_id)
        .where(SiteUrl.url_hash.in_(url_hashes))
    )
    return {
        url_hash: site_url_id
        for url_hash, site_url_id in (await session.execute(stmt)).all()
    }


async def _replace_page_stats(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    snapshot_id: uuid.UUID,
    projection: SnapshotProjection,
) -> None:
    """Delete-then-insert the snapshot's page stat rows (same tx)."""
    await session.execute(
        delete(TrafficPageStat).where(TrafficPageStat.snapshot_id == snapshot_id)
    )
    if not projection.pages:
        return
    site_url_ids = await _resolve_site_url_ids(
        session, task=task, url_hashes=[page.url_hash for page in projection.pages]
    )
    await session.execute(
        pg_insert(TrafficPageStat).values(
            [
                {
                    "workspace_id": task.workspace_id,
                    "project_id": task.project_id,
                    "snapshot_id": snapshot_id,
                    "site_url_id": site_url_ids.get(page.url_hash),
                    "canonical_url": page.canonical_url,
                    "metrics": page.metrics,
                    "source_metric_row_ids": page.source_metric_row_ids,
                    "source_artifact_ids": page.source_artifact_ids,
                }
                for page in projection.pages
            ]
        )
    )


async def _replace_query_stats(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    snapshot_id: uuid.UUID,
    projection: SnapshotProjection,
) -> None:
    """Delete-then-insert the snapshot's query stat rows (same tx)."""
    await session.execute(
        delete(TrafficQueryStat).where(TrafficQueryStat.snapshot_id == snapshot_id)
    )
    if not projection.queries:
        return
    await session.execute(
        pg_insert(TrafficQueryStat).values(
            [
                {
                    "workspace_id": task.workspace_id,
                    "project_id": task.project_id,
                    "snapshot_id": snapshot_id,
                    "normalized_query": query.normalized_query,
                    "metrics": query.metrics,
                    "source_metric_row_ids": query.source_metric_row_ids,
                    "source_artifact_ids": query.source_artifact_ids,
                }
                for query in projection.queries
            ]
        )
    )


async def refresh_traffic_snapshot(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    """``traffic_snapshot_refresh`` executor: rebuild one window's snapshots.

    Read phase: the window's consumed-dataset metric rows in bounded
    keyset batches, checking cooperative cancel at every batch boundary.
    Write phase: for each configured granularity
    (``TRAFFIC_SNAPSHOT_GRANULARITIES``) the pure projection is upserted and
    its page/query stat rows replaced — ALL of it in ONE transaction (one
    commit), so a refresh never leaves a half-written snapshot family.
    """
    if task.project_id is None:
        raise ValueError("traffic_snapshot_refresh task missing project_id")
    window_start, window_end = payload_window(task, kind="traffic_snapshot_refresh")
    async with session_factory() as session:
        project_origin = await session.scalar(
            select(SiteHealthProfile.root_url).where(
                SiteHealthProfile.workspace_id == task.workspace_id,
                SiteHealthProfile.project_id == task.project_id,
            )
        )
        inputs: list[TrafficMetricRowInput] = []
        after_id: uuid.UUID | None = None
        while True:
            await _raise_if_task_terminal(session_factory, task.id)
            batch = await _metric_row_batch(
                session,
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                window_start=window_start,
                window_end=window_end,
                after_id=after_id,
                limit=_METRIC_ROW_BATCH_SIZE,
            )
            if not batch:
                break
            inputs.extend(_to_input(row) for row in batch)
            after_id = batch[-1].id
            if len(batch) < _METRIC_ROW_BATCH_SIZE:
                break

        for granularity in sorted(TRAFFIC_SNAPSHOT_GRANULARITIES):
            projection = build_traffic_projection(
                rows=inputs,
                window_start=window_start,
                window_end=window_end,
                granularity=granularity,
                project_origin=project_origin,
            )
            snapshot_id = await _upsert_snapshot(
                session,
                task=task,
                window_start=window_start,
                window_end=window_end,
                granularity=granularity,
                projection=projection,
            )
            await _replace_page_stats(
                session, task=task, snapshot_id=snapshot_id, projection=projection
            )
            await _replace_query_stats(
                session, task=task, snapshot_id=snapshot_id, projection=projection
            )
            if granularity == TRAFFIC_DEFAULT_GRANULARITY:
                from app.domain.opportunities.verification import (
                    enqueue_implementation_verification,
                )

                await enqueue_implementation_verification(
                    session,
                    workspace_id=task.workspace_id,
                    project_id=task.project_id,
                    trigger_kind="traffic_snapshot",
                    trigger_id=snapshot_id,
                    trigger_revision=str(task.id),
                )
        await _enqueue_demand_refresh(
            session,
            task=task,
            inputs=inputs,
            window_start=window_start,
            window_end=window_end,
        )
        await session.commit()


async def _enqueue_demand_refresh(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    inputs: list[TrafficMetricRowInput],
    window_start: date,
    window_end: date,
) -> None:
    if task.project_id is None:
        raise ValueError("traffic refresh requires project_id")
    source_revision = stable_hash(
        {
            "metric_row_ids": sorted(str(row.id) for row in inputs),
            "window": [window_start.isoformat(), window_end.isoformat()],
        }
    )[:24]
    await enqueue_demand_snapshot_refresh(
        session,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        window_start=window_start,
        window_end=window_end,
        source_revision=source_revision,
    )


# =========================================================================
# A10 — read services (persisted projections only, invariant 7)
# =========================================================================


# Cursor endpoint scope labels (the keyset fingerprint binds the cursor to
# the endpoint + the active filters — site-health convention, contract C4).
_PAGES_CURSOR_SCOPE = "traffic-pages"
_QUERIES_CURSOR_SCOPE = "traffic-queries"


async def get_traffic_dashboard(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    granularity: str = TRAFFIC_DEFAULT_GRANULARITY,
) -> TrafficDashboardResponse:
    """Serve the headline Traffic projection from the persisted snapshot.

    The persisted ``metrics`` JSONB already carries the exact totals/series
    fragments (A7 writes them in the served shape); this maps them into the
    strict response model. An absent snapshot yields the empty payload.
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
        return _empty_dashboard(
            project_id=project_id,
            from_date=from_date,
            to_date=to_date,
            granularity=granularity,
        )

    metrics = snapshot.metrics or {}
    series_raw = metrics.get("series") or {}
    totals = _totals(metrics.get("totals"))
    observed = (
        totals.impressions,
        totals.clicks,
        totals.sessions or 0,
        totals.conversions or 0,
    )
    return TrafficDashboardResponse(
        project_id=project_id,
        evidence_state="available" if any(observed) else "observed_zero",
        window_start=snapshot.window_start.isoformat(),
        window_end=snapshot.window_end.isoformat(),
        granularity=snapshot.granularity,
        totals=totals,
        series=TrafficSeries(
            **{
                name: metric_series_points(series_raw.get(name))
                for name in TRAFFIC_SERIES_NAMES
            }
        ),
        formula_version=snapshot.formula_version,
        normalization_version=snapshot.normalization_version,
    )


# The two persisted stat models share the columns the keyset read touches
# (metrics/workspace_id/project_id/snapshot_id/id), so the shared helpers below
# stay generic in the model and return its CONCRETE row type rather than Base.
async def _stat_page_rows[StatModel: (TrafficPageStat, TrafficQueryStat)](
    session: AsyncSession,
    *,
    model: type[StatModel],
    scope: str,
    filters: dict[str, object],
    snapshot_id: uuid.UUID,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    sort_key: str,
    descending: bool,
    keyset: tuple[float | None, uuid.UUID] | None,
) -> tuple[list[StatModel], str | None]:
    """One keyset page of a snapshot's persisted stat rows + the cursor.

    Ordering is ``(sort_metric [direction] NULLS LAST, id ASC)`` over the
    STORED aggregate in the metrics JSONB — paging/sorting never recomputes
    from ``IntegrationMetricRow`` (invariant 7). The ``+1`` lookahead row
    decides whether a continuation cursor is emitted (site-health
    convention).
    """
    # The persisted aggregate column: (metrics ->> '<key>')::float. JSONB
    # ``->>`` yields SQL NULL for a JSON null/absent key, so NULL ratio /
    # GA4-absent values sort NULLS LAST and cast cleanly.
    metric_expr = cast(model.metrics[sort_key].astext, Float)
    stmt = (
        select(model)
        .where(model.workspace_id == workspace_id)
        .where(model.project_id == project_id)
        .where(model.snapshot_id == snapshot_id)
    )
    if keyset is not None:
        cur_value, cur_id = keyset
        if cur_value is None:
            # Past the non-NULL run: only NULL rows with a later id remain.
            stmt = stmt.where(metric_expr.is_(None), model.id > cur_id)
        else:
            boundary = (
                metric_expr < cur_value if descending else metric_expr > cur_value
            )
            stmt = stmt.where(
                or_(
                    boundary,
                    and_(metric_expr == cur_value, model.id > cur_id),
                    metric_expr.is_(None),
                )
            )
    direction = metric_expr.desc() if descending else metric_expr.asc()
    stmt = stmt.order_by(direction.nulls_last(), model.id.asc()).limit(
        TRAFFIC_TABLE_PAGE_SIZE + 1
    )

    rows = list((await session.scalars(stmt)).all())
    next_cursor: str | None = None
    if len(rows) > TRAFFIC_TABLE_PAGE_SIZE:
        rows = rows[:TRAFFIC_TABLE_PAGE_SIZE]
        last = rows[-1]
        last_value = _float_or_none((last.metrics or {}).get(sort_key))
        next_cursor = encode_keyset_cursor(
            scope=scope,
            filters=filters,
            sort_values=[
                "" if last_value is None else last_value,
                str(last.id),
            ],
        )
    return rows, next_cursor


def _page_row(stat: TrafficPageStat) -> TrafficPageRow:
    metrics = stat.metrics or {}
    return TrafficPageRow(
        canonical_url=stat.canonical_url,
        site_url_id=stat.site_url_id,
        impressions=_int_or_zero(metrics.get("impressions")),
        clicks=_int_or_zero(metrics.get("clicks")),
        ctr=_float_or_none(metrics.get("ctr")),
        position=_float_or_none(metrics.get("position")),
        sessions=_int_or_none(metrics.get("sessions")),
        conversions=_int_or_none(metrics.get("conversions")),
    )


def _query_row(stat: TrafficQueryStat) -> TrafficQueryRow:
    metrics = stat.metrics or {}
    return TrafficQueryRow(
        normalized_query=stat.normalized_query,
        impressions=_int_or_zero(metrics.get("impressions")),
        clicks=_int_or_zero(metrics.get("clicks")),
        ctr=_float_or_none(metrics.get("ctr")),
        position=_float_or_none(metrics.get("position")),
    )


async def _stat_table[StatModel: (TrafficPageStat, TrafficQueryStat)](
    session: AsyncSession,
    *,
    model: type[StatModel],
    scope: str,
    sort_whitelist: frozenset[str],
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None,
    to_date: date | None,
    sort: str | None,
    cursor: str | None,
) -> tuple[list[StatModel], str | None]:
    """The shared keyset-table read behind the pages/queries endpoints.

    Validates the window, parses the whitelist-guarded sort, decodes the
    fingerprint-bound cursor, loads the default-granularity snapshot (the
    per-page/per-query folds are granularity-independent, so its stat rows
    serve every table request — the A9 themes precedent), and returns its
    persisted rows + continuation cursor. An absent snapshot yields an
    empty page. Each endpoint owns only its model/scope/whitelist and the
    row mapping below.
    """
    _validate_window(from_date, to_date)
    sort_key, descending = _parse_sort(sort, whitelist=sort_whitelist)
    normalized_sort = f"-{sort_key}" if descending else sort_key
    filters = _table_filters(
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        sort=normalized_sort,
    )
    keyset: tuple[float | None, uuid.UUID] | None = None
    if cursor:
        keyset = _decode_table_cursor(cursor, scope=scope, filters=filters)
    snapshot = await _load_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        granularity=TRAFFIC_DEFAULT_GRANULARITY,
    )
    if snapshot is None:
        return [], None
    return await _stat_page_rows(
        session,
        model=model,
        scope=scope,
        filters=filters,
        snapshot_id=snapshot.id,
        workspace_id=workspace_id,
        project_id=project_id,
        sort_key=sort_key,
        descending=descending,
        keyset=keyset,
    )


async def get_traffic_pages(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    sort: str | None = None,
    cursor: str | None = None,
) -> TrafficPagesPage:
    """Page the persisted per-page stat rows (keyset, contract C4).

    A pure read of the persisted ``TrafficPageStat`` rows of the snapshot
    matching the window (invariant 7). The opaque cursor is
    fingerprint-bound to this endpoint + the active filters, so a replay
    against a different window/sort is rejected (400) instead of silently
    skipping rows. An absent snapshot yields an empty page.
    """
    rows, next_cursor = await _stat_table(
        session,
        model=TrafficPageStat,
        scope=_PAGES_CURSOR_SCOPE,
        sort_whitelist=TRAFFIC_PAGE_SORT_WHITELIST,
        workspace_id=workspace_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        cursor=cursor,
    )
    return TrafficPagesPage(
        items=[_page_row(row) for row in rows], next_cursor=next_cursor
    )


async def get_traffic_queries(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_date: date | None = None,
    to_date: date | None = None,
    sort: str | None = None,
    cursor: str | None = None,
) -> TrafficQueriesPage:
    """Page the persisted per-query stat rows (keyset, contract C4).

    Same contract as :func:`get_traffic_pages` over ``TrafficQueryStat``
    (GSC-only measures; the key is the normalized query string).
    """
    rows, next_cursor = await _stat_table(
        session,
        model=TrafficQueryStat,
        scope=_QUERIES_CURSOR_SCOPE,
        sort_whitelist=TRAFFIC_QUERY_SORT_WHITELIST,
        workspace_id=workspace_id,
        project_id=project_id,
        from_date=from_date,
        to_date=to_date,
        sort=sort,
        cursor=cursor,
    )
    return TrafficQueriesPage(
        items=[_query_row(row) for row in rows], next_cursor=next_cursor
    )


# =========================================================================
# A11 — traffic-sync fan-out read (the enqueue stays in integrations)
# =========================================================================


async def list_traffic_sync_connections(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[IntegrationConnection]:
    """The distinct ACTIVE mapped GSC/GA4 connections of the project.

    The ``POST /projects/{id}/traffic/sync`` fan-out set: every ACTIVE
    ``IntegrationPropertyMapping`` of the project joined to its connection,
    restricted to the Traffic-consumed providers (``TRAFFIC_SYNC_PROVIDERS``
    — Bing carries no Traffic dataset) on a CONNECTED grant. One entry per
    connection (a connection with several mapped properties gets ONE run —
    sync runs are connection-scoped). Read-only; the enqueue per connection
    is owned by ``domain/integrations/sync.py`` (invariant 2).
    """
    stmt = (
        select(IntegrationConnection)
        .join(
            IntegrationPropertyMapping,
            and_(
                IntegrationPropertyMapping.workspace_id
                == IntegrationConnection.workspace_id,
                IntegrationPropertyMapping.connection_id == IntegrationConnection.id,
            ),
        )
        .join(
            IntegrationOAuthGrant,
            and_(
                IntegrationOAuthGrant.workspace_id
                == IntegrationConnection.workspace_id,
                IntegrationOAuthGrant.id == IntegrationConnection.grant_id,
            ),
        )
        .where(IntegrationConnection.workspace_id == workspace_id)
        .where(IntegrationPropertyMapping.project_id == project_id)
        .where(IntegrationPropertyMapping.status == MAPPING_STATUS_ACTIVE)
        .where(IntegrationConnection.provider.in_(sorted(TRAFFIC_SYNC_PROVIDERS)))
        .where(IntegrationOAuthGrant.status == GRANT_STATUS_CONNECTED)
        .order_by(
            IntegrationConnection.created_at.asc(), IntegrationConnection.id.asc()
        )
        .distinct()
    )
    return list((await session.scalars(stmt)).all())
