"""Identity synthesis validates schema and supplied evidence references."""

from __future__ import annotations

import json

import pytest

from app.domain.projects.onboarding.identity_research import synthesize_identity
from app.domain.projects.onboarding.research_evidence import ResearchEvidenceItem


class _Gateway:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.calls = 0

    async def complete_structured_json(self, **_kwargs) -> str:
        response = self.responses[self.calls]
        self.calls += 1
        return json.dumps(response)


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
    assert result.signature.category == "workflow software"
    assert result.field_evidence_refs == {"category": ["fp-1"]}
