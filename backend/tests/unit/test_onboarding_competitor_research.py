"""Deterministic competitor candidate and admission tests."""

from __future__ import annotations

import json

import pytest

from app.connectors.keenable import KeenableSearchResult
from app.domain.projects.discovery_schemas import DiscoveryProfile
from app.domain.projects.onboarding.competitor_research import (
    CandidateVerdict,
    CompetitorCandidate,
    _bounded_qualification_candidates,
    _candidate_pool,
    _is_direct,
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

    async def complete_structured_json(self, **_kwargs) -> str:
        response = self.responses[self.calls]
        self.calls += 1
        return json.dumps(response)


def _verdict(**updates) -> CandidateVerdict:
    values = {
        "candidate_id": "cand-1",
        "decision": "direct",
        "same_core_problem": True,
        "same_buyer": True,
        "credible_substitute": True,
        "geography": "match",
        "delivery_overlap": "partial",
        "positioning_overlap": "high",
        "product_substitutability": 0.8,
        "customer_use_case_overlap": 0.9,
        "geographic_relevance": 1.0,
        "question_visibility": 0.7,
        "confidence": 0.8,
        "evidence_refs": ["kc-search-1"],
        "reasoning": "The supplied evidence supports direct substitution.",
    }
    values.update(updates)
    return CandidateVerdict.model_validate(values)


def test_candidate_pool_uses_result_urls_dedupes_and_excludes_noise() -> None:
    results = [
        (
            "q1",
            KeenableSearchResult(
                title="Peer | Home", url="https://peer.com/product", snippet="one"
            ),
        ),
        (
            "q2",
            KeenableSearchResult(
                title="Peer", url="https://peer.com/about", snippet="two"
            ),
        ),
        (
            "q3",
            KeenableSearchResult(
                title="Owned", url="https://owned.com/about", snippet="owned"
            ),
        ),
        (
            "q4",
            KeenableSearchResult(
                title="LinkedIn", url="https://linkedin.com/company/peer"
            ),
        ),
    ]

    candidates, evidence = _candidate_pool(results, owned_domain="owned.com")

    assert [(item.name, item.domain) for item in candidates] == [("Peer", "peer.com")]
    assert len(candidates[0].evidence) == 1
    assert len(evidence) == 1


def test_direct_competitor_requires_all_hard_gates() -> None:
    assert _is_direct(_verdict())
    assert not _is_direct(_verdict(same_buyer=False))
    assert not _is_direct(_verdict(credible_substitute=False))
    assert not _is_direct(_verdict(geography="irrelevant"))


def test_qualification_evidence_uses_one_shared_character_budget(monkeypatch) -> None:
    from app.domain.projects.onboarding import competitor_research as module

    monkeypatch.setattr(
        module.brand_discovery_settings,
        "competitor_qualification_evidence_max_chars",
        7,
    )
    evidence = ResearchEvidenceItem(
        evidence_ref="kc-search-1",
        source_url="https://peer.example",
        text="abcdefghij",
        source_kind="external_search",
        supports=["competitors"],
    )
    candidates = tuple(
        CompetitorCandidate(
            candidate_id=f"cand-{index}",
            name=f"Peer {index}",
            domain=f"peer{index}.example",
            source_url=f"https://peer{index}.example",
            evidence=[evidence.model_copy(update={"evidence_ref": f"kc-{index}"})],
        )
        for index in range(2)
    )

    bounded = _bounded_qualification_candidates(candidates)

    assert (
        sum(len(item.text) for candidate in bounded for item in candidate.evidence) == 7
    )
    assert [candidate.candidate_id for candidate in bounded] == ["cand-0", "cand-1"]


@pytest.mark.asyncio
async def test_full_candidate_pool_skips_reformulation(monkeypatch) -> None:
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
    assert len(result.candidates) == 1


@pytest.mark.asyncio
async def test_qualification_retries_unknown_evidence_and_preserves_domain() -> None:
    evidence = ResearchEvidenceItem(
        evidence_ref="kc-search-1",
        source_url="https://peer.example/product",
        title="Peer",
        text="Peer serves the same buyer and job.",
        source_kind="external_search",
        provider="keenable",
    )
    candidate = CompetitorCandidate(
        candidate_id="cand-1",
        name="Peer",
        domain="peer.example",
        source_url=evidence.source_url,
        evidence=[evidence],
    )
    invalid = _verdict(evidence_refs=["invented-ref"]).model_dump(mode="json")
    valid = _verdict().model_dump(mode="json")
    gateway = _Gateway([{"verdicts": [invalid]}, {"verdicts": [valid]}])

    suggestions, verdicts = await qualify_competitors(
        gateway,
        profile=DiscoveryProfile(),
        signature=CompetitiveSignature(),
        candidates=(candidate,),
    )

    assert gateway.calls == 2
    assert suggestions[0].domains == ["peer.example"]
    assert verdicts[0]["candidate_id"] == "cand-1"
