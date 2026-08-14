"""Persistence executor for attribution snapshots."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import batched

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    AI_REFERRAL_RULE_VERSION,
    ANALYTICS_SNAPSHOT_GRANULARITIES,
)
from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_CONSUMED_DATASETS,
    ATTRIBUTION_FORMULA_VERSION,
)
from app.domain.analytics.ingest import metric_row_not_superseded
from app.domain.analytics.tasks import payload_window, raise_if_task_terminal
from app.domain.attribution.snapshot import (
    _METRIC_ROW_BATCH_SIZE,
    CombinedProjection,
    build_a1_projection,
    build_combined_projection,
)
from app.domain.commerce.orders import order_fact_not_superseded
from app.models.analytics import AnalyticsTask
from app.models.attribution import AttributionLink, AttributionSnapshot
from app.models.commerce import OrderFact
from app.models.integrations import IntegrationImportArtifact, IntegrationMetricRow
from app.models.product import Product

# --- Executor ------------------------------------------------------------------


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

    Workspace + project scoped (invariant 5) and latest-revision filtered
    (``metric_row_not_superseded`` — the one shared owner of the rule);
    the pure projection re-applies latest-selection inside. The id-keyset
    order keeps the scan stable across batches.
    """
    stmt = (
        select(IntegrationMetricRow)
        .where(IntegrationMetricRow.workspace_id == workspace_id)
        .where(IntegrationMetricRow.project_id == project_id)
        .where(IntegrationMetricRow.dataset.in_(sorted(ATTRIBUTION_CONSUMED_DATASETS)))
        .where(IntegrationMetricRow.date >= window_start)
        .where(IntegrationMetricRow.date <= window_end)
        .where(metric_row_not_superseded())
        .order_by(IntegrationMetricRow.id.asc())
        .limit(limit)
    )
    if after_id is not None:
        stmt = stmt.where(IntegrationMetricRow.id > after_id)
    return list((await session.scalars(stmt)).all())


