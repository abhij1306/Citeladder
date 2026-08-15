"""Strict API contracts for persisted Demand Intelligence projections."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class DemandRecomputeRequest(_Model):
    window_start: date
    window_end: date

    @field_validator("window_end")
    @classmethod
    def validate_window(cls, value: date, info) -> date:
        start = info.data.get("window_start")
        if start is not None and value < start:
            raise ValueError("window_end must not be before window_start")
        return value


class DemandRecomputeResponse(_Model):
    task_id: uuid.UUID | None
    status: str


class DemandSignalView(_Model):
    id: uuid.UUID
    snapshot_id: uuid.UUID
    signal_type: str
    state: str
    topic_cluster: str
    page_url: str
    evidence: dict[str, Any]
    metrics: dict[str, Any]
    coverage: dict[str, Any]
    limitations: list[str]
    priority_score: float | None
    priority_inputs: dict[str, Any]
    created_at: datetime


class DemandSnapshotView(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    window_start: date
    window_end: date
    source_hash: str
    prior_snapshot_id: uuid.UUID | None
    source_artifact_ids: list[str]
    source_metric_row_ids: list[str]
    coverage: dict[str, Any]
    summary: dict[str, Any]
    comparison: dict[str, Any] | None
    formula_version: str
    analyzer_version: str
    created_at: datetime
    signals: list[DemandSignalView] = Field(default_factory=list)


class BrandedQueryOverrideRequest(_Model):
    query: str = Field(min_length=1, max_length=512)
    classification: Literal["branded", "non_branded", "ambiguous"]


class BrandedQueryClassificationView(_Model):
    normalized_query: str
    classification: Literal["branded", "non_branded", "ambiguous"]
    matched_terms: list[str]
    classifier_version: str
    override_id: uuid.UUID | None


class QueryEvidenceRowView(_Model):
    id: uuid.UUID
    date: date
    normalized_query: str
    observed_page_url: str
    site_url_id: uuid.UUID | None
    resolved_page_url: str
    resolution_outcome: Literal["exact", "resolved", "ambiguous", "unresolved"]
    resolution_candidates: list[dict[str, Any]]
    property_ref: str
    impressions: int
    clicks: int
    ctr: float | None
    position: float | None
    source_metric_row_id: uuid.UUID
    source_artifact_id: uuid.UUID
    importer_version: str
    resolver_version: str


class QueryEvidenceSnapshotView(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    window_start: date
    window_end: date
    source_hash: str
    supersedes_snapshot_id: uuid.UUID | None
    state: Literal["available", "observed_zero", "unavailable"]
    source_metric_row_ids: list[str]
    source_artifact_ids: list[str]
    coverage: dict[str, Any]
    limitations: list[str]
    analyzer_version: str
    resolver_version: str
    created_at: datetime


class QueryEvidencePageView(_Model):
    snapshot: QueryEvidenceSnapshotView
    items: list[QueryEvidenceRowView]
    next_cursor: str | None


class QueryEvidenceSummaryView(_Model):
    snapshot: QueryEvidenceSnapshotView
    counts_by_resolution: dict[str, int]
