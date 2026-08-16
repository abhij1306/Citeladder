# Project request/response schemas (all ids string UUID; workspace-scoped).
#
# Adapted from the reference ``schemas/ai_visibility.py``
# (``AiVisibilityProjectCreate/Update``, ``CompetitorInput``) to UUID +
# workspace-scoped CiteLadder, and aligned to the committed frontend contract
# (``docs/frontend-architecture.md`` §7): brand aliases are carried nested under
# ``brand.aliases`` and the project response embeds its ``prompt_sets``.
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.brand_profile import (
    BRAND_PROFILE_PRODUCT_MAX_CHARS,
    BRAND_PROFILE_PRODUCTS_MAX_COUNT,
    BRAND_PROFILE_TEXT_MAX_CHARS,
)
from app.core.config.projects import (
    DEFAULT_BENCHMARK_MODE,
    DEFAULT_REPETITIONS,
    MAX_PROJECT_COMPETITORS,
    MAX_REPETITIONS,
    MIN_REPETITIONS,
)
from app.core.config.suggestions import (
    brand_suggestion_settings,
    prompt_suggestion_settings,
)
from app.domain.projects.normalization import normalize_primary_market
from app.domain.prompts.schemas import PromptSetResponse

BenchmarkMode = Literal["consumer_like", "controlled_localized", "forced_grounded"]

# The resolved business context is a small, known document; these bound what a
# client can persist into the JSONB column without pinning the exact field set,
# which is still settling.
BUSINESS_CONTEXT_MAX_KEYS = 32
BUSINESS_CONTEXT_MAX_CHARS = 8_000


BrandProfileOrigin = Literal["manual", "web_evidence", "ai_suggested"]
BrandProfileReviewState = Literal["unreviewed", "confirmed", "edited"]


# --------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------
class BrandInput(BaseModel):
    aliases: list[str] = Field(default_factory=list)


class BrandResponse(BaseModel):
    aliases: list[str] = Field(default_factory=list)
    logo_url: str | None = None


class CompetitorInput(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class CompetitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    logo_url: str | None = None


class ObservedCompetitorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_id: uuid.UUID
    name: str
    domain: str
    qualification_reason: str
    prompt_count: int
    engine_count: int
    market_relevant: bool
    analyzer_version: str
    source_analysis_ids: list[str] = Field(default_factory=list)
    source_artifact_ids: list[str] = Field(default_factory=list)
    status: str
    created_at: datetime


class BrandProfileFieldProvenance(BaseModel):
    origin: BrandProfileOrigin
    review_state: BrandProfileReviewState
    reviewed_by: uuid.UUID | None = None
    reviewed_at: datetime | None = None


class BrandProfileSources(BaseModel):
    description: BrandProfileFieldProvenance | None = None
    positioning: BrandProfileFieldProvenance | None = None
    products_services: BrandProfileFieldProvenance | None = None
    target_audience: BrandProfileFieldProvenance | None = None


class BrandProfileSourceArtifacts(BaseModel):
    description: uuid.UUID | None = None
    positioning: uuid.UUID | None = None
    products_services: uuid.UUID | None = None
    target_audience: uuid.UUID | None = None


class BrandKnowledgeFields(BaseModel):
    """The four brand-knowledge fields in their non-optional form.

    Shared by every request that carries brand knowledge as plain values with
    empty defaults (``ProjectCreate``, ``BrandContextRequest``).
    ``BrandProfileUpsert`` deliberately does NOT inherit this: its fields are
    ``| None`` because it is a PARTIAL upsert where "absent" and "cleared" must
    be distinguishable.
    """

    description: str = Field(default="", max_length=BRAND_PROFILE_TEXT_MAX_CHARS)
    positioning: str = Field(default="", max_length=BRAND_PROFILE_TEXT_MAX_CHARS)
    products_services: list[
        Annotated[str, Field(max_length=BRAND_PROFILE_PRODUCT_MAX_CHARS)]
    ] = Field(default_factory=list, max_length=BRAND_PROFILE_PRODUCTS_MAX_COUNT)
    target_audience: str = Field(default="", max_length=BRAND_PROFILE_TEXT_MAX_CHARS)
    # The resolved business context, carried from the confirmed discovery
    # profile. Bounded rather than free-form: this lands in a JSONB column, so an
    # unconstrained dict would let a client persist arbitrary payload size.
    business_context: dict[str, Any] = Field(
        default_factory=dict, max_length=BUSINESS_CONTEXT_MAX_KEYS
    )

    @field_validator("business_context")
    @classmethod
    def bound_business_context(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, default=str)) > BUSINESS_CONTEXT_MAX_CHARS:
            raise ValueError("business_context is too large")
        return value


