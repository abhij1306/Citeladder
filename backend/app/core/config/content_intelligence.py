"""Versioned policy for Content Intelligence artifacts and validation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, TypedDict


class ContentSkillDefinition(TypedDict):
    version: str
    brief_kinds: list[str]
    output_format: str
    required_sections: list[str]
    directive: str


CONTENT_PROJECTION_VERSION: Final = "content-projection-v1"
CONTENT_STRATEGY_VERSION: Final = "content-strategy-v1"
CONTENT_BRIEF_BUILDER_VERSION: Final = "content-brief-v1"
CONTENT_CONTEXT_POLICY_VERSION: Final = "content-context-v1"
CONTENT_VALIDATOR_VERSION: Final = "content-validator-v1"
CONTENT_VERIFIER_VERSION: Final = "content-verifier-v1"

CONTENT_CONTEXT_MAX_CHARS: Final = 18_000
CONTENT_CONTEXT_MAX_FACTS: Final = 80
CONTENT_CONTEXT_MAX_SOURCES: Final = 40
CONTENT_INVENTORY_LIST_LIMIT: Final = 250
CONTENT_ARTIFACT_LIST_LIMIT: Final = 100
CONTENT_REVISION_MAX_CHARS: Final = 100_000

QUESTION_STATES: Final = frozenset(
    {
        "answered_strong",
        "answered_weak",
        "missing",
        "conflicting",
        "unsupported",
        "historical_only",
        "not_applicable",
        "unavailable_evidence",
        "match_unverified",
    }
)
AUTOMATIC_BRIEF_STATES: Final = frozenset({"missing"})
BLOCKING_FACT_STATES: Final = frozenset(
    {"conflicting", "historical_only", "unsupported", "unavailable_evidence"}
)
REVISION_STATES: Final = frozenset(
    {"draft", "edited", "saved", "published_claimed", "discarded"}
)
REVISION_TRANSITIONS: Final = {
    "draft": frozenset({"edited", "saved", "discarded"}),
    "edited": frozenset({"edited", "saved", "discarded"}),
    "saved": frozenset({"published_claimed"}),
    "published_claimed": frozenset(),
    "discarded": frozenset(),
}

# Skills are data: domain code selects these definitions and freezes their
# version/directive/validator contract on the generation.
CONTENT_SKILL_CATALOG: Final[Mapping[str, ContentSkillDefinition]] = {
    "faq_visible": {
        "version": "1.0.0",
        "brief_kinds": ["faq"],
        "output_format": "markdown",
        "required_sections": ["questions_and_answers"],
        "directive": (
            "Write only the requested visible FAQ questions and grounded answers."
        ),
    },
    "faq_jsonld": {
        "version": "1.0.0",
        "brief_kinds": ["faq_schema"],
        "output_format": "jsonld",
        "required_sections": ["mainEntity"],
        "directive": (
            "Return FAQPage JSON-LD that exactly mirrors the supplied visible FAQ."
        ),
    },
    "answer_first": {
        "version": "1.0.0",
        "brief_kinds": ["section", "new_page"],
        "output_format": "markdown",
        "required_sections": ["answer", "support"],
        "directive": (
            "Lead with the direct answer, then provide grounded supporting detail."
        ),
    },
    "page_refresh": {
        "version": "1.0.0",
        "brief_kinds": ["page_refresh", "consolidation"],
        "output_format": "markdown",
        "required_sections": ["replacement_content"],
        "directive": "Refresh the target without changing unsupported facts or intent.",
    },
    "comparison": {
        "version": "1.0.0",
        "brief_kinds": ["comparison"],
        "output_format": "markdown",
        "required_sections": ["criteria", "limitations"],
        "directive": "Compare only evidenced criteria and state unknowns explicitly.",
    },
    "guide": {
        "version": "1.0.0",
        "brief_kinds": ["guide"],
        "output_format": "markdown",
        "required_sections": ["answer", "next_steps"],
        "directive": "Write an evidence-led decision guide with practical next steps.",
    },
    "education_admissions": {
        "version": "1.0.0",
        "brief_kinds": ["section", "new_page", "faq"],
        "output_format": "markdown",
        "required_sections": ["requirements", "process", "next_step"],
        "directive": (
            "Explain admissions using only current observed requirements and dates."
        ),
    },
    "education_program": {
        "version": "1.0.0",
        "brief_kinds": ["section", "new_page", "guide"],
        "output_format": "markdown",
        "required_sections": ["program", "evidence", "next_step"],
        "directive": (
            "Describe the education program and outcomes without invented proof."
        ),
    },
    "commerce_category": {
        "version": "1.0.0",
        "brief_kinds": ["category", "guide", "faq"],
        "output_format": "markdown",
        "required_sections": ["selection_guidance", "limitations"],
        "directive": (
            "Help shoppers select a category using evidenced attributes and policies."
        ),
    },
    "commerce_pdp": {
        "version": "1.0.0",
        "brief_kinds": ["pdp", "section", "faq"],
        "output_format": "markdown",
        "required_sections": ["summary", "specifications", "limitations"],
        "directive": (
            "Describe the product using only evidenced specifications and policies."
        ),
    },
    "commerce_policy": {
        "version": "1.0.0",
        "brief_kinds": ["policy", "faq"],
        "output_format": "markdown",
        "required_sections": ["policy", "exceptions", "next_step"],
        "directive": (
            "State only the supplied policy terms and make unknown exceptions explicit."
        ),
    },
    "internal_links": {
        "version": "1.0.0",
        "brief_kinds": ["internal_links"],
        "output_format": "markdown",
        "required_sections": ["links"],
        "directive": (
            "Recommend only valid supplied internal targets and explain each "
            "relationship."
        ),
    },
}
