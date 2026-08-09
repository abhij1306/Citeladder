from __future__ import annotations

import json

import httpx
import pytest

from app.connectors.agent.factory import create_model_gateway
from app.connectors.agent.native_openai import NativeOpenAIClient
from app.core.config.agent import DefaultAgentSettings


def _settings() -> DefaultAgentSettings:
    return DefaultAgentSettings(
        DEFAULT_AGENT_ADAPTER="openai_responses",
        DEFAULT_AGENT_API_KEY="native-key",
        DEFAULT_AGENT_BASE_URL="https://api.openai.test/v1",
        DEFAULT_AGENT_MODEL="gpt-test",
        DEFAULT_AGENT_MAX_OUTPUT_TOKENS=321,
    )


@pytest.mark.asyncio
async def test_native_adapter_uses_responses_contract_without_leaking_key() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-test-2026-08-01",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"ok":true}'}],
                    }
                ],
                "usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
            },
        )

    gateway = create_model_gateway(_settings(), transport=httpx.MockTransport(handler))
    assert isinstance(gateway, NativeOpenAIClient)
    result = await gateway.complete_structured(
        system="system",
        user="user",
        schema_name="fixture",
        schema={"type": "object", "additionalProperties": False},
    )
    assert captured["url"] == "https://api.openai.test/v1/responses"
    assert captured["authorization"] == "Bearer native-key"
    assert "native-key" not in json.dumps(captured["body"])
    assert captured["body"]["text"]["format"]["type"] == "json_schema"
    assert result.provider_adapter == "openai_responses"
    assert result.returned_model == "gpt-test-2026-08-01"
    assert result.usage["total_tokens"] == 7