async def _currency_by_artifact_id(
    session: AsyncSession, artifact_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """The persisted ISO currency per source artifact (``currency_code``).

    Reads the sanitized artifact payloads only (invariant 7 — never a
    provider call); artifacts without a stamped ``currency_code`` are
    absent from the map (their rows land in the unknown-currency
    partition).
    """
    if not artifact_ids:
        return {}
    currencies: dict[uuid.UUID, str] = {}
    for artifact_id_batch in batched(artifact_ids, _METRIC_ROW_BATCH_SIZE):
        stmt = select(
            IntegrationImportArtifact.id, IntegrationImportArtifact.payload
        ).where(IntegrationImportArtifact.id.in_(artifact_id_batch))
        for artifact_id, payload in (await session.execute(stmt)).all():
            code = (payload or {}).get("currency_code")
            if isinstance(code, str) and code:
                currencies[artifact_id] = code
    return currencies


async def _products_by_sku(
    session: AsyncSession, *, project_id: uuid.UUID
) -> dict[str, uuid.UUID]:
    """The project's own-catalog ``sku -> product id`` resolution map."""
    stmt = select(Product.sku, Product.id).where(Product.project_id == project_id)
    return {sku: product_id for sku, product_id in (await session.execute(stmt)).all()}


async def _orders_and_links(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> tuple[list[OrderFact], list[AttributionLink]]:
    start = datetime.combine(window_start, time.min, tzinfo=UTC)
    end = datetime.combine(window_end + timedelta(days=1), time.min, tzinfo=UTC)
    orders = list(
        (
            await session.scalars(
                select(OrderFact)
                .where(OrderFact.workspace_id == workspace_id)
                .where(OrderFact.project_id == project_id)
                .where(OrderFact.occurred_at >= start)
                .where(OrderFact.occurred_at < end)
                .where(order_fact_not_superseded())
                .order_by(OrderFact.id.asc())
            )
        ).all()
    )
    if not orders:
        return [], []
    order_ids = [order.id for order in orders]
    links: list[AttributionLink] = []
    for order_id_batch in batched(order_ids, _METRIC_ROW_BATCH_SIZE):
        rows = await session.scalars(
            select(AttributionLink)
            .where(AttributionLink.workspace_id == workspace_id)
            .where(AttributionLink.project_id == project_id)
            .where(AttributionLink.order_fact_id.in_(order_id_batch))
            .where(AttributionLink.rule_version == AI_REFERRAL_RULE_VERSION)
            .where(AttributionLink.analyzer_version == ATTRIBUTION_ANALYZER_VERSION)
            .order_by(AttributionLink.id.asc())
        )
        links.extend(rows.all())
    links.sort(key=lambda link: link.id)
    return orders, links


async def _upsert_snapshot(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    window_start: date,
    window_end: date,
    granularity: str,
    projection: CombinedProjection,
) -> None:
    """The transactional upsert of the one current snapshot row.

    ``INSERT ... ON CONFLICT (project_id, window_start, window_end,
    granularity) DO UPDATE`` — concurrent refreshes serialize on the
    unique row and can never create a duplicate "current" snapshot (the
    ``domain/analytics/ai_referrals_snapshot.py`` precedent). The A2 provenance arrays
    (``source_link_ids`` / ``source_order_fact_ids``) are insert-only nulls
    in this scope — Task 4 owns writing them, so a Task-1 re-refresh
    deliberately does not clobber them.
    """
    stmt = (
        pg_insert(AttributionSnapshot)
        .values(
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
            granularity=granularity,
            metrics=projection.metrics,
            source_link_ids=projection.source_link_ids,
            source_order_fact_ids=projection.source_order_fact_ids,
            source_metric_row_ids=projection.source_metric_row_ids,
            source_snapshot_ids=None,
            analyzer_version=ATTRIBUTION_ANALYZER_VERSION,
            formula_version=ATTRIBUTION_FORMULA_VERSION,
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
                "source_link_ids": projection.source_link_ids,
                "source_order_fact_ids": projection.source_order_fact_ids,
                "source_metric_row_ids": projection.source_metric_row_ids,
                "analyzer_version": ATTRIBUTION_ANALYZER_VERSION,
                "formula_version": ATTRIBUTION_FORMULA_VERSION,
            },
        )
    )
    await session.execute(stmt)


async def refresh_attribution_snapshot(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    """``attribution_snapshot`` executor: rebuild one window's A1 snapshots.

    Read phase: the window's latest consumed-dataset metric rows in
    bounded keyset batches (cooperative cancel at every batch boundary),
    plus the artifact-payload currencies and the project's sku map. Write
    phase: the pure A1 projection (granularity-INDEPENDENT — no series) is
    upserted for EVERY configured analytics granularity, ALL in ONE
    transaction (one commit), so a refresh never leaves a half-written
    snapshot family. NO provider I/O (invariant 7).
    """
    if task.project_id is None:
        raise ValueError("attribution_snapshot task missing project_id")
    window_start, window_end = payload_window(task, kind="attribution_snapshot")
    async with session_factory() as session:
        rows: list[IntegrationMetricRow] = []
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
            rows.extend(batch)
            after_id = batch[-1].id
            if len(batch) < _METRIC_ROW_BATCH_SIZE:
                break

        currencies = await _currency_by_artifact_id(
            session, list({row.source_artifact_id for row in rows})
        )
        products = await _products_by_sku(session, project_id=task.project_id)
        a1_projection = build_a1_projection(
            rows, products, currency_by_artifact_id=currencies
        )
        orders, links = await _orders_and_links(
            session,
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
        )
        projection = build_combined_projection(
            a1_projection,
            orders,
            links,
            window_start=window_start,
            window_end=window_end,
        )
        for granularity in sorted(ANALYTICS_SNAPSHOT_GRANULARITIES):
            await _upsert_snapshot(
                session,
                task=task,
                window_start=window_start,
                window_end=window_end,
                granularity=granularity,
                projection=projection,
            )
        await session.commit()
