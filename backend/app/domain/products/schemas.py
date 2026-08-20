# Product-catalog request/response schemas (ids string UUID, invariant 5).
#
# ``ProductResponse`` embeds the computed per-SKU ``completeness`` (pure
# function of the row, config matrix) so the catalog badge is always in sync.
# ORM -> DTO mappers live here (the surface is small enough that a separate
# mappers module would be indirection).
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config.products import PRODUCT_IMPORT_MAX_ROWS
from app.domain.products.completeness import product_completeness
from app.models.product import CompetitorProduct, Product


def _empty_str_to_none(value: Any) -> Any:
    # The model stores "" for an unbound external_item_ref; the DTO
    # contract is null (the frontend schema is strict-nullable).
    return None if value == "" else value


def _clean_str_list(values: Any) -> list[str]:
    # A non-list is a client payload bug, not an empty list: silently coercing
    # it to [] would erase stored aliases on update instead of returning 422.
    if not isinstance(values, list):
        raise ValueError("must be a list of strings")
    return [str(value).strip() for value in values if str(value).strip()]


def _clean_aliases(value: Any) -> list[str]:
    return _clean_str_list(value)


def _clean_optional_aliases(value: Any) -> list[str] | None:
    if value is None:
        return None
    return _clean_str_list(value)


def _clean_currency(value: Any) -> Any:
    # Runs as a BEFORE validator: `max_length=3` is enforced on the raw input,
    # so padded codes like " usd " must be trimmed before the length check.
    return value.strip().upper() if isinstance(value, str) else value


class ProductVariant(BaseModel):
    """One variant value object inside ``Product.variants``."""

    name: str = Field(min_length=1, max_length=255)
    sku: str = Field(default="", max_length=128)
    price: float | None = Field(default=None, ge=0)


class ProductCompleteness(BaseModel):
    """Computed data-quality badge: present/total against the config matrix."""

    score: float
    present: int
    total: int
    missing: list[str]


class ProductInput(BaseModel):
    """A single product on create/import. Currency is normalized to ISO-4217
    uppercase by the service."""

    sku: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    aliases: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=50
    )
    variants: list[ProductVariant] = Field(default_factory=list, max_length=50)
    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    url: str = Field(default="", max_length=2048)
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=100)

    _aliases_clean = field_validator("aliases", mode="before")(_clean_aliases)
    _currency_upper = field_validator("currency", mode="before")(_clean_currency)


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    aliases: list[Annotated[str, Field(max_length=255)]] | None = Field(
        default=None, max_length=50
    )
    variants: list[ProductVariant] | None = Field(default=None, max_length=50)
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    url: str | None = Field(default=None, max_length=2048)
    attributes: dict[str, Any] | None = Field(default=None, max_length=100)

    _aliases_clean = field_validator("aliases", mode="before")(_clean_optional_aliases)
    _currency_upper = field_validator("currency", mode="before")(_clean_currency)


class ProductImport(BaseModel):
    """CSV bulk-create payload: already-parsed product rows (JSON import)."""

    products: list[ProductInput] = Field(
        default_factory=list, max_length=PRODUCT_IMPORT_MAX_ROWS
    )


class ProductImportRowError(BaseModel):
    """One skipped import row (D1): the 1-based source row, the field that
    caused the skip, and a human reason. ``row`` counts DATA rows (the CSV
    header is row 0), matching the import dialog's preview numbering; for the
    JSON path it is the 1-based index into the ``products`` array."""

    row: int = Field(ge=1)
    field: str
    message: str


class ProductImportSummary(BaseModel):
    """Per-row outcome tally for one import (D1).

    ``updated`` is reserved: v1 imports are INSERT-only (an existing sku is
    skipped, never overwritten), so it is always 0 — it keeps the contract
    stable for a future upsert mode without a breaking change.
    """

    created: int = Field(ge=0)
    updated: int = Field(ge=0)
    skipped: int = Field(ge=0)
    errors: list[ProductImportRowError] = Field(default_factory=list)


class ProductImportResponse(BaseModel):
    """Bulk-import result (D1): the full refreshed catalog + the summary."""

    items: list[ProductResponse]
    summary: ProductImportSummary


class ProductAuditReferences(BaseModel):
    """Read-only delete-guard check (D4): how many audit configurations froze
    this product. Audit integrity is guaranteed by the freeze itself — this
    only backs the UX warning."""

    product_id: uuid.UUID
    referenced: bool
    audit_count: int = Field(ge=0)


class ProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    sku: str
    name: str
    aliases: list[str]
    variants: list[ProductVariant]
    price: float | None
    currency: str
    url: str
    attributes: dict[str, Any]
    # manual | imported | synced (config/products.py PRODUCT_ORIGINS).
    origin: Literal["manual", "imported", "synced"]
    # Feed provenance (commerce suite): required-nullable — null for
    # unbound manual/imported products. Never a token or PII field.
    connection_id: uuid.UUID | None
    external_item_ref: str | None
    last_seen_sync_run_id: uuid.UUID | None
    # Computed on read (never persisted): ``product_to_response`` overwrites
    # this placeholder via ``model_copy``.
    completeness: ProductCompleteness = Field(
        default_factory=lambda: ProductCompleteness(
            score=0.0, present=0, total=0, missing=[]
        )
    )
    created_at: datetime
    updated_at: datetime

    _external_item_ref_none = field_validator("external_item_ref", mode="before")(
        _empty_str_to_none
    )


class CompetitorProductInput(BaseModel):
    competitor_id: uuid.UUID
    name: str = Field(min_length=1, max_length=255)
    aliases: list[Annotated[str, Field(max_length=255)]] = Field(
        default_factory=list, max_length=50
    )
    price: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=3)
    url: str = Field(default="", max_length=2048)
    variants: list[ProductVariant] = Field(default_factory=list, max_length=50)
    attributes: dict[str, Any] = Field(default_factory=dict, max_length=100)
    availability: str = Field(default="", max_length=64)

    _aliases_clean = field_validator("aliases", mode="before")(_clean_aliases)
    _currency_upper = field_validator("currency", mode="before")(_clean_currency)


class CompetitorProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    aliases: list[Annotated[str, Field(max_length=255)]] | None = Field(
        default=None, max_length=50
    )
    price: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=3)
    url: str | None = Field(default=None, max_length=2048)
    variants: list[ProductVariant] | None = Field(default=None, max_length=50)
    attributes: dict[str, Any] | None = Field(default=None, max_length=100)
    availability: str | None = Field(default=None, max_length=64)

    _aliases_clean = field_validator("aliases", mode="before")(_clean_optional_aliases)
    _currency_upper = field_validator("currency", mode="before")(_clean_currency)


class CompetitorProductResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    competitor_id: uuid.UUID
    name: str
    aliases: list[str]
    price: float | None
    currency: str
    url: str
    variants: list[ProductVariant]
    attributes: dict[str, Any]
    availability: str
    extraction_fresh_at: datetime | None
    created_at: datetime
    updated_at: datetime


def product_to_response(product: Product) -> ProductResponse:
    dto = ProductResponse.model_validate(product)
    return dto.model_copy(
        update={"completeness": ProductCompleteness(**product_completeness(product))}
    )


def competitor_product_to_response(
    competitor_product: CompetitorProduct,
) -> CompetitorProductResponse:
    return CompetitorProductResponse.model_validate(competitor_product)


# --------------------------------------------------------------------------
# Visibility projections (persisted rows only, invariant 7)
# --------------------------------------------------------------------------
class BuyerDestinationKindCount(BaseModel):
    """One merchant-kind bucket of the persisted buyer-destination mix."""

    merchant_kind: str
    count: int = Field(ge=0)


class BuyerDestinationDomainCount(BaseModel):
    """One merchant-domain bucket of the persisted buyer-destination mix."""

    merchant_domain: str
    merchant_name: str
    merchant_kind: str
    count: int = Field(ge=0)


class BuyerDestinationMix(BaseModel):
    """Persisted buyer-destination mix (exact JSONB shape + ordering)."""

    total: int = Field(ge=0)
    by_kind: list[BuyerDestinationKindCount] = Field(default_factory=list)
    by_domain: list[BuyerDestinationDomainCount] = Field(default_factory=list)


class CompetitorCoPlacementItem(BaseModel):
    """One competitor product co-mentioned with the entry (persisted shape)."""

    competitor_product_id: uuid.UUID | None
    competitor_name: str
    product_name: str
    count: int = Field(ge=0)


class CompetitorCoPlacement(BaseModel):
    """Persisted competitor co-placement (``truncated`` always present)."""

    items: list[CompetitorCoPlacementItem] = Field(default_factory=list)
    truncated: bool = False


class FrozenPromptContext(BaseModel):
    """Frozen audit prompt context; no valence or sentiment inference."""

    prompt_index: int
    text: str
    theme: str
    intent: str


