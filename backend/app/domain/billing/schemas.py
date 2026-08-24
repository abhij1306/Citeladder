"""Safe public billing request/response contracts (v8 commercial surface).

Every response model is STRICT (``extra='forbid'``) and every list is present
and possibly empty — never null. Nullability is exactly as the frozen contract
states: null never ambiguously means both "unlimited" and "unresolved".

Invariant 6: no DTO here carries a provider price/plan/payment reference, an
external provider id, a payment instrument, a raw provider body, or a secret.
``provider_price_ref`` lives only in ``app.core.config.billing_catalog`` and reaches the
provider through the server-resolved quote; ``quote_id`` is an opaque server
digest over the safe resolved inputs PLUS that private ref, so it proves the
displayed terms without exposing any provider identity.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

# --- Shared vocabularies (mirror the config-owned tokens as Literals so
# FastAPI validates request bodies and the generated OpenAPI locks them) -----
CatalogAvailability = Literal["available", "unavailable"]
CapabilityTypeName = Literal[
    "flag",
    "counter.occupancy",
    "counter.consumable",
    "counter.rate",
    "level",
]
CounterCapabilityTypeName = Literal[
    "counter.occupancy", "counter.consumable", "counter.rate"
]
GrantSourceKind = Literal["plan", "addon", "topup", "trial", "override"]
CredentialMode = Literal["byok", "funded"]
BillingRegion = Literal["india", "international"]
EntitlementStatus = Literal["resolved", "entitlement_unresolved"]
PlanCatalogKey = Literal["tier_1", "tier_2", "tier_3", "enterprise"]
SelfServePlanCatalogKey = Literal["tier_1", "tier_2", "tier_3"]
ActivationKind = Literal["base", "addon", "topup"]
ActivationStatus = Literal["pending", "activated", "failed", "abandoned"]
LimitState = Literal["finite", "unlimited", "unknown"]
ProviderConnectionState = Literal["connected", "missing", "failed", "unavailable"]


class _StrictResponse(BaseModel):
    """Base for every response DTO: unspecified fields are forbidden."""

    model_config = ConfigDict(extra="forbid")


class _StrictRequest(BaseModel):
    """Base for every request DTO: a browser cannot smuggle extra fields."""

    model_config = ConfigDict(extra="forbid")


# --- Money and quotes ------------------------------------------------------
class MoneyResponse(_StrictResponse):
    currency: Literal["USD", "INR"]
    amount_minor: int = Field(ge=0)


class ResolvedQuoteResponse(_StrictResponse):
    """The server-resolved charge for one commercial intent.

    ``quote_id`` is an opaque server HMAC/digest over the safe resolved inputs
    and the PRIVATE provider price ref; it exposes no provider id. ``base_price``
    and ``credit_price`` stay separate: for BYOK ``credit_price`` is None, for
    funded it is non-null, and the funded total is base + credit.
    ``total_price`` is the provider charge INCLUDING tax.
    """

    quote_id: str
    catalog_revision: str
    catalog_key: str
    credential_mode: CredentialMode
    country_code: str
    region: BillingRegion
    base_price: MoneyResponse
    credit_price: MoneyResponse | None
    tax: MoneyResponse
    total_price: MoneyResponse
    expires_at: datetime


# --- Public catalog --------------------------------------------------------
class CapabilityValueResponse(_StrictResponse):
    """One capability row for the public plan comparison."""

    key: str
    capability_type: CapabilityTypeName
    value: bool | int | str | None
    issuable: bool


class CatalogProviderRouteResponse(_StrictResponse):
    logical_engine: str
    transport_provider: str
    model: str


class CatalogProviderResponse(_StrictResponse):
    """A PUBLIC provider row: availability only, never workspace state."""

    key: str
    label: str
    availability: CatalogAvailability
    unavailable_reason: str | None
    adapter_shipped: bool
    grant_key: str
    issuable: bool
    routes: list[CatalogProviderRouteResponse]


class CatalogPlanResponse(_StrictResponse):
    key: PlanCatalogKey
    name: str
    description: str
    cadence: Literal["monthly", "custom"]
    self_serve: bool
    contact_only: bool
    contact_url: str | None
    base_price: MoneyResponse | None
    credit_price: MoneyResponse | None
    funded_total_price: MoneyResponse | None
    checkout_available: bool
    unavailable_reason: str | None
    capabilities: list[CapabilityValueResponse]
    trial_availability: CatalogAvailability
    trial_unavailable_reason: str | None
    trial_days: int | None


class CatalogAddonResponse(_StrictResponse):
    key: str
    name: str
    description: str
    cadence: Literal["monthly"]
    unit_price: MoneyResponse | None
    quantity_min: int
    quantity_max: int
    availability: CatalogAvailability
    unavailable_reason: str | None
    grant_key: str
    grant_value_per_unit: int


class CatalogTopupResponse(_StrictResponse):
    key: str
    name: str
    description: str
    unit_price: MoneyResponse | None
    quantity_min: int
    quantity_max: int
    availability: CatalogAvailability
    unavailable_reason: str | None
    grant_key: Literal["audit_credits"]
    credits_per_unit: int | None
    expiry_days: int


class BillingCatalogResponse(_StrictResponse):
    """The public catalog. ``country_code`` is None for the preview (no country
    supplied); the region then defaults to the config-owned international
    preview. Checkout still requires a submitted country.
    """

    catalog_revision: str
    country_code: str | None
    region: BillingRegion
    currency: Literal["USD", "INR"]
    currency_minor_units: int
    plans: list[CatalogPlanResponse]
    addons: list[CatalogAddonResponse]
    topups: list[CatalogTopupResponse]
    providers: list[CatalogProviderResponse]


# --- Entitlement and usage reads ------------------------------------------
class GrantProvenanceResponse(_StrictResponse):
    """One grant's safe provenance. ``source_ref`` and every operator/provider
    internal are deliberately omitted. ``revoked_at`` is the earliest effective
    revocation, or null.
    """

    grant_id: uuid.UUID
    source_kind: GrantSourceKind
    key: str
    value: int
    valid_from: datetime
    effective_valid_until: datetime | None
    revoked_at: datetime | None
    catalog_revision: str


class ResolvedCapabilityResponse(_StrictResponse):
    key: str
    capability_type: CapabilityTypeName
    value: bool | int | str | None
    contributing_grant_ids: list[uuid.UUID]
    ordered_draw_grant_ids: list[uuid.UUID]


class SubscriptionSummaryResponse(_StrictResponse):
    """Null on the parent when no current base subscription exists."""

    catalog_key: str
    status: str
    current_period_end: datetime | None
    cancel_at_period_end: bool


class TrialGrantSummaryResponse(_StrictResponse):
    """Derived only from active/expired operator/dev/test trial grants."""

    deadline: datetime
    days_remaining: int
    exhausted: bool


class BillingEntitlementResponse(_StrictResponse):
    """The resolved account entitlement. There is deliberately NO
    ``funded_execution_allowed`` field: funded admission is an enforcement-time
    decision, not a published entitlement flag.
    """

    billing_account_id: uuid.UUID
    status: EntitlementStatus
    errors: list[str]
    registry_revision: str
    entitlement_lifecycle_version: int
    resolved_at: datetime
    valid_until: datetime | None
    subscription: SubscriptionSummaryResponse | None
    trial_grant: TrialGrantSummaryResponse | None
    capabilities: list[ResolvedCapabilityResponse]
    grants: list[GrantProvenanceResponse]


class UsageGrantBalanceResponse(_StrictResponse):
    grant_id: uuid.UUID
    source_kind: GrantSourceKind
    allowance: int
    consumed: int
    reserved: int
    remaining: int
    effective_valid_until: datetime | None


class UsageItemResponse(_StrictResponse):
    """One measurable counter. Nullability is EXPLICIT per ``limit_state``:

    - ``finite``: every numeric aggregate is present;
    - ``unlimited``: ``allowance`` and ``remaining`` are null and ``consumed``
      is measured;
    - ``unknown``: every aggregate numeric is null.

    Null is never used to ambiguously mean both unlimited and unresolved.
    """

    key: str
    capability_type: CounterCapabilityTypeName
    unit: str
    limit_state: LimitState
    allowance: int | None
    consumed: int | None
    reserved: int | None
    remaining: int | None
    window_started_at: datetime | None
    resets_at: datetime | None
    earliest_expiry: datetime | None
    grants: list[UsageGrantBalanceResponse]

    @model_validator(mode="after")
    def _check_limit_state_nullability(self) -> UsageItemResponse:
        aggregates = (self.allowance, self.consumed, self.reserved, self.remaining)
        if self.limit_state == "finite" and any(value is None for value in aggregates):
            raise ValueError("a finite usage item requires every numeric aggregate")
        if self.limit_state == "unlimited" and (
            self.allowance is not None
            or self.remaining is not None
            or self.consumed is None
        ):
            raise ValueError(
                "an unlimited usage item requires null allowance/remaining and a "
                "measured consumed"
            )
        if self.limit_state == "unknown" and any(
            value is not None for value in aggregates
        ):
            raise ValueError("an unknown usage item requires null numeric aggregates")
        return self


class BillingUsageResponse(_StrictResponse):
    billing_account_id: uuid.UUID
    entitlement_lifecycle_version: int
    status: EntitlementStatus
    items: list[UsageItemResponse]


# --- Commercial mutations -------------------------------------------------
def _normalized_country(value: str) -> str:
    """Normalize and validate an ISO alpha-2 country code.

    The browser supplies only the country; it can never submit an amount, a
    currency, a region, or a provider reference.
    """
    country = value.strip().upper()
    if len(country) != 2 or not country.isalpha():
        raise ValueError("country_code must be an ISO alpha-2 code")
    return country


class SubscriptionCreateRequest(_StrictRequest):
    catalog_key: SelfServePlanCatalogKey
    credential_mode: CredentialMode
    country_code: str
    trial_requested: bool = False

    @field_validator("country_code")
    @classmethod
    def _normalize_country(cls, value: str) -> str:
        return _normalized_country(value)


class AddonActivateRequest(_StrictRequest):
    catalog_key: str
    quantity: int = Field(ge=1)


class TopupPurchaseRequest(_StrictRequest):
    catalog_key: str
    quantity: int = Field(ge=1)


class ActivationResponse(_StrictResponse):
    """One commercial intent's safe state.

    ``checkout_url`` is non-null only while an external hosted checkout is
    actionable; ``failure_code`` is non-null only for ``failed``; ``quote`` is
    always present and stored for byte-equivalent replay.
    """

    activation_id: uuid.UUID
    kind: ActivationKind
    catalog_key: str
    quantity: int
    status: ActivationStatus
    quote: ResolvedQuoteResponse
    checkout_url: str | None
    expires_at: datetime
    failure_code: str | None


class SubscriptionChangeResponse(_StrictResponse):
    """A scheduled cancellation. Deliberately NOT ``ActivationResponse``: it has
    no pending/activated/failed/abandoned vocabulary.
    """

    catalog_key: str
    status: Literal["cancellation_scheduled", "already_scheduled"]
    effective_at: datetime


# --- Authenticated provider connection state ------------------------------
class ProviderProbeResponse(_StrictResponse):
    """Null on the parent for never-probed/missing/unavailable providers."""

    status: Literal["ok", "failed"]
    safe_reason: str | None
    tested_at: datetime
    model: str | None
    latency_ms: int | None


class ProviderConnectionStateResponse(_StrictResponse):
    """For Copilot, ``grant_key='provider.copilot'`` is descriptive catalog
    identity only; the registry's ``issuable=False`` remains authoritative.
    """

    key: str
    label: str
    state: ProviderConnectionState
    safe_reason: str | None
    grant_key: str
    latest_probe: ProviderProbeResponse | None


class ProviderConnectionStatesResponse(_StrictResponse):
    workspace_id: uuid.UUID
    providers: list[ProviderConnectionStateResponse]


__all__ = [
    "ActivationKind",
    "ActivationResponse",
    "ActivationStatus",
    "AddonActivateRequest",
    "BillingCatalogResponse",
    "BillingEntitlementResponse",
    "BillingRegion",
    "BillingUsageResponse",
    "CapabilityValueResponse",
    "CatalogAddonResponse",
    "CatalogAvailability",
    "CatalogPlanResponse",
    "CatalogProviderResponse",
    "CatalogProviderRouteResponse",
    "CatalogTopupResponse",
    "CredentialMode",
    "GrantProvenanceResponse",
    "GrantSourceKind",
    "LimitState",
    "MoneyResponse",
    "PlanCatalogKey",
    "ProviderConnectionState",
    "ProviderConnectionStateResponse",
    "ProviderConnectionStatesResponse",
    "ProviderProbeResponse",
    "ResolvedCapabilityResponse",
    "ResolvedQuoteResponse",
    "SelfServePlanCatalogKey",
    "SubscriptionChangeResponse",
    "SubscriptionCreateRequest",
    "SubscriptionSummaryResponse",
    "TopupPurchaseRequest",
    "TrialGrantSummaryResponse",
    "UsageGrantBalanceResponse",
    "UsageItemResponse",
]
