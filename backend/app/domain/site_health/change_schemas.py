"""Wire contracts for persisted crawl-to-crawl change intelligence."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


ChangeState = Literal["available", "unavailable", "non_comparable"]
ChangeClass = Literal[
    "improvement",
    "neutral-change",
    "potential-regression",
    "critical-regression",
]


class ChangeSummaryResponse(_Model):
    state: ChangeState
    reason_code: str | None = None
    snapshot_id: uuid.UUID | None = None
    crawl_a_id: uuid.UUID | None = None
    crawl_b_id: uuid.UUID | None = None
    complete_pair: bool
    analyzer_version: str
    page_analyzer_version: str
    extractor_version: str
    source_analysis_ids: list[uuid.UUID] = []
    coverage: dict[str, object] = {}
    summary: dict[str, object] = {}
    limitations: list[str] = []
    created_at: str | None = None


class ChangeObservationResponse(_Model):
    id: uuid.UUID
    site_url_id: uuid.UUID
    normalized_url: str
    field: str
    change_class: ChangeClass
    before_value: object | None = None
    after_value: object | None = None
    source_analysis_a_id: uuid.UUID | None = None
    source_analysis_b_id: uuid.UUID | None = None
    source_artifact_a_id: uuid.UUID | None = None
    source_artifact_b_id: uuid.UUID | None = None
    source_evaluation_a_id: uuid.UUID | None = None
    source_evaluation_b_id: uuid.UUID | None = None
    expected: bool
    implementation_event_id: uuid.UUID | None = None
    created_at: str


class ChangesPage(ChangeSummaryResponse):
    items: list[ChangeObservationResponse] = []
    next_cursor: str | None = None


__all__ = ["ChangeObservationResponse", "ChangeSummaryResponse", "ChangesPage"]
