"""Strict response contracts for persisted Commerce catalog health."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CommerceSyncSummary(_StrictModel):
    sync_run_id: uuid.UUID
    connection_id: uuid.UUID
    status: Literal[
        "queued",
        "leased",
        "running",
        "retry_wait",
        "succeeded",
        "failed",
        "cancelled",
    ]
    window_start: str
    window_end: str
    row_count: int
    error_code: str
    completed_at: str | None


class CommerceConnectionSummary(_StrictModel):
    connection_id: uuid.UUID
    provider: Literal["shopify"]
    label: str
    account_ref: str
    grant_status: Literal[
        "connected", "needs_reauth", "pending_revocation", "revoked", "error"
    ]
    last_synced_at: str | None
    latest_sync: CommerceSyncSummary | None


class ProductFeedHealth(_StrictModel):
    product_id: uuid.UUID | None
    connection_id: uuid.UUID
    external_item_ref: str
    sync_run_id: uuid.UUID
    status: Literal["healthy", "warning", "error", "unavailable"]
    highest_severity: Literal["info", "warning", "error"] | None
    issue_count: int
    rule_ids: list[str]
    last_seen_in_feed: bool


class CommerceCatalogHealth(_StrictModel):
    project_id: uuid.UUID
    connections: list[CommerceConnectionSummary]
    products: list[ProductFeedHealth]
    generated_at: str | None


class CommerceComparisonProduct(_StrictModel):
    id: uuid.UUID
    name: str
    sku: str
    competitor_name: str
    price: float | None
    currency: str
    attributes: dict[str, Any]
    visibility_rate: float
    average_rank: float | None
    win_rate: float | None


class CommerceAttributeGap(_StrictModel):
    field: str
    own_value: Any | None
    competitor_value: Any


class CommerceComparisonItem(_StrictModel):
    own_product: CommerceComparisonProduct
    competitor_product: CommerceComparisonProduct
    match_confidence: float
    match_reasons: list[str]
    attribute_gaps: list[CommerceAttributeGap]


class CommerceComparisonResponse(_StrictModel):
    id: uuid.UUID
    project_id: uuid.UUID
    audit_id: uuid.UUID
    matcher_version: str
    comparison_version: str
    source_metric_ids: list[uuid.UUID]
    source_artifact_ids: list[uuid.UUID]
    items: list[CommerceComparisonItem]
    created_at: datetime
