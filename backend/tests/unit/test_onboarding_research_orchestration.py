"""Onboarding v7 orchestration boundaries and degraded states."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.projects.brand_evidence import BrandEvidence
from app.domain.projects.discovery_schemas import DiscoveryProfile
from app.domain.projects.onboarding.competitor_research import (
    CompetitorCandidate,
    CompetitorResearchResult,
)
from app.domain.projects.onboarding.identity_research import (
    IdentityEvidenceResult,
    IdentityResearchEnvelope,
)
from app.domain.projects.onboarding.research_evidence import (
    CompetitiveSignature,
    ResearchEvidenceItem,
)


class _Harvest:
    def serialize(self) -> list[dict]:
        return []


def _identity() -> IdentityResearchEnvelope:
    return IdentityResearchEnvelope(
        status="ready",
        profile=DiscoveryProfile(
            category="workflow software",
            target_audience="operations teams",
            jobs_to_be_done=["coordinate work"],
        ),
        signature=CompetitiveSignature(
            category="workflow software",
            buyer="operations teams",
            core_job="coordinate work",
            market_context="US",
        ),
        field_evidence_refs={"category": ["ki-search-1"]},
    )


@pytest.mark.asyncio
async def test_ready_path_records_two_structured_phases(monkeypatch) -> None:
    from app.domain.projects.onboarding import research as module

    evidence = ResearchEvidenceItem(
        evidence_ref="ki-search-1",
        source_url="https://source.example/acme",
        text="Acme makes workflow software.",
        source_kind="external_search",
        provider="keenable",
    )
    gateway = SimpleNamespace(base_url_host="provider.invalid", model="fixture-model")
    candidate = CompetitorCandidate(
        candidate_id="cand-1",
        name="Peer",
        domain="peer.com",
        source_url="https://peer.com",
        evidence=[evidence.model_copy(update={"evidence_ref": "kc-search-1"})],
    )

    async def site_evidence(_site):
        return BrandEvidence()

    async def identity_evidence(*_args, **_kwargs):
        return IdentityEvidenceResult(items=(evidence,), state="ready")

    async def synthesize(*_args, **_kwargs):
        return _identity()

    async def discover(*_args, **_kwargs):
        return CompetitorResearchResult(
            candidates=(candidate,), evidence=tuple(candidate.evidence), state="ready"
        )

    async def qualify(*_args, **_kwargs):
        return [], [{"candidate_id": "cand-1", "decision": "exclude"}]

    async def verify(*_args, **_kwargs):
        return []

    async def topics(**_kwargs):
        return SimpleNamespace(topics=[], warnings=[])

    monkeypatch.setattr(module, "_site_evidence", site_evidence)
    monkeypatch.setattr(module, "_keenable_client", lambda: object())
    monkeypatch.setattr(module, "research_identity_evidence", identity_evidence)
    monkeypatch.setattr(module, "create_model_gateway", lambda: gateway)
    monkeypatch.setattr(module, "synthesize_identity", synthesize)
    monkeypatch.setattr(module, "discover_competitor_candidates", discover)
    monkeypatch.setattr(module, "qualify_competitors", qualify)
    monkeypatch.setattr(module, "_verify_competitors", verify)
    monkeypatch.setattr(
        module, "harvest_offerings", lambda *_args, **_kwargs: _Harvest()
    )
    monkeypatch.setattr(module, "select_topics", topics)

    result = await module.research_brand(
        brand_name="Acme",
        primary_market="US",
        industry="Software",
        subindustry="Workflow",
        language_code="en",
        site=SimpleNamespace(
            canonical_url="https://acme.com", registrable_domain="acme.com"
        ),
    )

    assert [call["phase"] for call in result.model_calls] == [
        "identity",
        "competitor_qualification",
    ]
    assert result.provider == "provider.invalid"
    assert result.competitor_verdicts[0]["candidate_id"] == "cand-1"
    assert any(item["capture_method"] == "external_search" for item in result.evidence)


@pytest.mark.asyncio
async def test_missing_keenable_degrades_without_failing_identity(monkeypatch) -> None:
    from app.domain.projects.onboarding import research as module

    gateway = SimpleNamespace(base_url_host="provider.invalid", model="fixture-model")

    async def site_evidence(_site):
        return BrandEvidence()

    async def synthesize(*_args, **_kwargs):
        return _identity().model_copy(update={"field_evidence_refs": {}})

    async def verify(*_args, **_kwargs):
        return []

    async def topics(**_kwargs):
        return SimpleNamespace(topics=[], warnings=[])

    monkeypatch.setattr(module, "_site_evidence", site_evidence)
    monkeypatch.setattr(module, "_keenable_client", lambda: None)
    monkeypatch.setattr(module, "create_model_gateway", lambda: gateway)
    monkeypatch.setattr(module, "synthesize_identity", synthesize)
    monkeypatch.setattr(module, "_verify_competitors", verify)
    monkeypatch.setattr(
        module, "harvest_offerings", lambda *_args, **_kwargs: _Harvest()
    )
    monkeypatch.setattr(module, "select_topics", topics)

    result = await module.research_brand(
        brand_name="Acme",
        primary_market="US",
        industry="Software",
        subindustry="Workflow",
        language_code="en",
        site=SimpleNamespace(
            canonical_url="https://acme.com", registrable_domain="acme.com"
        ),
    )

    assert result.profile["category"] == "workflow software"
    assert "external_research_unavailable" in result.warnings
    assert "competitors_not_found" in result.warnings
    assert [call["phase"] for call in result.model_calls] == ["identity"]