class ProductVisibilityEntry(BaseModel):
    """One own product's persisted aggregate for the selected audit."""

    product_id: uuid.UUID | None
    sku: str
    name: str
    # Row-level analyzer version (mixed-version audits label each row with
    # its ACTUAL persisted version, not snapshots[0]).
    product_analyzer_version: str
    mention_count: int
    sov_share: float
    avg_rank: float | None
    rank_distribution: dict[str, int]
    price_mention_count: int
    price_accuracy_rate: float | None
    win_rate: float | None
    price_mismatch_rate: float | None
    price_relation_counts: dict[str, int]
    attribute_dimension_frequency: dict[str, dict[str, int]]
    buyer_destination_mix: BuyerDestinationMix
    competitor_co_placement: CompetitorCoPlacement
    prompt_coverage: float | None = None
    frozen_prompt_context: list[FrozenPromptContext] = Field(default_factory=list)
    conversation_themes: list[str] = Field(default_factory=list)
    visibility_rate: float
    top_three_rate: float
    engine_coverage: int = Field(ge=0)
    visibility_delta: float | None


class CompetitorProductVisibilityEntry(BaseModel):
    """One competitor product's persisted aggregate for the selected audit."""

    competitor_product_id: uuid.UUID | None
    competitor_name: str
    name: str
    product_analyzer_version: str
    mention_count: int
    sov_share: float
    avg_rank: float | None
    rank_distribution: dict[str, int]
    price_mention_count: int
    price_accuracy_rate: float | None
    win_rate: float | None
    price_mismatch_rate: float | None
    price_relation_counts: dict[str, int]
    attribute_dimension_frequency: dict[str, dict[str, int]]
    buyer_destination_mix: BuyerDestinationMix
    competitor_co_placement: CompetitorCoPlacement
    prompt_coverage: float | None = None
    frozen_prompt_context: list[FrozenPromptContext] = Field(default_factory=list)
    conversation_themes: list[str] = Field(default_factory=list)
    visibility_rate: float
    top_three_rate: float
    engine_coverage: int = Field(ge=0)


class ProductVisibilitySummary(BaseModel):
    products_tracked: int = Field(ge=0)
    products_visible: int = Field(ge=0)
    visibility_rate: float
    top_three_rate: float
    average_rank: float | None
    competitor_wins: int = Field(ge=0)


class ProductVisibilityResponse(BaseModel):
    """Selected-audit product dashboard projection (mirror VisibilityResponse).

    Identity (sku/name/competitor_name) comes from the audit's FROZEN
    configuration so the projection survives later catalog deletes.
    """

    project_id: uuid.UUID
    audit_id: uuid.UUID
    audit_status: str
    product_analyzer_version: str
    product_scoring_rule_version: str
    total_mentions: int
    total_analyses: int
    summary: ProductVisibilitySummary
    products: list[ProductVisibilityEntry]
    competitor_products: list[CompetitorProductVisibilityEntry]
    created_at: datetime


class ProductVisibilityTrendPoint(BaseModel):
    audit_id: uuid.UUID
    observed_at: datetime
    visibility_rate: float
    top_three_rate: float
    average_rank: float | None


class ProductVisibilityTrendResponse(BaseModel):
    project_id: uuid.UUID
    product_id: uuid.UUID
    sku: str
    name: str
    points: list[ProductVisibilityTrendPoint]


class ProductEvidenceItem(BaseModel):
    """One projected evidence row (mention / attribute / destination).

    Strict frontend contract: exactly this pinned key set is emitted (no
    top-level ``mention_id`` — ``ProductMention.id`` surfaces as
    ``evidence_id`` on ``product_mention`` rows). Kind-specific fields are
    present on every row and null for the other kinds.
    """

    # Common identity + provenance (every kind).
    evidence_id: uuid.UUID
    analysis_id: uuid.UUID
    evidence_kind: str
    audit_id: uuid.UUID
    task_id: uuid.UUID
    artifact_id: uuid.UUID | None
    logical_engine: str
    transport_model: str
    prompt_text: str
    prompt_index: int
    repetition: int
    product_analyzer_version: str
    matched_name: str
    matched_sku: str
    created_at: datetime
    # Product-mention fields (null for non-product_mention kinds).
    first_offset: int | None = None
    rank_position: int | None = None
    price_value: float | None = None
    price_matches_catalog: bool | None = None
    price_relation: str | None = None
    price_text: str = ""
    price_currency: str = ""
    # Attribute-mention fields (null for non-attribute_mention kinds).
    attribute_dimension: str | None = None
    attribute_group: str | None = None
    attribute_text: str | None = None
    attribute_offset: int | None = None
    # Buyer-destination fields (null for non-buyer_destination kinds).
    merchant_name: str | None = None
    merchant_domain: str | None = None
    merchant_kind: str | None = None
    destination_url: str | None = None


class ProductEvidenceResponse(BaseModel):
    items: list[ProductEvidenceItem]
    truncated: bool
