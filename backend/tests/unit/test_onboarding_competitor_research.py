"""Deterministic competitor candidate and admission tests."""

from __future__ import annotations

import json

import pytest

from app.connectors.keenable import KeenableSearchResult
from app.domain.projects.discovery_schemas import DiscoveryProfile
from app.domain.projects.onboarding.competitor_research import (
    CandidateVerdict,
    CompetitorCandidate,
    _candidate_pool,
    _is_direct,
    qualify_competitors,
)
from app.domain.projects.onboarding.research_evidence import (
    CompetitiveSignature,
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
