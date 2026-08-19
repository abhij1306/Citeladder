# Agentic-commerce vocabulary + gates (invariant 1).
#
# Owns EVERY deterministic commerce token the M2a analyzer v2 reads: the
# win-rate rule, the attribute-dimension catalog (+ its extraction window),
# the price-relation/merchant-kind vocabularies, the merchant domain map, the
# co-placement cap, the shopping-surface gate, and the evidence-kind/evidence-
# identity tokens. Domain, analysis, worker, and API code READS these; it
# never hard-codes the literals inline.
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.task_queue import ERROR_MAX_ATTEMPTS, PostgresQueueSpec

# --- Discovery and catalog-comparison policy --------------------------------
# These knobs are deliberately centralised: discovery workers may change over
# time, but a persisted run freezes the values and versions below.
COMMERCE_DISCOVERY_VERSION: Final = "commerce-discovery-1"
COMMERCE_MATCHER_VERSION: Final = "commerce-matcher-1"
COMMERCE_COMPARISON_VERSION: Final = "commerce-comparison-1"
COMMERCE_DISCOVERY_RUN_STATUS_QUEUED: Final = "queued"
COMMERCE_DISCOVERY_RUN_STATUS_RUNNING: Final = "running"
COMMERCE_DISCOVERY_RUN_STATUS_COMPLETED: Final = "completed"
COMMERCE_DISCOVERY_RUN_STATUS_PARTIALLY_COMPLETED: Final = "partially_completed"
COMMERCE_DISCOVERY_RUN_STATUS_FAILED: Final = "failed"
COMMERCE_DISCOVERY_RUN_TERMINAL_STATUSES: Final[frozenset[str]] = frozenset(
    {
        COMMERCE_DISCOVERY_RUN_STATUS_COMPLETED,
        COMMERCE_DISCOVERY_RUN_STATUS_PARTIALLY_COMPLETED,
        COMMERCE_DISCOVERY_RUN_STATUS_FAILED,
    }
)
COMMERCE_DISCOVERY_TASK_KIND_DISCOVER: Final = "discover"
COMMERCE_ACQUISITION_STATE_QUEUE_READY: Final = "queue_ready"
COMMERCE_ACQUISITION_STATE_ACQUIRED: Final = "acquired"
COMMERCE_MATCH_REASON_REVIEWED_DISCOVERY: Final = "reviewed_discovery"
COMMERCE_DISCOVERED_SKU_PREFIX: Final = "discovered-"
COMMERCE_EVIDENCE_LABEL_CATALOG: Final = "catalog"
COMMERCE_EVIDENCE_LABEL_DISCOVERY: Final = "discovery"
COMMERCE_DISCOVERY_INPUT_UPLOAD: Final = "upload"
COMMERCE_DISCOVERY_INPUT_URL: Final = "url"
COMMERCE_DISCOVERY_INPUTS: Final[frozenset[str]] = frozenset(
    {COMMERCE_DISCOVERY_INPUT_UPLOAD, COMMERCE_DISCOVERY_INPUT_URL}
)
COMMERCE_CANDIDATE_KIND_OWN: Final = "own"
COMMERCE_CANDIDATE_KIND_COMPETITOR: Final = "competitor"
COMMERCE_CANDIDATE_KINDS: Final[frozenset[str]] = frozenset(
    {COMMERCE_CANDIDATE_KIND_OWN, COMMERCE_CANDIDATE_KIND_COMPETITOR}
)
COMMERCE_REVIEW_ACCEPTED: Final = "accepted"
COMMERCE_REVIEW_REJECTED: Final = "rejected"
COMMERCE_REVIEW_STATUSES: Final[frozenset[str]] = frozenset(
    {COMMERCE_REVIEW_ACCEPTED, COMMERCE_REVIEW_REJECTED}
)
COMMERCE_MATCH_GTIN: Final = "gtin"
COMMERCE_MATCH_BRAND_MODEL: Final = "brand_model"
COMMERCE_MATCH_FAMILY_VARIANT: Final = "family_variant"
COMMERCE_MATCH_SIMILARITY: Final = "title_attribute_similarity"
COMMERCE_MATCH_REASONS: Final[tuple[str, ...]] = (
    COMMERCE_MATCH_GTIN,
    COMMERCE_MATCH_BRAND_MODEL,
    COMMERCE_MATCH_FAMILY_VARIANT,
    COMMERCE_MATCH_SIMILARITY,
)
COMMERCE_GTIN_KEYS: Final[tuple[str, ...]] = ("gtin", "upc", "ean")
COMMERCE_MODEL_KEYS: Final[tuple[str, ...]] = ("mpn", "model", "model_number")
COMMERCE_BRAND_KEY: Final = "brand"
COMMERCE_FAMILY_KEYS: Final[tuple[str, ...]] = ("family", "product_family")
COMMERCE_VARIANT_KEYS: Final[tuple[str, ...]] = ("variant", "variant_name")
COMMERCE_SIMILARITY_ATTRIBUTE_KEYS: Final[tuple[str, ...]] = (
    "brand",
    "category",
    "material",
    "color",
    "size",
)
COMMERCE_EVIDENCE_KIND_UPLOAD: Final = "upload"
COMMERCE_EVIDENCE_KIND_URL: Final = "url"
COMMERCE_EVIDENCE_KIND_CRAWLED: Final = "crawled"
COMMERCE_EVIDENCE_KIND_STRUCTURED: Final = "structured"
COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING: Final = "google_shopping"
COMMERCE_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        COMMERCE_EVIDENCE_KIND_UPLOAD,
        COMMERCE_EVIDENCE_KIND_URL,
        COMMERCE_EVIDENCE_KIND_CRAWLED,
        COMMERCE_EVIDENCE_KIND_STRUCTURED,
        COMMERCE_EVIDENCE_KIND_GOOGLE_SHOPPING,
    }
)
COMMERCE_DISCOVERY_ERROR_EMPTY_EXTRACTION: Final = "commerce_empty_extraction"
COMMERCE_DISCOVERY_ERROR_HTTP_STATUS: Final = "commerce_http_status"
COMMERCE_DISCOVERY_ERROR_LEGACY_PLACEHOLDER: Final = "commerce_legacy_placeholder"
COMMERCE_DISCOVERY_ERROR_WORKER_CRASH: Final = "commerce_worker_crash"


