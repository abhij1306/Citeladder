"""Unit tests for the onboarding research module's evidence filters.

``app/domain/projects/onboarding/research.py`` sat at 41% line coverage. The
model call and the site fetch belong in the component suite; the filters below
are pure, and each one exists because of a specific way a competitor set went
wrong in production.

Two are worth naming, because the tests are the record of them:

- An evidence URL says where a competitor was *mentioned*, not where it lives.
  Folding evidence URLs in unconditionally let a reference host become the
  competitor's own domain whenever its real site failed to resolve — Myntra was
  persisted with ``wikipedia.org``, which loses every real ``myntra.com``
  citation and misattributes every Wikipedia one.
- The four qualification dimensions all measure OVERLAP, and none measures
  KIND. An ecommerce implementation agency was returned with Shopify Plus,
  BigCommerce, and Salesforce Commerce Cloud: same words, same buyers, same
  questions, and not one of them is something you hire instead of the agency.
"""

from __future__ import annotations

import pytest

from app.core.config.observed_competitors import EXCLUDED_RESEARCH_DOMAINS
from app.domain.projects.discovery_schemas import DiscoveryCompetitorSuggestion
from app.domain.projects.onboarding.research import (
    _competitor_domain_candidates,
    _customer_warnings,
    _fallback_profile,
    _is_excluded_research_url,
    _is_peer_company,
)


def _candidate(**overrides: object) -> DiscoveryCompetitorSuggestion:
    values: dict[str, object] = {"name": "Globex", "domains": [], "evidence_urls": []}
    values.update(overrides)
    return DiscoveryCompetitorSuggestion(**values)  # type: ignore[arg-type]


# --- reference-host exclusion ---------------------------------------------


@pytest.mark.parametrize("domain", sorted(EXCLUDED_RESEARCH_DOMAINS))
def test_every_configured_reference_host_is_excluded(domain: str) -> None:
    assert _is_excluded_research_url(f"https://{domain}/wiki/Something") is True


@pytest.mark.parametrize("domain", sorted(EXCLUDED_RESEARCH_DOMAINS))
def test_a_subdomain_of_a_reference_host_is_excluded(domain: str) -> None:
    # ``en.wikipedia.org`` is the same reference host as ``wikipedia.org``.
    assert _is_excluded_research_url(f"https://en.{domain}/page") is True


def test_a_real_company_site_is_not_excluded() -> None:
    assert _is_excluded_research_url("https://myntra.com/") is False
    assert _is_excluded_research_url("https://shop.myntra.com/men") is False


def test_a_host_that_merely_ends_with_a_reference_name_is_not_excluded() -> None:
    # Suffix matching is on the DOT boundary, so a company that happens to
    # contain a reference host's name is still a real competitor.
    assert _is_excluded_research_url("https://notwikipedia.org/") is False


@pytest.mark.parametrize("value", ["", "not a url", "http://", "ftp://x"])
def test_an_unparseable_url_is_excluded_rather_than_adopted(value: str) -> None:
    # Fail closed: a URL that cannot be normalized must never become a
    # competitor's persisted domain.
    assert _is_excluded_research_url(value) is True


# --- domain adoption ------------------------------------------------------


def test_declared_domains_are_always_candidates() -> None:
    candidate = _candidate(domains=["globex.com", "globex.co.uk"])

    assert _competitor_domain_candidates(candidate) == ["globex.com", "globex.co.uk"]


def test_a_usable_evidence_url_supplements_the_declared_domains() -> None:
    candidate = _candidate(
        domains=["globex.com"], evidence_urls=["https://globex.io/about"]
    )

    assert _competitor_domain_candidates(candidate) == [
        "globex.com",
        "https://globex.io/about",
    ]


def test_a_reference_host_never_becomes_a_competitor_domain() -> None:
    # The regression this function exists for.
    candidate = _candidate(
        domains=[],
        evidence_urls=["https://en.wikipedia.org/wiki/Myntra", "https://myntra.com/"],
    )

    candidates = _competitor_domain_candidates(candidate)

    assert candidates == ["https://myntra.com/"]
    assert not any("wikipedia" in value for value in candidates)


