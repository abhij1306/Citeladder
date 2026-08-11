# Content-generation request/response DTOs (workspace-scoped, invariant 5).
#
# Wire contract for `/content/generations`. The list item is bounded (no
# ``output_text``); the detail is the full record. Neither ever carries the
# provider API key or a raw request body containing it (invariant 6) — the
# only provider fields exposed are provenance (requested/returned model,
# finish reason, usage, latency).
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.content import (
    CONTENT_DEFAULT_OUTPUT_TYPE,
    CONTENT_DEFAULT_SKILL,
    CONTENT_HISTORY_TITLE_MAX_LEN,
    CONTENT_OUTPUT_TYPES,
    CONTENT_PROMPT_MAX_LEN,
    CONTENT_SKILLS,
)


class ContentGenerationCreate(BaseModel):
    """`POST /content/generations` body (workspace resolved from session)."""

    project_id: uuid.UUID
    prompt: str
    skill_id: str = CONTENT_DEFAULT_SKILL
    opportunity_id: uuid.UUID | None = None
    output_type: str = CONTENT_DEFAULT_OUTPUT_TYPE
    website_context_enabled: bool = True
    brief_id: uuid.UUID | None = None

    @field_validator("prompt")
    @classmethod
    def _prompt_trimmed_bounded(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("prompt must not be empty")
        if len(trimmed) > CONTENT_PROMPT_MAX_LEN:
            raise ValueError(f"prompt exceeds {CONTENT_PROMPT_MAX_LEN} characters")
        return trimmed

    @field_validator("output_type")
    @classmethod
    def _output_type_known(cls, value: str) -> str:
        if value not in CONTENT_OUTPUT_TYPES:
            raise ValueError(f"unknown output_type: {value}")
        return value

    @field_validator("skill_id")
    @classmethod
    def _skill_known(cls, value: str) -> str:
        if value not in CONTENT_SKILLS:
            raise ValueError(f"unknown skill_id: {value}")
        return value


def prompt_preview(prompt: str) -> str:
    """Deterministic history label: first line, trimmed to the config cap."""
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else ""
    return first_line[:CONTENT_HISTORY_TITLE_MAX_LEN]


class ContentGenerationListItem(BaseModel):
    """Bounded history-list projection (never ``output_text``)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    output_type: str
    skill_id: str = CONTENT_DEFAULT_SKILL
    opportunity_id: uuid.UUID | None = None
    brief_id: uuid.UUID | None = None
    context_package_id: uuid.UUID | None = None
    website_context_status: str
    requested_model: str
    returned_model: str | None = None
    provider: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str = ""
    prompt_preview: str = ""


class WebsiteContextSummary(BaseModel):
    """Provenance for the frozen Website-context snapshot (which crawl,
    how fresh, which sources). Never page bodies, never the key."""

    crawl_id: str
    crawl_completed_at: str | None = None
    extractor_version: str = ""
    analyzer_version: str = ""
    page_count: int = 0
    char_count: int = 0
    site_url_ids: list[str] = []
    artifact_ids: list[str] = []
    content_hashes: list[str] = []


class ContentGenerationDetail(BaseModel):
    """Full projection of one generation (never the API key)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    output_type: str
    skill_id: str = CONTENT_DEFAULT_SKILL
    opportunity_id: uuid.UUID | None = None
    brief_id: uuid.UUID | None = None
    context_package_id: uuid.UUID | None = None
    skill_version: str = ""
    evidence_context: dict | None = None
    feedback: str | None = None
    feedback_at: datetime | None = None
    website_context_status: str
    requested_model: str
    returned_model: str | None = None
    provider: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str = ""
    prompt_preview: str = ""
    prompt: str
    website_context_enabled: bool
    website_context_summary: WebsiteContextSummary | None = None
    finish_reason: str | None = None
    output_truncated: bool = False
    output_text: str | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    error_detail: str = ""
    generator_version: str = ""
    validator_snapshot: dict | None = None


class ContentFeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(accepted|rejected)$")


class ContentStrategyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    site_snapshot_id: uuid.UUID
    demand_snapshot_id: uuid.UUID | None = None
    source_hash: str
    inventory_summary: dict
    coverage: dict
    priorities: list
    program: list
    limitations: list
    source_versions: dict
    created_at: datetime


class ContentInventoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    site_snapshot_id: uuid.UUID
    site_analysis_id: uuid.UUID
    site_url_id: uuid.UUID
    canonical_url: str
    page_kind: str
    purpose: dict
    coverage: dict
    evidence: dict
    source_versions: dict
    created_at: datetime


class ContentBriefCreate(BaseModel):
    project_id: uuid.UUID
    question_id: str = Field(min_length=1, max_length=128)
    kind: Literal["faq"] = Field(default="faq", max_length=32)
    target_url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=255)


class ContentBriefResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    strategy_snapshot_id: uuid.UUID | None = None
    prior_brief_id: uuid.UUID | None = None
    version: int
    identity_hash: str
    kind: str
    title: str
    target: dict
    requirements: dict
    allowed_facts: list
    prohibited_claims: list
    source_refs: list
    verification_criteria: list
    brief_builder_version: str
    evidence_hash: str
    created_at: datetime


class TaskContextResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    brief_id: uuid.UUID | None = None
    task_type: str
    manifest: dict
    rendered_context: dict
    omissions: list
    selection_policy_version: str
    manifest_hash: str
    char_count: int
    created_at: datetime


class BriefGenerationCreate(BaseModel):
    skill_id: str = Field(min_length=1, max_length=64)


class ContentValidationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    content_generation_id: uuid.UUID
    status: str
    blocking: bool
    checks: list
    validator_version: str
    brief_evidence_hash: str
    context_manifest_hash: str
    created_at: datetime


class ContentRevisionCreate(BaseModel):
    visible_content: str | None = None
    structured_data: dict | None = None


class ContentRevisionUpdate(BaseModel):
    visible_content: str = Field(min_length=1, max_length=100_000)
    structured_data: dict | None = None


class ContentRevisionTransitionRequest(BaseModel):
    state: str = Field(pattern="^(saved|published_claimed|discarded)$")
    target_url: str = Field(default="", max_length=2048)
    reason: str = Field(default="", max_length=512)


class ContentRevisionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    content_generation_id: uuid.UUID
    state: str
    visible_content: str
    structured_data: dict | None = None
    content_hash: str
    validation_snapshot: dict[str, Any]
    publication_target_url: str
    publication_claimed_at: datetime | None = None
    saved_at: datetime | None = None
    created_by_user_id: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime


class ContentVerificationCreate(BaseModel):
    site_snapshot_id: uuid.UUID


class ContentVerificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    revision_id: uuid.UUID
    site_snapshot_id: uuid.UUID
    demand_snapshot_id: uuid.UUID | None = None
    status: str
    requirements: list
    comparison: dict
    coverage: dict
    verifier_version: str
    created_at: datetime
