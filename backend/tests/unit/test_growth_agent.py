from __future__ import annotations

import json

import pytest

from app.connectors.agent.gateway import FakeModelGateway
from app.core.config.agent import AGENT_TASK_POLICIES, TOOL_KIND_AUTOMATIC
from app.domain.agent import context as agent_context
from app.domain.agent.service import _build_plan, _validate_result
from app.domain.agent.tools import (
    TOOL_DEFINITIONS,
    _bounded_result,
    _serialized_chars,
    validate_automatic_tools,
)


def test_every_task_plan_is_bounded_and_allowlisted() -> None:
    for task_type, policy in AGENT_TASK_POLICIES.items():
        scope = {key: "fixture" for key in policy.required_scope}
        plan = _build_plan(task_type, scope)
        assert len(plan) <= policy.max_steps
        assert len(plan) <= policy.max_tool_calls
        assert {step["tool_name"] for step in plan} <= set(policy.allowed_tools)


def test_automatic_tools_have_no_external_effect() -> None:
    validate_automatic_tools()
    assert all(
        not item.external_effect
        for item in TOOL_DEFINITIONS.values()
        if item.kind == TOOL_KIND_AUTOMATIC
    )


def test_result_rejects_citation_absent_from_context() -> None:
    validation = _validate_result(
        {"citations": ["allowed", "fabricated"]}, context_ids={"allowed"}
    )
    assert validation == {
        "status": "blocked",
        "validator_version": "agent-result-v1",
        "unsupported_output": True,
        "invalid_citation_ids": ["fabricated"],
        "citation_count": 2,
    }


@pytest.mark.asyncio
async def test_fake_gateway_records_structured_call_and_provenance() -> None:
    gateway = FakeModelGateway('{"conclusion":"grounded"}')
    result = await gateway.complete_structured(
        system="bounded",
        user="evidence",
        schema_name="result",
        schema={"type": "object"},
    )
    assert json.loads(result.content) == {"conclusion": "grounded"}
    assert result.provider_adapter == "fake"
    assert result.endpoint_host == "fake.invalid"
    assert gateway.calls[0]["schema_name"] == "result"


def test_context_budget_accounts_for_complete_serialized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent_context, "AGENT_CONTEXT_MAX_CHARS", 70)
    monkeypatch.setattr(agent_context, "AGENT_CONTEXT_SECTION_MAX_CHARS", 70)
    rendered, truncations = agent_context._enforce_budgets(
        {
            "first": [{"value": "a" * 20}],
            "second": [{"value": "b" * 80}],
            "third": [{"value": "c" * 20}],
        }
    )
    assert agent_context._serialized_size(rendered) <= 70
    assert truncations["second"] == 1
    assert truncations["third"] == 1


def test_tool_result_boundary_redacts_and_bounds_nested_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.domain.agent.tools.AGENT_TOOL_RESULT_MAX_CHARS", 240)
    result = _bounded_result(
        {
            "state": "available",
            "nested": {"api_key": "do-not-return", "body": "x" * 500},
            "artifact_refs": [
                {"kind": "snapshot", "id": str(index)} for index in range(20)
            ],
        },
        maximum_items=5,
    )
    serialized = json.dumps(result)
    assert "do-not-return" not in serialized
    assert _serialized_chars(result) <= 240
    assert result["truncated"] is True
