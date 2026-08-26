"""Authenticated, bounded Keenable search/fetch transport."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.connectors.answer_engines.errors import (
    ProviderError,
    classify_provider_status,
    parse_retry_after,
)
from app.core.config.provider_catalog import (
    ERROR_CONNECTION,
    ERROR_PARSE,
    ERROR_TIMEOUT,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KeenableSearchResult:
    title: str
    url: str
    description: str = ""
    snippet: str = ""
    published_at: str = ""
    acquired_at: str = ""


@dataclass(frozen=True, slots=True)
class KeenableSearchResponse:
    results: tuple[KeenableSearchResult, ...]


@dataclass(frozen=True, slots=True)
class KeenableFetchResponse:
    url: str
    title: str
    content: str
    published_at: str = ""
    acquired_at: str = ""
    live: bool = False


class KeenableClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("Keenable API key is not configured")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._transport = transport

    async def search(
        self,
        query: str,
        *,
        site: str | None = None,
        max_results: int,
        snippet_max_length: int,
    ) -> KeenableSearchResponse:
        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "snippet_max_length": snippet_max_length,
        }
        if site:
            payload["site"] = site
        body = await self._request("POST", "/v1/search", json=payload)
        raw_results = body.get("results", body.get("data"))
        if not isinstance(raw_results, list):
            raise _parse_error("search response is missing results")
        results = tuple(
            result
            for item in raw_results
            if isinstance(item, dict) and (result := _search_result(item)) is not None
        )
        return KeenableSearchResponse(results=results)

    async def fetch(
        self, url: str, *, live: bool, max_chars: int
    ) -> KeenableFetchResponse:
        body = await self._request(
            "GET", "/v1/fetch", params={"url": url, "live": live, "max": max_chars}
        )
        nested = body.get("data")
        payload: dict[str, Any] = nested if isinstance(nested, dict) else body
        content = payload.get(
            "markdown", payload.get("content", payload.get("text", ""))
        )
        if not isinstance(content, str):
            raise _parse_error("fetch response content is not text")
        return KeenableFetchResponse(
            url=str(payload.get("url") or url),
            title=str(payload.get("title") or ""),
            content=content[:max_chars],
            published_at=_timestamp(payload.get("published_at")),
            acquired_at=_timestamp(payload.get("acquired_at")),
            live=live,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = {"X-API-Key": self._api_key, "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method, self._base_url + path, headers=headers, **kwargs
                )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise ProviderError(
                "Keenable request timed out",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Keenable connection error: {type(exc).__name__}",
                error_code=ERROR_CONNECTION,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            logger.warning(
                "keenable call failed",
                extra={"status": response.status_code, "error_code": error_code},
            )
            raise ProviderError(
                f"Keenable returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=parse_retry_after(
                    response.headers.get("retry-after")
                ),
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise _parse_error("Keenable returned non-JSON") from exc
        if not isinstance(body, dict):
            raise _parse_error("Keenable returned a non-object response")
        return body


def _search_result(item: dict[str, Any]) -> KeenableSearchResult | None:
    url = item.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    return KeenableSearchResult(
        title=str(item.get("title") or ""),
        url=url,
        description=str(item.get("description") or ""),
        snippet=str(item.get("snippet") or ""),
        published_at=_timestamp(item.get("published_at")),
        acquired_at=_timestamp(item.get("acquired_at")),
    )


def _timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _parse_error(message: str) -> ProviderError:
    return ProviderError(message, error_code=ERROR_PARSE, retryable=False)
