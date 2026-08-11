from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.connectors.agent.gateway import FakeModelGateway
from app.core.config.agent import (
    AGENT_TASK_POLICIES,
    TOOL_KIND_AUTOMATIC,
    DefaultAgentSettings,
)
from app.domain.agent import context as agent_context
from app.domain.agent import service as agent_service
from app.domain.agent.service import (
    _build_plan,
    _public_narrative_text,
    _validate_result,
)
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


def test_ranked_opportunity_budget_keeps_actionable_roadmap_items() -> None:
    definition = TOOL_DEFINITIONS["opportunities.read_ranked"]
    items = [
        {
            "id": str(uuid.uuid4()),
            "rank": rank,
            "priority_score": 100 - rank,
            "severity": "high",
            "type": "site",
            "title": f"Action {rank}",
            "remediation": "Make the evidence-backed change and measure it.",
            "target_key": f"target-{rank}",
            "target_url": f"https://example.com/{rank}",
        }
        for rank in range(1, definition.maximum_result_items + 1)
    ]

    result = _bounded_result(
        {
            "state": "available",
            "items": items,
            "truncated": True,
            "artifact_refs": [
                {"kind": "opportunity", "id": item["id"]} for item in items
            ],
        },
        maximum_items=definition.maximum_result_items,
    )

    assert definition.maximum_result_items == 10
    assert result["items"] == items
    assert "reason" not in result
    assert len(agent_service._roadmap_view(result)["items"]) == 10


def test_public_narrative_rejects_internal_ids() -> None:
    assert _public_narrative_text("Improve the pricing page.") == (
        "Improve the pricing page."
    )
    assert (
        _public_narrative_text(
            "Use evidence 28f6952b-1483-4a2d-b53a-cbd37f9f1f4a first."
        )
        == ""
    )


@pytest.mark.parametrize("invalid_limit", [0, -1])
def test_agent_output_limit_must_be_positive(
    monkeypatch: pytest.MonkeyPatch, invalid_limit: int
) -> None:
    monkeypatch.setenv("DEFAULT_AGENT_MAX_OUTPUT_TOKENS", str(invalid_limit))
    with pytest.raises(ValidationError):
        DefaultAgentSettings(_env_file=None)


def test_context_text_redacts_embedded_secret_assignments() -> None:
    value = agent_context._redacted_text(
        'Keep this title; api_key="do-not-store"; remediation follows.'
    )
    assert "do-not-store" not in value
    assert "api_key=[redacted]" in value


def test_tool_redaction_uses_sensitive_key_boundaries() -> None:
    result = _bounded_result(
        {
            "total_tokens": 10,
            "tokenizer": "v1",
            "credential_source": "workspace",
            "access_token": "hidden",
            "api_key": "hidden-too",
            "access-token": "hidden-three",
            "apiKey": "hidden-four",
        },
        maximum_items=10,
    )
    assert result["total_tokens"] == 10
    assert result["tokenizer"] == "v1"
    assert result["credential_source"] == "workspace"
    assert result["access_token"] == "[redacted]"
    assert result["api_key"] == "[redacted]"
    assert result["access-token"] == "[redacted]"
    assert result["apiKey"] == "[redacted]"


@pytest.mark.asyncio
async def test_execution_timeout_rolls_back_before_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = AsyncMock()
    session.scalar.return_value = None

    async def timeout(*_args: object, **_kwargs: object) -> None:
        raise TimeoutError

    monkeypatch.setattr(agent_service, "_execute_available_steps", timeout)
    await agent_service._execute_with_timeout(
        session,
        run=SimpleNamespace(id=uuid.uuid4()),
        user_id=uuid.uuid4(),
        gateway=None,
    )
    session.rollback.assert_awaited_once_with()
    session.scalar.assert_awaited_once()
