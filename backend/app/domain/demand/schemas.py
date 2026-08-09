"""Strict API contracts for persisted Demand Intelligence projections."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.demand import JOURNEY_SOURCES, JOURNEY_STATUSES


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class JourneyDefinitionWrite(_Model):
    slug: str = Field(
        min_length=1, max_length=96, pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$"
    )
    name: str = Field(min_length=1, max_length=255)
    status: str = "active"
    definition: dict[str, Any]
    source_kind: str = "user"
    source_version: str = Field(default="", max_length=64)

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in JOURNEY_STATUSES:
            raise ValueError(f"unknown journey status: {value!r}")
        return value

    @field_validator("source_kind")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if value not in JOURNEY_SOURCES:
            raise ValueError(f"unknown journey source: {value!r}")
        return value


class JourneyDefinitionView(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    slug: str
    name: str
    status: str
    current_version: int
    definition: dict[str, Any]
    source_kind: str
    source_version: str
    version_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


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
    audience: str
    intent: str
    journey_stage: str
    topic_cluster: str
    page_url: str
    evidence: dict[str, Any]
    metrics: dict[str, Any]
    coverage: dict[str, Any]
    limitations: list[str]
    priority_score: float | None
    priority_inputs: dict[str, Any]
    model_provenance: dict[str, Any] | None
    created_at: datetime


class DemandSnapshotView(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    window_start: date
    window_end: date
    source_hash: str
    site_snapshot_id: uuid.UUID | None
    prior_snapshot_id: uuid.UUID | None
    source_artifact_ids: list[str]
    source_metric_row_ids: list[str]
    source_audit_ids: list[str]
    journey_version_ids: list[str]
    coverage: dict[str, Any]
    summary: dict[str, Any]
    comparison: dict[str, Any] | None
    formula_version: str
    analyzer_version: str
    created_at: datetime
    signals: list[DemandSignalView] = Field(default_factory=list)


class DemandSnapshotList(_Model):
    items: list[DemandSnapshotView]


class DemandDatasetCapability(_Model):
    provider: str
    dataset: str
    state: str
    latest_artifact_id: uuid.UUID | None
    coverage: dict[str, Any]
    provider_metadata: dict[str, Any]


class DemandCapabilityView(_Model):
    datasets: list[DemandDatasetCapability]
