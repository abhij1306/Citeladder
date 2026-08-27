"""Deterministic competitor evidence and admission tests."""

from __future__ import annotations

import json

import pytest

from app.connectors.keenable import KeenableSearchResult
from app.domain.projects.discovery_schemas import DiscoveryProfile
from app.domain.projects.onboarding.competitor_research import (
    NamedCompetitor,
    _admitted_competitors,
    _bounded_evidence,
    _search_evidence,
    competitor_queries,
    discover_competitor_candidates,
    qualify_competitors,
)
from app.domain.projects.onboarding.research_evidence import (
    CompetitiveSignature,
    ResearchCallBudget,
    ResearchEvidenceItem,
)


class _Gateway:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = 0
        self.users: list[str] = []

    async def complete_structured_json(self, **kwargs) -> str:
        self.users.append(kwargs["user"])
        response = self.responses[self.calls]
        self.calls += 1
        return json.dumps(response)


def _competitor(**updates) -> dict:
    values = {
        "name": "Peer",
        "domain": "peer.com",
        "business_model": "retail",
        "same_buyer": True,
        "same_market": True,
        "confidence": 0.8,
        "evidence_refs": ["kc-search-1"],
        "reasoning": "Named in the supplied listing as a value rival.",
    }
    values.update(updates)
    return NamedCompetitor.model_validate(values).model_dump(mode="json")


def test_search_evidence_dedupes_by_domain_and_drops_owned_site() -> None:
    results = [
        (
            "q1",
            KeenableSearchResult(
                title="Listicle | Home", url="https://blog.com/top-10", snippet="one"
            ),
        ),
        (
            "q2",
            KeenableSearchResult(
                title="Listicle", url="https://blog.com/other", snippet="two"
            ),
        ),
        (
            "q3",
            KeenableSearchResult(
                title="Owned", url="https://owned.com/about", snippet="owned"
            ),
        ),
    ]

    evidence = _search_evidence(results, owned_domain="owned.com")

    assert [item.source_url for item in evidence] == ["https://blog.com/other"]
    assert evidence[0].evidence_ref == "kc-search-1"
    assert evidence[0].source_kind == "external_search"


def test_queries_are_short_keyword_searches_not_signature_prose() -> None:
    signature = CompetitiveSignature(
        category="family apparel retail for value-seeking households",
        buyer="budget-conscious parents and caregivers across the country",
        core_job="provide affordable everyday clothing for the whole family",
        market_context="Australian national value fashion market",
    )

    queries = competitor_queries(
        brand_name="Acme", signature=signature, market="Australia"
    )

    assert all(len(query) <= 80 for query in queries), queries
    assert "Acme competitors" in queries
    assert "Acme alternatives" in queries
    # Signature prose must not be pasted into a query verbatim.
    assert not any(signature.core_job in query for query in queries)


def test_admission_drops_wrong_buyer_market_aggregators_and_duplicates() -> None:
    competitors = [
        NamedCompetitor.model_validate(_competitor(confidence=0.4)),
        NamedCompetitor.model_validate(
            _competitor(name="Best", domain="peer.com", confidence=0.9)
        ),
        NamedCompetitor.model_validate(_competitor(name="Off", same_buyer=False)),
        NamedCompetitor.model_validate(_competitor(name="Far", same_market=False)),
        NamedCompetitor.model_validate(_competitor(name="Directory", domain="g2.com")),
        NamedCompetitor.model_validate(_competitor(name="Bad", domain="not a domain")),
        # A hallucinated, unregistrable domain must never reach the customer.
        NamedCompetitor.model_validate(_competitor(name="Fake", domain="peer.example")),
    ]

    admitted = _admitted_competitors(competitors)

    # Highest confidence first, one row per domain, no aggregators.
    assert [(item.name, item.domain) for item in admitted] == [("Peer", "peer.com")]


def test_reasoning_is_truncated_rather_than_rejected() -> None:
    item = NamedCompetitor.model_validate(_competitor(reasoning="x" * 5000))

    assert len(item.reasoning) == 240


def test_evidence_uses_one_shared_character_budget(monkeypatch) -> None:
    from app.domain.projects.onboarding import competitor_research as module

    monkeypatch.setattr(
        module.brand_discovery_settings,
        "competitor_qualification_evidence_max_chars",
        7,
    )
    evidence = tuple(
        ResearchEvidenceItem(
            evidence_ref=f"kc-search-{index}",
            source_url=f"https://peer{index}.com",
            text="abcdefghij",
            source_kind="external_search",
            supports=["competitors"],
        )
        for index in range(2)
    )

    bounded = _bounded_evidence(evidence)

    assert sum(len(item.text) for item in bounded) == 7


@pytest.mark.asyncio
async def test_full_evidence_pool_skips_reformulation(monkeypatch) -> None:
    from app.domain.projects.onboarding import competitor_research as module

    monkeypatch.setattr(module.brand_discovery_settings, "competitor_candidate_cap", 1)
    monkeypatch.setattr(
        module.brand_discovery_settings, "competitor_fetch_max_pages", 0
    )
    calls = 0

    async def search(_client, _queries):
        nonlocal calls
        calls += 1
        return [
            (
                "query-1",
                KeenableSearchResult(
                    title="Peer", url="https://peer.com", snippet="Peer"
                ),
            )
        ]

    monkeypatch.setattr(module, "_search_queries", search)

    result = await discover_competitor_candidates(
        object(),
        brand_name="Acme",
        owned_domain="acme.com",
        signature=CompetitiveSignature(
            category="workflow software", buyer="operations teams"
        ),
        budget=ResearchCallBudget(6),
    )

    assert calls == 1
    assert len(result.evidence) == 1
    assert result.state == "ready"


@pytest.mark.asyncio
async def test_qualification_retries_unknown_evidence_and_keeps_domain() -> None:
    evidence = (
        ResearchEvidenceItem(
            evidence_ref="kc-search-1",
            source_url="https://listicle.com/top-10",
            title="Top 10",
            text="Peer is the best-known rival in this market.",
            source_kind="external_search",
            provider="keenable",
        ),
    )
    invalid = _competitor(evidence_refs=["invented-ref"])
    valid = _competitor()
    gateway = _Gateway([{"competitors": [invalid]}, {"competitors": [valid]}])

    suggestions, verdicts = await qualify_competitors(
        gateway,
        profile=DiscoveryProfile(),
        signature=CompetitiveSignature(),
        evidence=evidence,
    )

    assert gateway.calls == 2
    assert "CORRECTION_REQUIRED" not in gateway.users[0]
    assert '"allowed_evidence_refs": ["kc-search-1"]' in gateway.users[0]
    assert "invented-ref" in gateway.users[1]
    assert suggestions[0].domains == ["peer.com"]
    assert suggestions[0].name == "Peer"
    assert verdicts[0]["domain"] == "peer.com"
