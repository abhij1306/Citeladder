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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.content import (
    CONTENT_DEFAULT_OUTPUT_TYPE,
    CONTENT_DEFAULT_SKILL,
    CONTENT_FEEDBACK_REASONS,
    CONTENT_HISTORY_TITLE_MAX_LEN,
    CONTENT_OUTPUT_TYPES,
    CONTENT_PROMPT_MAX_LEN,
    CONTENT_SKILL_CATALOG_VERSION,
    CONTENT_SKILL_REGISTRY,
    CONTENT_SKILLS,
)


class ContentSkillView(BaseModel):
    """One reusable output format, as offered to the picker.

    Carries the user-facing copy plus the craft constraints, so the client can
    explain a skill without duplicating any directive text of its own.
    """

    id: str
    label: str
    channel: str
    description: str
    structure: list[str] = []
    tone: str = ""
    length_hint: str = ""


class ContentSkillCatalog(BaseModel):
    """The full skill catalog and the version that produced its directives."""

    version: str
    default_skill_id: str
    skills: list[ContentSkillView]


def skill_catalog() -> ContentSkillCatalog:
    """Project the config registry onto the wire, in registry (UI) order."""
    return ContentSkillCatalog(
        version=CONTENT_SKILL_CATALOG_VERSION,
        default_skill_id=CONTENT_DEFAULT_SKILL,
        skills=[
            ContentSkillView(
                id=definition.id,
                label=definition.label,
                channel=definition.channel,
                description=definition.description,
                structure=list(definition.structure),
                tone=definition.tone,
                length_hint=definition.length_hint,
            )
            for definition in CONTENT_SKILL_REGISTRY.values()
        ],
    )


class ContentGenerationCreate(BaseModel):
    """`POST /content/generations` body (workspace resolved from session)."""

    project_id: uuid.UUID
    prompt: str
    skill_id: str = CONTENT_DEFAULT_SKILL
    opportunity_id: uuid.UUID | None = None
    output_type: str = CONTENT_DEFAULT_OUTPUT_TYPE

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
    grounding_status: str
    requested_model: str
    returned_model: str | None = None
    provider: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str = ""
    prompt_preview: str = ""


class ContentContextSummary(BaseModel):
    """Bounded public provenance: counts and URLs, never the rendered blocks."""

    version: str = ""
    crawl_page_count: int = 0
    crawl_urls: list[str] = []
    crawl_completed_at: str | None = None
    brand_fields: list[str] = []
    search_connected: bool = False
    omissions: list[dict] = []


class ContentContextPreview(BaseModel):
    """Pre-flight answer for the composer indicator: what will ground a draft.

    A missing crawl or an unconnected Search Console is a neutral absence, not
    a fault — the client renders it as such.
    """

    crawl_available: bool = False
    crawl_page_count: int = 0
    crawl_completed_at: str | None = None
    brand_fields: list[str] = []
    search_connected: bool = False


class ContentGenerationDetail(BaseModel):
    """Full projection of one generation (never the API key)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    status: str
    output_type: str
    skill_id: str = CONTENT_DEFAULT_SKILL
    opportunity_id: uuid.UUID | None = None
    skill_version: str = ""
    feedback: str | None = None
    feedback_reason: str = ""
    feedback_at: datetime | None = None
    grounding_status: str
    requested_model: str
    returned_model: str | None = None
    provider: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    error_code: str = ""
    prompt_preview: str = ""
    prompt: str
    grounding_summary: ContentContextSummary
    finish_reason: str | None = None
    output_truncated: bool = False
    output_text: str | None = None
    usage: dict | None = None
    latency_ms: int | None = None
    error_detail: str = ""
    generator_version: str = ""


class ContentFeedbackRequest(BaseModel):
    feedback: str = Field(pattern="^(accepted|rejected)$")
    #: Optional rejection category; ignored on an acceptance.
    reason: str = ""

    @field_validator("reason")
    @classmethod
    def _reason_known(cls, value: str) -> str:
        if value and value not in CONTENT_FEEDBACK_REASONS:
            raise ValueError(f"unknown feedback reason: {value}")
        return value
