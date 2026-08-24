"""CSV export projection for persisted product visibility snapshots."""

from __future__ import annotations

import csv
import io
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.csv_cells import csv_cell
from app.analysis.product_service import build_product_scoring_config
from app.core.config.commerce import (
    PRICE_RELATION_HIGHER,
    PRICE_RELATION_LOWER,
    PRICE_RELATION_MATCH,
    PRICE_RELATION_MISMATCH,
)
from app.domain.products.visibility import (
    _EMPTY_DESTINATION_MIX,
    _entry_metrics,
    _load_audit_and_snapshots,
    _normalize_aggregate,
    select_current_snapshots,
)
from app.models.audit import Audit
from app.models.product import ProductMetricSnapshot

_CSV_COLUMNS = [
    "audit_id",
    "product",
    "sku",
    "mentions",
    "sov",
    "avg_rank",
    "price_accuracy",
    "engine",
    "product_analyzer_version",
    "win_rate",
    "price_mismatch_rate",
    "price_relation_match_count",
    "price_relation_higher_count",
    "price_relation_lower_count",
    "price_relation_mismatch_count",
    "attribute_dimension_frequency",
    "buyer_destination_mix",
]


def _optional_csv_value(value: object) -> object:
    return "" if value is None else value


def _relation_csv_values(relation_counts: dict) -> dict[str, int]:
    return {
        "price_relation_match_count": int(
            relation_counts.get(PRICE_RELATION_MATCH) or 0
        ),
        "price_relation_higher_count": int(
            relation_counts.get(PRICE_RELATION_HIGHER) or 0
        ),
        "price_relation_lower_count": int(
            relation_counts.get(PRICE_RELATION_LOWER) or 0
        ),
        "price_relation_mismatch_count": int(
            relation_counts.get(PRICE_RELATION_MISMATCH) or 0
        ),
    }


def _json_csv_values(aggregate: dict) -> dict[str, str]:
    def encode(value: object, fallback: dict) -> str:
        return json.dumps(value or fallback, sort_keys=True, separators=(",", ":"))

    return {
        "attribute_dimension_frequency": encode(
            aggregate.get("attribute_dimension_frequency"), {}
        ),
        "buyer_destination_mix": encode(
            aggregate.get("buyer_destination_mix"), _EMPTY_DESTINATION_MIX
        ),
    }


def _csv_row(
    *,
    audit_id: str,
    name: str,
    sku: str,
    engine: str,
    aggregate: dict,
    analyzer_version: str,
) -> dict[str, object]:
    relation_counts = aggregate.get("price_relation_counts") or {}
    row = {
        "audit_id": audit_id,
        "product": csv_cell(name),
        "sku": csv_cell(sku),
        "mentions": aggregate.get("mention_count", 0),
        "sov": aggregate.get("sov_share", 0.0),
        "avg_rank": _optional_csv_value(aggregate.get("avg_rank")),
        "price_accuracy": _optional_csv_value(aggregate.get("price_accuracy_rate")),
        "engine": engine,
        "product_analyzer_version": analyzer_version,
        "win_rate": _optional_csv_value(aggregate.get("win_rate")),
        "price_mismatch_rate": _optional_csv_value(
            aggregate.get("price_mismatch_rate")
        ),
    }
    row.update(_relation_csv_values(relation_counts))
    row.update(_json_csv_values(aggregate))
    return row


def _per_engine_metrics(snapshot: ProductMetricSnapshot) -> dict:
    return (snapshot.metrics or {}).get("per_engine") or {}


async def load_product_visibility_export_bundle(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> tuple[Audit, list[ProductMetricSnapshot]]:
    """Load the audit and snapshots used by the CSV projection."""
    return await _load_audit_and_snapshots(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit_id=audit_id,
    )


def product_visibility_csv(
    audit: Audit,
    snapshots: list[ProductMetricSnapshot],
) -> str:
    """Render persisted product visibility rows as a deterministic CSV."""
    config = build_product_scoring_config(audit.configuration)
    by_entry = select_current_snapshots(snapshots)
    ordered = [(entry.id, entry.name, entry.sku) for entry in config.products]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS)
    writer.writeheader()
    for entry_id, name, sku in ordered:
        snapshot = by_entry.get(entry_id)
        if snapshot is None:
            continue
        writer.writerow(
            _csv_row(
                audit_id=str(audit.id),
                name=name,
                sku=sku,
                engine="all",
                aggregate=_entry_metrics(snapshot, None),
                analyzer_version=snapshot.product_analyzer_version,
            )
        )
        per_engine = _per_engine_metrics(snapshot)
        for engine in sorted(per_engine):
            aggregate = per_engine[engine]
            if aggregate is None:
                continue
            writer.writerow(
                _csv_row(
                    audit_id=str(audit.id),
                    name=name,
                    sku=sku,
                    engine=engine,
                    aggregate=_normalize_aggregate(aggregate),
                    analyzer_version=snapshot.product_analyzer_version,
                )
            )
    return buffer.getvalue()
