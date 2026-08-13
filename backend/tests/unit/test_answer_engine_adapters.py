"""Answer-engine adapter unit tests for the active direct transports.

Covers the adapter acceptance for the v2 direct-provider matrix: OpenAI direct
(``openai`` transport → ChatGPT, Responses API + web-search grounding), Gemini
direct (``google``), and Claude direct (``anthropic``). Each parser assertion
checks the recorded provenance triple — ``logical_engine`` +
``transport_provider`` + ``transport_model`` (invariant 10). HTTP transports are
mocked; no real API spend. Retired transports have no adapter; their rejection
is covered by the factory/worker/API tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.connectors.answer_engines.anthropic import (
    AnthropicAnswerEngineAdapter,
    _raise_for_search_error,
)
from app.connectors.answer_engines.anthropic import (
    _payload as anthropic_payload,
)
from app.connectors.answer_engines.anthropic_parser import parse_anthropic_message
from app.connectors.answer_engines.contracts import AnswerEngineRequest
from app.connectors.answer_engines.errors import ProviderError, safe_error_detail
from app.connectors.answer_engines.gemini import GeminiAnswerEngineAdapter
from app.connectors.answer_engines.gemini_parser import parse_interaction
from app.connectors.answer_engines.openai import OpenAIAnswerEngineAdapter
from app.connectors.answer_engines.openai import _payload as openai_payload
from app.connectors.answer_engines.openai_parser import parse_openai_response
from app.core.config.provider_catalog import measurement_route

_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures"
_CHATGPT_BENCHMARK_MODEL = measurement_route("chatgpt", "benchmark").transport_model
_CLAUDE_BENCHMARK_MODEL = measurement_route("claude", "benchmark").transport_model
_GEMINI_BENCHMARK_MODEL = measurement_route("gemini", "benchmark").transport_model


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURE_DIR / name).read_text())


def _mock_transport(payload: dict, status_code: int = 200) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Gemini direct (google transport) — NEW coverage
# ---------------------------------------------------------------------------
_GEMINI_GROUNDED = {
    "id": "int_1",
    "status": "completed",
    "model": "gemini-flash-latest",
    "usage": {"total_tokens": 120},
    "steps": [
        {"type": "thought", "signature": "drop-me"},
        {
            "type": "google_search_call",
            "id": "call_1",
            "arguments": {"queries": ["best running shoes australia"]},
        },
        {"type": "google_search_result"},
        {
            "type": "model_output",
            "content": [
                {
                    "type": "text",
                    "text": "Brooks is a strong pick for road running.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://grounding-api-redirect/xyz",
                            "title": "runnersworld.com",
                            "start_index": 0,
                            "end_index": 6,
                        }
                    ],
                }
            ],
        },
    ],
}


def test_gemini_parser_grounding_citations_and_provenance() -> None:
    result = parse_interaction(
        _GEMINI_GROUNDED,
        logical_engine="gemini",
        transport_provider="google",
        model="gemini-flash-latest",
        latency_ms=42,
    )
    # Provenance triple (invariant 10).
    assert result.logical_engine == "gemini"
    assert result.transport_provider == "google"
    assert result.transport_model == "gemini-flash-latest"
    # Grounding + citation parsing.
    assert result.search_used is True
    assert len(result.search_events) == 1
    assert result.search_events[0].query == "best running shoes australia"
    assert len(result.citations) == 1
    citation = result.citations[0]
    # Domain is derived from the title (the url is a redirect).
    assert citation.domain == "runnersworld.com"
    assert citation.cited_text == "Brooks"
    # Thought steps are dropped from the answer text.
    assert result.answer_text == "Brooks is a strong pick for road running."


def test_gemini_parser_no_search_is_valid_result() -> None:
    payload = {
        "model": "gemini-flash-latest",
        "steps": [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "From memory: A, B."}],
            }
        ],
    }
    result = parse_interaction(
        payload,
        logical_engine="gemini",
        transport_provider="google",
        model="gemini-flash-latest",
        latency_ms=1,
    )
    assert result.search_used is False
    assert result.citations == ()
    assert result.answer_text == "From memory: A, B."


def test_gemini_parser_queries_as_bare_string_not_split_per_char() -> None:
    payload = {
        "model": "gemini-flash-latest",
        "steps": [
            {
                "type": "google_search_call",
                "id": "gs_1",
                # A malformed payload: queries is a bare string, and args is
                # exercised as a dict. Must not split per-character or crash.
                "arguments": {"queries": "nike running shoes"},
            },
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "Answer."}],
            },
        ],
    }
    result = parse_interaction(
        payload,
        logical_engine="gemini",
        transport_provider="google",
        model="gemini-flash-latest",
        latency_ms=1,
    )
    # The bare string yields no per-character queries.
    assert all(len(e.query) != 1 for e in result.search_events)
    assert not any(e.query for e in result.search_events)


def test_gemini_parser_tolerates_non_dict_arguments() -> None:
    payload = {
        "model": "gemini-flash-latest",
        "steps": [
            {"type": "google_search_call", "id": "gs_1", "arguments": "oops"},
            {
                "type": "model_output",
                "content": [{"type": "text", "text": "Answer."}],
            },
        ],
    }
    # Must not raise on a non-dict arguments field.
    result = parse_interaction(
        payload,
        logical_engine="gemini",
        transport_provider="google",
        model="gemini-flash-latest",
        latency_ms=1,
    )
    assert result.answer_text == "Answer."


async def test_gemini_adapter_executes_and_records_provenance() -> None:
    adapter = GeminiAnswerEngineAdapter(api_key="secret-google-key")
    transport = _mock_transport(_GEMINI_GROUNDED)
    request = AnswerEngineRequest(
        prompt="running shoes",
        system_instruction="",
        model=_GEMINI_BENCHMARK_MODEL,
        timeout_seconds=5,
        retrieval_enabled=True,
        max_output_tokens=4096,
        reasoning_effort="minimal",
    )
    adapter = GeminiAnswerEngineAdapter(
        api_key="k", client=httpx.AsyncClient(transport=transport)
    )
    result = await adapter.execute(request)
    assert result.transport_provider == "google"
    assert result.logical_engine == "gemini"
    assert result.search_used is True


async def test_gemini_adapter_maps_http_error() -> None:
    transport = _mock_transport({"error": {"status": "RESOURCE_EXHAUSTED"}}, 429)
    adapter = GeminiAnswerEngineAdapter(
        api_key="k", client=httpx.AsyncClient(transport=transport)
    )
    with pytest.raises(ProviderError) as excinfo:
        await adapter.execute(
            AnswerEngineRequest(
                prompt="x",
                system_instruction="",
                model=measurement_route("gemini", "pulse").transport_model,
                timeout_seconds=5,
                retrieval_enabled=False,
                max_output_tokens=600,
                reasoning_effort="minimal",
            )
        )
    assert excinfo.value.error_code == "rate_limit"
    assert excinfo.value.retryable is True


def test_gemini_adapter_requires_key() -> None:
    with pytest.raises(ProviderError) as excinfo:
        GeminiAnswerEngineAdapter(api_key="")
    assert excinfo.value.error_code == "auth_failure"


# ---------------------------------------------------------------------------
# Claude direct (anthropic transport)
# ---------------------------------------------------------------------------
def test_anthropic_payload_uses_native_web_search_and_top_level_system() -> None:
    request = AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model=_CLAUDE_BENCHMARK_MODEL,
        timeout_seconds=30,
        retrieval_enabled=True,
        max_output_tokens=4096,
        reasoning_effort="low",
    )
    payload = anthropic_payload(request, country_code="AU")
    assert payload["system"] == "Answer for Australia."
    assert payload["messages"] == [{"role": "user", "content": "cheap baby clothes"}]
    tool = payload["tools"][0]
    assert tool["type"] == "web_search_20250305"
    assert tool["name"] == "web_search"
    assert tool["user_location"] == {"type": "approximate", "country": "AU"}


def test_anthropic_payload_omits_system_and_location_when_absent() -> None:
    request = AnswerEngineRequest(
        prompt="school uniforms",
        system_instruction="",
        model=_CLAUDE_BENCHMARK_MODEL,
        timeout_seconds=30,
        retrieval_enabled=True,
        max_output_tokens=4096,
        reasoning_effort="low",
    )
    payload = anthropic_payload(request, country_code="")
    assert "system" not in payload
    assert "user_location" not in payload["tools"][0]


def test_anthropic_parser_extracts_answer_citations_and_provenance() -> None:
    payload = {
        "id": "msg_1",
        "type": "message",
        "model": "claude-sonnet-4-6",
        "stop_reason": "end_turn",
        "content": [
            {"type": "text", "text": "Let me search."},
            {
                "type": "server_tool_use",
                "id": "srvtoolu_1",
                "name": "web_search",
                "input": {"query": "affordable baby clothes australia"},
            },
            {
                "type": "text",
                "text": "Best&Less is a great option.",
                "citations": [
                    {
                        "type": "web_search_result_location",
                        "url": "https://www.bestandless.com.au/baby",
                        "title": "Best&Less baby",
                        "cited_text": "Best&Less baby clothing from $5",
                    }
                ],
            },
        ],
        "usage": {
            "input_tokens": 40,
            "output_tokens": 60,
            "server_tool_use": {"web_search_requests": 1},
        },
    }
    result = parse_anthropic_message(
        payload,
        logical_engine="claude",
        transport_provider="anthropic",
        requested_model="claude-sonnet-4-6",
        latency_ms=12,
    )
    assert result.logical_engine == "claude"
    assert result.transport_provider == "anthropic"
    assert result.transport_model == "claude-sonnet-4-6"
    assert result.answer_text == "Let me search.\n\nBest&Less is a great option."
    assert result.search_used is True
    assert result.search_events[0].query == "affordable baby clothes australia"
    assert result.provider_metadata["query_text_available"] is True
    assert result.citations[0].domain == "bestandless.com.au"
    assert result.citations[0].cited_text == "Best&Less baby clothing from $5"
    assert result.normalized_usage.total_tokens == 100
    assert result.normalized_usage.web_search_requests == 1


def test_anthropic_safe_error_detail_extracts_type_and_message() -> None:
    body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the API.",
        },
    }
    assert safe_error_detail(body) == (
        "invalid_request_error: Your credit balance is too low to access the API."
    )
    # Malformed / empty bodies degrade to an empty string, never raise.
    assert safe_error_detail({}) == ""
    assert safe_error_detail({"error": "not-a-dict"}) == ""
    # Non-dict top-level payloads degrade the same way.
    assert safe_error_detail([]) == ""
    assert safe_error_detail("oops") == ""
    # Oversized messages are length-capped.
    long_body = {"error": {"type": "api_error", "message": "x" * 10_000}}
    assert len(safe_error_detail(long_body)) < 300


async def test_anthropic_http_error_surfaces_safe_detail() -> None:
    error_body = {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "Your credit balance is too low to access the API.",
        },
    }
    transport = _mock_transport(error_body, status_code=400)
    adapter = AnthropicAnswerEngineAdapter(
        api_key="secret-anthropic-key",
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(ProviderError) as excinfo:
        await adapter.execute(
            AnswerEngineRequest(
                prompt="x",
                system_instruction="",
                model=_CLAUDE_BENCHMARK_MODEL,
                timeout_seconds=5,
                retrieval_enabled=True,
                max_output_tokens=4096,
                reasoning_effort="low",
            )
        )
    assert "HTTP 400" in str(excinfo.value)
    assert "credit balance is too low" in str(excinfo.value)
    assert excinfo.value.retryable is False


def test_anthropic_search_error_raises_only_for_retryable_codes() -> None:
    rate_limited = {
        "content": [
            {
                "type": "web_search_tool_result",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "too_many_requests",
                },
            }
        ]
    }
    with pytest.raises(ProviderError) as excinfo:
        _raise_for_search_error(rate_limited)
    assert excinfo.value.retryable is True

    capped = {
        "content": [
            {
                "type": "web_search_tool_result",
                "content": {
                    "type": "web_search_tool_result_error",
                    "error_code": "max_uses_exceeded",
                },
            }
        ]
    }
    _raise_for_search_error(capped)  # must not raise


async def test_anthropic_adapter_executes_and_records_provenance() -> None:
    payload = {
        "id": "msg_2",
        "model": "claude-sonnet-4-6",
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    transport = _mock_transport(payload)
    adapter = AnthropicAnswerEngineAdapter(
        api_key="secret-anthropic-key",
        client=httpx.AsyncClient(transport=transport),
    )
    result = await adapter.execute(
        AnswerEngineRequest(
            prompt="x",
            system_instruction="",
            model=_CLAUDE_BENCHMARK_MODEL,
            timeout_seconds=5,
            retrieval_enabled=True,
            max_output_tokens=4096,
            reasoning_effort="low",
        )
    )
    assert result.transport_provider == "anthropic"
    assert result.logical_engine == "claude"
    assert result.transport_model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# OpenAI direct (openai transport → chatgpt) — v2 direct-provider matrix
# ---------------------------------------------------------------------------
def test_openai_payload_is_stateless_brand_free_with_country() -> None:
    request = AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model=_CHATGPT_BENCHMARK_MODEL,
        timeout_seconds=30,
        retrieval_enabled=True,
        max_output_tokens=4096,
        reasoning_effort="none",
    )
    payload = openai_payload(request, country_code="AU")
    # Only the user prompt goes in ``input``; no brand/competitor/domain list.
    assert payload["input"] == "cheap baby clothes"
    assert payload["instructions"] == "Answer for Australia."
    assert payload["model"] == _CHATGPT_BENCHMARK_MODEL
    assert payload["store"] is False
    assert "max_output_tokens" in payload
    tool = payload["tools"][0]
    assert tool["type"] == "web_search"
    assert tool["user_location"] == {"type": "approximate", "country": "AU"}
    # The request body must never carry a credential.
    assert "api_key" not in payload
    assert "Authorization" not in payload


def test_openai_payload_omits_instructions_and_location_when_absent() -> None:
    request = AnswerEngineRequest(
        prompt="school uniforms",
        system_instruction="",
        model=_CHATGPT_BENCHMARK_MODEL,
        timeout_seconds=30,
        retrieval_enabled=True,
        max_output_tokens=4096,
        reasoning_effort="none",
    )
    payload = openai_payload(request, country_code="")
    assert "instructions" not in payload
    assert "user_location" not in payload["tools"][0]


def test_openai_parser_grounded_fixture_provenance_and_citations() -> None:
    result = parse_openai_response(
        _load_fixture("openai_responses_grounded.json"),
        logical_engine="chatgpt",
        transport_provider="openai",
        requested_model="gpt-5.4",
        latency_ms=15,
    )
    # Provenance triple (invariant 10): chatgpt via openai.
    assert result.logical_engine == "chatgpt"
    assert result.transport_provider == "openai"
    assert result.transport_model == "gpt-5.4"
    assert result.search_used is True
    # Two search calls: one single query + one call with two queries → 3 events.
    assert len(result.search_events) == 3
    assert result.search_events[0].query == "affordable baby clothes australia"
    assert result.search_events[1].query == "cheap kids clothing sale"
    assert result.search_events[2].query == "best value baby onesies au"
    # The two-query call shares one call id / call_sequence.
    assert result.search_events[1].call_sequence == 1
    assert result.search_events[2].call_sequence == 1
    assert result.search_events[1].query_sequence == 0
    assert result.search_events[2].query_sequence == 1
    # Citation offsets → cited_text; domain normalized from the url host.
    citation = result.citations[0]
    assert citation.domain == "bestandless.com.au"
    assert citation.cited_text == "Best&Less"
    assert citation.start_index == 0
    assert citation.end_index == 9
    assert result.normalized_usage.web_search_requests == 2
    assert result.normalized_usage.total_tokens == 100


def test_openai_parser_no_search_fixture_is_valid_result() -> None:
    result = parse_openai_response(
        _load_fixture("openai_responses_no_search.json"),
        logical_engine="chatgpt",
        transport_provider="openai",
        requested_model="gpt-5.4",
        latency_ms=3,
    )
    assert result.search_used is False
    assert result.search_events == ()
    assert result.citations == ()
    assert result.answer_text == "From memory: options include A and B."


async def test_openai_http_error_surfaces_safe_detail() -> None:
    error_body = {
        "error": {
            "type": "insufficient_quota",
            "message": "You exceeded your current quota, please check your plan.",
        }
    }
    transport = _mock_transport(error_body, status_code=429)
    adapter = OpenAIAnswerEngineAdapter(
        api_key="secret-openai-key",
        client=httpx.AsyncClient(transport=transport),
    )
    with pytest.raises(ProviderError) as excinfo:
        await adapter.execute(
            AnswerEngineRequest(
                prompt="x",
                system_instruction="",
                model=_CHATGPT_BENCHMARK_MODEL,
                timeout_seconds=5,
                retrieval_enabled=True,
                max_output_tokens=4096,
                reasoning_effort="none",
            )
        )
    assert "HTTP 429" in str(excinfo.value)
    assert "exceeded your current quota" in str(excinfo.value)
    assert excinfo.value.retryable is True


def test_openai_parser_count_only_call_preserves_empty_query() -> None:
    payload = {
        "model": "gpt-5.4",
        "output": [
            {
                "type": "web_search_call",
                "id": "ws_1",
                "status": "completed",
                "action": {"type": "search"},
            },
            {
                "type": "message",
                "id": "msg_1",
                "content": [{"type": "output_text", "text": "Answer."}],
            },
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }
    result = parse_openai_response(
        payload,
        logical_engine="chatgpt",
        transport_provider="openai",
        requested_model="gpt-5.4",
        latency_ms=1,
    )
    # A search happened but no query text — count-only, never invented.
    assert result.search_used is True
    assert len(result.search_events) == 1
    assert result.search_events[0].query == ""
    assert result.normalized_usage.web_search_requests == 1
    assert result.provider_metadata["query_text_available"] is False


def test_openai_parser_drops_reasoning_and_redacts_metadata() -> None:
    result = parse_openai_response(
        _load_fixture("openai_responses_grounded.json"),
        logical_engine="chatgpt",
        transport_provider="openai",
        requested_model="gpt-5.4",
        latency_ms=1,
    )
    meta = result.provider_metadata
    # Reasoning content is never retained in the evidence envelope.
    for item in meta["evidence_items"]:
        assert item["type"] != "reasoning"
    # No credentials / raw headers / request echo in metadata.
    serialized = json.dumps(meta)
    assert "Authorization" not in serialized
    assert "Bearer" not in serialized
    assert "api_key" not in serialized


def test_openai_parser_prefers_provider_returned_model() -> None:
    payload = {
        "model": "gpt-5.4-2026",
        "output": [
            {
                "type": "message",
                "id": "m",
                "content": [{"type": "output_text", "text": "ok"}],
            }
        ],
    }
    result = parse_openai_response(
        payload,
        logical_engine="chatgpt",
        transport_provider="openai",
        requested_model="gpt-5.4",
        latency_ms=1,
    )
    assert result.transport_model == "gpt-5.4-2026"
