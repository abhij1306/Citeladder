"""Durable Growth Agent orchestration state.

The agent owns conversations and bounded execution provenance only. Domain facts,
content, demand, audits, opportunities, and corrections remain in their existing
owners; result references below point back to those artifacts.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

_WORKSPACE_FK = "workspaces.id"
_PROJECT_FK = "projects.id"
_USER_FK = "users.id"
_TASK_RUN_FK = "agent_task_runs.id"
_SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AgentConversation(Base):
    """Project-scoped conversation continuity; messages are never project facts."""

    __tablename__ = "agent_conversations"
    __table_args__ = (
        Index(
            "ix_agent_conversations_project_updated", "project_id", "updated_at", "id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255), default="New conversation")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_USER_FK, ondelete=_SET_NULL), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AgentMessage(Base):
    """Append-only user/assistant message with artifact citations."""

    __tablename__ = "agent_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="ck_agent_message_role"),
        Index(
            "ix_agent_messages_conversation_created",
            "conversation_id",
            "created_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    task_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_TASK_RUN_FK, ondelete=_SET_NULL, use_alter=True),
        nullable=True,
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_USER_FK, ondelete=_SET_NULL), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class AgentTaskRun(Base):
    """One bounded, idempotent orchestration run and its frozen result."""

    __tablename__ = "agent_task_runs"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "idempotency_key", name="uq_agent_run_ws_idempotency"
        ),
        CheckConstraint(
            "status IN ('draft','validating','queued','planning','running',"
            "'awaiting_user','awaiting_task','completed','partially_completed',"
            "'failed','cancelled')",
            name="ck_agent_task_run_status",
        ),
        Index("ix_agent_task_runs_project_created", "project_id", "created_at", "id"),
        Index("ix_agent_task_runs_status", "status", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_USER_FK, ondelete=_SET_NULL), nullable=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_conversations.id", ondelete=_SET_NULL),
        nullable=True,
        index=True,
    )
    parent_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_TASK_RUN_FK, ondelete=_SET_NULL),
        nullable=True,
    )
    context_package_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("task_context_packages.id", ondelete=_SET_NULL, use_alter=True),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    task_type: Mapped[str] = mapped_column(String(64), index=True)
    objective: Mapped[str] = mapped_column(Text)
    requested_outputs: Mapped[list] = mapped_column(JSONB, default=list)
    task_policy_version: Mapped[str] = mapped_column(String(32))
    allowed_tools: Mapped[list] = mapped_column(JSONB, default=list)
    resource_scope: Mapped[dict] = mapped_column(JSONB, default=dict)
    industry_pack_id: Mapped[str] = mapped_column(String(64), default="")
    industry_pack_version: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="draft")
    plan: Mapped[list] = mapped_column(JSONB, default=list)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    decisions: Mapped[list] = mapped_column(JSONB, default=list)
    provider_adapter: Mapped[str] = mapped_column(String(64), default="")
    endpoint_host: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    capability_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    instruction_version: Mapped[str] = mapped_column(String(64), default="")
    skill_version: Mapped[str] = mapped_column(String(64), default="")
    usage: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class AgentTaskStep(Base):
    """Persisted plan step; mutable state with immutable attempts beneath it."""

    __tablename__ = "agent_task_steps"
    __table_args__ = (
        UniqueConstraint("task_run_id", "ordinal", name="uq_agent_step_run_ordinal"),
        CheckConstraint(
            "status IN ('pending','running','awaiting_user','awaiting_task',"
            "'completed','failed','cancelled','skipped')",
            name="ck_agent_task_step_status",
        ),
        Index("ix_agent_task_steps_status_child", "status", "child_task_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_TASK_RUN_FK, ondelete="CASCADE"),
        index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(128))
    tool_name: Mapped[str] = mapped_column(String(128))
    tool_version: Mapped[str] = mapped_column(String(32))
    tool_kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    child_task_kind: Mapped[str] = mapped_column(String(64), default="")
    child_task_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    error_detail: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class AgentToolAttempt(Base):
    """Append-only audit record for one actual typed-tool invocation."""

    __tablename__ = "agent_tool_attempts"
    __table_args__ = (
        UniqueConstraint(
            "step_id", "attempt_number", name="uq_agent_tool_attempt_number"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_TASK_RUN_FK, ondelete="CASCADE"),
        index=True,
    )
    step_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_task_steps.id", ondelete="CASCADE"),
        index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(128))
    tool_version: Mapped[str] = mapped_column(String(32))
    input: Mapped[dict] = mapped_column(JSONB, default=dict)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str] = mapped_column(String(64), default="")
    retryable: Mapped[bool] = mapped_column(default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class PriorityOverrideProposal(Base):
    """Visible, reversible proposal beside the unchanged deterministic order."""

    __tablename__ = "priority_override_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active','withdrawn')", name="ck_priority_override_status"
        ),
        Index("ix_priority_override_project_created", "project_id", "created_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_WORKSPACE_FK, ondelete="CASCADE"),
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), index=True
    )
    task_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(_TASK_RUN_FK, ondelete="CASCADE"),
        index=True,
    )
    deterministic_order: Mapped[list] = mapped_column(JSONB)
    proposed_order: Mapped[list] = mapped_column(JSONB)
    reasoning: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey(_USER_FK, ondelete=_SET_NULL), nullable=True
    )
    withdrawn_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
