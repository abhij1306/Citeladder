"""Typed, audit-bound competitor comparison projections."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import COMMERCE_RECOMMENDATION_ATTRIBUTE_KEYS
from app.domain.commerce.matching import match_candidate
from app.domain.commerce.schemas import (
    CommerceAttributeGap,
    CommerceComparisonItem,
    CommerceComparisonProduct,
    CommerceComparisonResponse,
)
from app.domain.products.visibility import (
    _entry_metrics,
    _rate,
    _snapshot_entry_id,
    select_current_snapshots,
)
from app.models.audit import Audit
from app.models.commerce import CompetitorComparisonSnapshot
from app.models.product import ProductMetricSnapshot, ProductResponseAnalysis


class CommerceComparisonNotFoundError(LookupError):
    pass


def _entry_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


def _usable_catalog_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parsed = [dict(row) for row in rows]
    return [row for row in parsed if _entry_id(row)]


def _metric_map(
    snapshots: list[ProductMetricSnapshot],
) -> dict[str, ProductMetricSnapshot]:
    return select_current_snapshots(
        [snapshot for snapshot in snapshots if _snapshot_entry_id(snapshot)]
    )


def _comparison_product(
    row: dict[str, Any],
    snapshot: ProductMetricSnapshot,
    *,
    total_analyses: int,
    competitor: bool,
) -> CommerceComparisonProduct:
    metrics = _entry_metrics(snapshot)
    return CommerceComparisonProduct(
        id=uuid.UUID(_entry_id(row)),
        name=str(row.get("name") or ""),
        sku="" if competitor else str(row.get("sku") or ""),
        competitor_name=(str(row.get("competitor_name") or "") if competitor else ""),
        price=float(row["price"]) if row.get("price") is not None else None,
        currency=str(row.get("currency") or ""),
        attributes=dict(row.get("attributes") or {}),
        visibility_rate=_rate(metrics["mention_count"], total_analyses),
        average_rank=metrics["avg_rank"],
        win_rate=metrics["win_rate"],
    )


def _attribute_gaps(
    own: dict[str, Any], competitor: dict[str, Any]
) -> list[CommerceAttributeGap]:
    own_attributes = dict(own.get("attributes") or {})
    competitor_attributes = dict(competitor.get("attributes") or {})
    return [
        CommerceAttributeGap(
            field=field,
            own_value=own_attributes.get(field),
            competitor_value=competitor_attributes[field],
        )
        for field in COMMERCE_RECOMMENDATION_ATTRIBUTE_KEYS
        if own_attributes.get(field) in (None, "", [])
        and competitor_attributes.get(field) not in (None, "", [])
    ]


def _comparison_item(
    competitor: dict[str, Any],
    own_rows: list[dict[str, Any]],
    metrics: dict[str, ProductMetricSnapshot],
    *,
    total_analyses: int,
) -> CommerceComparisonItem | None:
    matches = match_candidate(competitor, own_rows)
    if not matches:
        return None
    selected = matches[0]
    own = next(
        (row for row in own_rows if _entry_id(row) == str(selected.target_id)),
        None,
    )
    if own is None:
        return None
    own_snapshot = metrics.get(_entry_id(own))
    competitor_snapshot = metrics.get(_entry_id(competitor))
    if own_snapshot is None or competitor_snapshot is None:
        return None
    return CommerceComparisonItem(
        own_product=_comparison_product(
            own,
            own_snapshot,
            total_analyses=total_analyses,
            competitor=False,
        ),
        competitor_product=_comparison_product(
            competitor,
            competitor_snapshot,
            total_analyses=total_analyses,
            competitor=True,
        ),
        match_confidence=selected.confidence,
        match_reasons=list(selected.reasons),
        attribute_gaps=_attribute_gaps(own, competitor),
    )


def _comparison_items(
    audit: Audit,
    snapshots: list[ProductMetricSnapshot],
    *,
    total_analyses: int,
) -> list[CommerceComparisonItem]:
    configuration = audit.configuration or {}
    own_rows = _usable_catalog_rows(configuration.get("products") or [])
    competitor_rows = _usable_catalog_rows(
        configuration.get("competitor_products") or []
    )
    metrics = _metric_map(snapshots)
    projected = (
        _comparison_item(
            competitor,
            own_rows,
            metrics,
            total_analyses=total_analyses,
        )
        for competitor in competitor_rows
    )
    return [item for item in projected if item is not None]


def _comparison_sources(
    items: list[CommerceComparisonItem],
    snapshots: list[ProductMetricSnapshot],
) -> tuple[list[ProductMetricSnapshot], list[uuid.UUID]]:
    matched_entry_ids = {
        str(product.id)
        for item in items
        for product in (item.own_product, item.competitor_product)
    }
    source_snapshots = [
        snapshot
        for entry_id, snapshot in select_current_snapshots(snapshots).items()
        if entry_id in matched_entry_ids
    ]
    source_artifact_ids = sorted(
        {
            uuid.UUID(str(artifact_id))
            for snapshot in source_snapshots
            for artifact_id in (snapshot.source_artifact_ids or [])
        },
        key=str,
    )
    return source_snapshots, source_artifact_ids


def _source_catalog_ids(audit: Audit) -> dict[str, list[str]]:
    configuration = audit.configuration or {}
    return {
        "products": [
            _entry_id(item)
            for item in _usable_catalog_rows(configuration.get("products") or [])
        ],
        "competitor_products": [
            _entry_id(item)
            for item in _usable_catalog_rows(
                configuration.get("competitor_products") or []
            )
        ],
    }


async def persist_comparison_snapshot(
    session: AsyncSession, *, audit: Audit
) -> CompetitorComparisonSnapshot | None:
    existing = await session.scalar(
        select(CompetitorComparisonSnapshot).where(
            CompetitorComparisonSnapshot.audit_id == audit.id
        )
    )
    if existing is not None:
        return existing
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.audit_id == audit.id,
                    ProductMetricSnapshot.workspace_id == audit.workspace_id,
                )
            )
        ).all()
    )
    if not snapshots:
        return None
    total_analyses = int(
        await session.scalar(
            select(func.count())
            .select_from(ProductResponseAnalysis)
            .where(ProductResponseAnalysis.audit_id == audit.id)
        )
        or 0
    )
    items = _comparison_items(audit, snapshots, total_analyses=total_analyses)
    source_snapshots, source_artifact_ids = _comparison_sources(items, snapshots)
    row = CompetitorComparisonSnapshot(
        workspace_id=audit.workspace_id,
        project_id=audit.project_id,
        audit_id=audit.id,
        source_catalog_ids=_source_catalog_ids(audit),
        source_artifact_ids=[str(value) for value in source_artifact_ids],
        comparison={
            "items": [item.model_dump(mode="json") for item in items],
            "source_metric_ids": [str(snapshot.id) for snapshot in source_snapshots],
        },
        truncated=False,
    )
    session.add(row)
    await session.flush()
    return row


def _response(row: CompetitorComparisonSnapshot) -> CommerceComparisonResponse:
    items = [
        CommerceComparisonItem.model_validate(item)
        for item in (row.comparison or {}).get("items") or []
    ]
    source_metric_ids = [
        uuid.UUID(str(value))
        for value in (row.comparison or {}).get("source_metric_ids") or []
    ]
    return CommerceComparisonResponse(
        id=row.id,
        project_id=row.project_id,
        audit_id=row.audit_id,
        matcher_version=row.matcher_version,
        comparison_version=row.comparison_version,
        source_metric_ids=source_metric_ids,
        source_artifact_ids=[
            uuid.UUID(str(value)) for value in row.source_artifact_ids or []
        ],
        items=items,
        created_at=row.created_at,
    )


async def get_comparison_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> CommerceComparisonResponse:
    statement = select(CompetitorComparisonSnapshot).where(
        CompetitorComparisonSnapshot.workspace_id == workspace_id,
        CompetitorComparisonSnapshot.project_id == project_id,
    )
    if audit_id is not None:
        statement = statement.where(CompetitorComparisonSnapshot.audit_id == audit_id)
    row = await session.scalar(
        statement.order_by(CompetitorComparisonSnapshot.created_at.desc()).limit(1)
    )
    if row is None:
        raise CommerceComparisonNotFoundError("Commerce comparison not available")
    return _response(row)