class CommerceIntelligenceSettings(BaseSettings):
    """Operational bounds for deterministic Commerce discovery workers."""

    model_config = SettingsConfigDict(env_prefix="COMMERCE_", extra="ignore")

    discovery_lease_ttl_seconds: float = Field(default=120.0, ge=1.0)
    discovery_max_attempts: int = Field(default=3, ge=1, le=20)
    discovery_preview_max_rows: int = Field(default=500, ge=1, le=5000)
    discovery_max_candidates_per_run: int = Field(default=500, ge=1, le=5000)
    discovery_max_artifact_payload_chars: int = Field(default=16_000, ge=256)
    discovery_worker_batch_size: int = Field(default=4, ge=1, le=100)
    discovery_heartbeat_interval_seconds: float = Field(default=30.0, gt=0)
    discovery_poll_interval_seconds: float = Field(default=1.0, gt=0)
    discovery_lease_reclaim_batch_size: int = Field(default=100, ge=1, le=1000)
    discovery_retry_base_delay_seconds: float = Field(default=2.0, gt=0)
    discovery_retry_max_delay_seconds: float = Field(default=60.0, gt=0)
    discovery_max_extraction_bytes: int = Field(default=1_000_000, ge=1024)
    discovery_max_field_chars: int = Field(default=1024, ge=32, le=16_000)
    discovery_max_schema_blocks: int = Field(default=32, ge=1, le=500)
    discovery_max_schema_nodes: int = Field(default=200, ge=1, le=5000)
    discovery_max_variants: int = Field(default=50, ge=1, le=500)
    discovery_max_aliases: int = Field(default=50, ge=1, le=500)
    discovery_max_attribute_items: int = Field(default=50, ge=1, le=500)
    discovery_max_trace_entries: int = Field(default=20, ge=1, le=500)
    discovery_retryable_http_statuses: tuple[int, ...] = (429,)
    discovery_server_error_status_floor: int = Field(default=500, ge=400, le=599)
    discovery_allowed_content_types: tuple[str, ...] = (
        "text/html",
        "application/xhtml+xml",
        "application/json",
        "application/ld+json",
    )
    discovery_structured_source_hosts: tuple[str, ...] = ()
    discovery_google_shopping_source_hosts: tuple[str, ...] = ()
    discovery_schema_confidence: float = Field(default=0.9, ge=0, le=1)
    discovery_html_confidence: float = Field(default=0.6, ge=0, le=1)
    comparison_max_entries: int = Field(default=1_000, ge=1, le=10_000)
    title_attribute_similarity_threshold: float = Field(default=0.82, ge=0, le=1)
    match_ambiguity_margin: float = Field(default=0.05, ge=0, le=1)

    def retry_delay(
        self, attempt: int, retry_after_seconds: float | None = None
    ) -> float:
        """Deterministic bounded backoff for a completed network attempt."""
        if retry_after_seconds is not None:
            return min(retry_after_seconds, self.discovery_retry_max_delay_seconds)
        return min(
            self.discovery_retry_base_delay_seconds * (2**attempt),
            self.discovery_retry_max_delay_seconds,
        )


