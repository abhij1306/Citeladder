from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.connectors.agent.gateway import FakeModelGateway
from app.core.config.agent import AGENT_TASK_POLICIES, DefaultAgentSettings
from app.domain.agent.schemas import AgentArtifactReference, AgentTaskSubmit
from app.domain.agent.service import (
    _artifact_refs,
    _deterministic_narrative,
    _json_hash,
    _limitations,
    _parse_narrative,
    _roadmap_items,
)
from app.domain.agent.tools import _EXECUTORS


def test_task_and_tool_catalogs_are_fixed_and_read_only() -> None:
    assert set(AGENT_TASK_POLICIES) == {"explain", "build_roadmap"}
    assert set(_EXECUTORS) == {
        "site.read_snapshot",
        "demand.read_snapshot",
        "opportunities.read_ranked",
        "audits.read_latest",
    }
    assert set(AGENT_TASK_POLICIES["build_roadmap"].allowed_tools) == {
        "site.read_snapshot",
        "demand.read_snapshot",
        "opportunities.read_ranked",
    }


def test_submit_contract_rejects_removed_conversation_and_scope_fields() -> None:
    with pytest.raises(ValidationError):
        AgentTaskSubmit.model_validate(
            {
                "project_id": "00000000-0000-0000-0000-000000000001",
                "task_type": "explain",
                "objective": "Explain current evidence",
                "conversation_id": "00000000-0000-0000-0000-000000000002",
                "resource_scope": {},
            }
        )


def test_submit_contract_strips_objective_and_rejects_whitespace_only() -> None:
    payload = {
        "project_id": "00000000-0000-0000-0000-000000000001",
        "task_type": "explain",
        "objective": "  Explain current evidence  ",
    }
    assert (
        AgentTaskSubmit.model_validate(payload).objective == "Explain current evidence"
    )
    with pytest.raises(ValidationError):
        AgentTaskSubmit.model_validate({**payload, "objective": " \t\n "})


def test_agent_retry_delay_increases_and_caps() -> None:
    settings = DefaultAgentSettings(
        default_agent_retry_base_delay_seconds=2,
        default_agent_retry_max_delay_seconds=5,
    )
    assert [settings.retry_delay(attempt) for attempt in (1, 2, 3, 4)] == [
        2,
        4,
        5,
        5,
    ]


def test_narrative_contract_is_minimal_and_strict() -> None:
    assert _parse_narrative(
        '{"summary":"Grounded.","observations":[],"limitations":["Partial."]}'
    ) == {
        "summary": "Grounded.",
        "observations": [],
        "limitations": ["Partial."],
    }
    with pytest.raises(ValueError):
        _parse_narrative('{"summary":""}')


@pytest.mark.parametrize(
    "payload",
    [
        {"summary": 42, "observations": [], "limitations": []},
        {"summary": "Valid", "observations": [42], "limitations": []},
        {"summary": "Valid", "observations": [], "limitations": [False]},
    ],
)
def test_narrative_contract_rejects_non_string_values(payload: dict) -> None:
    with pytest.raises(ValueError):
        _parse_narrative(json.dumps(payload))


def test_public_artifact_reference_requires_a_uuid() -> None:
    with pytest.raises(ValidationError):
        AgentArtifactReference.model_validate({"kind": "snapshot", "id": "not-a-uuid"})


def test_roadmap_filters_incomplete_items_and_keeps_valid_order() -> None:
    valid = {
        "rank": 1,
        "title": "Fix the page",
        "remediation": "Improve the answer.",
        "target_url": None,
        "priority_score": 9.5,
        "severity": "high",
    }
    evidence = [
        {
            "tool": "opportunities.read_ranked",
            "evidence": {
                "items": [valid, {**valid, "rank": 2, "severity": None}, None]
            },
        }
    ]

    assert _roadmap_items(evidence) == [valid]


def test_unknown_unavailable_tool_is_ignored_like_other_public_source_projection() -> (
    None
):
    evidence = [
        {
            "tool": "legacy.read_unknown",
            "evidence": {"state": "unavailable", "reason": "unknown"},
        },
        {
            "tool": "demand.read_snapshot",
            "evidence": {"state": "unavailable", "reason": "no_demand_snapshot"},
        },
    ]

    assert _limitations(evidence) == [
        "Search Demand is unavailable. No Search Demand snapshot is available yet."
    ]


@pytest.mark.parametrize(
    ("count", "summary"),
    [
        (1, "1 prioritized next step is available."),
        (2, "2 prioritized next steps are available."),
    ],
)
def test_roadmap_summary_uses_matching_verb(count: int, summary: str) -> None:
    narrative = _deterministic_narrative(
        "build_roadmap",
        evidence=[{"evidence": {"state": "available"}}],
        roadmap_items=[{} for _ in range(count)],
    )

    assert narrative["summary"] == summary


def test_artifact_refs_are_deduplicated_without_copying_evidence() -> None:
    refs = _artifact_refs(
        [
            {
                "evidence": {
                    "artifact_refs": [
                        {"kind": "demand_snapshot", "id": "one"},
                        {"kind": "demand_snapshot", "id": "one"},
                    ]
                }
            }
        ]
    )
    assert refs == [{"kind": "demand_snapshot", "id": "one"}]
    assert _json_hash({"b": 2, "a": 1}) == _json_hash({"a": 1, "b": 2})


@pytest.mark.asyncio
async def test_fake_gateway_records_bounded_narration_provenance() -> None:
    gateway = FakeModelGateway('{"answer":"Grounded.","limitations":[]}')
    result = await gateway.complete_structured(
        system="bounded",
        user=json.dumps({"evidence": []}),
        schema_name="bounded_agent_result",
        schema={"type": "object"},
    )
    assert result.provider_adapter == "fake"
    assert gateway.calls[0]["schema_name"] == "bounded_agent_result"
