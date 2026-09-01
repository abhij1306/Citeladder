"""Vocabulary shared by the executable Site Health family profile."""

from __future__ import annotations

from typing import Final

TRAIT_CONDITION_ALWAYS: Final = "always"
TRAIT_CONDITION_RESEARCH_SENSITIVE: Final = "research_sensitive"
TRAIT_CONDITION_FRESHNESS_SENSITIVE: Final = "freshness_sensitive"
TRAIT_CONDITION_PROCEDURAL: Final = "procedural"
TRAIT_CONDITION_CASE_STUDY: Final = "case_study"
TRAIT_CONDITION_REVIEW: Final = "review"
TRAIT_CONDITION_COMPANY_PROFILE: Final = "company_profile"
TRAIT_CONDITIONS: Final = frozenset(
    {
        TRAIT_CONDITION_ALWAYS,
        TRAIT_CONDITION_RESEARCH_SENSITIVE,
        TRAIT_CONDITION_FRESHNESS_SENSITIVE,
        TRAIT_CONDITION_PROCEDURAL,
        TRAIT_CONDITION_CASE_STUDY,
        TRAIT_CONDITION_REVIEW,
        TRAIT_CONDITION_COMPANY_PROFILE,
    }
)

FAMILY_GAP_REASONS: Final = frozenset(
    {
        "claim_support_attachment_unavailable",
        "pricing_commerce_evaluator_unavailable",
        "policy_schema_contract_unavailable",
        "purpose_answer_evaluator_unavailable",
        "responsible_publisher_evaluator_unavailable",
    }
)
FAMILY_NOT_APPLICABLE_REASONS: Final = frozenset(
    {
        "commerce_facts_not_required_for_page_purpose",
        "freshness_context_irrelevant",
        "source_support_not_required_by_context",
        "structured_representation_not_required_for_page_purpose",
        "visible_attribution_not_required_for_page_purpose",
    }
)
