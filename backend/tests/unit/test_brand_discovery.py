"""Reliability-first onboarding unit contracts."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.projects.discovery_schemas import BrandDiscoveryCreate
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
    BRAND_DIAGNOSTIC,
    MARKET_VISIBILITY,
    validate_portfolio,
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


def test_fallback_portfolio_is_exactly_five_neutral_and_five_branded() -> None:
    industry, context = industry_context("Ecommerce")
    prompts = fallback_portfolio(
        brand_name="Flipkart",
        primary_market="IN",
        industry=industry,
        industry_context=context,
        products_services=["online marketplace"],
        target_audience="Indian shoppers",
    )

    quality = validate_portfolio(
        prompts,
        brand_terms=["Flipkart"],
        competitor_terms=["Amazon"],
        primary_market="IN",
        context_terms=["online marketplace", *(context.get("use_cases") or [])],
    )
    assert quality.errors == ()
    assert [item["cohort"] for item in prompts].count(MARKET_VISIBILITY) == 5
    assert [item["cohort"] for item in prompts].count(BRAND_DIAGNOSTIC) == 5
    assert all("India" in item["text"] or "Indian" in item["text"] for item in prompts)


def test_prompt_gate_rejects_brand_leak_and_missing_brand() -> None:
    _, context = industry_context("Software")
    prompts = fallback_portfolio(
        brand_name="Acme",
        primary_market="US",
        industry="Software",
        industry_context=context,
        products_services=["analytics software"],
        target_audience="marketing teams",
    )
    assert prompts[0]["cohort"] == MARKET_VISIBILITY
    assert prompts[5]["cohort"] == BRAND_DIAGNOSTIC
    prompts[0] = {**prompts[0], "text": "Is Acme the best analytics software in US?"}
    prompts[5] = {
        **prompts[5],
        "text": "What analytics software helps marketing teams in US?",
    }

    result = validate_portfolio(
        prompts,
        brand_terms=["Acme"],
        competitor_terms=[],
    )

    assert "prompt[0].neutrality" in result.errors
    assert "prompt[5].brand_required" in result.errors


@pytest.mark.parametrize("industry", industry_names())
def test_fallback_portfolio_validates_for_every_industry(industry: str) -> None:
    _, context = industry_context(industry)
    prompts = fallback_portfolio(
        brand_name="Acme",
        primary_market="US",
        industry=industry,
        industry_context=context,
        products_services=[],
        target_audience="",
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
    assert catalog["prompt_cohorts"] == [MARKET_VISIBILITY, BRAND_DIAGNOSTIC]
    assert catalog["required_fields"] == [
        "brand_name",
        "website_url",
        "primary_market",
    ]
