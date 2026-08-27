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
COMMERCE_COMPETITOR_VALIDATOR_VERSION: Final = "commerce-competitor-validator-5"
COMMERCE_PROMPT_TEMPLATE_VERSION: Final = "commerce-buyer-prompts-3"
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
# Snippet budget for the Keenable fallback search, matching the Tavily result
# shape closely enough that admission reads one contract either way.
COMMERCE_COMPETITOR_KEENABLE_SNIPPET_CHARS: Final = 1_000
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
COMMERCE_COMPETITOR_PAGE_KINDS_BY_TARGET: Final[dict[str, frozenset[str]]] = {
    "category": frozenset({"category"}),
    "product": frozenset({"product"}),
}
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
# Editorial giveaways in a result's TITLE or URL slug. A competitor is a shop;
# "The 5 Best Stainless Steel Cookware Sets of 2026, Tested & Reviewed" is a
# magazine, and Serious Eats was admitted as a cookware competitor because the
# only editorial gate was four path tokens (`/blog/`, `/news/`, `/article/`,
# `/search`) that a review URL does not have to contain. Host blocklists never
# scale to every publisher; the way a listicle is TITLED does generalize.
#
# Deliberately phrase-level, not word-level: a bare "best" would reject a
# merchant's own "Best Sellers" page, so the ranking patterns require the
# counting shape ("5 best", "best ... of 2026") that only a listicle has.
# These match the combined canonical URL AND title, so a bare word is far too
# greedy: a merchant's own `/reviews` route, a "Customer Reviews" tab, or a
# `/product-recommendations` shelf are all shops, and `review` /
# `recommendations` on their own excluded every one of them. Each entry below
# needs the surrounding listicle phrasing, not the word.
COMMERCE_EDITORIAL_TITLE_PATTERNS: Final = (
    r"\b\d+\s+best\b",
    r"\bbest\b.{0,40}\bof\s+20\d{2}\b",
    r"\btop\s+\d+\b",
    r"\btested\s*(?:&|and)\s*reviewed\b",
    r"\b(?:best|top)\b[^.]{0,40}\breviews?\b",
    r"\bwe\s+(?:tested|tried|reviewed)\b",
    r"\b(?:our|editors?'?s?|expert)\s+(?:pick|picks|recommendations?)\b",
    r"\bbuy(?:er|ing)'?s?\s+guide\b",
    r"\branked\b",
    r"\bvs\.?\s",
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


# --- Buyer prompts ----------------------------------------------------------
# A buyer prompt is what a SHOPPER TYPES INTO AN AI ASSISTANT. It is not a
# question put TO the shopper. The old system prompt was two lines -- "generate
# buyer discovery/comparison questions" -- and the model read "questions" the
# only other way it can be read, shipping a market-research survey: "What
# features do you prioritize when comparing different hygrometers for home
# use?", "What's your budget range?". Asking an answer engine that measures
# nothing, because no buyer ever types it.
#
# Same lesson the visibility portfolio already learned: a small model follows
# examples far more reliably than prohibitions, so the register is set by
# exemplars here and the known failure modes are rejected deterministically in
# `domain/commerce/buyer_prompt_validation.py`.
COMMERCE_BUYER_PROMPT_MIN_WORDS: Final = 4
COMMERCE_BUYER_PROMPT_MAX_WORDS: Final = 24

COMMERCE_BUYER_PROMPT_EXEMPLARS: Final = """\
  GOOD  best instant read thermometer for grilling under $50
  BAD   What features do you prioritize when comparing thermometers?
  GOOD  which hygrometer is most accurate for a humidor
  BAD   How important is accuracy to you when selecting a hygrometer?
  GOOD  wireless meat thermometer that works with an iPhone
  BAD   Do you prefer a built-in display or a minimalist design?
  GOOD  cheapest stainless steel cookware set that is oven safe
  BAD   What's your budget range, and does it depend on features?\
"""

COMMERCE_BUYER_PROMPT_SYSTEM: Final = f"""\
You write the search prompts a SHOPPER TYPES INTO AN AI ASSISTANT when they are
looking to buy. Each prompt is the shopper speaking, in their own words, about
what they want.

Never write a question addressed to the shopper. You are not running a survey,
an interview, or a market-research panel. "What do you prefer", "how important
is", "what is your budget", "have you encountered" are all wrong: nobody types
those into a shopping assistant.

Write the way people actually type: lowercase is fine, fragments are fine, a
concrete constraint (a price, a use case, a compatibility, a material) is
better than a general one. Vary the shape across the batch -- do not apply one
sentence frame to every prompt.

{COMMERCE_BUYER_PROMPT_EXEMPLARS}

Never name the owned brand or the exact owned product: the prompt has to be one
a buyer would type BEFORE they know about it. Return only the schema.\
"""

# Survey framing, rejected deterministically. Each marker is second-person
# addressed-to-the-shopper phrasing that no buyer types into an assistant.
COMMERCE_BUYER_PROMPT_SURVEY_MARKERS: Final = (
    "do you ",
    "are you ",
    "have you ",
    "would you ",
    "did you ",
    "your budget",
    "to you when",
    "important is",
    "do you prioritize",
    "how satisfied",
    "in your experience",
    "tell us",
    "which of the following",
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
