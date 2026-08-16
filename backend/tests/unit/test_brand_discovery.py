"""Reliability-first onboarding unit contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.config.brand_discovery import _discovery_research_system_prompt
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryCreate,
    CompetitorQualification,
    ConfirmedDiscoveryProfile,
    DiscoveryCompetitorSuggestion,
)
from app.domain.projects.onboarding import prompt_generation
from app.domain.projects.onboarding.industry_library import (
    industry_context,
    industry_names,
)
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_primary_market,
    normalize_website_url,
)
from app.domain.projects.onboarding.prompt_generation import fallback_portfolio
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_RELEVANT,
    MARKET_VISIBILITY,
    validate_portfolio,
)
from app.domain.projects.onboarding.research import (
    _customer_warnings,
    _is_peer_company,
)
from app.domain.projects.onboarding.service import discovery_catalog
from app.domain.projects.onboarding.site_resolution import resolve_site


def test_normalizes_url_idn_path_fragment_and_market() -> None:
    url, domain = normalize_website_url("HTTPS://WWW.Example.COM:443/shop#offers")

    assert url == "https://www.example.com/shop"
    assert domain == "example.com"
    assert normalize_primary_market("in") == "IN"
    assert normalize_primary_market("global") == "GLOBAL"


@pytest.mark.parametrize(
    "value", ["", "localhost", "127.0.0.1", "ftp://example.com", "example"]
)
def test_rejects_non_public_or_invalid_urls(value: str) -> None:
    with pytest.raises(InvalidWebsiteUrl):
        normalize_website_url(value)


@pytest.mark.parametrize("value", ["I", "IND", "12", "worldwide"])
def test_rejects_invalid_primary_market(value: str) -> None:
    with pytest.raises(ValueError, match="primary_market"):
        normalize_primary_market(value)


def test_general_industry_is_deterministic_fallback() -> None:
    selected, context = industry_context("Unknown vertical")

    assert selected == "General"
    assert len(context["archetypes"]) == 5

    prompts = fallback_portfolio(
        primary_market="US",
        industry=selected,
        industry_context=context,
        products_services=[],
    )
    assert prompts[0]["theme"] == "Professional Help"
    assert all("products and services" not in item["text"] for item in prompts)


def test_research_prompt_defers_generation_until_icp_confirmation() -> None:
    prompt = _discovery_research_system_prompt(3, 4)

    assert "Do not generate search prompts" in prompt
    assert "after the user confirms or edits the ICP" in prompt


@pytest.mark.parametrize(
    "payload",
    [
        {"positioning": " ", "target_audience": "buyers", "products_services": ["x"]},
        {"positioning": "value", "target_audience": " ", "products_services": ["x"]},
        {
            "positioning": "value",
            "target_audience": "buyers",
            "products_services": [" "],
        },
    ],
)
def test_confirmed_icp_rejects_blank_required_values(payload: dict) -> None:
    with pytest.raises(ValueError):
        ConfirmedDiscoveryProfile.model_validate(payload)


def _candidate(name: str, business_model: str | None) -> DiscoveryCompetitorSuggestion:
    return DiscoveryCompetitorSuggestion(
        name=name,
        domains=[f"{name.lower().replace(' ', '')}.com"],
        business_model=business_model,
        qualification=CompetitorQualification(
            # Deliberately perfect. The point of the case is that every
            # dimension the model scores can agree while the answer is wrong.
            product_substitutability=1.0,
            customer_use_case_overlap=1.0,
            geographic_relevance=1.0,
            question_visibility=1.0,
        ),
    )


def test_platform_vendors_are_not_peers_of_a_services_firm() -> None:
    """The exact failure: an ecommerce agency handed the platforms it implements.

    CUBE27 builds ecommerce sites; discovery returned Shopify Plus, BigCommerce,
    Salesforce Commerce Cloud, SAP Commerce Cloud and commercetools. Nobody
    hires a storefront platform instead of an implementation partner.
    """
    for vendor in ("Shopify Plus", "commercetools", "BigCommerce"):
        assert not _is_peer_company(
            _candidate(vendor, "b2b_saas"), brand_model="professional_service"
        ), vendor


def test_peer_agencies_survive_the_class_filter() -> None:
    assert _is_peer_company(
        _candidate("Publicis Sapient", "professional_service"),
        brand_model="professional_service",
    )


def test_class_filter_abstains_when_the_model_did_not_classify() -> None:
    """An unstated business model is not evidence of a mismatch."""
    assert _is_peer_company(_candidate("Unknown Co", None), brand_model="b2b_saas")


def test_research_prompt_separates_services_firms_from_the_products_they_build() -> (
    None
):
    prompt = _discovery_research_system_prompt(3, 4)

    assert "WHAT DOES THE BUYER ACTUALLY RECEIVE?" in prompt
    assert "THE SAME KIND OF COMPANY" in prompt


def test_complete_research_does_not_warn_about_internal_fallbacks() -> None:
    assert _customer_warnings(model_available=True, competitors_found=True) == []


def test_materially_incomplete_research_keeps_customer_warnings() -> None:
    assert _customer_warnings(model_available=False, competitors_found=False) == [
        "research_degraded",
        "competitors_not_found",
    ]


@pytest.mark.asyncio
async def test_https_to_http_redirect_is_not_used_as_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RedirectingFetcher:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        async def fetch(self, _request: object):
            return SimpleNamespace(
                status_code=200,
                final_url="http://example.com/",
                body=b"<html><title>Untrusted</title><p>content</p></html>",
                charset="utf-8",
            )

    monkeypatch.setattr(
        "app.domain.projects.onboarding.site_resolution.SecureFetcher",
        RedirectingFetcher,
    )

    resolved = await resolve_site("example.com", "https://example.com/")

    assert resolved.page is None
    assert resolved.warning == "research_degraded"


def test_fallback_portfolio_is_balanced_and_all_prompts_are_unbranded() -> None:
    industry, context = industry_context("Ecommerce")
    prompts = fallback_portfolio(
        primary_market="IN",
        industry=industry,
        industry_context=context,
        products_services=["online marketplace"],
    )

    quality = validate_portfolio(
        prompts,
        brand_terms=["Flipkart"],
        competitor_terms=["Amazon"],
        primary_market="IN",
        context_terms=[
            "online marketplace",
            *(context.get("use_cases") or []),
            *(context.get("topics") or []),
        ],
    )
    assert quality.errors == ()
    assert [item["cohort"] for item in prompts].count(MARKET_VISIBILITY) == 5
    assert [item["cohort"] for item in prompts].count(BRAND_RELEVANT) == 5
    assert all(
        "online marketplace" not in item["text"].casefold()
        for item in prompts
        if item["cohort"] == MARKET_VISIBILITY
    )
    assert all(
        "online marketplace" in item["text"].casefold()
        for item in prompts
        if item["cohort"] == BRAND_RELEVANT
    )
    assert all("flipkart" not in item["text"].casefold() for item in prompts)
    assert any("India" in item["text"] or "Indian" in item["text"] for item in prompts)


def test_confirmed_target_audience_changes_generated_portfolio() -> None:
    industry, context = industry_context("Software")
    shared = {
        "primary_market": "US",
        "industry": industry,
        "industry_context": context,
        "products_services": ["analytics software"],
    }

    enterprise = fallback_portfolio(
        **shared, target_audience="enterprise marketing teams"
    )
    agencies = fallback_portfolio(**shared, target_audience="independent agencies")

    assert [item["text"] for item in enterprise] != [item["text"] for item in agencies]
    assert any("enterprise marketing teams" in item["text"] for item in enterprise)
    assert any("independent agencies" in item["text"] for item in agencies)


def test_fallback_uses_general_templates_when_industry_archetypes_are_empty() -> None:
    _, context = industry_context("Software")
    prompts = fallback_portfolio(
        primary_market="US",
        industry="Software",
        industry_context={**context, "archetypes": []},
        products_services=["analytics software"],
    )

    assert len(prompts) == 10
    assert prompts[0]["text"].startswith(
        "What are my best options for analytics software"
    )


def test_fallback_reports_missing_brand_relevant_templates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, context = industry_context("Software")
    monkeypatch.setattr(
        prompt_generation,
        "load_industry_library",
        lambda: {"brand_relevant_archetypes": [], "industries": {}},
    )

    with pytest.raises(RuntimeError, match="brand-relevant archetypes"):
        fallback_portfolio(
            primary_market="US",
            industry="Software",
            industry_context=context,
            products_services=["analytics software"],
        )


def test_prompt_gate_rejects_tracked_names_in_both_cohorts() -> None:
    _, context = industry_context("Software")
    prompts = fallback_portfolio(
        primary_market="US",
        industry="Software",
        industry_context=context,
        products_services=["analytics software"],
    )
    assert prompts[0]["cohort"] == MARKET_VISIBILITY
    assert prompts[5]["cohort"] == BRAND_RELEVANT
    prompts[0] = {**prompts[0], "text": "Is Acme the best analytics software in US?"}
    prompts[1] = {**prompts[1], "theme": "Acme pricing"}
    prompts[2] = {**prompts[2], "theme": ""}
    prompts[5] = {
        **prompts[5],
        "text": "Which Acme analytics tools help marketing teams in US?",
    }

    result = validate_portfolio(
        prompts,
        brand_terms=["Acme"],
        competitor_terms=[],
    )

    assert "prompt[0].tracked_name" in result.errors
    assert "prompt[1].tracked_topic_name" in result.errors
    assert "prompt[2].topic" in result.errors
    assert "prompt[5].tracked_name" in result.errors


def test_portfolio_must_stay_grounded_in_confirmed_context() -> None:
    """Grounding is a portfolio-level floor, not a per-prompt keyword quota.

    The rule this replaced required every confirmed phrase to appear verbatim,
    which rewarded stuffing mechanical context clauses into otherwise natural
    questions. Sharing vocabulary with two confirmed terms proves the portfolio
    is about this brand without dictating how it reads.
    """
    _, context = industry_context("Software")
    prompts = fallback_portfolio(
        primary_market="US",
        industry="Software",
        industry_context=context,
        products_services=["analytics software"],
    )
    replacements = [
        "Where can I find dependable business tools in US?",
        "Which business tools best suit my growing team in US?",
        "I'm looking for reliable digital options for my team in US",
        "How do I compare business tools on price and quality?",
        "Where can I find dependable digital tools for my team in US?",
    ]
    for index, text in enumerate(replacements, start=5):
        prompts[index] = {**prompts[index], "text": text}

    result = validate_portfolio(
        prompts,
        brand_terms=["Acme"],
        competitor_terms=[],
        primary_market="US",
        context_terms=["analytics software", "integrations"],
    )

    assert "portfolio.grounding" in result.errors


def test_prompt_gate_rejects_third_person_buyer_language() -> None:
    """Asking *about* the audience is the marketer tell worth catching."""
    _, context = industry_context("Ecommerce")
    prompts = fallback_portfolio(
        primary_market="US",
        industry="Ecommerce",
        industry_context=context,
        products_services=["kids clothing"],
    )
    prompts[0] = {
        **prompts[0],
        "text": "Where can shoppers buy kids clothing online in US?",
    }

    result = validate_portfolio(
        prompts,
        brand_terms=["Best&Less"],
        competitor_terms=[],
    )

    assert "prompt[0].third_person_audience" in result.errors


def test_prompt_gate_keeps_pronoun_free_buyer_searches() -> None:
    """Real queries often have no pronoun at all; that must not be an error.

    The former rule demanded an i/me/my/we/us/our token, which rejected the
    single most common shape of real buyer query and forced the stilted
    "...should I consider..." phrasing it was meant to prevent.
    """
    prompts = [
        {
            "text": "best mattress for back pain india under 20000",
            "theme": "mattress for back pain",
            "intent": "purchase",
            "cohort": "market_visibility",
        },
        {
            "text": "memory foam vs spring mattress",
            "theme": "mattress types",
            "intent": "comparison",
            "cohort": "market_visibility",
        },
    ]

    result = validate_portfolio(prompts, brand_terms=["Wakefit"], competitor_terms=[])

    assert not [error for error in result.errors if error.startswith("prompt[")]


def test_best_less_fallback_produces_real_searches_when_research_degrades() -> None:
    industry, context = industry_context("Ecommerce")
    prompts = fallback_portfolio(
        primary_market="AU",
        industry=industry,
        industry_context=context,
        products_services=[
            "womens clothing",
            "mens clothing",
            "kids clothing",
            "baby clothing",
            "homewares",
        ],
        price_tier="budget",
    )

    assert len(prompts) == 10
    assert prompts[5]["text"] == (
        "Which affordable women's clothing options should I consider in Australia?"
    )
    assert prompts[5]["theme"] == "Women's Clothing"
    assert all("best&less" not in item["text"].casefold() for item in prompts)
    assert all(
        "for buying products online in Australia" not in item["text"]
        for item in prompts
    )
    assert all(len(item["text"].split()) >= 6 for item in prompts)


@pytest.mark.parametrize("industry", industry_names())
def test_fallback_portfolio_validates_for_every_industry(industry: str) -> None:
    _, context = industry_context(industry)
    prompts = fallback_portfolio(
        primary_market="US",
        industry=industry,
        industry_context=context,
        products_services=[],
    )
    result = validate_portfolio(
        prompts,
        brand_terms=["Acme"],
        competitor_terms=[],
        primary_market="US",
        context_terms=[
            *(context.get("use_cases") or []),
            *(context.get("topics") or []),
        ],
    )
    assert result.errors == ()


def test_create_contract_requires_primary_market() -> None:
    with pytest.raises(ValueError):
        BrandDiscoveryCreate.model_validate(
            {"brand_name": "Acme", "website_url": "https://acme.example"}
        )


def test_catalog_exposes_only_current_research_methods_and_cohorts() -> None:
    catalog = discovery_catalog()

    assert "firecrawl_rendered" not in catalog["capture_methods"]
    assert catalog["prompt_cohorts"] == [MARKET_VISIBILITY, BRAND_RELEVANT]
    assert catalog["required_fields"] == [
        "brand_name",
        "website_url",
        "primary_market",
    ]
