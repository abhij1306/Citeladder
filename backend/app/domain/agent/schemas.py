"""Strict public contracts for Growth Agent conversations and task runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.config.agent import AGENT_OBJECTIVE_MAX_CHARS


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCreate(_StrictModel):
    project_id: uuid.UUID
    title: str = Field(default="New conversation", min_length=1, max_length=255)


class ConversationItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MessageItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    conversation_id: uuid.UUID
    task_run_id: uuid.UUID | None
    role: str
    content: str
    citations: list[str]
    created_at: datetime


class ConversationDetail(ConversationItem):
    messages: list[MessageItem]


class AgentTaskSubmit(_StrictModel):
    project_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    parent_run_id: uuid.UUID | None = None
    task_type: str = Field(min_length=1, max_length=64)
    objective: str = Field(min_length=1, max_length=AGENT_OBJECTIVE_MAX_CHARS)
    requested_outputs: list[str] = Field(default_factory=list, max_length=8)
    resource_scope: dict[str, Any] = Field(default_factory=dict)


class AgentDecisionConfirm(_StrictModel):
    decision: str = Field(pattern="^(save_content|run_audit)$")
    confirmed: bool


class AgentStepItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    ordinal: int
    name: str
    tool_name: str
    tool_version: str
    tool_kind: str
    status: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    child_task_kind: str
    child_task_id: uuid.UUID | None
    retry_count: int
    error_code: str
    error_detail: str
    started_at: datetime | None
    completed_at: datetime | None


class ContextPackageItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    brief_id: uuid.UUID | None
    task_type: str
    manifest: dict[str, Any]
    rendered_context: dict[str, Any]
    omissions: list[dict[str, Any]]
    selection_policy_version: str
    manifest_hash: str
    char_count: int
    created_at: datetime


class AgentTaskRunItem(_StrictModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    project_id: uuid.UUID
    conversation_id: uuid.UUID | None
    parent_run_id: uuid.UUID | None
    context_package_id: uuid.UUID | None
    task_type: str
    objective: str
    requested_outputs: list[str]
    task_policy_version: str
    allowed_tools: list[str]
    resource_scope: dict[str, Any]
    industry_pack_id: str
    industry_pack_version: str
    status: str
    plan: list[dict[str, Any]]
    result: dict[str, Any] | None
    validation: dict[str, Any] | None
    decisions: list[dict[str, Any]]
    provider_adapter: str
    endpoint_host: str
    model: str
    capability_snapshot: dict[str, Any]
    instruction_version: str
    skill_version: str
    usage: dict[str, int] | None
    latency_ms: int | None
    error_code: str
    error_detail: str
    completed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime
    steps: list[AgentStepItem] = Field(default_factory=list)
    context: ContextPackageItem | None = None


class TaskCatalogItem(_StrictModel):
    task_type: str
    title: str
    description: str
    allowed_tools: list[str]
    required_scope: list[str]
    requested_outputs: list[str]
    max_steps: int
    max_tool_calls: int


class ToolCatalogItem(_StrictModel):
    name: str
    version: str
    domain: str
    kind: str
    description: str
    idempotent: bool
    external_effect: bool
    maximum_result_items: int


class AgentCapabilities(_StrictModel):
    configured: bool
    provider_adapter: str
    endpoint_host: str
    model: str
    model_capabilities: dict[str, Any]
    policy_version: str
    context_policy_version: str
    tool_registry_version: str
    task_catalog: list[TaskCatalogItem]
    tool_catalog: list[ToolCatalogItem]


class CorrectionProposalAccept(_StrictModel):
    reason: str = Field(min_length=1, max_length=512)


class PriorityOverrideWithdraw(_StrictModel):
    reason: str = Field(min_length=1, max_length=512)
