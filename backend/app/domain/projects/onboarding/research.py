"""One structured application-model call with deterministic degradation."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, Field, ValidationError

from app.connectors.agent.client import AgentNotConfiguredError, DefaultAgentClient
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.brand_discovery import (
    CAPTURE_METHOD_APPLICATION_MODEL,
    CAPTURE_METHOD_CRAWLER,
    DISCOVERY_RESEARCH_SYSTEM_PROMPT,
    brand_discovery_settings,
)
from app.domain.projects.discovery_schemas import (
    DiscoveryCompetitorSuggestion,
    DiscoveryEvidence,
    DiscoveryProfile,
    DiscoveryPromptSuggestion,
)
from app.domain.projects.onboarding.industry_library import library_version
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_website_url,
)
from app.domain.projects.onboarding.prompt_generation import (
    fallback_portfolio,
    validated_portfolio,
)
from app.domain.projects.onboarding.site_resolution import (
    SiteNotFoundError,
    resolve_site,
)


class ResearchEnvelope(BaseModel):
    profile: DiscoveryProfile
    competitors: list[DiscoveryCompetitorSuggestion] = Field(default_factory=list)
    topics: list[str] = Field(min_length=1, max_length=20)
    prompts: list[DiscoveryPromptSuggestion] = Field(
        min_length=(
            brand_discovery_settings.market_prompt_count
            + brand_discovery_settings.diagnostic_prompt_count
        ),
        max_length=(
            brand_discovery_settings.market_prompt_count
            + brand_discovery_settings.diagnostic_prompt_count
        ),
    )


@dataclass(frozen=True, slots=True)
class ResearchResult:
    profile: dict
    competitors: list[dict]
    topics: list[str]
    prompts: list[dict]
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


def _fallback_profile(*, brand_name: str, industry: str) -> DiscoveryProfile:
    return DiscoveryProfile(
        description=f"{brand_name} is being reviewed for AI visibility.",
        industry=industry,
        field_confidence={"industry": 1.0, "description": 0.2},
    )


async def _verified_competitor(
    candidate: DiscoveryCompetitorSuggestion,
    *,
    owned_domain: str,
    semaphore: asyncio.Semaphore,
) -> DiscoveryCompetitorSuggestion | None:
    qualification = candidate.qualification
    if qualification is None:
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
    domain_candidates = list(
        dict.fromkeys([*candidate.domains, *candidate.evidence_urls])
    )
    for domain_value in domain_candidates[:2]:
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
    candidates: list[DiscoveryCompetitorSuggestion], *, owned_domain: str
) -> list[DiscoveryCompetitorSuggestion]:
    semaphore = asyncio.Semaphore(
        brand_discovery_settings.competitor_verification_concurrency
    )
    verified = await asyncio.gather(
        *(
            _verified_competitor(
                item,
                owned_domain=owned_domain,
                semaphore=semaphore,
            )
            for item in candidates[: brand_discovery_settings.maximum_competitors]
        ),
        return_exceptions=True,
    )
    return [
        item for item in verified if isinstance(item, DiscoveryCompetitorSuggestion)
    ]


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
    warnings = [site.warning] if site.warning else []
    model_result, provider, model = await _research_model(
        brand_name=brand_name,
        site=site,
        industry=industry,
        subindustry=subindustry,
        primary_market=primary_market,
        language_code=language_code,
        industry_context=industry_context,
    )
    profile = (
        model_result.profile
        if model_result is not None
        else _fallback_profile(brand_name=brand_name, industry=industry)
    )
    if model_result is None:
        warnings.append("research_degraded")

    verified = await _verified_from_model(model_result, site.registrable_domain)
    if not verified:
        warnings.append("competitors_not_found")
    fallback = fallback_portfolio(
        brand_name=brand_name,
        primary_market=primary_market,
        industry=industry,
        industry_context=industry_context,
        products_services=profile.products_services,
        target_audience=profile.target_audience,
    )
    model_prompts = (
        [item.model_dump() for item in model_result.prompts]
        if model_result is not None
        else []
    )
    prompts, prompt_warnings = validated_portfolio(
        model_prompts,
        fallback_prompts=fallback,
        brand_name=brand_name,
        primary_market=primary_market,
        context_terms=[
            *profile.products_services,
            *(industry_context.get("use_cases") or []),
            *(industry_context.get("topics") or []),
        ],
        competitor_terms=[
            term for item in verified for term in [item.name, *item.aliases]
        ],
    )
    warnings.extend(prompt_warnings)
    topics = list(
        dict.fromkeys(
            (model_result.topics if model_result is not None else [])
            or list(industry_context.get("topics") or [industry])
        )
    )
    evidence = _research_evidence(site, model_result, provider, model)
    return ResearchResult(
        profile=profile.model_dump(),
        competitors=[item.model_dump() for item in verified],
        topics=topics,
        prompts=prompts,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
        provider=provider,
        model=model,
    )


async def _research_model(**kwargs):
    try:
        return await _model_research(_research_request(**kwargs))
    except (AgentNotConfiguredError, ProviderError, ValidationError, ValueError):
        return None, "", ""


async def _verified_from_model(model_result, owned_domain):
    if model_result is None:
        return []
    return await _verify_competitors(
        model_result.competitors, owned_domain=owned_domain
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
                supports=["profile", "competitors", "topics", "prompts"],
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
):
    return json.dumps(
        {
            "brand_name": brand_name,
            "official_website": site.canonical_url,
            "official_site_text": _site_text(site.page),
            "industry": industry,
            "subindustry": subindustry,
            "primary_market": primary_market,
            "language_code": language_code,
            "industry_library_version": library_version(),
            "industry_context": industry_context,
            "competitor_limit": brand_discovery_settings.maximum_competitors,
        },
        ensure_ascii=False,
    )


async def _model_research(request):
    client = DefaultAgentClient()
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
