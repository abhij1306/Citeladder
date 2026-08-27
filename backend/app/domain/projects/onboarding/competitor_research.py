"""Search-backed competitor candidate discovery and qualification."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

from app.connectors.agent.gateway import ModelGateway
from app.connectors.keenable import (
    KeenableClient,
    KeenableFetchResponse,
    KeenableSearchResult,
)
from app.core.config.brand_discovery import (
    BRAND_COMPETITOR_QUALIFICATION_VERSION,
    BUSINESS_MODELS,
    COMPETITOR_EXCLUDED_DOMAINS,
    COMPETITOR_QUALIFICATION_SYSTEM_PROMPT,
    brand_discovery_settings,
)
from app.core.config.observed_competitors import EXCLUDED_RESEARCH_DOMAINS
from app.domain.projects.discovery_schemas import (
    BusinessModel,
    CompetitorQualification,
    DiscoveryCompetitorSuggestion,
    DiscoveryProfile,
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
from app.domain.projects.onboarding.structured_repair import (
    complete_validated_envelope,
)


class NamedCompetitor(BaseModel):
    """One competitor the model read out of the research evidence."""

    name: str = Field(min_length=1, max_length=255)
    domain: str = Field(min_length=1, max_length=255)
    business_model: BusinessModel | None = None
    same_buyer: bool = True
    same_market: bool = True
    confidence: float = Field(default=0.5, ge=0, le=1)
    evidence_refs: list[str] = Field(default_factory=list)
    # Bounded in the schema so a long batch of rationales cannot overrun the
    # agent's output cap, and truncated rather than rejected so a slightly long
    # one never costs a whole regeneration.
    reasoning: str = Field(default="", json_schema_extra={"maxLength": 240})

    @field_validator("reasoning", mode="before")
    @classmethod
    def _bound_reasoning(cls, value: object) -> object:
        return value[:240] if isinstance(value, str) else value


class CompetitorQualificationEnvelope(BaseModel):
    competitors: list[NamedCompetitor] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompetitorResearchResult:
    evidence: tuple[ResearchEvidenceItem, ...]
    state: str


# Signature fields are model-written prose ("budget-conscious parents and
# caregivers in Australia"). Pasted into a search engine whole they produce
# sentence-length queries that match documents ABOUT the words rather than the
# competitors themselves - which is how "X alternatives" returned SaaS listing
# sites. Queries are therefore built from a few bounded keywords, the way a
# person actually searches.
QUERY_TERM_MAX_WORDS: Final = 6


def _terms(value: str, *, limit: int = QUERY_TERM_MAX_WORDS) -> str:
    return " ".join(value.split()[:limit]).strip(" ,.;:-")


def competitor_queries(
    *, brand_name: str, signature: CompetitiveSignature, market: str = ""
) -> tuple[str, ...]:
    category = _terms(signature.category)
    place = _terms(market or signature.market_context, limit=3)
    scoped = f"{category} {place}".strip()
    return tuple(
        dict.fromkeys(
            query
            for query in (
                f"best {scoped} brands",
                f"{scoped} stores list",
                f"{brand_name} competitors",
                f"{brand_name} alternatives",
            )
            if query.strip()
        )
    )


async def discover_competitor_candidates(
    client: KeenableClient,
    *,
    brand_name: str,
    owned_domain: str,
    signature: CompetitiveSignature,
    budget: ResearchCallBudget,
    market: str = "",
) -> CompetitorResearchResult:
    """Gather the research text competitors will be read out of.

    Search results are pages ABOUT the brand, so they are evidence, not
    candidates. The most promising ones are additionally fetched so the model
    reads the full list of names rather than a truncated snippet.
    """
    queries = competitor_queries(
        brand_name=brand_name, signature=signature, market=market
    )
    admitted = budget.take(
        min(len(queries), brand_discovery_settings.competitor_search_count)
    )
    results = await _search_queries(client, queries[:admitted])
    evidence = _search_evidence(results, owned_domain=owned_domain)
    if len(evidence) < brand_discovery_settings.competitor_candidate_cap:
        reformulations = _reformulations(signature, market=market)
        extra_count = budget.take(
            min(
                len(reformulations),
                brand_discovery_settings.competitor_search_reformulation_cap,
            )
        )
        extra = await _search_queries(client, reformulations[:extra_count])
        evidence = _search_evidence([*results, *extra], owned_domain=owned_domain)
    if not evidence:
        return CompetitorResearchResult(evidence=(), state="no_results")

    fetch_count = budget.take(
        min(len(evidence), brand_discovery_settings.competitor_fetch_max_pages)
    )
    fetched = await _fetch_pages(client, evidence[:fetch_count])
    # Fetched pages first: ``_bounded_evidence`` spends a fixed character
    # budget in order, and the search rows are snippets of the same pages.
    # Putting the snippets first let them consume the budget and truncate the
    # full-text listicle the competitor names are actually written in.
    return CompetitorResearchResult(
        evidence=tuple([*fetched, *evidence]), state="ready"
    )


async def _fetch_pages(
    client: KeenableClient, targets: list[ResearchEvidenceItem]
) -> list[ResearchEvidenceItem]:
    semaphore = asyncio.Semaphore(brand_discovery_settings.keenable_concurrency)

    async def fetch(item: ResearchEvidenceItem) -> KeenableFetchResponse:
        async with semaphore:
            return await client.fetch(
                item.source_url,
                live=True,
                max_chars=brand_discovery_settings.keenable_fetch_max_chars,
            )

    responses = await asyncio.gather(
        *(fetch(item) for item in targets), return_exceptions=True
    )
    fetched: list[ResearchEvidenceItem] = []
    for index, response in enumerate(responses, start=1):
        if isinstance(response, BaseException) or not response.content.strip():
            continue
        fetched.append(
            ResearchEvidenceItem(
                evidence_ref=f"kc-fetch-{index}",
                source_url=response.url,
                title=response.title,
                text=response.content,
                source_kind="external_fetch",
                provider="keenable",
                published_at=response.published_at,
                acquired_at=response.acquired_at,
                live=response.live,
                supports=["competitors"],
            )
        )
    return fetched


async def qualify_competitors(
    client: ModelGateway,
    *,
    profile: DiscoveryProfile,
    signature: CompetitiveSignature,
    evidence: tuple[ResearchEvidenceItem, ...],
) -> tuple[list[DiscoveryCompetitorSuggestion], list[dict]]:
    """Read competitor names out of the gathered research evidence.

    Search returns pages ABOUT the brand - listicles, directories, coupon and
    analytics sites - so a result's own domain is almost never a competitor.
    The competitors are the companies named inside that text, which is what the
    model is asked for here. Every returned domain is resolved downstream, so a
    name the model invents cannot reach the customer.
    """
    bounded = _bounded_evidence(evidence)
    known_refs = {item.evidence_ref for item in bounded}
    request = json.dumps(
        {
            "prompt_version": BRAND_COMPETITOR_QUALIFICATION_VERSION,
            "brand_profile": profile.model_dump(mode="json"),
            "competitive_signature": signature.model_dump(mode="json"),
            "allowed_business_models": list(BUSINESS_MODELS),
            "allowed_evidence_refs": sorted(known_refs),
            "target_competitors": brand_discovery_settings.target_competitors,
            "maximum_competitors": brand_discovery_settings.maximum_competitors,
            "research_evidence": [item.model_dump(mode="json") for item in bounded],
        },
        ensure_ascii=False,
    )

    def validate(envelope: CompetitorQualificationEnvelope) -> None:
        unknown = {
            ref for item in envelope.competitors for ref in item.evidence_refs
        } - known_refs
        if unknown:
            raise ValueError(
                f"competitor response cited unknown evidence refs {sorted(unknown)}; "
                f"allowed refs are {sorted(known_refs)}"
            )

    envelope = await complete_validated_envelope(
        client,
        system=COMPETITOR_QUALIFICATION_SYSTEM_PROMPT,
        user=request,
        schema_name="competitor_qualification",
        envelope_type=CompetitorQualificationEnvelope,
        validate=validate,
    )
    admitted = _admitted_competitors(envelope.competitors)
    return (
        [_suggestion(item) for item in admitted],
        [item.model_dump(mode="json") for item in envelope.competitors],
    )


def _admitted_competitors(
    competitors: list[NamedCompetitor],
) -> list[NamedCompetitor]:
    """Keep same-buyer, same-market names on a usable domain, best first."""
    seen: set[str] = set()
    admitted: list[NamedCompetitor] = []
    for item in competitors:
        if not (item.same_buyer and item.same_market):
            continue
        domain = _bare_domain(item.domain)
        if not domain or _excluded_domain(domain) or domain in seen:
            continue
        seen.add(domain)
        admitted.append(item.model_copy(update={"domain": domain}))
    admitted.sort(key=lambda item: (-item.confidence, item.name.casefold()))
    return admitted


def _bare_domain(value: str) -> str:
    try:
        _, domain = normalize_website_url(value)
    except InvalidWebsiteUrl:
        return ""
    return domain


def _bounded_evidence(
    evidence: tuple[ResearchEvidenceItem, ...],
) -> tuple[ResearchEvidenceItem, ...]:
    """Trim evidence text to the configured qualification character budget."""
    remaining = brand_discovery_settings.competitor_qualification_evidence_max_chars
    bounded: list[ResearchEvidenceItem] = []
    for item in evidence:
        if remaining <= 0:
            break
        text = item.text[:remaining]
        remaining -= len(text)
        bounded.append(item.model_copy(update={"text": text}))
    return tuple(bounded)


async def _search_queries(
    client: KeenableClient, queries: tuple[str, ...]
) -> list[tuple[str, KeenableSearchResult]]:
    responses = await asyncio.gather(
        *(
            client.search(
                query,
                max_results=brand_discovery_settings.competitor_search_max_results,
                snippet_max_length=brand_discovery_settings.keenable_snippet_max_chars,
            )
            for query in queries
        ),
        return_exceptions=True,
    )
    flattened: list[tuple[str, KeenableSearchResult]] = []
    for query_index, response in enumerate(responses, start=1):
        if isinstance(response, BaseException):
            continue
        flattened.extend(
            (f"competitor-query-{query_index}", result) for result in response.results
        )
    return flattened


def _search_evidence(
    results: list[tuple[str, KeenableSearchResult]], *, owned_domain: str
) -> list[ResearchEvidenceItem]:
    """One evidence row per distinct source page, best-ranked pages first."""
    evidence: list[ResearchEvidenceItem] = []
    seen: set[str] = set()
    for query_ref, result in sorted(results, key=_candidate_source_rank):
        if len(evidence) >= brand_discovery_settings.competitor_candidate_cap:
            break
        try:
            _, domain = normalize_website_url(result.url)
        except InvalidWebsiteUrl:
            continue
        if domain == owned_domain or domain in seen:
            continue
        seen.add(domain)
        evidence.append(
            ResearchEvidenceItem(
                evidence_ref=f"kc-search-{len(evidence) + 1}",
                source_url=result.url,
                title=result.title,
                text=(result.snippet or result.description)[
                    : brand_discovery_settings.keenable_snippet_max_chars
                ],
                source_kind="external_search",
                provider="keenable",
                query_ref=query_ref,
                published_at=result.published_at,
                acquired_at=result.acquired_at,
                supports=["competitors"],
            )
        )
    return evidence


def _suggestion(item: NamedCompetitor) -> DiscoveryCompetitorSuggestion:
    return DiscoveryCompetitorSuggestion(
        name=item.name,
        domains=[item.domain],
        qualification=CompetitorQualification(
            product_substitutability=item.confidence,
            customer_use_case_overlap=item.confidence,
            geographic_relevance=1.0 if item.same_market else 0.0,
            question_visibility=item.confidence,
        ),
        business_model=item.business_model,
        reasoning=item.reasoning,
        evidence_urls=[],
        confidence=item.confidence,
    )


def _reformulations(
    signature: CompetitiveSignature, *, market: str = ""
) -> tuple[str, ...]:
    place = _terms(market or signature.market_context, limit=3)
    adjacent = _terms(next(iter(signature.adjacent_categories), ""))
    terms = _terms(" ".join(signature.search_terms[:3]), limit=5)
    return tuple(
        dict.fromkeys(
            query
            for query in (
                f"{adjacent} brands {place}".strip(),
                f"{terms} {place}".strip(),
            )
            if query.strip()
        )
    )


def _excluded_domain(domain: str) -> bool:
    excluded = {*COMPETITOR_EXCLUDED_DOMAINS, *EXCLUDED_RESEARCH_DOMAINS}
    return any(domain == item or domain.endswith(f".{item}") for item in excluded)


def _candidate_source_rank(
    item: tuple[str, KeenableSearchResult],
) -> tuple[int, int, str]:
    path = urlsplit(item[1].url).path.strip("/")
    depth = 0 if not path else path.count("/") + 1
    return (depth, len(path), item[1].url.casefold())
