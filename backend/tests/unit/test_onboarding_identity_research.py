"""Identity synthesis validates schema and supplied evidence references."""

from __future__ import annotations

import asyncio
import json

import pytest

from app.connectors.keenable import KeenableFetchResponse, KeenableSearchResult
from app.domain.projects.onboarding.identity_research import (
    _identity_fetch_evidence,
    synthesize_identity,
)
from app.domain.projects.onboarding.research_evidence import (
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


class _FetchClient:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def fetch(self, url: str, **_kwargs) -> KeenableFetchResponse:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0)
        self.active -= 1
        return KeenableFetchResponse(url=url, title="Peer", content="Evidence")


@pytest.mark.asyncio
async def test_identity_fetches_obey_configured_concurrency(monkeypatch) -> None:
    from app.domain.projects.onboarding import identity_research as module

    monkeypatch.setattr(module.brand_discovery_settings, "keenable_concurrency", 2)
    monkeypatch.setattr(module.brand_discovery_settings, "identity_fetch_max_pages", 3)
    selected = [
        (
            f"ki-search-{index}",
            KeenableSearchResult(
                title=f"Peer {index}", url=f"https://peer{index}.example"
            ),
        )
        for index in range(3)
    ]
    client = _FetchClient()

    evidence = await _identity_fetch_evidence(
        client,
        selected=selected,
        owned_domain="owned.example",
        budget=ResearchCallBudget(3),
    )

    assert len(evidence) == 3
    assert client.max_active == 2


@pytest.mark.asyncio
async def test_identity_synthesis_retries_an_invented_reference() -> None:
    base = {
        "status": "ready",
        "profile": {"brand_name": "Acme"},
        "signature": {
            "category": "workflow software",
            "buyer": "operations teams",
            "core_job": "coordinate work",
        },
    }
    gateway = _Gateway(
        [
            {**base, "field_evidence_refs": {"category": ["invented"]}},
            {**base, "field_evidence_refs": {"category": ["fp-1"]}},
        ]
    )
    evidence = ResearchEvidenceItem(
        evidence_ref="fp-1",
        source_url="https://acme.example",
        title="Acme",
        text="Workflow software for operations teams.",
        source_kind="first_party",
    )

    result = await synthesize_identity(
        gateway,
        brand_name="Acme",
        primary_market="US",
        industry="software",
        subindustry="workflow",
        language_code="en",
        evidence=[evidence],
    )

    assert gateway.calls == 2
    assert "CORRECTION_REQUIRED" not in gateway.users[0]
    assert '"allowed_evidence_refs": ["fp-1"]' in gateway.users[0]
    assert "invented" in gateway.users[1]
    assert "fp-1" in gateway.users[1]
    assert result.signature.category == "workflow software"
    assert result.field_evidence_refs == {"category": ["fp-1"]}