commerce_intelligence_settings = CommerceIntelligenceSettings()


def _commerce_discovery_task_model():
    # Lazy import keeps models -> config imports acyclic.
    from app.models.commerce import CommerceDiscoveryTask

    return CommerceDiscoveryTask


def _commerce_discovery_claim_order(model):
    return (
        model.priority.desc(),
        model.available_at.asc(),
        model.randomized_position.asc(),
        model.id.asc(),
    )


COMMERCE_DISCOVERY_QUEUE_SPEC = PostgresQueueSpec(
    model_ref=_commerce_discovery_task_model,
    lease_ttl=lambda: commerce_intelligence_settings.discovery_lease_ttl_seconds,
    claim_order=_commerce_discovery_claim_order,
    max_attempts_error=ERROR_MAX_ATTEMPTS,
    parent_id_attr="run_id",
)

# --- Win rate (§5.1) -------------------------------------------------------
# When True, the win-rate denominator is only the SKU's mention rows with a
# non-null rank_position: an execution that enumerates competitors without
# mentioning the SKU is not a loss (it is invisible to win rate).
PRODUCT_WIN_REQUIRES_ENUMERATION: Final = True

# --- Attribute dimensions (§5.3) -------------------------------------------
# Deterministic phrase-matched attribute mentions. Frequency only — valence
# is not deterministic and is deferred to the sentiment layer.
ATTRIBUTE_DIMENSION_GROUPS: Final[frozenset[str]] = frozenset(
    {"characteristics", "facts", "ratings"}
)

# Character window scanned for attribute phrases / destination URLs around a
# product mention's original-text offset (clipped to the mention's line).
PRODUCT_ATTRIBUTE_WINDOW_CHARS: Final = 200

# Bound on persisted competitor co-placement pairs per entry aggregate
# (O(mentions^2) per execution); ``truncated`` records when the cap is hit.
CO_PLACEMENT_MAX_PAIRS: Final = 1000


@dataclass(frozen=True)
class AttributeDimension:
    """One deterministic attribute dimension: casefolded whole-phrase literals."""

    key: str
    group: str  # characteristics | facts | ratings
    phrases: tuple[str, ...]


