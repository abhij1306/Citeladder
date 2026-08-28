# Prompt-generation configuration (invariant 1: all config lives here).
#
# Owns the knobs, enumerations, and system prompt for the AI-assisted prompt
# generation surface. Domain and API code read these values; the application
# model is never a measurement engine.
from __future__ import annotations

from typing import Final

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- Prompt lifecycle ------------------------------------------------------
# Generation creates active library entries. Measurement is still explicitly
# initiated by running or scheduling an audit; a second approval gate here
# adds no safety and fragments the portfolio lifecycle.
PROMPT_STATUS_ACTIVE: Final = "active"
PROMPT_STATUS_ARCHIVED: Final = "archived"
PROMPT_STATUSES: Final[frozenset[str]] = frozenset(
    {PROMPT_STATUS_ACTIVE, PROMPT_STATUS_ARCHIVED}
)
DEFAULT_PROMPT_STATUS: Final = PROMPT_STATUS_ACTIVE

# Three cohorts, no aliases. ``core`` is the only organic one and the only one
# that reaches the AI Visibility score; the other two name the tracked brand and
# are reported as separate diagnostics. Two legacy organic values once sat here
# so that pre-existing rows stayed visible -- they are gone, along with the rows.
PROMPT_COHORT_CORE: Final = "core"
PROMPT_COHORT_COMPARISON: Final = "comparison"
PROMPT_COHORT_BRAND_DIAGNOSTIC: Final = "brand_diagnostic"
PROMPT_COHORT_COMMERCE: Final = "commerce"
ORGANIC_PROMPT_COHORTS: Final[frozenset[str]] = frozenset({PROMPT_COHORT_CORE})
PROMPT_COHORTS: Final[frozenset[str]] = ORGANIC_PROMPT_COHORTS | {
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMMERCE,
}
# The cohort VIEW a caller may request on the read APIs. `core` selects the
# whole organic set above; it is not the same thing as the stored `core` value.
REQUESTABLE_PROMPT_COHORTS: Final[frozenset[str]] = frozenset(
    {PROMPT_COHORT_CORE, PROMPT_COHORT_COMPARISON, PROMPT_COHORT_COMMERCE}
)
PROMPT_NEAR_DUPLICATE_SIMILARITY: Final = 0.9
ONBOARDING_PROMPT_SET_NAME: Final = "AI Visibility"

# --- Topic origin ----------------------------------------------------------
TOPIC_ORIGIN_MANUAL: Final = "manual"
TOPIC_ORIGIN_GENERATED: Final = "generated"
TOPIC_ORIGINS: Final[frozenset[str]] = frozenset(
    {TOPIC_ORIGIN_MANUAL, TOPIC_ORIGIN_GENERATED}
)

# --- Generation pipeline version (stamped into generation_evidence) --------
GENERATOR_VERSION: Final = "prompt-gen-v19"
COMMERCE_VALIDATION_SKU_PREVIEW_LIMIT: Final = 10
COMMERCE_BUYER_DESTINATION_PROMPT_TEMPLATE: Final = (
    "Where can I buy {product_name} online?"
)
COMMERCE_MERCHANT_COMPARISON_PROMPT_TEMPLATE: Final = (
    "What are the best alternatives to {product_name} in {category}?"
)

# Open-vocabulary confirmed onboarding fields that can ground generated prompt
# text. Topic creation has a separate Pass 1 owner.
PROMPT_GROUNDING_BUSINESS_CONTEXT_FIELDS: Final[tuple[str, ...]] = (
    "category",
    "category_aliases",
    "category_terms",
    "jobs_to_be_done",
    "service_areas",
    "buyer_roles",
)

# --- Topical binding (project-identity prompt admission) -------------------
# Outcome codes for ``BindingResult`` / the coded API errors built from it.
BINDING_CODE_ACCEPTED: Final = "accepted"
CODE_PROMPT_OFF_TOPIC: Final = "prompt_off_topic"
CODE_BINDING_VOCABULARY_EMPTY: Final = "binding_vocabulary_empty"

# Minimum length of a normalized token eligible for binding (both sides:
# vocabulary build AND prompt text). Shorter tokens (digits, TLD fragments)
# never admit a prompt on their own.
TOPICAL_BINDING_MIN_TOKEN_CHARS: Final = 3

