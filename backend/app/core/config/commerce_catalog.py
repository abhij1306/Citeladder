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
COMMERCE_COMPETITOR_VALIDATOR_VERSION: Final = "commerce-competitor-validator-3"
COMMERCE_PROMPT_TEMPLATE_VERSION: Final = "commerce-buyer-prompts-2"
COMMERCE_RECOMMENDATION_PARSER_VERSION: Final = "commerce-recommendation-parser-2"
COMMERCE_RECOMMENDATION_MATCHER_VERSION: Final = "commerce-recommendation-matcher-2"
COMMERCE_SHELF_FORMULA_VERSION: Final = "commerce-shelf-formulas-2"

COMMERCE_PROMPTS_MIN: Final = 2
COMMERCE_PROMPTS_DEFAULT: Final = 5
COMMERCE_PROMPTS_MAX: Final = 10
COMMERCE_COMPETITOR_RESULT_LIMIT: Final = 5
COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT: Final = 10
COMMERCE_IMPORT_MAX_BYTES: Final = 2_000_000
COMMERCE_IMPORT_MAX_ROWS: Final = 10_000
COMMERCE_IMPORT_ERROR_LIMIT: Final = 100

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
COMMERCE_SECOND_HAND_TOKENS: Final = ("used", "pre-owned", "second hand", "refurbished")
COMMERCE_DOLLAR_CURRENCY_BY_COUNTRY: Final = {
    "AU": "AUD",
    "CA": "CAD",
    "US": "USD",
}
COMMERCE_VISIBLE_PRICE_CURRENCY_MARKERS: Final[tuple[tuple[str, str], ...]] = (
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