# Category-keyed seed catalog. The scorer always evaluates DEFAULT plus the
# category-specific tuple; unknown/empty categories evaluate DEFAULT only.
ATTRIBUTE_DIMENSIONS: Final[dict[str, tuple[AttributeDimension, ...]]] = {
    "DEFAULT": (
        AttributeDimension(
            key="price",
            group="facts",
            phrases=("price", "cost", "priced at", "sale price"),
        ),
        AttributeDimension(
            key="warranty",
            group="facts",
            phrases=("warranty", "guarantee", "coverage"),
        ),
        AttributeDimension(
            key="shipping",
            group="facts",
            phrases=("shipping", "delivery", "ships", "free shipping"),
        ),
        AttributeDimension(
            key="returns",
            group="facts",
            phrases=("returns", "return policy", "refund", "exchange"),
        ),
        AttributeDimension(
            key="materials",
            group="characteristics",
            phrases=("material", "materials", "made from", "made of", "fabric"),
        ),
        AttributeDimension(
            key="sizing",
            group="facts",
            phrases=("size", "sizes", "sizing", "size guide"),
        ),
    ),
    "footwear": (
        AttributeDimension(
            key="fit",
            group="ratings",
            phrases=("fit", "fits", "true to size", "runs small", "runs large"),
        ),
        AttributeDimension(
            key="comfort",
            group="ratings",
            phrases=("comfort", "comfortable", "cushioning", "cushioned"),
        ),
        AttributeDimension(
            key="support",
            group="characteristics",
            phrases=("arch support", "ankle support", "stability"),
        ),
        AttributeDimension(
            key="traction",
            group="characteristics",
            phrases=("traction", "grip", "outsole"),
        ),
        AttributeDimension(
            key="waterproofing",
            group="characteristics",
            phrases=("waterproof", "water resistant", "water-resistant"),
        ),
    ),
    "outerwear": (
        AttributeDimension(
            key="warmth",
            group="ratings",
            phrases=("warmth", "warm", "temperature rating"),
        ),
        AttributeDimension(
            key="insulation",
            group="characteristics",
            phrases=("insulation", "insulated", "down fill", "synthetic fill"),
        ),
        AttributeDimension(
            key="weather_protection",
            group="characteristics",
            phrases=(
                "waterproof",
                "water resistant",
                "water-resistant",
                "windproof",
                "wind resistant",
            ),
        ),
        AttributeDimension(
            key="breathability",
            group="ratings",
            phrases=("breathability", "breathable", "ventilation"),
        ),
        AttributeDimension(
            key="layering",
            group="facts",
            phrases=("layering", "layer", "midlayer", "shell"),
        ),
    ),
    "accessories": (
        AttributeDimension(
            key="compatibility",
            group="facts",
            phrases=("compatibility", "compatible with", "works with", "fits"),
        ),
        AttributeDimension(
            key="capacity",
            group="facts",
            phrases=("capacity", "volume", "litre", "liter"),
        ),
        AttributeDimension(
            key="dimensions",
            group="facts",
            phrases=("dimensions", "height", "width", "depth"),
        ),
        AttributeDimension(
            key="durability",
            group="ratings",
            phrases=("durability", "durable", "wear resistance"),
        ),
        AttributeDimension(
            key="weight",
            group="facts",
            phrases=("weight", "lightweight", "weighs"),
        ),
    ),
}

# --- Price relation (§5.2) --------------------------------------------------
PRICE_RELATION_MATCH: Final = "match"
PRICE_RELATION_HIGHER: Final = "higher"
PRICE_RELATION_LOWER: Final = "lower"
PRICE_RELATIONS: Final[frozenset[str]] = frozenset(
    {PRICE_RELATION_MATCH, PRICE_RELATION_HIGHER, PRICE_RELATION_LOWER}
)
# Legacy v1 boolean fallback label (projection-only; never persisted on a v2
# row): a v1 ``price_matches_catalog=False`` reads as ``mismatch`` with no
# direction available.
PRICE_RELATION_MISMATCH: Final = "mismatch"

# --- Merchant presence / buyer destination (§5.4) ---------------------------
MERCHANT_KIND_MARKETPLACE: Final = "marketplace"
MERCHANT_KIND_RETAILER: Final = "retailer"
MERCHANT_KIND_BRAND_SITE: Final = "brand_site"
MERCHANT_KIND_OTHER: Final = "other"
MERCHANT_KINDS: Final[frozenset[str]] = frozenset(
    {
        MERCHANT_KIND_MARKETPLACE,
        MERCHANT_KIND_RETAILER,
        MERCHANT_KIND_BRAND_SITE,
        MERCHANT_KIND_OTHER,
    }
)

# Known buyer destinations: normalized host -> (display name, kind). Matched
# suffix-safe via ``domain_matches`` so a subdomain of ``amazon.com`` is the
# Amazon marketplace but ``notamazon.com`` stays ``other``.
MERCHANT_DOMAINS: Final[dict[str, tuple[str, str]]] = {
    "amazon.com": ("Amazon", MERCHANT_KIND_MARKETPLACE),
    "ebay.com": ("eBay", MERCHANT_KIND_MARKETPLACE),
    "etsy.com": ("Etsy", MERCHANT_KIND_MARKETPLACE),
    "walmart.com": ("Walmart", MERCHANT_KIND_RETAILER),
    "target.com": ("Target", MERCHANT_KIND_RETAILER),
    "bestbuy.com": ("Best Buy", MERCHANT_KIND_RETAILER),
}

