"""Sanitized order fact derivation + the order retention sweep.

One immutable ``OrderFact`` per order per order revision: a later sync
returning the same order (refund/cancellation/fulfilment revision — the
GraphQL window filter is ``updated_at``-driven) inserts a NEW fact at the
next ``resync_seq`` per ``(connection_id, order_ref_hash)``; prior rows
stay immutable and consumers read the LATEST per order via
``order_fact_not_superseded``.

The sequence is NOT the run-window sequence (overlapping windows can
share one run revision while the same order legitimately revises): it is
allocated as ``max(existing)+1`` per order while the integration worker
holds the connection row lock in the owner-gated finalize transaction,
with an in-memory allocation map for intra-run duplicates and
``ON CONFLICT DO NOTHING`` making a retried finalize idempotent.

Every fact derives ONLY from sanitized artifact payloads: derivation
re-validates the payload keys against ``ORDER_SANITIZED_KEYS`` and
rejects (skips) any order carrying an unexpected key — raw provider JSON
never reaches the fact rows.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.config.commerce import (
    COMMERCE_IMPORTER_VERSION,
    ORDER_RETENTION_DAYS,
    ORDER_RETENTION_DELETE_BATCH_SIZE,
    ORDER_SANITIZE_VERSION,
    ORDER_SANITIZED_KEYS,
)
from app.domain.analytics.tasks import raise_if_task_terminal
from app.models.analytics import AnalyticsTask
from app.models.commerce import OrderFact
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product


def order_fact_not_superseded() -> ColumnElement[bool]:
    """SQL WHERE fragment: no later-``resync_seq`` fact for the order exists.

    The "latest revision per order" rule as a reusable clause (mirrors
    ``metric_row_not_superseded`` — ONE owner, invariant 2). The identity
    is ``(connection_id, order_ref_hash)``: a fact superseded by a later
    revision at a higher ``resync_seq`` is stale evidence and is filtered
    out of every projection/read.
    """
    newer = aliased(OrderFact)
    return ~(
        select(newer.id)
        .where(newer.connection_id == OrderFact.connection_id)
        .where(newer.order_ref_hash == OrderFact.order_ref_hash)
        .where(newer.resync_seq > OrderFact.resync_seq)
        .correlate(OrderFact)
        .exists()
    )


def _str(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_datetime(value: object) -> datetime | None:
    """Parse an ISO-8601 provider timestamp; malformed degrades to None."""
    text = _str(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _parse_total(value: object) -> Decimal | None:
    text = _str(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _sanitized_line_items(
    value: object, *, product_ids_by_sku: Mapping[str, uuid.UUID]
) -> list[dict] | None:
    """Re-validate + SKU-resolve the sanitized line items.

    Only ``ORDER_LINE_ITEM_KEYS`` are read; ``product_id`` is resolved by
    ``(project_id, sku)`` (unresolved stays null) and added AFTER the
    sanitize boundary — it was never part of the artifact payload.
    Returns ``None`` when the payload shape is not a list of mappings.
    """
    if not isinstance(value, list):
        return None
    items: list[dict] = []
    for entry in value:
        if not isinstance(entry, Mapping):
            continue
        sku = _str(entry.get("sku"))
        quantity = entry.get("quantity")
        items.append(
            {
                "sku": sku,
                "quantity": (
                    quantity
                    if isinstance(quantity, int) and not isinstance(quantity, bool)
                    else 0
                ),
                "unit_price": _str(entry.get("unit_price")),
                "product_id": (
                    str(product_ids_by_sku[sku]) if sku in product_ids_by_sku else None
                ),
            }
        )
    return items


def _sanitized_orders(orders: list) -> list[Mapping]:
    return [order for order in orders if isinstance(order, Mapping)]


def _referenced_skus(orders: list[Mapping]) -> set[str]:
    return {
        _str(item.get("sku"))
        for order in orders
        for item in (order.get("line_items") or [])
        if isinstance(item, Mapping) and _str(item.get("sku"))
    }


async def _product_ids_by_sku(
    session: AsyncSession, *, project_id: uuid.UUID, skus: set[str]
) -> dict[str, uuid.UUID]:
    if not skus:
        return {}
    rows = await session.execute(
        select(Product.sku, Product.id).where(
            Product.project_id == project_id,
            Product.sku.in_(sorted(skus)),
        )
    )
    return {sku: product_id for sku, product_id in rows.all()}


async def _sequence_allocations(
    session: AsyncSession,
    *,
    connection_id: uuid.UUID,
    orders: list[Mapping],
) -> dict[str, int]:
    order_hashes = sorted({_str(order.get("order_ref_hash")) for order in orders})
    rows = await session.execute(
        select(OrderFact.order_ref_hash, func.max(OrderFact.resync_seq))
        .where(OrderFact.connection_id == connection_id)
        .where(OrderFact.order_ref_hash.in_(order_hashes))
        .group_by(OrderFact.order_ref_hash)
    )
    return {order_hash: int(max_seq) for order_hash, max_seq in rows.all()}


def _order_fact_values(
    order: Mapping,
    *,
    run: IntegrationSyncRun,
    mapping: IntegrationPropertyMapping,
    connection: IntegrationConnection,
    artifact: IntegrationImportArtifact,
    product_ids_by_sku: Mapping[str, uuid.UUID],
    resync_seq: int,
) -> dict | None:
    if not set(order) <= ORDER_SANITIZED_KEYS:
        return None
    order_ref_hash = _str(order.get("order_ref_hash"))
    occurred_at = _parse_datetime(order.get("occurred_at"))
    total_amount = _parse_total(order.get("total_amount"))
    if not order_ref_hash or occurred_at is None or total_amount is None:
        return None
    line_items = _sanitized_line_items(
        order.get("line_items"), product_ids_by_sku=product_ids_by_sku
    )
    if line_items is None:
        return None
    attribution_keys = order.get("attribution_keys")
    return {
        "workspace_id": run.workspace_id,
        "project_id": mapping.project_id,
        "connection_id": connection.id,
        "provider": connection.provider,
        "order_ref_hash": order_ref_hash,
        "resync_seq": resync_seq,
        "occurred_at": occurred_at,
        "currency": _str(order.get("currency"))[:3],
        "total_amount": total_amount,
        "line_items": line_items,
        "attribution_keys": (
            dict(attribution_keys) if isinstance(attribution_keys, Mapping) else {}
        ),
        "source_artifact_id": artifact.id,
        "importer_version": COMMERCE_IMPORTER_VERSION,
        "order_sanitize_version": ORDER_SANITIZE_VERSION,
    }


async def _insert_order_fact(session: AsyncSession, *, values: dict) -> None:
    await session.execute(
        pg_insert(OrderFact)
        .values(**values)
        .on_conflict_do_nothing(
            index_elements=["connection_id", "order_ref_hash", "resync_seq"]
        )
    )


async def derive_order_facts(
    session: AsyncSession,
    *,
    mapping: IntegrationPropertyMapping,
    connection: IntegrationConnection,
    run: IntegrationSyncRun,
    artifact: IntegrationImportArtifact,
    orders: list,
) -> int:
    """Insert one new ``OrderFact`` per sanitized order in one artifact.

    The caller (the integration worker's finalize) holds the connection
    row lock, so the ``max(existing)+1`` allocation per order serializes
    against concurrent finalizes for the same connection. Returns the
    number of fact rows STAGED (conflict-safe: a finalize replay stages
    the same rows and the unique identity tuple absorbs them).
    """
    sanitized_orders = _sanitized_orders(orders)
    if not sanitized_orders:
        return 0
    # SKU -> product id for line-item resolution (one query per artifact).
    product_ids_by_sku = await _product_ids_by_sku(
        session,
        project_id=mapping.project_id,
        skus=_referenced_skus(sanitized_orders),
    )
    # Current per-order sequence maxima for THIS connection (the caller's
    # connection row lock serializes the read+insert).
    allocations = await _sequence_allocations(
        session, connection_id=connection.id, orders=sanitized_orders
    )
    staged = 0
    for order in sanitized_orders:
        # Re-validate the sanitized boundary: an unexpected key means the
        # payload is not a SanitizedOrder product — rejected, never
        # persisted (raw provider JSON must never reach the fact rows).
        order_ref_hash = _str(order.get("order_ref_hash"))
        next_seq = allocations.get(order_ref_hash, -1) + 1
        values = _order_fact_values(
            order,
            run=run,
            mapping=mapping,
            connection=connection,
            artifact=artifact,
            product_ids_by_sku=product_ids_by_sku,
            resync_seq=next_seq,
        )
        if values is None:
            continue
        allocations[order_ref_hash] = next_seq
        await _insert_order_fact(session, values=values)
        staged += 1
    return staged


# --- order_retention_sweep ----------------------------------------------------


async def _delete_expired_orders_batch(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    cutoff: datetime,
    limit: int,
) -> int:
    """Delete one bounded batch of expired order facts (CASCADE children).

    Deterministic batch composition (oldest first) and one commit per
    batch — mirrors the referral retention sweep (invariant 9).
    """
    fact_ids = list(
        (
            await session.scalars(
                select(OrderFact.id)
                .where(OrderFact.workspace_id == workspace_id)
                .where(OrderFact.occurred_at < cutoff)
                .order_by(OrderFact.occurred_at.asc(), OrderFact.id.asc())
                .limit(limit)
            )
        ).all()
    )
    if not fact_ids:
        return 0
    await session.execute(delete(OrderFact).where(OrderFact.id.in_(fact_ids)))
    await session.commit()
    return len(fact_ids)


async def run_order_retention_sweep(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    """``order_retention_sweep`` executor: hard-delete expired order facts.

    Workspace-scoped (the task carries no project): every ``OrderFact`` in
    the task's workspace whose ``occurred_at`` is past
    ``ORDER_RETENTION_DAYS`` is deleted in bounded committed batches with
    cooperative cancel at each batch boundary (invariant 9). GA4 metric
    rows are untouched. Idempotent: a re-run simply finds less (then
    nothing) to delete.
    """
    if not (task.payload or {}).get("sweep_key"):
        raise ValueError("order_retention_sweep payload missing sweep_key")
    # One fixed horizon per run: the cutoff never drifts mid-sweep.
    cutoff = datetime.now(UTC) - timedelta(days=ORDER_RETENTION_DAYS)
    async with session_factory() as session:
        while True:
            await raise_if_task_terminal(session_factory, task.id)
            deleted = await _delete_expired_orders_batch(
                session,
                workspace_id=task.workspace_id,
                cutoff=cutoff,
                limit=ORDER_RETENTION_DELETE_BATCH_SIZE,
            )
            if deleted == 0:
                break
