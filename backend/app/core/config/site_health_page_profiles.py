"""Config-owned Product fact and schema policy used by the shared registry."""

from __future__ import annotations

from typing import Final

from app.core.config.site_health_taxonomy import (
    PAGE_KIND_PRODUCT,
    PageKindSchemaExpectation,
)

# Product / Offer property paths retained by the bounded structured-data
# extractor.  These are intentionally separate from the generic per-type
# expectation table so acquisition work does not need to touch it.
PRODUCT_SCHEMA_PROPERTY_PATHS: Final[frozenset[str]] = frozenset(
    {
        "sku",
        "gtin",
        "gtin8",
        "gtin12",
        "gtin13",
        "gtin14",
        "mpn",
        "brand",
        "offers.price",
        "offers.priceCurrency",
        "offers.availability",
        "offers.shippingDetails",
        "offers.hasMerchantReturnPolicy",
        "hasVariant",
        "isVariantOf",
        "aggregateRating",
        "review",
        "ratingValue",
    }
)
PRODUCT_RECOGNIZED_SCHEMA_TYPES: Final[frozenset[str]] = frozenset(
    {"Offer", "AggregateRating"}
)
PRODUCT_FACT_MAX_VALUES: Final = 12
PRODUCT_FACT_MAX_VALUE_CHARS: Final = 256
PRODUCT_NESTED_VALUE_KEYS: Final[tuple[str, ...]] = ("name", "ratingValue")

# Product pages keep the base Product requirement but complete the documented
# Product/Offer contract with identity, offer, variant, trust, and delivery
# properties.  The generic rules consume this effective expectation.
PRODUCT_SCHEMA_EXPECTATION: Final = PageKindSchemaExpectation(
    page_kind=PAGE_KIND_PRODUCT,
    expected_types=("Product",),
    required_properties=("name", "offers"),
    recommended_properties=(
        "sku",
        "gtin",
        "brand",
        "offers.price",
        "offers.priceCurrency",
        "offers.availability",
        "hasVariant",
        "aggregateRating",
        "offers.shippingDetails",
        "offers.hasMerchantReturnPolicy",
    ),
)

# Claims a PDP is actually expected to SHOW. ``gtin`` is deliberately absent:
# a barcode number is real, correct data that essentially no storefront prints
# on the page, so parity-checking it reported a mismatch on every compliant
# product page -- 36 of 37 PDPs on the reference crawl.
PRODUCT_PARITY_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "sku",
    "brand",
    "price",
    "availability",
)

# ``availability`` is a schema.org URI enum; the page says it in English. The
# raw value can never appear in visible text, so it is compared through this
# map instead. Keys and values are matched after the same normalization the
# parity check applies to visible text (non-alphanumerics removed).
PRODUCT_AVAILABILITY_VISIBLE_TERMS: Final[dict[str, tuple[str, ...]]] = {
    "instock": ("instock", "addtocart", "addtobag", "addtobasket", "available"),
    "onlineonly": ("instock", "onlineonly", "available"),
    "instoreonly": ("instoreonly", "availableinstore"),
    "outofstock": (
        "outofstock",
        "soldout",
        "unavailable",
        "notavailable",
        "notifyme",
    ),
    "soldout": ("soldout", "outofstock", "unavailable", "notavailable"),
    "preorder": ("preorder", "preordernow"),
    "presale": ("presale", "preorder"),
    "backorder": ("backorder", "backordered"),
    "discontinued": ("discontinued", "nolongeravailable"),
    "limitedavailability": ("limitedstock", "lowstock", "limitedavailability"),
}

# These states must be checked before positive terms such as ``available``.
# Otherwise "not available" can corroborate an ``InStock`` claim.
PRODUCT_NEGATIVE_AVAILABILITY_KEYS: Final[tuple[str, ...]] = (
    "outofstock",
    "soldout",
    "discontinued",
)

# A schema name and its visible heading rarely match character for character:
# "Dillen Letter Carrier, Caramel" is the same product as the "Dillen Letter
# Carrier" in the H1. Substring containment called that a mismatch on 36 of 37
# PDPs, so comparison is by shared word tokens instead.
SCHEMA_CONTENT_MATCH_MIN_TOKEN_OVERLAP: Final = 0.6
PRODUCT_PARITY_NORMALIZATION_PATTERN: Final = r"[^a-z0-9]+"
PRODUCT_SCHEMA_URI_SEPARATOR: Final = "/"
PRODUCT_PARITY_SCHEMA_FACT_KEYS: Final[dict[str, str]] = {
    "sku": "sku",
    "gtin": "gtin",
    "brand": "brand",
    "price": "price",
    "availability": "availability",
}

# Stable reason tokens stored in classifier evidence.  They are config-owned
# so a wording/policy revision is explicit and replayable.
CLASSIFICATION_OTHER_REASON_NO_SIGNALS: Final = "no_classification_signals"
CLASSIFICATION_OTHER_REASON_SCHEMA_ONLY: Final = "schema_only"
CLASSIFICATION_OTHER_REASON_CONFLICT: Final = "conflicting_top_tier_evidence"
CLASSIFICATION_MAX_ALTERNATIVES: Final = 8

# Grouped issue history remains bounded even for a long-lived monitored URL.
ISSUE_HISTORY_TIMELINE_MAX_CRAWLS: Final = 24
