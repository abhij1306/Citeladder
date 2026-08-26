"""Search-backed competitor candidate discovery and qualification."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

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


class CompetitorCandidate(BaseModel):
    candidate_id: str
    name: str
    domain: str
    source_url: str
    evidence: list[ResearchEvidenceItem] = Field(default_factory=list)


class CandidateVerdict(BaseModel):
    candidate_id: str
    decision: Literal["direct", "adjacent", "exclude"]
    same_core_problem: bool
    same_buyer: bool
    credible_substitute: bool
    geography: Literal["match", "partial", "irrelevant", "unknown"]
    delivery_overlap: Literal["match", "partial", "mismatch", "unknown"]
    positioning_overlap: Literal["high", "medium", "low", "unknown"]
    product_substitutability: float = Field(ge=0, le=1)
    customer_use_case_overlap: float = Field(ge=0, le=1)
    geographic_relevance: float = Field(ge=0, le=1)
    question_visibility: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    business_model: BusinessModel | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=2000)


class CompetitorQualificationEnvelope(BaseModel):
    verdicts: list[CandidateVerdict] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class CompetitorResearchResult:
    candidates: tuple[CompetitorCandidate, ...]
    evidence: tuple[ResearchEvidenceItem, ...]
    state: str


def competitor_queries(
    *, brand_name: str, signature: CompetitiveSignature
) -> tuple[str, ...]:
    qualifiers = " ".join(signature.qualifiers[:2])
    return (
        f"{signature.category} providers for {signature.buyer} "
        f"{signature.core_job} {signature.market_context} official sites",
        (
            f"{signature.delivery_model} {signature.category} for "
            f"{signature.buyer} companies"
        ),
        (
            f"{signature.category} {qualifiers} "
            f"{signature.market_context} brands providers"
        ),
        f"{brand_name} alternatives competitors official sites",
    )


async def discover_competitor_candidates(
    client: KeenableClient,
    *,
    brand_name: str,
    owned_domain: str,
    signature: CompetitiveSignature,
    budget: ResearchCallBudget,
) -> CompetitorResearchResult:
    queries = competitor_queries(brand_name=brand_name, signature=signature)
    admitted = budget.take(
        min(len(queries), brand_discovery_settings.competitor_search_count)
    )
    results = await _search_queries(client, queries[:admitted])
    candidates, evidence = _candidate_pool(results, owned_domain=owned_domain)
    if len(candidates) < brand_discovery_settings.competitor_candidate_cap:
        reformulations = _reformulations(signature)
        extra_count = budget.take(
            min(
                len(reformulations),
                brand_discovery_settings.competitor_search_reformulation_cap,
            )
        )
        extra = await _search_queries(client, reformulations[:extra_count])
        candidates, evidence = _candidate_pool(
            [*results, *extra], owned_domain=owned_domain
        )
    if not candidates:
        return CompetitorResearchResult(candidates=(), evidence=(), state="no_results")

    fetch_count = budget.take(
        min(len(candidates), brand_discovery_settings.competitor_fetch_max_pages)
    )
    semaphore = asyncio.Semaphore(brand_discovery_settings.keenable_concurrency)

    async def fetch_candidate(
        candidate: CompetitorCandidate,
    ) -> KeenableFetchResponse:
        async with semaphore:
            return await client.fetch(
                candidate.source_url,
                live=True,
                max_chars=brand_discovery_settings.keenable_fetch_max_chars,
            )

    fetched = await asyncio.gather(
        *(fetch_candidate(candidate) for candidate in candidates[:fetch_count]),
        return_exceptions=True,
    )
    enriched: list[CompetitorCandidate] = []
    all_evidence = list(evidence)
    for index, candidate in enumerate(candidates):
        additions: list[ResearchEvidenceItem] = []
        if index < fetch_count:
            response = fetched[index]
            if not isinstance(response, BaseException) and response.content.strip():
                item = ResearchEvidenceItem(
                    evidence_ref=f"kc-fetch-{index + 1}",
                    source_url=response.url,
                    title=response.title,
                    text=response.content,
                    source_kind="external_fetch",
                    provider="keenable",
                    query_ref=candidate.candidate_id,
                    published_at=response.published_at,
                    acquired_at=response.acquired_at,
                    live=response.live,
                    supports=["competitors"],
                )
                additions.append(item)
                all_evidence.append(item)
        enriched.append(
            candidate.model_copy(update={"evidence": [*candidate.evidence, *additions]})
        )
    return CompetitorResearchResult(
        candidates=tuple(enriched), evidence=tuple(all_evidence), state="ready"
    )


async def qualify_competitors(
    client: ModelGateway,
    *,
    profile: DiscoveryProfile,
    signature: CompetitiveSignature,
    candidates: tuple[CompetitorCandidate, ...],
) -> tuple[list[DiscoveryCompetitorSuggestion], list[dict]]:
    candidates = _bounded_qualification_candidates(candidates)
    request = json.dumps(
        {
            "prompt_version": BRAND_COMPETITOR_QUALIFICATION_VERSION,
            "profile": profile.model_dump(mode="json"),
            "competitive_signature": signature.model_dump(mode="json"),
            "allowed_business_models": list(BUSINESS_MODELS),
            "candidates": [item.model_dump(mode="json") for item in candidates],
        },
        ensure_ascii=False,
    )
    by_id = {item.candidate_id: item for item in candidates}
    known_refs = {
        item.candidate_id: {evidence.evidence_ref for evidence in item.evidence}
        for item in candidates
    }
    for attempt in range(brand_discovery_settings.synthesis_max_attempts):
        raw = await client.complete_structured_json(
            system=COMPETITOR_QUALIFICATION_SYSTEM_PROMPT,
            user=request,
            schema_name="competitor_qualification",
            schema=CompetitorQualificationEnvelope.model_json_schema(),
        )
        try:
            envelope = CompetitorQualificationEnvelope.model_validate_json(raw)
            _validate_verdicts(envelope.verdicts, by_id=by_id, known_refs=known_refs)
            break
        except (ValidationError, ValueError):
            if attempt + 1 >= brand_discovery_settings.synthesis_max_attempts:
                raise
    else:  # pragma: no cover - loop either breaks or raises
        raise RuntimeError("competitor qualification attempts exhausted")

    direct = [verdict for verdict in envelope.verdicts if _is_direct(verdict)]
    direct.sort(key=_ranking_key)
    suggestions = [_suggestion(by_id[item.candidate_id], item) for item in direct]
    return suggestions, [item.model_dump(mode="json") for item in envelope.verdicts]


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


def _candidate_pool(
    results: list[tuple[str, KeenableSearchResult]], *, owned_domain: str
) -> tuple[list[CompetitorCandidate], list[ResearchEvidenceItem]]:
    candidates: list[CompetitorCandidate] = []
    evidence: list[ResearchEvidenceItem] = []
    by_domain: dict[str, int] = {}
    ordered_results = sorted(results, key=_candidate_source_rank)
    for query_ref, result in ordered_results:
        try:
            _, domain = normalize_website_url(result.url)
        except InvalidWebsiteUrl:
            continue
        if domain == owned_domain or _excluded_domain(domain):
            continue
        if domain in by_domain:
            continue
        if len(candidates) >= brand_discovery_settings.competitor_candidate_cap:
            continue
        search_item = ResearchEvidenceItem(
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
        evidence.append(search_item)
        candidate = CompetitorCandidate(
            candidate_id=f"cand-{len(candidates) + 1}",
            name=_display_name(result, domain),
            domain=domain,
            source_url=result.url,
            evidence=[search_item],
        )
        by_domain[domain] = len(candidates)
        candidates.append(candidate)
    return candidates, evidence


def _bounded_qualification_candidates(
    candidates: tuple[CompetitorCandidate, ...],
) -> tuple[CompetitorCandidate, ...]:
    remaining = brand_discovery_settings.competitor_qualification_evidence_max_chars
    bounded: list[CompetitorCandidate] = []
    for candidate in candidates:
        evidence: list[ResearchEvidenceItem] = []
        for item in candidate.evidence:
            text = item.text[:remaining]
            remaining -= len(text)
            evidence.append(item.model_copy(update={"text": text}))
        bounded.append(candidate.model_copy(update={"evidence": evidence}))
    return tuple(bounded)


def _validate_verdicts(verdicts, *, by_id, known_refs) -> None:
    seen: set[str] = set()
    for verdict in verdicts:
        if verdict.candidate_id not in by_id or verdict.candidate_id in seen:
            raise ValueError(
                "qualification response used an unknown/duplicate candidate"
            )
        seen.add(verdict.candidate_id)
        if not set(verdict.evidence_refs).issubset(known_refs[verdict.candidate_id]):
            raise ValueError("qualification response cited unknown evidence")
        if verdict.decision == "direct" and not _is_direct(verdict):
            raise ValueError("direct verdict failed hard admission gates")


def _is_direct(verdict: CandidateVerdict) -> bool:
    return (
        verdict.decision == "direct"
        and verdict.same_core_problem
        and verdict.same_buyer
        and verdict.credible_substitute
        and verdict.geography != "irrelevant"
    )


def _ranking_key(verdict: CandidateVerdict) -> tuple:
    geography = {"match": 0, "partial": 1, "unknown": 2, "irrelevant": 3}
    positioning = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
    delivery = {"match": 0, "partial": 1, "mismatch": 2, "unknown": 3}
    scores = (
        verdict.product_substitutability,
        verdict.customer_use_case_overlap,
        verdict.geographic_relevance,
        verdict.question_visibility,
    )
    return (
        geography[verdict.geography],
        positioning[verdict.positioning_overlap],
        delivery[verdict.delivery_overlap],
        -verdict.confidence,
        -sum(scores),
        verdict.candidate_id,
    )


def _suggestion(
    candidate: CompetitorCandidate, verdict: CandidateVerdict
) -> DiscoveryCompetitorSuggestion:
    return DiscoveryCompetitorSuggestion(
        name=candidate.name,
        domains=[candidate.domain],
        qualification=CompetitorQualification(
            product_substitutability=verdict.product_substitutability,
            customer_use_case_overlap=verdict.customer_use_case_overlap,
            geographic_relevance=verdict.geographic_relevance,
            question_visibility=verdict.question_visibility,
        ),
        business_model=verdict.business_model,
        reasoning=verdict.reasoning,
        evidence_urls=list(
            dict.fromkeys(item.source_url for item in candidate.evidence)
        ),
        confidence=verdict.confidence,
    )


def _reformulations(signature: CompetitiveSignature) -> tuple[str, ...]:
    adjacent = " ".join(signature.adjacent_categories[:2])
    terms = " ".join(signature.search_terms[:4])
    return (
        f"{signature.category} {adjacent} alternatives for {signature.buyer}",
        f"{terms} providers {signature.market_context} official sites",
    )


def _excluded_domain(domain: str) -> bool:
    excluded = {*COMPETITOR_EXCLUDED_DOMAINS, *EXCLUDED_RESEARCH_DOMAINS}
    return any(domain == item or domain.endswith(f".{item}") for item in excluded)


def _display_name(result: KeenableSearchResult, domain: str) -> str:
    title = result.title.split("|")[0].split("—")[0].strip()
    if title and len(title) <= 255:
        return title
    return domain.split(".")[0].replace("-", " ").title()


def _candidate_source_rank(
    item: tuple[str, KeenableSearchResult],
) -> tuple[int, int, str]:
    path = urlsplit(item[1].url).path.strip("/")
    depth = 0 if not path else path.count("/") + 1
    return (depth, len(path), item[1].url.casefold())
