from __future__ import annotations

from typing import Final

from app.core.config.entitlements import (
    KEY_AUDIT_CREDITS,
    KEY_PROVIDER_COPILOT,
    KEY_PROVIDER_GROK,
    KEY_PROVIDER_PERPLEXITY,
)

CADENCE_MONTHLY: Final = "monthly"

CADENCES: Final = frozenset({CADENCE_MONTHLY})

SUBSCRIPTION_KIND_BASE: Final = "base"

SUBSCRIPTION_KIND_ADDON: Final = "addon"

SUBSCRIPTION_KINDS: Final = frozenset({SUBSCRIPTION_KIND_BASE, SUBSCRIPTION_KIND_ADDON})

PROVIDER_RAZORPAY: Final = "razorpay"

SUBSCRIPTION_PENDING: Final = "pending"

SUBSCRIPTION_TRIALING: Final = "trialing"

SUBSCRIPTION_ACTIVE: Final = "active"

SUBSCRIPTION_PAST_DUE: Final = "past_due"

SUBSCRIPTION_CANCEL_SCHEDULED: Final = "cancel_scheduled"

SUBSCRIPTION_CANCELLED: Final = "cancelled"

SUBSCRIPTION_UNPAID: Final = "unpaid"

SUBSCRIPTION_EXPIRED: Final = "expired"

LIVE_SUBSCRIPTION_STATUSES: Final = frozenset(
    {
        SUBSCRIPTION_PENDING,
        SUBSCRIPTION_TRIALING,
        SUBSCRIPTION_ACTIVE,
        SUBSCRIPTION_PAST_DUE,
        SUBSCRIPTION_CANCEL_SCHEDULED,
    }
)

RAZORPAY_EVENT_TYPES: Final = frozenset(
    {
        "subscription.authenticated",
        "subscription.activated",
        "subscription.charged",
        "subscription.pending",
        "subscription.halted",
        "subscription.cancelled",
        "subscription.completed",
        "subscription.expired",
        "subscription.paused",
        "subscription.resumed",
    }
)

RAZORPAY_PAYMENT_EVENT_TYPES: Final = frozenset({"payment.captured", "payment.failed"})

PAYMENT_PENDING: Final = "payment_pending"

PAYMENT_PAID: Final = "paid"

PAYMENT_FAILED: Final = "payment_failed"

RAZORPAY_PAYMENT_STATUS_MAP: Final[dict[str, str]] = {
    "created": PAYMENT_PENDING,
    "authorized": PAYMENT_PENDING,
    "partially_paid": PAYMENT_PENDING,
    "captured": PAYMENT_PAID,
    "paid": PAYMENT_PAID,
    "failed": PAYMENT_FAILED,
    "cancelled": PAYMENT_FAILED,
    "expired": PAYMENT_FAILED,
    "refunded": PAYMENT_FAILED,
}

RAZORPAY_STATUS_MAP: Final[dict[str, str]] = {
    "created": SUBSCRIPTION_PENDING,
    "authenticated": SUBSCRIPTION_PENDING,
    "active": SUBSCRIPTION_ACTIVE,
    "pending": SUBSCRIPTION_PAST_DUE,
    "halted": SUBSCRIPTION_UNPAID,
    "cancelled": SUBSCRIPTION_CANCELLED,
    "completed": SUBSCRIPTION_EXPIRED,
    "expired": SUBSCRIPTION_EXPIRED,
    "paused": SUBSCRIPTION_PAST_DUE,
}

REGION_INDIA: Final = "india"

REGION_INTERNATIONAL: Final = "international"

REGIONS: Final[tuple[str, ...]] = (REGION_INDIA, REGION_INTERNATIONAL)

INDIA_COUNTRY_CODE: Final = "IN"

PREVIEW_REGION: Final = REGION_INTERNATIONAL

CURRENCY_USD: Final = "USD"

CURRENCY_INR: Final = "INR"

