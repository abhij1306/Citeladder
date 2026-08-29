"""Versioned policy for the conservative observed-site architecture model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.config.brand_discovery import SERVICE_BUSINESS_MODELS
from app.core.config.site_health_taxonomy import (
    PAGE_KIND_ABOUT_CONTACT,
    PAGE_KIND_ARTICLE,
    PAGE_KIND_CATEGORY,
    PAGE_KIND_COMPARISON,
    PAGE_KIND_DOCS,
    PAGE_KIND_FAQ,
    PAGE_KIND_GUIDE,
    PAGE_KIND_HOMEPAGE,
    PAGE_KIND_LOCAL,
    PAGE_KIND_PRICING,
    PAGE_KIND_PRODUCT,
    PAGE_KIND_SERVICE,
    PAGE_KIND_TRUST_POLICY,
)

ARCHITECTURE_FORMULA_VERSION: Final = "sh-architecture-1"
ARCHETYPE_POLICY_VERSION: Final = "sh-archetypes-1"

ARCHETYPE_COMMERCE: Final = "commerce"
ARCHETYPE_SOFTWARE: Final = "software"
ARCHETYPE_SERVICES: Final = "services"
ARCHETYPE_OTHER: Final = "other"

ARCHETYPE_SOURCE_ONBOARDING: Final = "onboarding_profile"
ARCHETYPE_SOURCE_ABSTAINED: Final = "abstained"
# A user correction is a PRESENTATION-layer override: it re-reads the same
# persisted evidence under a different archetype and never rewrites, re-scores,
# or re-derives the immutable model row.
ARCHETYPE_BUSINESS_MODEL_CONFIDENCE_FLOOR: Final = 0.65
ARCHETYPE_CONTRADICTION_MIN_PAGES: Final = 5
ARCHETYPE_CONTRADICTION_SHARE: Final = 0.6

ARCHETYPE_BY_BUSINESS_MODEL: Final[dict[str, str]] = {
    "retail": ARCHETYPE_COMMERCE,
    "d2c_product": ARCHETYPE_COMMERCE,
    "marketplace": ARCHETYPE_COMMERCE,
    "b2b_saas": ARCHETYPE_SOFTWARE,
    **{model: ARCHETYPE_SERVICES for model in SERVICE_BUSINESS_MODELS},
    "regulated_finance": ARCHETYPE_SERVICES,
}

# A crawl may veto an unconfirmed onboarding archetype, but can never assign
# one. These are intentionally broad structural contradictions rather than a
# second page classifier.
ARCHETYPE_CONTRADICTING_PAGE_KINDS: Final[dict[str, frozenset[str]]] = {
    ARCHETYPE_COMMERCE: frozenset(
        {PAGE_KIND_DOCS, PAGE_KIND_SERVICE, PAGE_KIND_COMPARISON}
    ),
    ARCHETYPE_SOFTWARE: frozenset({PAGE_KIND_PRODUCT, PAGE_KIND_CATEGORY}),
    ARCHETYPE_SERVICES: frozenset(
        {PAGE_KIND_PRODUCT, PAGE_KIND_CATEGORY, PAGE_KIND_DOCS}
    ),
}
ARCHETYPE_CORROBORATING_PAGE_KINDS: Final[dict[str, frozenset[str]]] = {
    ARCHETYPE_COMMERCE: frozenset({PAGE_KIND_PRODUCT, PAGE_KIND_CATEGORY}),
    ARCHETYPE_SOFTWARE: frozenset(
        {PAGE_KIND_DOCS, PAGE_KIND_SERVICE, PAGE_KIND_PRICING, PAGE_KIND_COMPARISON}
    ),
    ARCHETYPE_SERVICES: frozenset(
        {PAGE_KIND_SERVICE, PAGE_KIND_LOCAL, PAGE_KIND_ABOUT_CONTACT}
    ),
}

ARCHITECTURE_HUB_PAGE_KINDS: Final[frozenset[str]] = frozenset(
    {PAGE_KIND_HOMEPAGE, PAGE_KIND_CATEGORY, PAGE_KIND_DOCS}
)
ARCHITECTURE_DETAIL_PAGE_KINDS: Final[frozenset[str]] = frozenset(
    {
        PAGE_KIND_PRODUCT,
        PAGE_KIND_ARTICLE,
        PAGE_KIND_GUIDE,
        PAGE_KIND_LOCAL,
        PAGE_KIND_SERVICE,
    }
)

ARCHITECTURE_EXCESSIVE_DEPTH_MIN: Final = 5
ARCHITECTURE_DUPLICATE_METADATA_MIN_URLS: Final = 3
ARCHITECTURE_DUPLICATE_METADATA_RATE: Final = 0.5
ARCHITECTURE_UNHUBBED_PAGE_KIND_MIN_URLS: Final = 3
ARCHITECTURE_MAX_PAGES: Final = 500
ARCHITECTURE_MAX_EVIDENCE_ITEMS: Final = 25
# Beyond this, an exported sibling set of one page kind renders as one count line.
ARCHITECTURE_PAGE_KIND_COLLAPSE_MIN: Final = 8
ARCHITECTURE_MAX_BREADCRUMB_ITEMS: Final = 16


@dataclass(frozen=True, slots=True)
class CommonStructure:
    key: str
    label: str
    page_kinds: frozenset[str] = frozenset()
    path_segments: frozenset[str] = frozenset()
    local_market_only: bool = False


COMMON_STRUCTURES: Final[dict[str, tuple[CommonStructure, ...]]] = {
    ARCHETYPE_COMMERCE: (
        CommonStructure("products", "Product pages", frozenset({PAGE_KIND_PRODUCT})),
        CommonStructure(
            "categories", "Category pages", frozenset({PAGE_KIND_CATEGORY})
        ),
        CommonStructure(
            "shipping_returns",
            "Shipping / returns",
            path_segments=frozenset(
                {"shipping", "returns", "refund-policy", "shipping-policy"}
            ),
        ),
        CommonStructure(
            "contact",
            "Contact",
            path_segments=frozenset({"contact", "contact-us"}),
        ),
        CommonStructure(
            "help_hub",
            "Help / FAQ hub",
            frozenset({PAGE_KIND_FAQ}),
            frozenset({"help", "support", "faq"}),
        ),
        CommonStructure(
            "editorial",
            "Editorial content",
            frozenset({PAGE_KIND_ARTICLE, PAGE_KIND_GUIDE}),
        ),
    ),
    ARCHETYPE_SOFTWARE: (
        CommonStructure("pricing", "Pricing", frozenset({PAGE_KIND_PRICING})),
        CommonStructure(
            "features", "Product / feature pages", frozenset({PAGE_KIND_SERVICE})
        ),
        CommonStructure("docs", "Documentation", frozenset({PAGE_KIND_DOCS})),
        CommonStructure(
            "contact", "About / contact", frozenset({PAGE_KIND_ABOUT_CONTACT})
        ),
        CommonStructure(
            "comparison", "Comparison pages", frozenset({PAGE_KIND_COMPARISON})
        ),
        CommonStructure(
            "editorial",
            "Editorial content",
            frozenset({PAGE_KIND_ARTICLE, PAGE_KIND_GUIDE}),
        ),
    ),
    ARCHETYPE_SERVICES: (
        CommonStructure("services", "Service pages", frozenset({PAGE_KIND_SERVICE})),
        CommonStructure(
            "contact", "About / contact", frozenset({PAGE_KIND_ABOUT_CONTACT})
        ),
        CommonStructure(
            "trust", "Trust / policy pages", frozenset({PAGE_KIND_TRUST_POLICY})
        ),
        CommonStructure(
            "locations",
            "Location pages",
            frozenset({PAGE_KIND_LOCAL}),
            local_market_only=True,
        ),
        CommonStructure(
            "guides", "Guides", frozenset({PAGE_KIND_GUIDE, PAGE_KIND_ARTICLE})
        ),
    ),
    ARCHETYPE_OTHER: (),
}


__all__ = [name for name in globals() if name.isupper() or name == "CommonStructure"]
