"""Public contracts for bounded Growth Agent runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.core.config.agent import AGENT_OBJECTIVE_MAX_CHARS

AgentTaskType = Literal["explain", "build_roadmap"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentTaskSubmit(_StrictModel):
    project_id: uuid.UUID
    task_type: AgentTaskType
    objective: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=AGENT_OBJECTIVE_MAX_CHARS,
        ),
    ]


class AgentArtifactReference(_StrictModel):
    kind: str
    id: uuid.UUID


class AgentRoadmapItem(_StrictModel):
    rank: int
    title: str
    remediation: str
    target_url: str | None
    priority_score: float
    severity: str


class AgentEvidenceSource(_StrictModel):
    key: Literal["site_health", "search_demand", "opportunities", "ai_visibility"]
    label: str
    availability: Literal["available", "unavailable"]
    window: dict[str, str] | None = None
    coverage: dict[str, int | float | str | None] | None = None
    reason: str | None = None


class AgentTaskResult(_StrictModel):
    summary: str
    observations: list[str]
    roadmap_items: list[AgentRoadmapItem]
    sources: list[AgentEvidenceSource]
    limitations: list[str]
    artifact_refs: list[AgentArtifactReference]


class AgentTaskRunSummary(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    task_type: AgentTaskType
    objective: str
    status: str
    error_code: str
    error_detail: str
    attempt_count: int
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AgentTaskRunDetail(AgentTaskRunSummary):
    result: AgentTaskResult | None
