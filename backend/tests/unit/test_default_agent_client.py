"""Application-model client tests (mock transport; no external model calls)."""

from __future__ import annotations

import json

import httpx
import pytest

from app.connectors.agent.client import AgentNotConfiguredError, DefaultAgentClient
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.agent import DefaultAgentSettings
from app.core.config.provider_catalog import ERROR_PARSE, ERROR_RATE_LIMIT


def _settings(*, api_key: str = "test-key") -> DefaultAgentSettings:
    return DefaultAgentSettings(
        DEFAULT_AGENT_API_KEY=api_key,
        DEFAULT_AGENT_BASE_URL="https://mock.nvidia.test/v1",
        DEFAULT_AGENT_MODEL="nvidia/test-model",
        DEFAULT_AGENT_TIMEOUT_SECONDS=5,
        DEFAULT_AGENT_MAX_OUTPUT_TOKENS=123,
    )


def _client(handler) -> DefaultAgentClient:
    return DefaultAgentClient(_settings(), transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_complete_json_uses_json_mode_without_key_in_body() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": '{"ok":true}'}}]}
        )

    result = await _client(handler).complete_json(system="system", user="user")

    assert result == '{"ok":true}'
    assert captured["authorization"] == "Bearer test-key"
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 123
    assert "test-key" not in json.dumps(body)


@pytest.mark.asyncio
async def test_complete_json_removes_markdown_fences() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '```json\n{"ok":true}\n```'}}]},
        )

    result = await _client(handler).complete_json(system="system", user="user")

    assert result == '{"ok":true}'


@pytest.mark.asyncio
async def test_complete_structured_json_requests_strict_schema() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    await _client(handler).complete_structured_json(
        system="system",
        user="user",
        schema_name="brand_research",
        schema={"type": "object", "additionalProperties": False},
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"] == {"type": "json_object"}
    assert "additionalProperties" in body["messages"][1]["content"]


@pytest.mark.asyncio
async def test_native_schema_mode_is_explicitly_configurable() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    settings = _settings().model_copy(update={"structured_output_mode": "json_schema"})
    client = DefaultAgentClient(settings, transport=httpx.MockTransport(handler))
    await client.complete_structured_json(
        system="system",
        user="user",
        schema_name="brand_research",
        schema={"type": "object", "additionalProperties": False},
    )

    body = captured["body"]
    assert isinstance(body, dict)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True


def test_gmi_rejects_unverified_strict_schema_mode() -> None:
    with pytest.raises(ValueError, match="strict json_schema"):
        DefaultAgentSettings(
            DEFAULT_AGENT_API_KEY="key",
            DEFAULT_AGENT_BASE_URL="https://api.gmi-serving.com/v1",
            DEFAULT_AGENT_MODEL="fixture-model",
            DEFAULT_AGENT_STRUCTURED_OUTPUT_MODE="json_schema",
        )


@pytest.mark.asyncio
async def test_errors_are_classified_and_do_not_expose_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "4"})

    with pytest.raises(ProviderError) as excinfo:
        await _client(handler).complete_json(system="s", user="u")

    assert excinfo.value.error_code == ERROR_RATE_LIMIT
    assert excinfo.value.retry_after_seconds == 4
    assert "test-key" not in str(excinfo.value)


@pytest.mark.asyncio
async def test_malformed_success_body_is_a_parse_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ProviderError) as excinfo:
        await _client(handler).complete_json(system="s", user="u")
    assert excinfo.value.error_code == ERROR_PARSE


def test_missing_key_is_rejected() -> None:
    with pytest.raises(AgentNotConfiguredError):
        DefaultAgentClient(_settings(api_key=""))


def test_mistral_configuration_is_entirely_env_driven(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFAULT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("DEFAULT_AGENT_BASE_URL", "https://api.mistral.ai/v1")
    monkeypatch.setenv("DEFAULT_AGENT_MODEL", "mistral-small-2603")
    monkeypatch.setenv("MISTRAL_API_KEY", "mistral-key")
    settings = DefaultAgentSettings(_env_file=None)
    assert settings.resolved_api_key == "mistral-key"
    assert settings.base_url == "https://api.mistral.ai/v1"
    assert settings.model == "mistral-small-2603"


def test_gmi_configuration_is_shared_by_default_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFAULT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("DEFAULT_AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("DEFAULT_AGENT_MODEL", raising=False)
    monkeypatch.setenv("GMICLOUD_API_KEY", "gmi-key")
    monkeypatch.setenv("GMICLOUD_BASE_URL", "https://api.gmi-serving.com/v1")
    monkeypatch.setenv("GMICLOUD_MODEL", "fixture-model")

    settings = DefaultAgentSettings(_env_file=None)

    assert settings.resolved_api_key == "gmi-key"
    assert settings.base_url == "https://api.gmi-serving.com/v1"
    assert settings.model == "fixture-model"


@pytest.mark.parametrize("missing", ["base_url", "model"])
def test_endpoint_and_model_are_required_for_configuration(missing: str) -> None:
    settings = _settings().model_copy(update={missing: ""})

    assert not settings.configured
    with pytest.raises(AgentNotConfiguredError):
        DefaultAgentClient(settings)


def test_matching_provider_key_precedes_generic_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_AGENT_API_KEY", "application-key")
    monkeypatch.setenv("DEFAULT_AGENT_BASE_URL", "https://api.mistral.ai/v1")
    monkeypatch.setenv("MISTRAL_API_KEY", "provider-key")
    settings = DefaultAgentSettings(_env_file=None)
    assert settings.resolved_api_key == "provider-key"


@pytest.mark.parametrize(
    ("base_url", "provider_variable", "expected"),
    [
        ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "nvidia-key"),
        ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "groq-key"),
        (
            "https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1",
            "AWS_BEARER_TOKEN_BEDROCK",
            "bedrock-key",
        ),
    ],
)
def test_provider_keys_are_selected_only_for_matching_hosts(
    monkeypatch: pytest.MonkeyPatch,
    base_url: str,
    provider_variable: str,
    expected: str,
) -> None:
    monkeypatch.delenv("DEFAULT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("DEFAULT_AGENT_BASE_URL", base_url)
    monkeypatch.setenv(provider_variable, expected)

    settings = DefaultAgentSettings(_env_file=None)

    assert settings.resolved_api_key == expected


def test_provider_key_does_not_leak_to_lookalike_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DEFAULT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("DEFAULT_AGENT_BASE_URL", "https://evilgroq.com/v1")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    settings = DefaultAgentSettings(_env_file=None)

    assert settings.resolved_api_key == ""
