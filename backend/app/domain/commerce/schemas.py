"""Strict response contracts for persisted Commerce catalog health."""

from __future__ import annotations

import uuid
from typing import Literal

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
