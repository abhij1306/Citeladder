"""Public contracts for bounded Growth Agent runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.core.config.agent import AGENT_OBJECTIVE_MAX_CHARS


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentTaskSubmit(_StrictModel):
    project_id: uuid.UUID
    task_type: Literal["explain", "build_roadmap"]
    objective: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=AGENT_OBJECTIVE_MAX_CHARS,
        ),
    ]


class AgentToolAttemptItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    run_attempt: int
    ordinal: int
    tool_name: str
    tool_version: str
    status: str
    input: dict[str, Any]
    artifact_refs: list[dict[str, Any]]
    output_hash: str
    omissions: list[dict[str, Any]]
    error_code: str
    retryable: bool
    latency_ms: int
    created_at: datetime


class AgentTaskRunItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    task_type: str
    objective: str
    task_policy_version: str
    status: str
    result: dict[str, Any] | None
    provider_adapter: str
    endpoint_host: str
    model: str
    instruction_version: str
    usage: dict[str, int] | None
    latency_ms: int | None
    error_code: str
    error_detail: str
    attempt_count: int
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    attempts: list[AgentToolAttemptItem] = Field(default_factory=list)
