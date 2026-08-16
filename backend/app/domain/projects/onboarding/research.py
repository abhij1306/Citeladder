"""One structured application-model call with deterministic degradation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import (
    BUSINESS_MODELS,
    BUYER_REGISTERS,
    CAPTURE_METHOD_APPLICATION_MODEL,
    CAPTURE_METHOD_CRAWLER,
    CONTEXT_PROFILE_VERSION,
    DISCOVERY_RESEARCH_SYSTEM_PROMPT,
    KNOWLEDGE_STRENGTHS,
    MARKET_SCOPES,
    SECTORS,
    brand_discovery_settings,
    same_business_class,
)
from app.core.config.observed_competitors import EXCLUDED_RESEARCH_DOMAINS
from app.domain.projects.brand_evidence import collect_brand_evidence
from app.domain.projects.discovery_schemas import (
    DiscoveryCompetitorSuggestion,
    DiscoveryEvidence,
    DiscoveryProfile,
)
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_website_url,
)
from app.domain.projects.onboarding.site_resolution import (
    SiteNotFoundError,
    resolve_site,
)

# Verify more candidates than we can keep. Domain resolution is the main
# source of loss, and it is not correlated with how good a competitor is, so a
# deeper pool converts directly into recall.
COMPETITOR_POOL_MULTIPLIER = 3


class ResearchEnvelope(BaseModel):
    profile: DiscoveryProfile
    competitors: list[DiscoveryCompetitorSuggestion] = Field(default_factory=list)
    topics: list[str] = Field(min_length=1, max_length=20)


@dataclass(frozen=True, slots=True)
class ResearchResult:
    profile: dict
    competitors: list[dict]
    topics: list[str]
    evidence: list[dict]
    warnings: list[str]
    provider: str
    model: str


def _site_text(page) -> str:
    if page is None:
        return ""
    return "\n".join(
        item for item in (page.title, page.meta_description, page.text) if item
    )[: brand_discovery_settings.synthesis_evidence_max_chars]


async def _site_evidence(site) -> str:
    """Read a few high-signal pages, not just the homepage.

    A homepage is often a slogan and a hero image, which is exactly the case
    where the model has to guess -- and guessing is what produces confident
    nonsense for brands it does not know. `collect_brand_evidence` reads /about,
    /products, /services and /pricing when the homepage is thin, inside a fixed
    wall-clock budget, with an in-process cache and single-flight. It never
    raises, so a blocked or slow site degrades to homepage text rather than
    failing onboarding.
    """
    try:
        evidence = await collect_brand_evidence(site.canonical_url)
    except Exception:  # noqa: BLE001 - evidence is best-effort by contract
        return ""
    if not evidence.pages:
        return ""
    return evidence.serialize()[: brand_discovery_settings.synthesis_evidence_max_chars]


def _fallback_profile(*, brand_name: str, industry: str) -> DiscoveryProfile:
    return DiscoveryProfile(
        description=f"{brand_name} is being reviewed for AI visibility.",
        industry=industry,
        field_confidence={"industry": 1.0, "description": 0.2},
    )


def _competitor_domain_candidates(
    candidate: DiscoveryCompetitorSuggestion,
) -> list[str]:
    """Domains that may be adopted as this competitor's OWN site.

    An evidence URL records where the competitor was *mentioned*, not where it
    lives. Folding evidence URLs in unconditionally let a reference host become
    the competitor's domain whenever its real site failed to resolve — Myntra
    was persisted with ``wikipedia.org``, which both loses every real
    ``myntra.com`` citation and misattributes every Wikipedia one. Evidence
    URLs stay eligible only when they are not a known research/reference host.
    """
    evidence = [
        url for url in candidate.evidence_urls if not _is_excluded_research_url(url)
    ]
    return list(dict.fromkeys([*candidate.domains, *evidence]))


def _is_excluded_research_url(value: str) -> bool:
    try:
        _, domain = normalize_website_url(value)
    except InvalidWebsiteUrl:
        return True
    return any(
        domain == excluded or domain.endswith(f".{excluded}")
        for excluded in EXCLUDED_RESEARCH_DOMAINS
    )


def _is_peer_company(
    candidate: DiscoveryCompetitorSuggestion, *, brand_model: str
) -> bool:
    """Reject a competitor that is a different KIND of company than the brand.

    The four qualification dimensions measure overlap -- substitutability, use
    case, geography, question visibility -- and every one of them can score high
    across the service/product line. An ecommerce implementation agency was
    returned with Shopify Plus, BigCommerce, Salesforce Commerce Cloud, SAP
    Commerce Cloud and commercetools: same words, same buyers, same questions,
    and not one of them is something you hire instead of the agency. Kind is the
    dimension that was missing, so it is checked separately.

    Abstains when the model declined to classify the competitor, because an
    unstated model is not evidence of a mismatch.
    """
    if candidate.business_model is None:
        return True
    return same_business_class(candidate.business_model, brand_model)


async def _verified_competitor(
    candidate: DiscoveryCompetitorSuggestion,
    *,
    owned_domain: str,
    brand_model: str,
    semaphore: asyncio.Semaphore,
) -> DiscoveryCompetitorSuggestion | None:
    qualification = candidate.qualification
    if qualification is None:
        return None
    if not _is_peer_company(candidate, brand_model=brand_model):
        return None
    floor = brand_discovery_settings.competitor_min_dimension_score
    if (
        min(
            qualification.product_substitutability,
            qualification.customer_use_case_overlap,
            qualification.geographic_relevance,
            qualification.question_visibility,
        )
        < floor
    ):
        return None
    for domain_value in _competitor_domain_candidates(candidate)[:2]:
        try:
            url, candidate_domain = normalize_website_url(domain_value)
        except InvalidWebsiteUrl:
            continue
        if candidate_domain == owned_domain:
            continue
        try:
            async with semaphore:
                site = await resolve_site(domain_value, url)
        except SiteNotFoundError:
            continue
        evidence_urls = list(
            dict.fromkeys([*candidate.evidence_urls, site.canonical_url])
        )
        return candidate.model_copy(
            update={"domains": [candidate_domain], "evidence_urls": evidence_urls}
        )
    return None


async def _verify_competitors(
    candidates: list[DiscoveryCompetitorSuggestion],
    *,
    owned_domain: str,
    brand_model: str,
) -> list[DiscoveryCompetitorSuggestion]:
    """Verify a pool, then keep the best survivors.

    The cap used to be applied *before* verification, so a candidate whose
    domain failed to resolve simply vanished and nothing took its place -- five
    proposals minus two unreachable sites shipped three competitors, while a
    perfectly good sixth candidate was never even considered. Verifying a larger
    pool and truncating afterwards is what makes the cap a cap rather than a
    quota that silently under-fills.
    """
    limit = brand_discovery_settings.maximum_competitors
    pool = candidates[: limit * COMPETITOR_POOL_MULTIPLIER]
    semaphore = asyncio.Semaphore(
        brand_discovery_settings.competitor_verification_concurrency
    )
    verified = await asyncio.gather(
        *(
            _verified_competitor(
                item,
                owned_domain=owned_domain,
                brand_model=brand_model,
                semaphore=semaphore,
            )
            for item in pool
        ),
        return_exceptions=True,
    )
    # Model order is its own confidence ranking, so first-past-the-post over the
    # verified set preserves it without inventing a second scoring rule.
    survivors = [
        item for item in verified if isinstance(item, DiscoveryCompetitorSuggestion)
    ]
    return survivors[:limit]


async def research_brand(
    *,
    brand_name: str,
    primary_market: str,
    industry: str,
    subindustry: str,
    language_code: str,
    site,
    industry_context: dict,
) -> ResearchResult:
    site_evidence = await _site_evidence(site)
    model_result, provider, model = await _research_model(
        brand_name=brand_name,
        site=site,
        industry=industry,
        subindustry=subindustry,
        primary_market=primary_market,
        language_code=language_code,
        industry_context=industry_context,
        site_evidence=site_evidence,
    )
    profile = (
        model_result.profile
        if model_result is not None
        else _fallback_profile(brand_name=brand_name, industry=industry)
    )
    verified = await _verified_from_model(model_result, site.registrable_domain)
    warnings = _customer_warnings(
        model_available=model_result is not None,
        competitors_found=bool(verified),
    )
    topics = (
        list(model_result.topics)
        if model_result is not None
        else [*(profile.products_services or []), industry]
    )
    evidence = _research_evidence(site, model_result, provider, model)
    return ResearchResult(
        profile=profile.model_dump(),
        competitors=[item.model_dump() for item in verified],
        topics=list(dict.fromkeys(topic for topic in topics if topic.strip())),
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
        provider=provider,
        model=model,
    )


def _customer_warnings(*, model_available: bool, competitors_found: bool) -> list[str]:
    """Expose only degraded outcomes that need the customer's attention.

    Homepage extraction and prompt validation have deterministic, provenance-
    preserving fallbacks. Surfacing those internal recovery paths as errors made
    every otherwise complete review look broken. A warning remains appropriate
    when the research model itself was unavailable or no competitor survived
    evidence verification, because those conditions materially reduce the
    review the customer receives.
    """
    warnings = []
    if not model_available:
        warnings.append("research_degraded")
    if not competitors_found:
        warnings.append("competitors_not_found")
    return warnings


async def _research_model(**kwargs):
    try:
        return await _model_research(_research_request(**kwargs))
    except (AgentNotConfiguredError, ProviderError, ValidationError, ValueError):
        return None, "", ""


async def _verified_from_model(model_result, owned_domain):
    if model_result is None:
        return []
    return await _verify_competitors(
        model_result.competitors,
        owned_domain=owned_domain,
        brand_model=model_result.profile.business_model,
    )


def _research_evidence(site, model_result, provider, model):
    captured_at = datetime.now(UTC)
    evidence = [
        DiscoveryEvidence(
            source_url=site.canonical_url,
            capture_method=CAPTURE_METHOD_CRAWLER,
            method="direct_homepage",
            confidence=0.9 if site.page is not None else 0.4,
            captured_at=captured_at,
            supports=["official_website", "owned_domain", "profile"],
        ).model_dump(mode="json")
    ]
    if model_result is not None:
        evidence.append(
            DiscoveryEvidence(
                source_url="model://application-research",
                capture_method=CAPTURE_METHOD_APPLICATION_MODEL,
                method="structured_research",
                provider=provider,
                model=model,
                confidence=0.7,
                captured_at=captured_at,
                supports=["profile", "competitors", "topics"],
            ).model_dump(mode="json")
        )
    return evidence


def _research_request(
    *,
    brand_name,
    site,
    industry,
    subindustry,
    primary_market,
    language_code,
    industry_context,
    site_evidence="",
):
    # The industry pair is passed as a *hint* only. It used to supply the topic
    # list that filled prompt slots, which is why every Software brand asked
    # about "analytics software"; the model now resolves its own category and
    # the hint merely disambiguates when site evidence is thin.
    return json.dumps(
        {
            "brand_name": brand_name,
            "official_website": site.canonical_url,
            "official_site_text": site_evidence or _site_text(site.page),
            "user_supplied_industry_hint": industry,
            "user_supplied_subindustry_hint": subindustry,
            "primary_market": primary_market,
            "language_code": language_code,
            "context_profile_version": CONTEXT_PROFILE_VERSION,
            "allowed_business_models": list(BUSINESS_MODELS),
            "allowed_market_scopes": list(MARKET_SCOPES),
            "allowed_buyer_registers": list(BUYER_REGISTERS),
            "allowed_sectors": list(SECTORS),
            "allowed_knowledge_strengths": list(KNOWLEDGE_STRENGTHS),
            "competitor_limit": (
                brand_discovery_settings.maximum_competitors
                * COMPETITOR_POOL_MULTIPLIER
            ),
        },
        ensure_ascii=False,
    )


async def _model_research(request):
    client = create_model_gateway()
    for attempt in range(brand_discovery_settings.synthesis_max_attempts):
        raw = await client.complete_structured_json(
            system=DISCOVERY_RESEARCH_SYSTEM_PROMPT,
            user=request,
            schema_name="brand_onboarding_research",
            schema=ResearchEnvelope.model_json_schema(),
        )
        try:
            result = ResearchEnvelope.model_validate_json(raw)
            return result, client.base_url_host, client.model
        except ValidationError:
            if attempt + 1 >= brand_discovery_settings.synthesis_max_attempts:
                raise
    raise RuntimeError("structured research attempts were exhausted")