SHOPPING_SURFACE_MEASUREMENT: Final = ""
# The disabled probe gate. A future record maps surface id -> its frozen
# identity keys (``logical_engine``, ``transport_provider``,
# ``transport_model``); the planner then freezes one
# ``AuditShoppingSurfaceSnapshot`` per configured surface. No entries in M2a
# and ``MEASUREMENT_ROUTES`` is unchanged, so no probe tasks/snapshots exist.
SHOPPING_SURFACES: Final[dict[str, dict[str, str]]] = {}

# --- Product evidence projection --------------------------------------------
# The three projected evidence kinds on ``GET /products/{id}/visibility/
# evidence`` (one base item per ProductMention, one per persisted attribute
# object, one per MerchantMention row).
PRODUCT_EVIDENCE_KIND_PRODUCT_MENTION: Final = "product_mention"
PRODUCT_EVIDENCE_KIND_ATTRIBUTE_MENTION: Final = "attribute_mention"
PRODUCT_EVIDENCE_KIND_BUYER_DESTINATION: Final = "buyer_destination"
PRODUCT_EVIDENCE_KINDS: Final[frozenset[str]] = frozenset(
    {
        PRODUCT_EVIDENCE_KIND_PRODUCT_MENTION,
        PRODUCT_EVIDENCE_KIND_ATTRIBUTE_MENTION,
        PRODUCT_EVIDENCE_KIND_BUYER_DESTINATION,
    }
)

# Fixed UUID5 namespace for projected attribute-evidence row identity: an
# attribute mention lives inside a ProductMention JSONB list (no table/PK), so
# its stable ``evidence_id`` is derived from
# ``{analysis_id}:{mention_id}:{dimension}:{offset}`` under this namespace.
PRODUCT_ATTRIBUTE_EVIDENCE_NAMESPACE: Final[uuid.UUID] = uuid.UUID(
    "73a01bbd-f974-58d4-a213-a178455bc018"
)

# --- Shopify order sanitization (commerce suite, invariant 6) ---------------
# Versions the raw-order -> SanitizedOrder transform. Stamped on every
# sanitized artifact payload + OrderFact so a sanitizer change is visible in
# provenance (re-sanitization happens on the next sync, never in place).
ORDER_SANITIZE_VERSION: Final = "order-sanitize-1"
# Hex length of the persisted ``order_ref_hash``: the FULL HMAC-SHA256 of the
# raw Shopify order id keyed with ``Settings.order_hash_salt`` (the raw id
# never persists — it is PII-adjacent provider data).
ORDER_REF_HASH_HEX_LENGTH: Final = 64
# Persisted order facts are hard-deleted past this horizon by the order
# retention sweep (mirrors the referral retention posture).
ORDER_RETENTION_DAYS: Final = 90
# Bound on order facts deleted per committed sweep batch.
ORDER_RETENTION_DELETE_BATCH_SIZE: Final = 500

# The ONLY order-level keys the sanitizer allowlists (``SanitizedOrder``
# fields). Anything outside this set on a raw provider order — customer,
# email, phone, addresses, payment, note, IP — never survives.
ORDER_SANITIZED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "order_ref_hash",
        "occurred_at",
        "updated_at",
        "cancelled_at",
        "currency",
        "total_amount",
        "financial_status",
        "fulfillment_status",
        "journey_state",
        "line_items",
        "attribution_keys",
    }
)
# The ONLY keys a sanitized line item carries. ``product_id`` is added by
# order derivation AFTER SKU resolution (never part of the artifact payload).
ORDER_LINE_ITEM_KEYS: Final[tuple[str, ...]] = ("sku", "quantity", "unit_price")
# Journey coverage vocabulary: ``customerJourneySummary.ready`` false (or no
# visit) records EXPLICIT unavailable coverage — never a guessed journey.
ORDER_JOURNEY_STATE_AVAILABLE: Final = "available"
ORDER_JOURNEY_STATE_UNAVAILABLE: Final = "unavailable"
# The allowlist of non-PII attribution evidence keys a sanitized order may
# carry (URLs pre-sanitized through the shared referral-URL sanitizer).
ORDER_ATTRIBUTION_KEY_ALLOWLIST: Final[frozenset[str]] = frozenset(
    {
        "landing_url",
        "referrer_url",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "source_name",
    }
)

