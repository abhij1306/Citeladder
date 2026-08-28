# Prompt-set + prompt request/response schemas (Q3=A; ids string UUID).
#
# The dedicated prompt resource: prompt sets group prompts; each prompt carries
# text/theme/intent + cohort/enabled/origin fields. Adapted from the reference
# ``PromptInput`` and extended with the columns CiteLadder's prompt model adds.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from app.core.config.http import (
    PROMPT_IMPORT_MAX_ROWS,
    PROMPT_INTENT_MAX_CHARS,
    PROMPT_TEXT_MAX_CHARS,
)
from app.core.config.prompts import (
    PROMPT_COHORTS,
    PROMPT_STATUSES,
    prompt_generation_settings,
)

PromptIntent = Literal["", "discovery", "comparison", "purchase", "service", "local"]
# ``Literal`` requires inline literals for static checkers, so the values are
# repeated here; this guard keeps the alias in lock-step with the config
# constants (PROMPT_STATUS_*) so they cannot drift silently.
PromptStatus = Literal["active", "archived"]
# Same inline-literal rule as above: the values mirror ``PROMPT_ORIGIN_MANUAL``
# and ``PROMPT_ORIGIN_GENERATED`` in ``config/projects.py``. ``imported`` is not
# offered here — CSV import sets its own origin server-side.
PromptOrigin = Literal["manual", "generated"]
PromptCohort = Literal["core", "brand_diagnostic", "comparison", "commerce"]
assert set(get_args(PromptStatus)) == PROMPT_STATUSES
# Keep the API literal and persisted cohort catalog in lock-step.
assert set(get_args(PromptCohort)) == PROMPT_COHORTS


# --------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------
class PromptInput(BaseModel):
    """A single prompt on create/import. ``intent`` is validated + casefolded
    by the service; an unknown intent normalizes to ``""``.

    ``topic_id`` files the prompt under an existing topic at creation time, so a
    caller that creates topics first (onboarding, mirroring what ``/generate``
    does in one transaction) does not have to create-then-PATCH every prompt.
    The service validates it against the prompt's own project exactly as the
    update path does; ``None`` leaves the prompt untopiced.
    """

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=PROMPT_TEXT_MAX_CHARS)
    theme: str = Field(default="", max_length=255)
    intent: str = Field(default="", max_length=PROMPT_INTENT_MAX_CHARS)
    cohort: PromptCohort = "core"
    enabled: bool = True
    topic_id: uuid.UUID | None = None
    # Provenance. ``manual`` (the default) is free text a human typed and stays
    # subject to the topical-binding gate. ``generated`` marks a prompt the
    # backend's own agent produced from verified brand-website evidence — the
    # onboarding flow — which is constrained at generation time instead (see
    # ``create_prompt``).
    #
    # This is a CLIENT-SUPPLIED claim, so it is not trusted on its own: the
    # service re-verifies that the text really came from a generation the
    # backend performed before honouring the exemption.
    origin: PromptOrigin = "manual"
    # Backend-issued HMAC over this prompt's text, returned by the suggestion
    # endpoints. Required for ``origin="generated"`` to be honoured; ignored
    # otherwise. Without a valid receipt the prompt is stored as ``manual`` and
    # the binding gate applies as normal.
    generation_receipt: str = Field(default="", max_length=128)


class PromptCreate(PromptInput):
    prompt_set_id: uuid.UUID


class PromptUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = Field(
        default=None, min_length=1, max_length=PROMPT_TEXT_MAX_CHARS
    )
    theme: str | None = Field(default=None, max_length=255)
    intent: str | None = Field(default=None, max_length=PROMPT_INTENT_MAX_CHARS)
    cohort: PromptCohort | None = None
    enabled: bool | None = None
    status: PromptStatus | None = None
    topic_id: uuid.UUID | None = None


class PromptImport(BaseModel):
    """CSV bulk-create payload: already-parsed prompt rows.

    The browser parses the CSV at F7 and posts the rows here through the normal
    import path; the service persists them via the prompt resource with
    ``origin='imported'``.
    """

    prompts: list[PromptInput] = Field(
        default_factory=list, max_length=PROMPT_IMPORT_MAX_ROWS
    )


class PromptResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    prompt_set_id: uuid.UUID
    topic_id: uuid.UUID | None = None
    text: str
    theme: str
    intent: str
    # Empty for manual and imported prompts, which never went through the
    # buyer-query slot planner.
    buyer_stage: str = ""
    prompt_intent: str = ""
    cohort: PromptCohort
    branded: bool
    enabled: bool
    status: str
    origin: str
    generation_evidence: dict | None = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Prompt sets
# --------------------------------------------------------------------------
class PromptSetCreate(BaseModel):
    project_id: uuid.UUID
    name: str = Field(default="", max_length=255)
    description: str = Field(default="", max_length=1024)


class PromptSetUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=1024)


class PromptSetResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str = ""
    prompts: list[PromptResponse] = Field(default_factory=list)
    prompt_count: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Topics
# --------------------------------------------------------------------------
class TopicCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=1024)


class TopicUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)


class TopicResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str
    origin: str
    # Per-status prompt counts for the topics rail (projection, computed).
    active_count: int = 0
    proposed_count: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# AI generation + bulk review
# --------------------------------------------------------------------------
class PromptGenerateRequest(BaseModel):
    """Body for ``POST /prompt-sets/{id}/generate``.

    Prompt generation is an automatic bounded derivation. ``topic_id`` scopes
    generation to one existing topic; running or scheduling measurement remains
    the separate user decision.
    """

    count: int = Field(
        default_factory=lambda: prompt_generation_settings.default_count, ge=1
    )
    topic_id: uuid.UUID | None = None
    intents: list[PromptIntent] = Field(default_factory=list)
    cohort: PromptCohort = "core"


class PromptGenerateResponse(BaseModel):
    generated: list[PromptResponse] = Field(default_factory=list)
    topics: list[TopicResponse] = Field(default_factory=list)
    # What the caller asked for. A request can exceed what the selected topics
    # and archetypes can support, and returning fewer prompts with no
    # explanation is how a silent cap went unnoticed for a release.
    requested_count: int = 0
    # Total prompts dropped as duplicates: intra-response collapses (an
    # equivalent text repeated within one model response) plus DB
    # ``ON CONFLICT`` skips against pre-existing prompts in the set.
    dropped_duplicates: int = 0


class PromptBulkStatusRequest(BaseModel):
    """Bulk review transition (accept-all / archive-selected)."""

    prompt_ids: list[uuid.UUID] = Field(min_length=1)
    status: PromptStatus
