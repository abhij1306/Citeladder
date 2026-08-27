"""Configuration and version vocabulary for the Commerce replacement."""

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.dotenv import dotenv_sources

COMMERCE_PROJECTOR_VERSION: Final = "commerce-projector-3"
COMMERCE_IMPORTER_VERSION: Final = "commerce-catalog-importer-1"
COMMERCE_EDIT_VERSION: Final = "commerce-catalog-edit-2"
COMMERCE_CATEGORY_EDIT_VERSION: Final = "commerce-category-edit-1"
COMMERCE_COMPETITOR_PROVIDER_VERSION: Final = "tavily-commerce-1"
COMMERCE_COMPETITOR_VALIDATOR_VERSION: Final = "commerce-competitor-validator-4"
COMMERCE_PROMPT_TEMPLATE_VERSION: Final = "commerce-buyer-prompts-2"
COMMERCE_RECOMMENDATION_PARSER_VERSION: Final = "commerce-recommendation-parser-3"
COMMERCE_RECOMMENDATION_MATCHER_VERSION: Final = "commerce-recommendation-matcher-3"
COMMERCE_SHELF_FORMULA_VERSION: Final = "commerce-shelf-formulas-2"

COMMERCE_PROMPTS_MIN: Final = 2
COMMERCE_PROMPTS_DEFAULT: Final = 5
COMMERCE_PROMPTS_MAX: Final = 10
COMMERCE_COMPETITOR_RESULT_LIMIT: Final = 5
COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT: Final = 10
COMMERCE_IMPORT_MAX_BYTES: Final = 2_000_000
COMMERCE_IMPORT_MAX_ROWS: Final = 10_000
COMMERCE_IMPORT_ERROR_LIMIT: Final = 100
COMMERCE_RECOMMENDATION_RESOLVER_SPAN_LIMIT: Final = 12
COMMERCE_RECOMMENDATION_RESOLVER_SPAN_CHARS: Final = 2_000
COMMERCE_RECOMMENDATION_RESOLVER_RESULT_LIMIT: Final = 8
COMMERCE_COMPETITOR_QUERY_ATTRIBUTE_LIMIT: Final = 4
# Candidate verification fetches pages, so it is bounded twice: how many run at
# once, and how long any single page may take. Verification used to run one URL
# at a time with no per-URL deadline, so a discovery took minutes and held its
# queue lease open for all of them.
# A category or product name longer than this is a page title or a sentence of
# marketing copy, not something a buyer searches for.
COMMERCE_COMPETITOR_TARGET_NAME_MAX_WORDS: Final = 8
COMMERCE_COMPETITOR_VERIFY_CONCURRENCY: Final = 5
COMMERCE_COMPETITOR_VERIFY_TIMEOUT_SECONDS: Final = 10.0
COMMERCE_COMPETITOR_PRICE_BANDS: Final[tuple[tuple[float, str], ...]] = (
    (25.0, "under 25"),
    (75.0, "25 to 75"),
    (200.0, "75 to 200"),
    (500.0, "200 to 500"),
    (float("inf"), "over 500"),
)

COMMERCE_TARGET_KINDS: Final = frozenset({"category", "product"})
COMMERCE_CATEGORY_ROLES: Final = frozenset({"hub", "leaf", "unknown"})
COMMERCE_LIFECYCLE_STATES: Final = frozenset({"active", "archived"})
COMMERCE_COMPETITOR_STATES: Final = frozenset(
    {"pending", "approved", "rejected", "excluded"}
)
COMMERCE_OBSERVATION_CLASSES: Final = frozenset(
    {"owned", "approved_competitor", "ai_observed_competitor", "unresolved"}
)
COMMERCE_SURFACE_KINDS: Final = frozenset({"recommendation", "shopping_result"})
COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS: Final = (
    "/blog/",
    "/news/",
    "/article/",
    "/search",
)
COMMERCE_COMPETITOR_NON_PDP_HOST_SUFFIXES: Final = (
    "reddit.com",
    "youtube.com",
    "youtu.be",
    "medium.com",
)
# Marketplaces, resale and aggregators, for COMPETITOR DISCOVERY only. Each
# hosts real PDPs, so every structural gate passes them, and a category search
# returned Poshmark and Stylight listings of other retailers' products ahead of
# the brands that actually compete. They are someone else's shelf, never the
# competitor. Deliberately separate from the non-PDP host list above: Amazon is
# very much a PDP host, and AI Shelf must keep resolving it as one.
COMMERCE_COMPETITOR_EXCLUDED_HOST_SUFFIXES: Final = (
    "amazon.com",
    "ebay.com",
    "etsy.com",
    "poshmark.com",
    "stylight.com",
    "thredup.com",
    "depop.com",
    "mercari.com",
    "lyst.com",
    "shopstyle.com",
    "pinterest.com",
    "aliexpress.com",
    "walmart.com",
    "target.com",
    "shein.com",
    "temu.com",
    "vinted.com",
    "farfetch.com",
    "zalando.com",
    "google.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
)
COMMERCE_SECOND_HAND_TOKENS: Final = ("used", "pre-owned", "second hand", "refurbished")
COMMERCE_DOLLAR_CURRENCY_BY_COUNTRY: Final = {
    "AU": "AUD",
    "CA": "CAD",
    "US": "USD",
}
COMMERCE_VISIBLE_PRICE_CURRENCY_MARKERS: Final[tuple[tuple[str, str], ...]] = (
    ("$", ""),
    ("AUD", "AUD"),
    ("USD", "USD"),
    ("CAD", "CAD"),
    ("NZD", "NZD"),
    ("GBP", "GBP"),
    ("EUR", "EUR"),
    ("INR", "INR"),
    ("£", "GBP"),
    ("€", "EUR"),
    ("₹", "INR"),
)
COMMERCE_VISIBLE_PRICE_AMBIGUOUS_TOKENS: Final = (
    "%",
    "from ",
    "starting at ",
    "up to ",
    " over ",
    " under ",
)


class CommerceSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=dotenv_sources(), env_file_encoding="utf-8", extra="ignore"
    )

    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY")
    tavily_endpoint: str = Field(
        default="https://api.tavily.com/search", validation_alias="TAVILY_ENDPOINT"
    )
    tavily_timeout_seconds: float = Field(default=20.0, gt=0, le=60)


commerce_settings = CommerceSettings()