REGION_CURRENCIES: Final[dict[str, str]] = {
    REGION_INDIA: CURRENCY_INR,
    REGION_INTERNATIONAL: CURRENCY_USD,
}

CURRENCY_MINOR_UNITS: Final[dict[str, int]] = {CURRENCY_USD: 2, CURRENCY_INR: 2}

TAX_BEHAVIOR_EXCLUSIVE: Final = "exclusive"

TAX_BEHAVIOR_INCLUSIVE: Final = "inclusive"

TAX_BEHAVIORS: Final[frozenset[str]] = frozenset(
    {TAX_BEHAVIOR_EXCLUSIVE, TAX_BEHAVIOR_INCLUSIVE}
)

CADENCE_CUSTOM: Final = "custom"

PRICE_PURPOSE_BASE: Final = "base"

PRICE_PURPOSE_CREDIT: Final = "credit"

REASON_CHECKOUT_UNAVAILABLE: Final = "checkout_unavailable"

REASON_CONTACT_ONLY: Final = "contact_only"

REASON_TRIAL_UNAVAILABLE: Final = "trial_unavailable"

PLAN_TIER_1: Final = "tier_1"

PLAN_TIER_2: Final = "tier_2"

PLAN_TIER_3: Final = "tier_3"

PLAN_ENTERPRISE: Final = "enterprise"

PLAN_KEYS: Final[tuple[str, ...]] = (
    PLAN_TIER_1,
    PLAN_TIER_2,
    PLAN_TIER_3,
    PLAN_ENTERPRISE,
)

SELF_SERVE_PLAN_KEYS: Final[tuple[str, ...]] = (PLAN_TIER_1, PLAN_TIER_2, PLAN_TIER_3)

TIER_1_BASE_USD_MINOR: Final = 9_900

TIER_2_BASE_USD_MINOR: Final = 19_900

TIER_3_BASE_USD_MINOR: Final = 29_900

ADDON_EXTRA_PROJECT: Final = "addon_extra_project"

ADDON_EXTRA_PROMPTS: Final = "addon_extra_prompts"

TOPUP_AUDIT_CREDITS: Final = "topup_audit_credits"

ADDON_EXTRA_PROJECT_SLOTS_PER_UNIT: Final = 1

ADDON_EXTRA_PROMPTS_SLOTS_PER_UNIT: Final = 10

ADDON_QUANTITY_MIN: Final = 1

ADDON_QUANTITY_MAX: Final = 20

TOPUP_QUANTITY_MIN: Final = 1

TOPUP_QUANTITY_MAX: Final = 20

TOPUP_CREDIT_KEYS: Final[dict[str, str]] = {TOPUP_AUDIT_CREDITS: KEY_AUDIT_CREDITS}

COMING_SOON_PLAN_CAPABILITY_KEYS: Final[tuple[str, ...]] = (
    KEY_PROVIDER_GROK,
    KEY_PROVIDER_PERPLEXITY,
    KEY_PROVIDER_COPILOT,
)

COMING_SOON_ROW_PLAN_KEYS: Final[tuple[str, ...]] = (PLAN_TIER_2, PLAN_TIER_3)

ACTIVATION_KIND_BASE: Final = "base"

ACTIVATION_KIND_ADDON: Final = "addon"

ACTIVATION_KIND_TOPUP: Final = "topup"

ACTIVATION_KINDS: Final[frozenset[str]] = frozenset(
    {ACTIVATION_KIND_BASE, ACTIVATION_KIND_ADDON, ACTIVATION_KIND_TOPUP}
)

ACTIVATION_PENDING: Final = "pending"

ACTIVATION_ACTIVATED: Final = "activated"

ACTIVATION_FAILED: Final = "failed"

ACTIVATION_ABANDONED: Final = "abandoned"

ACTIVATION_STATUSES: Final[frozenset[str]] = frozenset(
    {
        ACTIVATION_PENDING,
        ACTIVATION_ACTIVATED,
        ACTIVATION_FAILED,
        ACTIVATION_ABANDONED,
    }
)

IDEMPOTENCY_STARTED: Final = "started"

