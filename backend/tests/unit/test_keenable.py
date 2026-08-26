"""Keenable transport tests use only an in-memory HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from app.connectors.answer_engines.errors import ProviderError
from app.connectors.keenable import KeenableClient
from app.core.config.provider_catalog import ERROR_PARSE, ERROR_RATE_LIMIT


def _client(handler) -> KeenableClient:
    return KeenableClient(
        api_key="keenable-test-key",
        base_url="https://mock.keenable.test",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


@pytest.mark.asyncio
async def test_search_uses_api_key_header_and_bounded_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["key"] = request.headers["x-api-key"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "Example",
                        "url": "https://example.com/about",
                        "snippet": "Evidence",
                    }
                ]
            },
        )

    response = await _client(handler).search(
        "example query", site="example.com", max_results=4, snippet_max_length=500
    )

    assert captured["path"] == "/v1/search"
    assert captured["key"] == "keenable-test-key"
    assert captured["body"] == {
        "query": "example query",
        "site": "example.com",
        "max_results": 4,
        "snippet_max_length": 500,
    }
    assert response.results[0].url == "https://example.com/about"
    assert "keenable-test-key" not in json.dumps(captured["body"])


@pytest.mark.asyncio
async def test_fetch_caps_content_and_accepts_nested_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/fetch"
        assert request.url.params["live"] == "true"
        return httpx.Response(
            200,
            json={
                "data": {
                    "url": "https://example.com",
                    "title": "Example",
                    "markdown": "abcdefgh",
                }
            },
        )

    response = await _client(handler).fetch(
        "https://example.com", live=True, max_chars=5
    )

    assert response.content == "abcde"
    assert response.live is True


@pytest.mark.asyncio
async def test_http_and_parse_errors_are_classified_without_secret() -> None:
    def rate_limited(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "3"})

    with pytest.raises(ProviderError) as excinfo:
        await _client(rate_limited).search(
            "query", max_results=1, snippet_max_length=100
        )
    assert excinfo.value.error_code == ERROR_RATE_LIMIT
    assert excinfo.value.retry_after_seconds == 3
    assert "keenable-test-key" not in str(excinfo.value)

    def malformed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"results": "not-a-list"})

    with pytest.raises(ProviderError) as excinfo:
        await _client(malformed).search("query", max_results=1, snippet_max_length=100)
    assert excinfo.value.error_code == ERROR_PARSE
