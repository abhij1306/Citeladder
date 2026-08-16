"""The business context resolved at onboarding.

This replaces the industry / sub-industry pair. The measured problem with a
taxonomy was never its depth: Feedonomics has a plausible leaf
(``Software > Commerce Technology``) and still produced prompts about "analytics
software" and "team collaboration", because the leaf carries a fixed topic list
that has nothing to do with the brand. Depth cannot fix that; only brand-derived
vocabulary can.

So the context is split three ways:

``sector``
    coarse, stable, reporting and benchmarking only -- never selects prompts.
``facets``
    a closed vocabulary (business model, market scope, buyer type, price tier)
    that *routes* which archetypes and which buyer register apply.
``category`` and ``category_terms``
    open vocabulary written by the model and grounded in site evidence. This is
    what actually reaches prompt generation.

Every field carries confidence, and ``knowledge_strength`` records how much the
model actually knew about the brand. Thin knowledge plus thin evidence must
produce fewer, lower-confidence facts rather than confident invention -- a brand
being invisible to answer engines is a finding, not a failure to paper over.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field, field_validator

from app.core.config.brand_discovery import BUSINESS_TYPES, PRICE_TIERS, SECTORS
from app.domain.projects.discovery_schemas import (
    BusinessModel,
    BuyerRegister,
    KnowledgeStrength,
    MarketScope,
)

BuyerType = Literal["b2b", "b2c", "both"]
assert set(get_args(BuyerType)) == set(BUSINESS_TYPES)

MAX_CATEGORY_TERMS = 12
MAX_JOBS = 6
MAX_ALIASES = 6
MAX_BUYER_ROLES = 4
MAX_SERVICE_AREAS = 8


def _clean_terms(values: list[str], limit: int) -> list[str]:
    """De-duplicate case-insensitively, preserve order, and bound the length."""
    seen: set[str] = set()
    cleaned: list[str] = []
    for value in values:
        text = " ".join(str(value).split())
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
    return cleaned[:limit]


class BusinessContextProfile(BaseModel):
    """What the business is, in the terms its buyers would recognise."""

    # --- open vocabulary: the part that reaches prompt generation ---------
    category: str = Field(default="", max_length=160)
    category_aliases: list[str] = Field(default_factory=list)
    category_terms: list[str] = Field(default_factory=list)
    jobs_to_be_done: list[str] = Field(default_factory=list)

    # --- closed facets: the part that routes archetypes ------------------
    sector: str = Field(default="Other")
    business_model: BusinessModel = "d2c_product"
    market_scope: MarketScope = "national"
    buyer_type: BuyerType = "both"
    price_tier: str = "unknown"
    buyer_register: BuyerRegister = "research_comparative"
    buyer_roles: list[str] = Field(default_factory=list)
    service_areas: list[str] = Field(default_factory=list)

    # --- existing ICP fields, unchanged in meaning ------------------------
    description: str = ""
    positioning: str = ""
    products_services: list[str] = Field(default_factory=list)
    target_audience: str = ""

    # --- provenance -------------------------------------------------------
    knowledge_strength: KnowledgeStrength = "none"
    field_confidence: dict[str, float] = Field(default_factory=dict)

    @field_validator("sector")
    @classmethod
    def _known_sector(cls, value: str) -> str:
        # An unrecognised sector degrades to "Other" rather than failing the
        # whole envelope: sector is a reporting label, never a gate.
        return value if value in SECTORS else "Other"

    @field_validator("price_tier")
    @classmethod
    def _known_price_tier(cls, value: str) -> str:
        return value if value in PRICE_TIERS else "unknown"

    @field_validator("category_aliases")
    @classmethod
    def _bounded_aliases(cls, value: list[str]) -> list[str]:
        return _clean_terms(value, MAX_ALIASES)

    @field_validator("category_terms")
    @classmethod
    def _bounded_terms(cls, value: list[str]) -> list[str]:
        return _clean_terms(value, MAX_CATEGORY_TERMS)

    @field_validator("jobs_to_be_done")
    @classmethod
    def _bounded_jobs(cls, value: list[str]) -> list[str]:
        return _clean_terms(value, MAX_JOBS)

    @field_validator("buyer_roles")
    @classmethod
    def _bounded_roles(cls, value: list[str]) -> list[str]:
        return _clean_terms(value, MAX_BUYER_ROLES)

    @field_validator("service_areas")
    @classmethod
    def _bounded_areas(cls, value: list[str]) -> list[str]:
        return _clean_terms(value, MAX_SERVICE_AREAS)

    def prompt_categories(self) -> list[str]:
        """Vocabulary for the `{category}` slot, brand-derived not table-derived.

        This is the single most important behaviour change in the rebuild: the
        old generator filled this slot from a fixed per-industry topic list, so
        every Software project asked about "analytics software". Here the terms
        come from the brand's own resolved category.
        """
        terms = [*self.category_terms, *self.products_services]
        if self.category:
            terms.append(self.category)
        return _clean_terms(terms, MAX_CATEGORY_TERMS)

    def is_thin(self) -> bool:
        """True when there is not enough grounding to fill a full portfolio.

        Callers should shorten the portfolio and say why, rather than padding it
        with confident-sounding invention.
        """
        return self.knowledge_strength == "none" or not self.prompt_categories()

    def thinness_reason(self) -> str:
        if self.knowledge_strength == "none":
            return "the model had no reliable knowledge of this brand"
        if not self.prompt_categories():
            return "no product or category vocabulary could be grounded"
        return ""