IDEMPOTENCY_COMPLETED: Final = "completed"

IDEMPOTENCY_FAILED: Final = "failed"

CREDENTIAL_MODE_BYOK: Final = "byok"

CREDENTIAL_MODE_FUNDED: Final = "funded"

CREDENTIAL_MODES: Final[frozenset[str]] = frozenset(
    {CREDENTIAL_MODE_BYOK, CREDENTIAL_MODE_FUNDED}
)

OPERATION_SUBSCRIPTION_CREATE: Final = "subscription.create"

OPERATION_SUBSCRIPTION_CANCEL: Final = "subscription.cancel"

OPERATION_ADDON_ACTIVATE: Final = "addon.activate"

OPERATION_ADDON_CANCEL: Final = "addon.cancel"

OPERATION_TOPUP_PURCHASE: Final = "topup.purchase"

REASON_TRIAL_REQUESTED_UNAVAILABLE: Final = "trial_unavailable"

REASON_IDEMPOTENCY_KEY_REQUIRED: Final = "idempotency_key_required"

REASON_IDEMPOTENCY_KEY_REUSED: Final = "idempotency_key_reused"

REASON_CATALOG_KEY_UNKNOWN: Final = "catalog_key_unknown"

REASON_QUANTITY_OUT_OF_BOUNDS: Final = "quantity_out_of_bounds"

REASON_SUBSCRIPTION_EXISTS: Final = "subscription_already_active"

REASON_ADDON_EXISTS: Final = "addon_already_active"

REASON_SUBSCRIPTION_PENDING: Final = "subscription_pending"

REASON_ADDON_PENDING: Final = "addon_pending"

REASON_NO_CURRENT_SUBSCRIPTION: Final = "no_current_subscription"

REASON_BASE_SUBSCRIPTION_REQUIRED: Final = "base_subscription_required"

REASON_PROVIDER_UNAVAILABLE: Final = "provider_unavailable"

REASON_PROVIDER_REJECTED: Final = "provider_rejected"

REASON_ACTIVATION_EXPIRED: Final = "activation_expired"

COMING_SOON_ADDON_KEYS: Final[frozenset[str]] = frozenset()

IDEMPOTENCY_KEY_MIN_LENGTH: Final = 8

IDEMPOTENCY_KEY_MAX_LENGTH: Final = 255

TELEMETRY_ENTITLEMENT_UNRESOLVED: Final = "billing.entitlement_unresolved"

TELEMETRY_FUNDED_BUDGET_EXHAUSTED: Final = "billing.funded_budget_exhausted"

TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED: Final = "billing.consumable_credits_exhausted"

TELEMETRY_DUPLICATE_GRANT_PREVENTED: Final = "billing.duplicate_grant_prevented"

BILLING_TELEMETRY_EVENTS: Final[tuple[str, ...]] = (
    TELEMETRY_ENTITLEMENT_UNRESOLVED,
    TELEMETRY_FUNDED_BUDGET_EXHAUSTED,
    TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED,
    TELEMETRY_DUPLICATE_GRANT_PREVENTED,
)

ACTIVATION_AUTHORITY_WEBHOOK: Final = "webhook"

ACTIVATION_AUTHORITY_RECONCILIATION: Final = "reconciliation"

USAGE_UNITS_BY_CAPABILITY_TYPE: Final[dict[str, str]] = {
    "counter.consumable": "credits",
    "counter.occupancy": "slots",
    "counter.rate": "runs",
}

COUNTRY_VERIFICATION_PROVISIONAL: Final = "provisional"

COUNTRY_VERIFICATION_DECLARED: Final = "declared"

CANCELLATION_SCHEDULED: Final = "cancellation_scheduled"

CANCELLATION_ALREADY_SCHEDULED: Final = "already_scheduled"

LIMIT_STATE_FINITE: Final = "finite"

LIMIT_STATE_UNLIMITED: Final = "unlimited"

LIMIT_STATE_UNKNOWN: Final = "unknown"
