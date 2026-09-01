"""Vocabulary and applicability keys for additive Site Health page traits."""

from __future__ import annotations

from typing import Final

PAGE_TRAIT_HAS_FAQ: Final = "has_faq"
PAGE_TRAIT_HAS_REVIEWS: Final = "has_reviews"
PAGE_TRAIT_HAS_VARIANTS: Final = "has_variants"
PAGE_TRAIT_LISTING: Final = "listing"
PAGE_TRAIT_LOCAL_INTENT: Final = "local_intent"
PAGE_TRAIT_CONTACT_INTENT: Final = "contact_intent"
PAGE_TRAIT_ABOUT_INTENT: Final = "about_intent"
PAGE_TRAIT_COMPANY_PROFILE_INTENT: Final = "company_profile_intent"
PAGE_TRAIT_CASE_STUDY_INTENT: Final = "case_study_intent"
PAGE_TRAIT_COMPARISON_CONTENT: Final = "comparison_content"
PAGE_TRAIT_PROCEDURAL: Final = "procedural"

PAGE_TRAITS: Final[tuple[str, ...]] = (
    PAGE_TRAIT_HAS_FAQ,
    PAGE_TRAIT_HAS_REVIEWS,
    PAGE_TRAIT_HAS_VARIANTS,
    PAGE_TRAIT_LISTING,
    PAGE_TRAIT_LOCAL_INTENT,
    PAGE_TRAIT_CONTACT_INTENT,
    PAGE_TRAIT_ABOUT_INTENT,
    PAGE_TRAIT_COMPANY_PROFILE_INTENT,
    PAGE_TRAIT_CASE_STUDY_INTENT,
    PAGE_TRAIT_COMPARISON_CONTENT,
    PAGE_TRAIT_PROCEDURAL,
)

PAGE_TRAIT_ROUTE_SEGMENTS: Final[dict[str, tuple[str, ...]]] = {
    PAGE_TRAIT_CONTACT_INTENT: ("contact", "contact-us", "get-in-touch", "enquiries"),
    PAGE_TRAIT_ABOUT_INTENT: ("about", "about-us", "our-story", "who-we-are", "team"),
    PAGE_TRAIT_CASE_STUDY_INTENT: ("case-study", "case-studies", "customers"),
    PAGE_TRAIT_COMPARISON_CONTENT: ("compare", "comparison", "comparisons", "vs"),
}

PAGE_TRAIT_TITLE_PHRASES: Final[dict[str, tuple[str, ...]]] = {
    PAGE_TRAIT_CONTACT_INTENT: ("contact us", "get in touch", "contact"),
    PAGE_TRAIT_ABOUT_INTENT: ("about us", "our story", "who we are"),
    PAGE_TRAIT_CASE_STUDY_INTENT: ("case study", "customer story", "success story"),
    PAGE_TRAIT_COMPARISON_CONTENT: ("vs", "versus", "compared", "comparison"),
}

PAGE_TRAIT_SCHEMA_TYPES: Final[dict[str, tuple[str, ...]]] = {
    PAGE_TRAIT_HAS_FAQ: ("FAQPage",),
    PAGE_TRAIT_HAS_REVIEWS: ("Review", "AggregateRating"),
    PAGE_TRAIT_PROCEDURAL: ("HowTo",),
}

PAGE_TRAIT_CONTACT_FORM_FIELDS: Final[frozenset[str]] = frozenset(
    {"email", "e-mail", "phone", "telephone", "message", "enquiry", "inquiry"}
)
PAGE_TRAIT_VARIANT_FORM_FIELDS: Final[frozenset[str]] = frozenset(
    {"colour", "color", "finish", "material", "size", "style"}
)
PAGE_TRAIT_PROCEDURAL_MIN_STEPS: Final = 3

PAGE_TRAIT_APPLICABILITY_PREFIX: Final = "page_trait:"
PAGE_TRAIT_CONTENT_APPLICABILITY_PREFIX: Final = "page_trait_content:"
PAGE_KIND_OR_TRAIT_CONTENT_APPLICABILITY_PREFIX: Final = "page_kind_or_trait_content:"


def _traits(*traits: str, reads_content: bool = False) -> str:
    """Build a config-owned trait applicability key."""
    prefix = (
        PAGE_TRAIT_CONTENT_APPLICABILITY_PREFIX
        if reads_content
        else PAGE_TRAIT_APPLICABILITY_PREFIX
    )
    return f"{prefix}{'|'.join(traits)}"


def _kinds_or_traits(*values: str) -> str:
    """Build a content-reading key that accepts a page kind or additive trait."""
    return f"{PAGE_KIND_OR_TRAIT_CONTENT_APPLICABILITY_PREFIX}{'|'.join(values)}"


TRAITS_VERSION: Final = "sh-traits-1"
