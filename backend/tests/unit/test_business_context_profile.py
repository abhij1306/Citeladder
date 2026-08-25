"""Unit tests for the onboarding business-context envelope.

``BusinessContextProfile`` is what onboarding hands to prompt generation, so its
validators are the last place a hallucinated sector, an unbounded term list, or
a duplicated category can be rejected before it reaches a portfolio. The module
had no tests at all, which meant every one of those guards was an untested
claim.

Pure model behaviour: no database, no network, no fixtures beyond literals.
"""

from __future__ import annotations

import pytest

from app.core.config.brand_discovery import BUSINESS_TYPES, PRICE_TIERS, SECTORS
from app.domain.projects.onboarding.context_profile import (
    MAX_ALIASES,
    MAX_BUYER_ROLES,
    MAX_CATEGORY_TERMS,
    MAX_JOBS,
    MAX_SERVICE_AREAS,
    BusinessContextProfile,
)


def test_defaults_are_the_thin_no_knowledge_envelope() -> None:
    profile = BusinessContextProfile()

    assert profile.category == ""
    assert profile.sector == "Other"
    assert profile.business_model == "d2c_product"
    assert profile.market_scope == "national"
    assert profile.buyer_type == "both"
    assert profile.price_tier == "unknown"
    assert profile.buyer_register == "research_comparative"
    assert profile.knowledge_strength == "none"
    assert profile.field_confidence == {}
    # A brand nothing is known about must read as thin, not as a confident empty
    # profile: the portfolio shortens rather than inventing vocabulary.
    assert profile.is_thin() is True


@pytest.mark.parametrize("sector", SECTORS)
def test_every_declared_sector_is_accepted(sector: str) -> None:
    assert BusinessContextProfile(sector=sector).sector == sector


def test_unknown_sector_degrades_to_other_rather_than_failing() -> None:
    # Sector is a reporting label, never a gate, so an unrecognised value must
    # not reject the whole envelope.
    assert BusinessContextProfile(sector="Underwater Basket Weaving").sector == "Other"


@pytest.mark.parametrize("tier", PRICE_TIERS)
def test_every_declared_price_tier_is_accepted(tier: str) -> None:
    assert BusinessContextProfile(price_tier=tier).price_tier == tier


def test_unknown_price_tier_degrades_to_unknown() -> None:
    assert BusinessContextProfile(price_tier="mid-market").price_tier == "unknown"


@pytest.mark.parametrize("buyer_type", BUSINESS_TYPES)
def test_buyer_type_literal_matches_the_configured_vocabulary(buyer_type: str) -> None:
    assert BusinessContextProfile(buyer_type=buyer_type).buyer_type == buyer_type


def test_buyer_type_outside_the_vocabulary_is_rejected() -> None:
    # Unlike sector and price tier, buyer_type ROUTES archetype selection, so it
    # fails closed instead of degrading.
    with pytest.raises(ValueError):
        BusinessContextProfile(buyer_type="b2g")


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("category_aliases", MAX_ALIASES),
        ("category_terms", MAX_CATEGORY_TERMS),
        ("jobs_to_be_done", MAX_JOBS),
        ("buyer_roles", MAX_BUYER_ROLES),
        ("service_areas", MAX_SERVICE_AREAS),
    ],
)
def test_every_bounded_list_truncates_to_its_limit(field: str, limit: int) -> None:
    values = [f"term-{index}" for index in range(limit + 5)]

    cleaned = getattr(BusinessContextProfile(**{field: values}), field)

    assert cleaned == values[:limit]


@pytest.mark.parametrize(
    "field",
    [
        "category_aliases",
        "category_terms",
        "jobs_to_be_done",
        "buyer_roles",
        "service_areas",
    ],
)
def test_every_bounded_list_dedupes_case_insensitively_and_preserves_order(
    field: str,
) -> None:
    cleaned = getattr(
        BusinessContextProfile(
            **{field: ["Running Shoes", "running shoes", "Trail Shoes"]}
        ),
        field,
    )

    # First spelling wins; the later casing variant is a duplicate, not a
    # second term.
    assert cleaned == ["Running Shoes", "Trail Shoes"]


@pytest.mark.parametrize(
    "field",
    [
        "category_aliases",
        "category_terms",
        "jobs_to_be_done",
        "buyer_roles",
        "service_areas",
    ],
)
def test_every_bounded_list_collapses_whitespace_and_drops_empties(field: str) -> None:
    cleaned = getattr(
        BusinessContextProfile(
            **{field: ["  Trail   Running  Shoes ", "", "   ", "\t\n"]}
        ),
        field,
    )

    assert cleaned == ["Trail Running Shoes"]


def test_prompt_categories_merge_terms_products_and_category_in_that_order() -> None:
    profile = BusinessContextProfile(
        category="Trail Running Shoes",
        category_terms=["trail shoes", "off-road running shoes"],
        products_services=["Peak Runner 3", "Ridge Trainer"],
    )

    assert profile.prompt_categories() == [
        "trail shoes",
        "off-road running shoes",
        "Peak Runner 3",
        "Ridge Trainer",
        "Trail Running Shoes",
    ]


def test_prompt_categories_dedupe_across_the_three_sources() -> None:
    profile = BusinessContextProfile(
        category="Trail Shoes",
        category_terms=["trail shoes"],
        products_services=["TRAIL SHOES"],
    )

    assert profile.prompt_categories() == ["trail shoes"]


def test_prompt_categories_are_bounded_by_the_term_limit() -> None:
    # ``products_services`` carries no field validator of its own, so the bound
    # has to hold at the point the vocabulary is READ, not only where it is set.
    profile = BusinessContextProfile(
        products_services=[
            f"product-{index}" for index in range(MAX_CATEGORY_TERMS + 8)
        ],
    )

    assert len(profile.prompt_categories()) == MAX_CATEGORY_TERMS


def test_thin_when_knowledge_is_none_even_with_grounded_vocabulary() -> None:
    profile = BusinessContextProfile(
        category="Trail Running Shoes",
        knowledge_strength="none",
    )

    assert profile.is_thin() is True
    assert (
        profile.thinness_reason() == "the model had no reliable knowledge of this brand"
    )


def test_thin_when_vocabulary_is_empty_even_with_strong_knowledge() -> None:
    profile = BusinessContextProfile(knowledge_strength="strong")

    assert profile.is_thin() is True
    assert (
        profile.thinness_reason()
        == "no product or category vocabulary could be grounded"
    )


def test_knowledge_strength_reason_wins_when_both_are_thin() -> None:
    profile = BusinessContextProfile(knowledge_strength="none")

    assert (
        profile.thinness_reason() == "the model had no reliable knowledge of this brand"
    )


@pytest.mark.parametrize("strength", ["strong", "weak"])
def test_grounded_profile_is_not_thin_and_gives_no_reason(strength: str) -> None:
    profile = BusinessContextProfile(
        category="Trail Running Shoes",
        knowledge_strength=strength,
    )

    assert profile.is_thin() is False
    assert profile.thinness_reason() == ""


def test_category_length_is_bounded() -> None:
    with pytest.raises(ValueError):
        BusinessContextProfile(category="x" * 161)
