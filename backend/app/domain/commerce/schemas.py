"""Public `/commerce/*` request and persisted-projection schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.config.commerce_catalog import (
    COMMERCE_IMPORT_MAX_BYTES,
    COMMERCE_PROMPTS_DEFAULT,
    COMMERCE_PROMPTS_MAX,
    COMMERCE_PROMPTS_MIN,
)

TargetKind = Literal["category", "product"]


class CommerceTarget(BaseModel):
    kind: TargetKind
    id: uuid.UUID


class CategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    role: Literal["hub", "leaf", "unknown"]
    canonical_url: str
    product_count: int = 0
    source_analysis_id: uuid.UUID | None
    projector_version: str


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    canonical_url: str
    name: str
    description: str
    brand: str
    price: float | None
    currency: str
    sku: str
    gtin: str
    mpn: str
    observed_external_id: str
    variants: list = Field(default_factory=list)
    attributes: dict = Field(default_factory=dict)
    field_sources: dict = Field(default_factory=dict)
    lifecycle_state: Literal["active", "archived"]
    category_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CatalogResponse(BaseModel):
    products: list[ProductResponse] = Field(default_factory=list)
    categories: list[CategoryResponse] = Field(default_factory=list)
    projection_tasks: dict[str, int] = Field(default_factory=dict)


class CatalogImportRequest(BaseModel):
    filename: str = Field(default="catalog.csv", max_length=255)
    content_type: str = Field(default="text/csv", max_length=128)
    content: str = Field(max_length=COMMERCE_IMPORT_MAX_BYTES)


class CatalogRowOutcome(BaseModel):
    row_number: int
    status: Literal["created", "updated", "unchanged", "rejected"]
    product_id: uuid.UUID | None = None
    error_code: str = ""
    detail: str = ""


class CatalogImportResponse(BaseModel):
    import_id: uuid.UUID
    created: int
    updated: int
    unchanged: int
    rejected: int
    row_outcomes: list[CatalogRowOutcome] = Field(default_factory=list)


class CatalogEditRequest(BaseModel):
    canonical_url: str | None = Field(default=None, max_length=2048)
    name: str | None = Field(default=None, max_length=512)
    description: str | None = None
    brand: str | None = Field(default=None, max_length=255)
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    sku: str | None = Field(default=None, max_length=255)
    gtin: str | None = Field(default=None, max_length=64)
    mpn: str | None = Field(default=None, max_length=255)
    variants: list | None = None
    attributes: dict | None = None
    category_ids: list[uuid.UUID] | None = None
    lifecycle_state: Literal["active", "archived"] | None = None


class DiscoveryRequest(BaseModel):
    targets: list[CommerceTarget] = Field(min_length=1)


class DiscoveryResponse(BaseModel):
    task_ids: list[uuid.UUID] = Field(default_factory=list)


class CompetitorCandidateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_kind: TargetKind
    target_id: uuid.UUID
    canonical_url: str
    product_name: str
    brand_name: str
    evidence: dict
    source_kind: str
    state: Literal["pending", "approved", "rejected", "excluded"]
    decision_at: datetime | None


class CompetitorDecisionRequest(BaseModel):
    decision: Literal["approved", "rejected"]


class BuyerPromptGenerateRequest(BaseModel):
    targets: list[CommerceTarget] = Field(min_length=1)
    count: int = Field(
        default=COMMERCE_PROMPTS_DEFAULT,
        ge=COMMERCE_PROMPTS_MIN,
        le=COMMERCE_PROMPTS_MAX,
    )


class BuyerPromptManualRequest(BaseModel):
    target: CommerceTarget
    text: str = Field(min_length=1, max_length=2000)


class BuyerPromptResponse(BaseModel):
    id: uuid.UUID
    target: CommerceTarget
    text: str
    enabled: bool
    approved_at: datetime | None


class BuyerPromptDecisionRequest(BaseModel):
    approved: bool


class RecommendationObservationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_id: uuid.UUID
    target_kind: TargetKind
    target_id: uuid.UUID
    product_id: uuid.UUID | None
    competitor_candidate_id: uuid.UUID | None
    observed_product: str
    observed_brand: str
    classification: str
    observed_title: str
    observed_price: float | None
    observed_currency: str
    merchant_url: str
    merchant_domain: str
    surface_kind: Literal["recommendation", "shopping_result"]
    rank: int | None
    order_observable: bool
    match_confidence: float
    artifact_id: uuid.UUID


class ShelfMetricResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_id: uuid.UUID
    target_kind: TargetKind
    target_id: uuid.UUID
    product_visibility: float
    share_of_shelf: float | None
    average_shelf_position: float | None
    first_position_win_rate: float | None
    successful_execution_count: int
    recognized_slot_count: int
    ranked_execution_count: int
    formula_version: str
    created_at: datetime


class ShelfResponse(BaseModel):
    snapshots: list[ShelfMetricResponse] = Field(default_factory=list)
    observations: list[RecommendationObservationResponse] = Field(default_factory=list)


class RecommendationSpan(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    brand: str = Field(default="", max_length=255)
    url: str = Field(default="", max_length=2048)
    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    surface_kind: Literal["recommendation", "shopping_result"] = "recommendation"
    rank: int | None = Field(default=None, ge=1)
    order_observable: bool = False

    @model_validator(mode="after")
    def rank_requires_order(self) -> RecommendationSpan:
        if (self.rank is None) != (not self.order_observable):
            raise ValueError("rank is present exactly when order is observable")
        return self