def test_a_competitor_known_only_from_reference_hosts_yields_no_domain() -> None:
    candidate = _candidate(
        domains=[],
        evidence_urls=["https://reddit.com/r/x", "https://youtube.com/watch?v=1"],
    )

    # Better to persist no domain than the wrong one: an empty list simply
    # fails verification, while a wrong domain misattributes every citation.
    assert _competitor_domain_candidates(candidate) == []


def test_declared_domains_keep_priority_over_evidence() -> None:
    candidate = _candidate(
        domains=["globex.com"], evidence_urls=["https://globex.com/press"]
    )

    assert _competitor_domain_candidates(candidate)[0] == "globex.com"


def test_duplicate_candidates_are_collapsed_in_order() -> None:
    candidate = _candidate(
        domains=["globex.com", "globex.com"],
        evidence_urls=["https://globex.io", "https://globex.io"],
    )

    assert _competitor_domain_candidates(candidate) == [
        "globex.com",
        "https://globex.io",
    ]


# --- peer-class filter ----------------------------------------------------


@pytest.mark.parametrize(
    ("brand_model", "competitor_model"),
    [
        ("b2b_saas", "marketplace"),
        ("d2c_product", "retail"),
        ("professional_service", "local_service"),
        ("healthcare_provider", "education_provider"),
    ],
)
def test_two_companies_of_the_same_kind_are_peers(
    brand_model: str, competitor_model: str
) -> None:
    candidate = _candidate(business_model=competitor_model)

    assert _is_peer_company(candidate, brand_model=brand_model) is True


@pytest.mark.parametrize(
    ("brand_model", "competitor_model"),
    [
        ("professional_service", "b2b_saas"),
        ("local_service", "marketplace"),
        ("b2b_saas", "healthcare_provider"),
        ("retail", "education_provider"),
    ],
)
def test_a_service_firm_and_a_product_company_are_not_peers(
    brand_model: str, competitor_model: str
) -> None:
    # The agency/platform confusion: every overlap dimension agrees and the
    # pairing is still wrong, because you do not hire one instead of the other.
    candidate = _candidate(business_model=competitor_model)

    assert _is_peer_company(candidate, brand_model=brand_model) is False


def test_the_filter_abstains_when_the_model_declined_to_classify() -> None:
    # An unstated business model is not evidence of a mismatch, so the
    # competitor survives to be judged on its evidence instead.
    candidate = _candidate(business_model=None)

    assert _is_peer_company(candidate, brand_model="b2b_saas") is True


# --- customer-facing warnings ---------------------------------------------


def test_a_complete_research_pass_warns_about_nothing() -> None:
    assert _customer_warnings(model_available=True, competitors_found=True) == []


def test_an_unavailable_research_model_is_surfaced_as_degraded() -> None:
    assert _customer_warnings(model_available=False, competitors_found=True) == [
        "research_degraded"
    ]


def test_finding_no_competitor_is_surfaced() -> None:
    assert _customer_warnings(model_available=True, competitors_found=False) == [
        "competitors_not_found"
    ]


def test_both_degraded_outcomes_are_reported_together() -> None:
    assert _customer_warnings(model_available=False, competitors_found=False) == [
        "research_degraded",
        "competitors_not_found",
    ]


# --- fallback profile -----------------------------------------------------


def test_the_fallback_profile_keeps_the_known_industry_confident() -> None:
    profile = _fallback_profile(
        brand_name="Acme", industry="Software", subindustry="Workflow tools"
    )

    assert profile.industry == "Software"
    # The declared subindustry becomes a usable category so competitor
    # discovery still runs when identity synthesis fails.
    assert profile.category == "Workflow tools"
    assert "Workflow tools" in profile.category_terms
    # Industry came from the user, so it is certain; the description is a
    # placeholder and must not claim to be researched.
    assert profile.field_confidence["industry"] == 1.0
    assert profile.field_confidence["description"] < 0.5
    assert "Acme" in profile.description