# --- Commerce importer version ------------------------------------------------
# Versions the artifact -> catalog/feed/order-fact derivation code (NOT the
# data revision — that identity is the fact's ``resync_seq``).
COMMERCE_IMPORTER_VERSION: Final = "commerce-importer-1"

# --- Feed rules (§9.3 deterministic rules only) ------------------------------
# Severity vocabulary for FeedIssue rows.
FEED_SEVERITY_INFO: Final = "info"
FEED_SEVERITY_WARNING: Final = "warning"
FEED_SEVERITY_ERROR: Final = "error"
FEED_SEVERITIES: Final[frozenset[str]] = frozenset(
    {FEED_SEVERITY_INFO, FEED_SEVERITY_WARNING, FEED_SEVERITY_ERROR}
)
# The in-scope deterministic rule ids. M3's ``feed.stale_catalog_data``,
# ``feed.ai_channel_ineligible``, and ``feed.entity_inconsistency`` are
# deliberately NOT here. The spec §9.3 "platform AI-eligibility verdict"
# feed source is a documented DELIBERATE EXCLUSION in this slice: it
# arrives with GMC (excluded) and Shopify's native Agentic Commerce
# Dashboard is not a read API we consume.
FEED_RULE_MISSING_SKU: Final = "feed.missing_sku"
FEED_RULE_MISSING_GTIN_MPN: Final = "feed.missing_gtin_mpn"
FEED_RULE_MISSING_AVAILABILITY: Final = "feed.missing_availability"
FEED_RULE_CATALOG_PRICE_DIVERGENCE: Final = "feed.catalog_price_divergence"
FEED_RULE_DUPLICATE_SKU_ACROSS_CONNECTIONS: Final = (
    "feed.duplicate_sku_across_connections"
)
FEED_RULE_SEVERITIES: Final[dict[str, str]] = {
    FEED_RULE_MISSING_SKU: FEED_SEVERITY_ERROR,
    FEED_RULE_MISSING_GTIN_MPN: FEED_SEVERITY_WARNING,
    FEED_RULE_MISSING_AVAILABILITY: FEED_SEVERITY_WARNING,
    FEED_RULE_CATALOG_PRICE_DIVERGENCE: FEED_SEVERITY_WARNING,
    FEED_RULE_DUPLICATE_SKU_ACROSS_CONNECTIONS: FEED_SEVERITY_ERROR,
}
FEED_RULES: Final[frozenset[str]] = frozenset(FEED_RULE_SEVERITIES)

# --- Catalog merge (§9.2) ------------------------------------------------------
# The platform-owned Product ``attributes`` keys a Shopify feed row may
# overwrite (``gtin`` comes from the variant barcode). Aliases are NEVER in
# the platform-owned set — a sync never creates/replaces/deletes an alias.
SHOPIFY_PLATFORM_ATTRIBUTE_KEYS: Final[frozenset[str]] = frozenset(
    {"gtin", "description", "vendor", "product_type", "status", "availability"}
)
# Shopify's single-variant placeholder title: normalized to "" so a real
# variant title never gets polluted by the provider's default.
SHOPIFY_DEFAULT_VARIANT_TITLE: Final = "Default Title"
# Availability attribute values projected from variant inventory (the
# catalog ``attributes["availability"]`` key). A null inventory quantity
# leaves the attribute ABSENT (the missing-availability rule fires).
SHOPIFY_AVAILABILITY_IN_STOCK: Final = "in_stock"
SHOPIFY_AVAILABILITY_OUT_OF_STOCK: Final = "out_of_stock"
# Catalog-price divergence rule: fire when the feed price differs from the
# persisted Product price by MORE than this absolute tolerance OR this
# relative fraction of the persisted price (whichever is larger) — exact
# equality within rounding never pages.
FEED_PRICE_DIVERGENCE_ABS_TOLERANCE: Final = "0.01"
FEED_PRICE_DIVERGENCE_REL_TOLERANCE: Final = "0.001"
