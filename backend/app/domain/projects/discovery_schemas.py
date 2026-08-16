"""Typed contracts for persisted onboarding discovery."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, get_args
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.brand_discovery import (
    BUSINESS_MODELS,
    BUYER_REGISTERS,
    DISCOVERY_CONFIRM_DOMAIN_MAX_CHARS,
    DISCOVERY_CONFIRM_MAX_DOMAINS,
    KNOWLEDGE_STRENGTHS,
    MARKET_SCOPES,
    PRICE_TIERS,
)
from app.core.config.projects import MAX_PROJECT_COMPETITORS
from app.domain.projects.normalization import normalize_primary_market
from app.domain.projects.schemas import CompetitorInput

ConfirmedDomain = Annotated[
    str, Field(min_length=1, max_length=DISCOVERY_CONFIRM_DOMAIN_MAX_CHARS)
]
PriceTier = Literal["budget", "mid_market", "premium", "luxury", "unknown"]
assert set(get_args(PriceTier)) == set(PRICE_TIERS)

# Business-context facets. Declared here rather than in the onboarding package
# because `onboarding/__init__` pulls in the service, which imports this module.
# Each is locked to its config vocabulary so the two cannot drift.
BusinessModel = Literal[
    "b2b_saas",
    "marketplace",
    "d2c_product",
    "retail",
    "local_service",
    "professional_service",
    "regulated_finance",
    "healthcare_provider",
    "education_provider",
]
MarketScope = Literal["global", "national", "regional", "local"]
KnowledgeStrength = Literal["strong", "weak", "none"]
BuyerRegister = Literal[
    "terse_transactional",
    "research_comparative",
    "advice_seeking",
    "local_urgent",
]
assert set(get_args(BusinessModel)) == set(BUSINESS_MODELS)
assert set(get_args(MarketScope)) == set(MARKET_SCOPES)
assert set(get_args(KnowledgeStrength)) == set(KNOWLEDGE_STRENGTHS)
assert set(get_args(BuyerRegister)) == set(BUYER_REGISTERS)


class BrandDiscoveryCreate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=255)
    website_url: str = Field(min_length=1, max_length=1024)
    industry: str = Field(default="General", max_length=255)
    subindustry: str = Field(default="", max_length=255)
    primary_market: str = Field(min_length=2, max_length=8)
    language_code: str = Field(default="en", max_length=16)

    _normalize_primary_market = field_validator("primary_market", mode="before")(
        normalize_primary_market
    )


class DiscoveryEvidence(BaseModel):
    source_url: str
    capture_method: str
    confidence: float = Field(ge=0, le=1)
    captured_at: datetime
    supports: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    method: str = ""


class DiscoveryProfile(BaseModel):
    """The reviewable business context, wire-side.

    `category` and `category_terms` are open vocabulary and carry the real
    specificity -- they are what reaches prompt generation. The remaining facets
    are a closed vocabulary that routes archetype selection and buyer register.
    See `onboarding.context_profile` for why a fixed industry tree cannot do
    this job.
    """

    description: str = ""
    positioning: str = ""
    products_services: list[str] = Field(default_factory=list)
    target_audience: str = ""
    industry: str = ""
    business_type: Literal["b2b", "b2c", "both"] = "both"
    price_tier: PriceTier = "unknown"
    field_confidence: dict[str, float] = Field(default_factory=dict)

    # --- resolved business context ---------------------------------------
    category: str = ""
    # Alternative phrasings of the same category, offered to the user as
    # choices. Onboarding is a confirmation step, not an authoring step: people
    # will pick the right label out of a list and will not write one.
    category_options: list[str] = Field(default_factory=list, max_length=5)
    category_aliases: list[str] = Field(default_factory=list)
    category_terms: list[str] = Field(default_factory=list)
    jobs_to_be_done: list[str] = Field(default_factory=list)
    sector: str = "Other"
    business_model: BusinessModel = "d2c_product"
    # Real businesses are often composite: Urban Company is a marketplace AND a
    # local service, and the half a single enum discards is exactly the half
    # that drives a whole family of buyer queries ("plumber near me").
    secondary_business_models: list[BusinessModel] = Field(default_factory=list)
    market_scope: MarketScope = "national"
    buyer_register: BuyerRegister = "research_comparative"
    buyer_roles: list[str] = Field(default_factory=list)
    service_areas: list[str] = Field(default_factory=list)
    knowledge_strength: KnowledgeStrength = "none"


class ConfirmedDiscoveryProfile(DiscoveryProfile):
    """The minimum structured ICP a person must confirm before generation."""

    positioning: str = Field(min_length=1)
    products_services: list[str] = Field(min_length=1)
    target_audience: str = Field(min_length=1)

    @field_validator("positioning", "target_audience")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("confirmed ICP text must not be blank")
        return value

    @field_validator("products_services")
    @classmethod
    def require_nonblank_products(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("products_services must contain a non-blank value")
        return cleaned


class CompetitorQualification(BaseModel):
    product_substitutability: float = Field(ge=0, le=1)
    customer_use_case_overlap: float = Field(ge=0, le=1)
    geographic_relevance: float = Field(ge=0, le=1)
    question_visibility: float = Field(ge=0, le=1)


class DiscoveryCompetitorSuggestion(CompetitorInput):
    qualification: CompetitorQualification | None = None
    # What kind of company THIS competitor is. The four qualification dimensions
    # all measure overlap and none of them measures *kind*, so a services firm
    # scored the platforms it implements as near-perfect substitutes -- every
    # dimension agreed, and the set was still wrong. Left unset when the model
    # declines to commit, in which case the peer-class filter abstains.
    business_model: BusinessModel | None = None
    reasoning: str = Field(default="", max_length=2000)
    evidence_urls: list[str] = Field(
        default_factory=list, max_length=DISCOVERY_CONFIRM_MAX_DOMAINS
    )
    confidence: float = Field(default=0, ge=0, le=1)

    @field_validator("evidence_urls")
    @classmethod
    def validate_evidence_urls(cls, values: list[str]) -> list[str]:
        for value in values:
            parts = urlsplit(value)
            if parts.scheme not in {"http", "https"} or not parts.hostname:
                raise ValueError("evidence_urls must contain HTTP(S) URLs")
        return values


class DiscoveryPromptSuggestion(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    theme: str = Field(default="", max_length=255)
    intent: Literal["discovery", "comparison", "purchase", "service", "local"]
    cohort: Literal["market_visibility", "brand_relevant"]


class BrandDiscoveryProgress(BaseModel):
    phase: Literal[
        "opening_website",
        "understanding_business",
        "finding_competitors",
        "preparing_review",
        "complete",
    ]
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    pages_read: int = Field(default=0, ge=0)
    competitors_found: int = Field(default=0, ge=0)
    prompts_prepared: int = Field(default=0, ge=0)
    updated_at: datetime


class DiscoveryCompetitorCandidates(BaseModel):
    competitors: list[DiscoveryCompetitorSuggestion] = Field(
        default_factory=list, max_length=MAX_PROJECT_COMPETITORS
    )


class BrandDiscoveryComplete(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    profile: ConfirmedDiscoveryProfile
    domains: list[ConfirmedDomain] = Field(
        min_length=1, max_length=DISCOVERY_CONFIRM_MAX_DOMAINS
    )
    competitors: list[CompetitorInput] = Field(
        default_factory=list, max_length=MAX_PROJECT_COMPETITORS
    )


class BrandDiscoveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None
    status: str
    progress: BrandDiscoveryProgress
    input_data: dict
    profile: DiscoveryProfile
    domains: list[str]
    competitors: list[DiscoveryCompetitorSuggestion]
    topics: list[str]
    prompt_suggestions: list[DiscoveryPromptSuggestion]
    evidence: list[DiscoveryEvidence]
    warnings: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    error_code: str = ""
    created_at: datetime
    updated_at: datetime


class BrandDiscoveryCatalogResponse(BaseModel):
    business_types: list[str]
    price_tiers: list[str]
    required_fields: list[str]
    optional_fields: list[str]
    capture_methods: list[str]
    maximum_competitors: int
    industries: list[str]
    subindustries: dict[str, list[str]]
    prompt_cohorts: list[str]


class BrandDiscoveryCompleteResponse(BaseModel):
    project_id: uuid.UUID
    crawl_id: uuid.UUID | None = None
    activation_state: Literal["queued"] = "queued"
    page_limit: int | None = None
    warnings: list[str] = Field(default_factory=list)