class BrandProfileUpsert(BaseModel):
    """Human-authored partial upsert; every supplied field becomes manual."""

    description: str | None = Field(
        default=None, max_length=BRAND_PROFILE_TEXT_MAX_CHARS
    )
    positioning: str | None = Field(
        default=None, max_length=BRAND_PROFILE_TEXT_MAX_CHARS
    )
    products_services: (
        list[Annotated[str, Field(max_length=BRAND_PROFILE_PRODUCT_MAX_CHARS)]] | None
    ) = Field(default=None, max_length=BRAND_PROFILE_PRODUCTS_MAX_COUNT)
    target_audience: str | None = Field(
        default=None, max_length=BRAND_PROFILE_TEXT_MAX_CHARS
    )


class BrandProfileResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    brand_id: uuid.UUID
    description: str
    positioning: str
    products_services: list[str] = Field(default_factory=list)
    target_audience: str
    sources: BrandProfileSources = Field(default_factory=BrandProfileSources)
    source_artifact_ids: BrandProfileSourceArtifacts = Field(
        default_factory=BrandProfileSourceArtifacts
    )
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------
# Project requests
# --------------------------------------------------------------------------
class ProjectCreate(BrandKnowledgeFields):
    # Inherits description/positioning/products_services/target_audience:
    # brand knowledge is optional at create, and onboarding sends what it
    # derived from the brand's own website. That seeds the BrandProfile and
    # therefore the topical-binding vocabulary — without it the vocabulary is
    # just the brand name, and correct brand-NEUTRAL prompts (the only kind
    # that can measure a competitor) have nothing legitimate to bind against.
    name: str = Field(min_length=1, max_length=255)
    brand_name: str = Field(default="", max_length=255)
    brand: BrandInput = Field(default_factory=BrandInput)
    website_url: str = Field(default="", max_length=1024)
    industry: str = Field(default="General", max_length=255)
    subindustry: str = Field(default="", max_length=255)
    primary_market: str = Field(default="GLOBAL", max_length=8)
    owned_domains: list[str] = Field(default_factory=list)
    unintended_domains: list[str] = Field(default_factory=list)
    competitors: list[CompetitorInput] = Field(
        default_factory=list, max_length=MAX_PROJECT_COMPETITORS
    )
    country_code: str = Field(default="", max_length=8)
    language_code: str = Field(default="", max_length=16)
    benchmark_mode: BenchmarkMode = DEFAULT_BENCHMARK_MODE
    default_repetitions: int = Field(
        default=DEFAULT_REPETITIONS, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )

    _normalize_primary_market = field_validator("primary_market", mode="before")(
        normalize_primary_market
    )

    @property
    def brand_aliases(self) -> list[str]:
        return self.brand.aliases


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    brand_name: str | None = Field(default=None, max_length=255)
    brand: BrandInput | None = None
    website_url: str | None = Field(default=None, max_length=1024)
    industry: str | None = Field(default=None, max_length=255)
    subindustry: str | None = Field(default=None, max_length=255)
    primary_market: str | None = Field(default=None, max_length=8)
    owned_domains: list[str] | None = None
    unintended_domains: list[str] | None = None
    competitors: list[CompetitorInput] | None = Field(
        default=None, max_length=MAX_PROJECT_COMPETITORS
    )
    country_code: str | None = Field(default=None, max_length=8)
    language_code: str | None = Field(default=None, max_length=16)
    benchmark_mode: BenchmarkMode | None = None
    default_repetitions: int | None = Field(
        default=None, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )

    _normalize_primary_market = field_validator("primary_market", mode="before")(
        lambda value: None if value is None else normalize_primary_market(value)
    )


