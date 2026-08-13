from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.connectors.agent.gateway import FakeModelGateway
from app.core.config.agent import AGENT_TASK_POLICIES, DefaultAgentSettings
from app.domain.agent.schemas import AgentTaskSubmit
from app.domain.agent.service import _artifact_refs, _json_hash, _parse_narrative
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
        retry_base_delay_seconds=2,
        retry_max_delay_seconds=5,
    )
    assert [settings.retry_delay(attempt) for attempt in (1, 2, 3, 4)] == [
        2,
        4,
        5,
        5,
    ]


def test_narrative_contract_is_minimal_and_strict() -> None:
    assert _parse_narrative('{"answer":"Grounded.","limitations":["Partial."]}') == {
        "answer": "Grounded.",
        "limitations": ["Partial."],
    }
    with pytest.raises(ValueError):
        _parse_narrative('{"answer":""}')


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
