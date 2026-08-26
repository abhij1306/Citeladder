"""Evidence selection and bounded identity synthesis for onboarding."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from urllib.parse import urldefrag, urlsplit

from pydantic import BaseModel, Field, ValidationError

from app.connectors.agent.gateway import ModelGateway
from app.connectors.keenable import (
    KeenableClient,
    KeenableFetchResponse,
    KeenableSearchResponse,
    KeenableSearchResult,
)
from app.core.config.brand_discovery import (
    BRAND_IDENTITY_PROMPT_VERSION,
    BUSINESS_MODELS,
    BUYER_REGISTERS,
    IDENTITY_RESEARCH_SYSTEM_PROMPT,
    KNOWLEDGE_STRENGTHS,
    MARKET_SCOPES,
    SECTORS,
    brand_discovery_settings,
)
from app.core.config.observed_competitors import EXCLUDED_RESEARCH_DOMAINS
from app.domain.projects.brand_evidence import BrandEvidence
from app.domain.projects.discovery_schemas import DiscoveryProfile
from app.domain.projects.onboarding.research_evidence import (
    CompetitiveSignature,
    ResearchCallBudget,
    ResearchEvidenceItem,
    evidence_payload,
)


class IdentityResearchEnvelope(BaseModel):
    status: str = Field(pattern="^(ready|insufficient_evidence|conflicting_evidence)$")
    profile: DiscoveryProfile = Field(default_factory=DiscoveryProfile)
    signature: CompetitiveSignature = Field(default_factory=CompetitiveSignature)
    field_evidence_refs: dict[str, list[str]] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class IdentityEvidenceResult:
    items: tuple[ResearchEvidenceItem, ...]
    state: str


def first_party_evidence(evidence: BrandEvidence) -> list[ResearchEvidenceItem]:
    remaining = brand_discovery_settings.synthesis_evidence_max_chars
    items: list[ResearchEvidenceItem] = []
    for index, page in enumerate(evidence.pages, start=1):
        if remaining <= 0:
            break
        text = "\n".join(
            part for part in (page.title, page.meta_description, page.text) if part
        )
        bounded = text[:remaining]
        remaining -= len(bounded)
        items.append(
            ResearchEvidenceItem(
                evidence_ref=f"fp-{index}",
                source_url=page.url,
                title=page.title,
                text=bounded,
                source_kind="first_party",
            )
        )
    return items


def identity_queries(
    *, brand_name: str, domain: str
) -> tuple[tuple[str, str | None], ...]:
    return (
        (
            "About company products services customers and how the "
            "offering is delivered",
            domain,
        ),
        (
            f"Independent description of {brand_name} {domain}: what it sells, "
            "customers, business model and market",
            None,
        ),
        (
            f"{brand_name} {domain} category positioning use cases alternatives",
            None,
        ),
    )


async def research_identity_evidence(
    client: KeenableClient,
    *,
    brand_name: str,
    owned_domain: str,
    first_party: list[ResearchEvidenceItem],
    budget: ResearchCallBudget,
) -> IdentityEvidenceResult:
    queries = identity_queries(brand_name=brand_name, domain=owned_domain)
    admitted = budget.take(
        min(len(queries), brand_discovery_settings.identity_search_count)
    )
    search_tasks = [
        client.search(
            query,
            site=site,
            max_results=brand_discovery_settings.identity_search_max_results,
            snippet_max_length=brand_discovery_settings.keenable_snippet_max_chars,
        )
        for query, site in queries[:admitted]
    ]
    responses = await asyncio.gather(*search_tasks, return_exceptions=True)
    if not any(not isinstance(item, BaseException) for item in responses):
        return IdentityEvidenceResult(items=(), state="failed")
    search_items, selected = _identity_search_evidence(
        responses, first_party=first_party
    )
    if not search_items:
        return IdentityEvidenceResult(items=(), state="no_results")
    fetch_items = await _identity_fetch_evidence(
        client,
        selected=selected,
        owned_domain=owned_domain,
        budget=budget,
    )
    return IdentityEvidenceResult(
        items=tuple([*search_items, *fetch_items]), state="ready"
    )


def _identity_search_evidence(
    responses: list[KeenableSearchResponse | BaseException],
    *,
    first_party: list[ResearchEvidenceItem],
) -> tuple[list[ResearchEvidenceItem], list[tuple[str, KeenableSearchResult]]]:
    seen = {_canonical_url(item.source_url) for item in first_party}
    selected: list[tuple[str, KeenableSearchResult]] = []
    items: list[ResearchEvidenceItem] = []
    for query_index, response in enumerate(responses, start=1):
        if isinstance(response, BaseException):
            continue
        for result in response.results:
            canonical = _canonical_url(result.url)
            if not canonical or canonical in seen or _noise_host(result.url):
                continue
            seen.add(canonical)
            ref = f"ki-search-{len(items) + 1}"
            items.append(_search_item(ref, result, query_index=query_index))
            selected.append((ref, result))
    return items, selected


def _search_item(
    ref: str, result: KeenableSearchResult, *, query_index: int
) -> ResearchEvidenceItem:
    return ResearchEvidenceItem(
        evidence_ref=ref,
        source_url=result.url,
        title=result.title,
        text=(result.snippet or result.description)[
            : brand_discovery_settings.keenable_snippet_max_chars
        ],
        source_kind="external_search",
        provider="keenable",
        query_ref=f"identity-query-{query_index}",
        published_at=result.published_at,
        acquired_at=result.acquired_at,
    )


async def _identity_fetch_evidence(
    client: KeenableClient,
    *,
    selected: list[tuple[str, KeenableSearchResult]],
    owned_domain: str,
    budget: ResearchCallBudget,
) -> list[ResearchEvidenceItem]:
    selected.sort(
        key=lambda pair: (
            0 if _host(pair[1].url) == owned_domain else 1,
            len(urlsplit(pair[1].url).path),
        )
    )
    fetch_count = budget.take(
        min(len(selected), brand_discovery_settings.identity_fetch_max_pages)
    )
    fetched = await asyncio.gather(
        *(
            client.fetch(
                result.url,
                live=_host(result.url) == owned_domain,
                max_chars=brand_discovery_settings.keenable_fetch_max_chars,
            )
            for _, result in selected[:fetch_count]
        ),
        return_exceptions=True,
    )
    return [
        _fetch_item(index, source_ref, result)
        for index, ((source_ref, _), result) in enumerate(
            zip(selected[:fetch_count], fetched, strict=True), start=1
        )
        if isinstance(result, KeenableFetchResponse) and result.content.strip()
    ]


async def synthesize_identity(
    client: ModelGateway,
    *,
    brand_name: str,
    primary_market: str,
    industry: str,
    subindustry: str,
    language_code: str,
    evidence: list[ResearchEvidenceItem],
) -> IdentityResearchEnvelope:
    request = json.dumps(
        {
            "brand_name": brand_name,
            "market_hint": primary_market,
            "industry_hint": industry,
            "subindustry_hint": subindustry,
            "language_hint": language_code,
            "prompt_version": BRAND_IDENTITY_PROMPT_VERSION,
            "allowed_business_models": list(BUSINESS_MODELS),
            "allowed_market_scopes": list(MARKET_SCOPES),
            "allowed_buyer_registers": list(BUYER_REGISTERS),
            "allowed_sectors": list(SECTORS),
            "allowed_knowledge_strengths": list(KNOWLEDGE_STRENGTHS),
            "evidence": evidence_payload(evidence),
        },
        ensure_ascii=False,
    )
    known_refs = {item.evidence_ref for item in evidence}
    for attempt in range(brand_discovery_settings.synthesis_max_attempts):
        raw = await client.complete_structured_json(
            system=IDENTITY_RESEARCH_SYSTEM_PROMPT,
            user=request,
            schema_name="brand_identity_research",
            schema=IdentityResearchEnvelope.model_json_schema(),
        )
        try:
            envelope = IdentityResearchEnvelope.model_validate_json(raw)
            returned_refs = {
                ref for refs in envelope.field_evidence_refs.values() for ref in refs
            }
            if not returned_refs.issubset(known_refs):
                raise ValueError("identity response cited unknown evidence")
            return envelope
        except (ValidationError, ValueError):
            if attempt + 1 >= brand_discovery_settings.synthesis_max_attempts:
                raise
    raise RuntimeError("identity synthesis attempts exhausted")


def _fetch_item(
    index: int, source_ref: str, result: KeenableFetchResponse
) -> ResearchEvidenceItem:
    return ResearchEvidenceItem(
        evidence_ref=f"ki-fetch-{index}",
        source_url=result.url,
        title=result.title,
        text=result.content,
        source_kind="external_fetch",
        provider="keenable",
        query_ref=source_ref,
        published_at=result.published_at,
        acquired_at=result.acquired_at,
        live=result.live,
    )


def _canonical_url(value: str) -> str:
    url, _ = urldefrag(value.strip())
    return url.rstrip("/").casefold()


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").removeprefix("www.").casefold()


def _noise_host(value: str) -> bool:
    host = _host(value)
    return any(
        host == item or host.endswith(f".{item}") for item in EXCLUDED_RESEARCH_DOMAINS
    )