# --------------------------------------------------------------------------
# Brand suggestions (stateless — the setup form may be pre-save, so brand
# context travels in the body instead of a project id in the path)
# --------------------------------------------------------------------------
class BrandContextRequest(BrandKnowledgeFields):
    brand_name: str = Field(min_length=1, max_length=255)
    website_url: str = Field(default="", max_length=1024)
    brand_aliases: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=50
    )
    country_code: str = Field(default="", max_length=8)
    language_code: str = Field(default="", max_length=16)
    # Backend-enforced consent gate (mirrors PromptGenerateRequest): brand
    # evidence is only sent to the default agent when this is true.
    confirm_send_evidence: bool = False
    count: int = Field(
        default_factory=lambda: brand_suggestion_settings.default_count, ge=1
    )


class CompetitorSuggestRequest(BrandContextRequest):
    existing_competitor_names: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=200
    )


class OwnedDomainSuggestRequest(BrandContextRequest):
    existing_owned_domains: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=200
    )


class CompetitorSuggestResponse(BaseModel):
    competitors: list[CompetitorInput] = Field(default_factory=list)
    dropped_duplicates: int = 0


class OwnedDomainSuggestResponse(BaseModel):
    domains: list[str] = Field(default_factory=list)
    dropped_duplicates: int = 0


class PromptSuggestRequest(BrandContextRequest):
    # Prompts carry their own count knobs (``PROMPT_SUGGESTION_*``): a starting
    # prompt set wants a higher default/cap than a competitor or domain list.
    count: int = Field(
        default_factory=lambda: prompt_suggestion_settings.default_count, ge=1
    )
    # Optional competitor context (the form may already hold manually entered
    # competitors) — feeds the generation message's competitor line.
    competitor_names: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=200
    )
    existing_prompt_texts: list[Annotated[str, Field(max_length=1024)]] = Field(
        default_factory=list, max_length=200
    )


class PromptSuggestionItem(BaseModel):
    text: str = Field(min_length=1)
    theme: str = Field(default="", max_length=255)
    intent: str = ""
    # Proof the backend generated this text, to be echoed back on create so the
    # prompt is stored as ``generated`` and skips the topical-binding gate (see
    # ``domain/prompts/receipts.py``). Opaque to the client.
    generation_receipt: str = ""


class SuggestedTopicGroup(BaseModel):
    """One agent-proposed topic and the prompts it grouped under it.

    The agent generates prompts grouped by topic and the persisted ``/generate``
    flow keeps that structure as real ``Topic`` rows. This response preserves it
    too so a caller that persists suggestions (onboarding) can create the same
    topics rather than landing an untopiced prompt set — the two entry points
    must produce the same shape of data.
    """

    name: str = Field(min_length=1, max_length=255)
    prompts: list[PromptSuggestionItem] = Field(default_factory=list)


class PromptSuggestResponse(BaseModel):
    # Flat list, kept for callers that only want prompt text (and so this stays
    # backwards compatible). ``topics`` carries the same prompts grouped.
    prompts: list[PromptSuggestionItem] = Field(default_factory=list)
    topics: list[SuggestedTopicGroup] = Field(default_factory=list)
    dropped_duplicates: int = 0


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------
class ProjectResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    brand_name: str
    brand: BrandResponse
    website_url: str
    industry: str
    subindustry: str
    primary_market: str
    owned_domains: list[str] = Field(default_factory=list)
    unintended_domains: list[str] = Field(default_factory=list)
    competitors: list[CompetitorResponse] = Field(default_factory=list)
    prompt_sets: list[PromptSetResponse] = Field(default_factory=list)
    country_code: str
    language_code: str
    benchmark_mode: str
    default_repetitions: int
    has_commerce_evidence: bool = False
    created_at: datetime
    updated_at: datetime
