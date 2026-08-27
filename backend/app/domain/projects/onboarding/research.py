"""Evidence-first onboarding identity and competitor research orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.gateway import ModelGateway
from app.connectors.answer_engines.errors import ProviderError
from app.connectors.keenable import KeenableClient
from app.core.config.brand_discovery import (
    BRAND_COMPETITOR_QUALIFICATION_VERSION,
    BRAND_IDENTITY_PROMPT_VERSION,
    CAPTURE_METHOD_APPLICATION_MODEL,
    CAPTURE_METHOD_CRAWLER,
    CAPTURE_METHOD_EXTERNAL_FETCH,
    CAPTURE_METHOD_EXTERNAL_SEARCH,
    MARKET_CONTEXT_TERMS,
    brand_discovery_settings,
    same_business_class,
)
from app.core.config.observed_competitors import EXCLUDED_RESEARCH_DOMAINS
from app.core.config.visibility_prompts import TOPIC_SELECTION_PROMPT_VERSION
from app.domain.projects.brand_evidence import BrandEvidence, collect_brand_evidence
from app.domain.projects.discovery_schemas import (
    DiscoveryCompetitorSuggestion,
    DiscoveryEvidence,
    DiscoveryProfile,
)
from app.domain.projects.offering_harvest import harvest_offerings
from app.domain.projects.onboarding.competitor_research import (
    discover_competitor_candidates,
    qualify_competitors,
)
from app.domain.projects.onboarding.identity_research import (
    IdentityResearchEnvelope,
    first_party_evidence,
    research_identity_evidence,
    synthesize_identity,
)
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_website_url,
)
from app.domain.projects.onboarding.research_evidence import (
    CompetitiveSignature,
    ResearchCallBudget,
    ResearchEvidenceItem,
)
from app.domain.projects.onboarding.site_resolution import (
    SiteNotFoundError,
    resolve_site,
)
from app.domain.projects.onboarding.topic_selection import select_topics

COMPETITOR_POOL_MULTIPLIER = 3


def market_terms(primary_market: str) -> str:
    """The plain place name a buyer would search, e.g. ``AU`` -> ``Australia``."""
    terms = MARKET_CONTEXT_TERMS.get(primary_market.upper())
    return terms[0] if terms else primary_market


@dataclass(frozen=True, slots=True)
class ResearchResult:
    profile: dict
    competitive_signature: dict
    competitors: list[dict]
    competitor_verdicts: list[dict]
    topics: list[dict]
    offerings: list[dict]
    evidence: list[dict]
    evidence_manifest: list[dict]
    model_calls: list[dict]
    warnings: list[str]
    provider: str
    model: str
    pages_read: int


@dataclass(frozen=True, slots=True)
class _IdentityPhase:
    external_state: str
    external: list[ResearchEvidenceItem]
    identity: IdentityResearchEnvelope | None
    gateway: ModelGateway | None
    model_calls: list[dict]


@dataclass(frozen=True, slots=True)
class _CompetitorPhase:
    suggestions: list[DiscoveryCompetitorSuggestion]
    verdicts: list[dict]
    evidence: list[ResearchEvidenceItem]
    qualification_available: bool


async def _site_evidence(site) -> BrandEvidence:
    try:
        return await collect_brand_evidence(site.canonical_url)
    except Exception:  # noqa: BLE001 - evidence is best-effort by contract
        return BrandEvidence()


def _fallback_profile(
    *, brand_name: str, industry: str, subindustry: str
) -> DiscoveryProfile:
    # The declared industry/subindustry is user-supplied, so it is always
    # present and is a usable category of last resort. It is carried into
    # ``category``/``category_terms`` for the downstream readers that still
    # need a category -- ``business_category`` in topic selection -- NOT to
    # keep competitor discovery running: the fallback signature deliberately
    # leaves ``category`` empty, which skips the competitor phase entirely.
    category = subindustry.strip() or industry.strip()
    return DiscoveryProfile(
        description=f"{brand_name} is being reviewed for AI visibility.",
        industry=industry,
        category=category,
        category_terms=[term for term in (category, industry.strip()) if term],
        field_confidence={"industry": 1.0, "description": 0.2},
    )


async def research_brand(
    *,
    brand_name: str,
    primary_market: str,
    industry: str,
    subindustry: str,
    language_code: str,
    site,
    on_competitor_phase: Callable[[], Awaitable[None]] | None = None,
) -> ResearchResult:
    """Research one brand. `on_competitor_phase` reports the longest phase.

    The frontend timeline has always had a "Finding comparable brands" step,
    but nothing emitted it, so the bar sat on step one for the whole run and
    the pipeline read as hung.
    """
    website_evidence = await _site_evidence(site)
    first_party = first_party_evidence(website_evidence)
    budget = ResearchCallBudget(brand_discovery_settings.keenable_total_call_cap)
    keenable = _keenable_client()
    identity_phase = await _run_identity_phase(
        keenable=keenable,
        brand_name=brand_name,
        owned_domain=site.registrable_domain,
        primary_market=primary_market,
        industry=industry,
        subindustry=subindustry,
        language_code=language_code,
        first_party=first_party,
        budget=budget,
    )
    profile, signature = _profile_and_signature(
        identity_phase.identity,
        brand_name=brand_name,
        industry=industry,
        subindustry=subindustry,
        primary_market=primary_market,
    )
    if on_competitor_phase is not None:
        await on_competitor_phase()
    competitor_phase = await _run_competitor_phase(
        keenable=keenable,
        gateway=identity_phase.gateway,
        profile=profile,
        signature=signature,
        brand_name=brand_name,
        owned_domain=site.registrable_domain,
        primary_market=primary_market,
        budget=budget,
        model_calls=identity_phase.model_calls,
    )
    verified = await _verify_competitors(
        competitor_phase.suggestions,
        owned_domain=site.registrable_domain,
        brand_model=profile.business_model,
    )
    harvest = harvest_offerings(website_evidence.pages, brand_terms=[brand_name])
    selection = await select_topics(
        brand_name=brand_name,
        brand_aliases=[],
        competitors=[item.name for item in verified],
        business_category=profile.category,
        business_aliases=[*profile.category_aliases, *profile.category_options],
        sector=profile.sector,
        business_model=profile.business_model,
        market=primary_market,
        harvest=harvest,
        page_evidence=_page_evidence(website_evidence),
        allow_model_prior=profile.has_reliable_prior(),
    )
    all_evidence = [
        *first_party,
        *identity_phase.external,
        *competitor_phase.evidence,
    ]
    warnings = _customer_warnings(
        model_available=identity_phase.identity is not None,
        competitors_found=bool(verified),
        external_state=identity_phase.external_state,
        conflicting=_identity_conflicts(identity_phase.identity),
        qualification_available=competitor_phase.qualification_available,
    )
    warnings.extend(selection.warnings)
    if selection.provider and selection.model:
        identity_phase.model_calls.append(
            _model_call_values(
                phase="topic_selection",
                provider=selection.provider,
                model=selection.model,
                prompt_version=TOPIC_SELECTION_PROMPT_VERSION,
                outcome=(
                    "failed"
                    if "topic_selection_unavailable" in selection.warnings
                    else "succeeded"
                ),
            )
        )
    provider, model = _successful_model_provenance(identity_phase.model_calls)
    return ResearchResult(
        profile=profile.model_dump(),
        competitive_signature=signature.model_dump(),
        competitors=[item.model_dump() for item in verified],
        competitor_verdicts=competitor_phase.verdicts,
        topics=[topic.model_dump(mode="json") for topic in selection.topics],
        offerings=harvest.serialize(),
        evidence=_research_evidence(site, all_evidence, identity_phase.model_calls),
        evidence_manifest=[item.model_dump(mode="json") for item in all_evidence],
        model_calls=identity_phase.model_calls,
        warnings=list(dict.fromkeys(warnings)),
        provider=provider,
        model=model,
        pages_read=len(website_evidence.pages),
    )


async def _run_identity_phase(
    *,
    keenable: KeenableClient | None,
    brand_name: str,
    owned_domain: str,
    primary_market: str,
    industry: str,
    subindustry: str,
    language_code: str,
    first_party: list[ResearchEvidenceItem],
    budget: ResearchCallBudget,
) -> _IdentityPhase:
    external_state, external = await _external_identity_evidence(
        keenable,
        brand_name=brand_name,
        owned_domain=owned_domain,
        first_party=first_party,
        budget=budget,
    )
    gateway: ModelGateway | None = None
    identity: IdentityResearchEnvelope | None = None
    model_calls: list[dict] = []
    try:
        gateway = create_model_gateway()
        identity = await synthesize_identity(
            gateway,
            brand_name=brand_name,
            primary_market=primary_market,
            industry=industry,
            subindustry=subindustry,
            language_code=language_code,
            evidence=[*first_party, *external],
        )
        model_calls.append(
            _model_call(
                phase="identity",
                gateway=gateway,
                prompt_version=BRAND_IDENTITY_PROMPT_VERSION,
                outcome="succeeded",
            )
        )
    except (AgentNotConfiguredError, ProviderError, ValidationError, ValueError):
        if gateway is not None:
            model_calls.append(
                _model_call(
                    phase="identity",
                    gateway=gateway,
                    prompt_version=BRAND_IDENTITY_PROMPT_VERSION,
                    outcome="failed",
                )
            )
            gateway = None
        identity = None
    return _IdentityPhase(
        external_state=external_state,
        external=external,
        identity=identity,
        gateway=gateway,
        model_calls=model_calls,
    )


async def _external_identity_evidence(
    keenable: KeenableClient | None,
    *,
    brand_name: str,
    owned_domain: str,
    first_party: list[ResearchEvidenceItem],
    budget: ResearchCallBudget,
) -> tuple[str, list[ResearchEvidenceItem]]:
    if keenable is None:
        return "unavailable", []
    try:
        result = await research_identity_evidence(
            keenable,
            brand_name=brand_name,
            owned_domain=owned_domain,
            first_party=first_party,
            budget=budget,
        )
    except ProviderError:
        return "failed", []
    return result.state, list(result.items)


def _profile_and_signature(
    identity: IdentityResearchEnvelope | None,
    *,
    brand_name: str,
    industry: str,
    subindustry: str,
    primary_market: str,
) -> tuple[DiscoveryProfile, CompetitiveSignature]:
    if identity is not None:
        # A researched identity can still land without a category - typically
        # when the evidence conflicts and the model declines to guess. The
        # stand-in must stay as narrow as the evidence: the declared
        # subindustry is user-supplied and sector-wide, and searching it turned
        # a linen-womenswear brand into a query for "Apparel", which returned
        # A.P.C. Paris. An empty category skips competitor search, and
        # returning no competitors is better than returning the wrong ones.
        signature = identity.signature
        if not signature.category:
            signature = signature.model_copy(
                update={"category": _evidence_category(identity.profile)}
            )
        return identity.profile, signature
    profile = _fallback_profile(
        brand_name=brand_name, industry=industry, subindustry=subindustry
    )
    return profile, CompetitiveSignature(
        # The fallback profile's category IS the declared subindustry, so it is
        # deliberately not carried into the signature. The competitor phase
        # already returns nothing without a gateway; leaving this empty also
        # stops it spending the search budget on a sector-wide query first.
        category="",
        buyer=profile.target_audience,
        core_job=(profile.jobs_to_be_done or [""])[0],
        market_context=primary_market,
        search_terms=profile.category_terms[:8],
    )


def _evidence_category(profile: DiscoveryProfile) -> str:
    """The narrowest category the evidence itself supports, or nothing.

    Every source here is model-written from first-party and retrieved
    evidence. The user-declared industry/subindustry is deliberately excluded:
    it is a sector, and a sector-wide competitor search is what produced an
    unrelated brand.
    """
    candidates = [
        profile.category,
        *profile.category_terms,
        *profile.products_services,
    ]
    return next((value.strip() for value in candidates if value.strip()), "")


async def _run_competitor_phase(
    *,
    keenable: KeenableClient | None,
    gateway: ModelGateway | None,
    profile: DiscoveryProfile,
    signature: CompetitiveSignature,
    brand_name: str,
    owned_domain: str,
    primary_market: str,
    budget: ResearchCallBudget,
    model_calls: list[dict],
) -> _CompetitorPhase:
    empty = _CompetitorPhase([], [], [], False)
    if keenable is None or not signature.category:
        return empty
    evidence: list[ResearchEvidenceItem] = []
    try:
        result = await discover_competitor_candidates(
            keenable,
            brand_name=brand_name,
            owned_domain=owned_domain,
            signature=signature,
            budget=budget,
            market=market_terms(primary_market),
        )
        evidence = list(result.evidence)
        if not evidence or gateway is None:
            return _CompetitorPhase([], [], evidence, False)
        suggestions, verdicts = await qualify_competitors(
            gateway,
            profile=profile,
            signature=signature,
            evidence=result.evidence,
        )
        model_calls.append(
            _model_call(
                phase="competitor_qualification",
                gateway=gateway,
                prompt_version=BRAND_COMPETITOR_QUALIFICATION_VERSION,
                outcome="succeeded",
            )
        )
        return _CompetitorPhase(suggestions, verdicts, evidence, True)
    except (ProviderError, ValidationError, ValueError):
        if gateway is not None and evidence:
            model_calls.append(
                _model_call(
                    phase="competitor_qualification",
                    gateway=gateway,
                    prompt_version=BRAND_COMPETITOR_QUALIFICATION_VERSION,
                    outcome="failed",
                )
            )
        return _CompetitorPhase([], [], evidence, False)


def _identity_conflicts(identity: IdentityResearchEnvelope | None) -> bool:
    return identity is not None and identity.status == "conflicting_evidence"


def _successful_model_provenance(model_calls: list[dict]) -> tuple[str, str]:
    for call in model_calls:
        if call["outcome"] == "succeeded":
            return call["provider"], call["model"]
    return "", ""


def _keenable_client() -> KeenableClient | None:
    key = brand_discovery_settings.keenable_api_key.get_secret_value()
    if not key:
        return None
    return KeenableClient(
        api_key=key,
        base_url=brand_discovery_settings.keenable_base_url,
        timeout_seconds=brand_discovery_settings.keenable_request_timeout_seconds,
    )


def _page_evidence(evidence: BrandEvidence) -> list[dict[str, str]]:
    budget = brand_discovery_settings.topic_evidence_max_chars_per_page
    return [
        {
            "evidence_ref": f"page-{index}",
            "url": page.url,
            "title": page.title,
            "text": page.text[:budget],
        }
        for index, page in enumerate(evidence.pages, start=1)
    ]


def _model_call(*, phase: str, gateway, prompt_version: str, outcome: str) -> dict:
    return _model_call_values(
        phase=phase,
        provider=gateway.base_url_host,
        model=gateway.model,
        prompt_version=prompt_version,
        outcome=outcome,
    )


def _model_call_values(
    *, phase: str, provider: str, model: str, prompt_version: str, outcome: str
) -> dict:
    return {
        "phase": phase,
        "provider": provider,
        "model": model,
        "prompt_version": prompt_version,
        "outcome": outcome,
    }


def _research_evidence(site, items, model_calls):
    captured_at = datetime.now(UTC)
    evidence = []
    for item in items:
        capture_method = {
            "first_party": CAPTURE_METHOD_CRAWLER,
            "external_search": CAPTURE_METHOD_EXTERNAL_SEARCH,
            "external_fetch": CAPTURE_METHOD_EXTERNAL_FETCH,
        }[item.source_kind]
        evidence.append(
            DiscoveryEvidence(
                source_url=item.source_url,
                capture_method=capture_method,
                method=item.evidence_ref,
                provider=item.provider,
                confidence=0.9 if item.source_kind == "first_party" else 0.7,
                captured_at=captured_at,
                supports=item.supports,
            ).model_dump(mode="json")
        )
    if not evidence:
        evidence.append(
            DiscoveryEvidence(
                source_url=site.canonical_url,
                capture_method=CAPTURE_METHOD_CRAWLER,
                method="direct_homepage",
                confidence=0.4,
                captured_at=captured_at,
                supports=["official_website", "owned_domain", "profile"],
            ).model_dump(mode="json")
        )
    model_supports = {
        "identity": ["profile"],
        "competitor_qualification": ["competitors"],
        "topic_selection": ["topics"],
    }
    for call in model_calls:
        evidence.append(
            DiscoveryEvidence(
                source_url=f"model://application-research/{call['phase']}",
                capture_method=CAPTURE_METHOD_APPLICATION_MODEL,
                method=call["prompt_version"],
                provider=call["provider"],
                model=call["model"],
                confidence=0.7 if call["outcome"] == "succeeded" else 0,
                captured_at=captured_at,
                supports=(
                    model_supports.get(call["phase"], [])
                    if call["outcome"] == "succeeded"
                    else []
                ),
            ).model_dump(mode="json")
        )
    return evidence


def _customer_warnings(
    *,
    model_available: bool,
    competitors_found: bool,
    external_state: str = "ready",
    conflicting: bool = False,
    qualification_available: bool = True,
) -> list[str]:
    warnings = []
    if external_state in {"unavailable", "failed"}:
        warnings.append("external_research_unavailable")
    elif external_state == "no_results":
        warnings.append("external_research_no_results")
    if conflicting:
        warnings.append("conflicting_evidence")
    if not model_available or not qualification_available:
        warnings.append("research_degraded")
    if not competitors_found:
        warnings.append("competitors_not_found")
    return warnings


def _competitor_domain_candidates(
    candidate: DiscoveryCompetitorSuggestion,
) -> list[str]:
    """Usable domains for this candidate, declared ones filtered like evidence.

    The exclusion list was applied to `evidence_urls` only, so a declared
    domain naming a directory or analytics site was still tried -- and, being
    first, it consumed one of the two attempts and could be persisted as the
    competitor's domain.
    """
    return [
        value
        for value in dict.fromkeys([*candidate.domains, *candidate.evidence_urls])
        if not _is_excluded_research_url(value)
    ]


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
    if candidate.qualification is None or not _is_peer_company(
        candidate, brand_model=brand_model
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
                resolved = await resolve_site(domain_value, url)
        except SiteNotFoundError:
            continue
        return candidate.model_copy(
            update={
                "domains": [candidate_domain],
                "evidence_urls": list(
                    dict.fromkeys([*candidate.evidence_urls, resolved.canonical_url])
                ),
            }
        )
    return None


async def _verify_competitors(
    candidates: list[DiscoveryCompetitorSuggestion],
    *,
    owned_domain: str,
    brand_model: str,
) -> list[DiscoveryCompetitorSuggestion]:
    limit = brand_discovery_settings.maximum_competitors
    semaphore = asyncio.Semaphore(
        brand_discovery_settings.competitor_verification_concurrency
    )
    verified = await asyncio.gather(
        *(
            _verified_competitor(
                candidate,
                owned_domain=owned_domain,
                brand_model=brand_model,
                semaphore=semaphore,
            )
            for candidate in candidates[: limit * COMPETITOR_POOL_MULTIPLIER]
        ),
        return_exceptions=True,
    )
    return [
        item for item in verified if isinstance(item, DiscoveryCompetitorSuggestion)
    ][:limit]