# Generic English function/question/commerce words plus legal-suffix and
# host-label noise excluded from BOTH sides of the binding match, so a prompt
# can never pass on generic wording alone. One owner (invariant 1);
# ``domain/prompts/topical_binding.py`` reads it, nothing re-lists these.
TOPICAL_BINDING_STOPWORDS: Final[frozenset[str]] = frozenset(
    {
        # Function words.
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "so",
        "than",
        "as",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "from",
        "by",
        "with",
        "about",
        "into",
        "over",
        "under",
        "after",
        "before",
        "between",
        "through",
        "during",
        "without",
        "within",
        "per",
        "via",
        "nor",
        "off",
        "up",
        "down",
        "out",
        "again",
        "once",
        "too",
        "very",
        "just",
        "not",
        "no",
        "any",
        "all",
        "both",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "own",
        "same",
        # Pronouns + question words.
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "this",
        "that",
        "these",
        "those",
        "who",
        "whom",
        "whose",
        "which",
        "what",
        "when",
        "where",
        "why",
        "how",
        # Auxiliaries + generic verbs.
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "can",
        "could",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "ought",
        "get",
        "gets",
        "got",
        "make",
        "makes",
        "made",
        "use",
        "used",
        "using",
        "work",
        "works",
        "need",
        "needs",
        "want",
        "wants",
        # Generic commerce/question filler.
        "best",
        "top",
        "good",
        "better",
        "new",
        "latest",
        "cheap",
        "cheapest",
        "buy",
        "buying",
        "shop",
        "shopping",
        "store",
        "online",
        "price",
        "prices",
        "pricing",
        "cost",
        "costs",
        "deal",
        "deals",
        "review",
        "reviews",
        "guide",
        "compare",
        "comparison",
        "vs",
        "versus",
        "near",
        "option",
        "options",
        "brand",
        "brands",
        "product",
        "products",
        "number",
        # Legal-suffix + host-label noise.
        "inc",
        "llc",
        "ltd",
        "corp",
        "corporation",
        "company",
        "co",
        "gmbh",
        "www",
        "com",
        "net",
        "org",
        "io",
        "app",
        "dev",
    }
)

# --- System prompt ---------------------------------------------------------
# There is no separate instruction set for this surface any more. Manual
# generation on an existing project asks for the same thing onboarding does --
# realistic buyer questions for a known topic -- so it uses the same exemplar
# driven instruction from `config/visibility_prompts.py`, chosen by the
# project's business model, and the same deterministic style gate. Two
# instruction sets meant two registers, and this one still carried the
# "avoid padded lead-ins" prose that models ignore.


class PromptGenerationSettings(BaseSettings):
    """Env-overridable generation knobs (``GENERATION_*``).

    ``max_count`` stands in for the future subscription-tier limit; keep it in
    env until billing tiers exist.
    """

    model_config = SettingsConfigDict(extra="ignore")

    # ``ge=1`` floors mirror ``PromptGenerateRequest.count``'s ``ge=1``: a
    # zero/negative env override would otherwise produce an unrequestable
    # default or an always-rejecting cap, so fail at settings construction.
    default_count: int = Field(
        default=10,
        ge=1,
        validation_alias=AliasChoices(
            "GENERATION_DEFAULT_COUNT", "generation_default_count"
        ),
    )
    max_count: int = Field(
        default=100,
        ge=1,
        validation_alias=AliasChoices("GENERATION_MAX_COUNT", "generation_max_count"),
    )
    model_batch_size: int = Field(
        default=20,
        ge=1,
        validation_alias=AliasChoices(
            "GENERATION_MODEL_BATCH_SIZE", "generation_model_batch_size"
        ),
    )
    # Upper bound on how many existing prompt texts are sent to the model as
    # "do not duplicate" context, so the user message can't grow unbounded as
    # a set accumulates prompts. Must be >= 0: a negative env override would
    # silently reverse the slice (``[:negative]`` drops from the tail), so
    # reject it at construction. Zero is valid — it sends no existing prompts.
    existing_prompt_context_limit: int = Field(
        default=200,
        ge=0,
        validation_alias=AliasChoices(
            "GENERATION_EXISTING_PROMPT_CONTEXT_LIMIT",
            "generation_existing_prompt_context_limit",
        ),
    )


prompt_generation_settings = PromptGenerationSettings()
