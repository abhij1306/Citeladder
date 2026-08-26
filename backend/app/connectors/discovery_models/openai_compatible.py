"""Provider-neutral OpenAI-compatible Content generation transport."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.connectors.answer_engines.errors import (
    ProviderError,
    classify_provider_status,
    parse_retry_after,
)
from app.connectors.discovery_models.contracts import (
    DiscoveryRequest,
    DiscoveryResponse,
)
from app.core.config.provider_catalog import (
    ERROR_AUTH,
    ERROR_CONNECTION,
    ERROR_PARSE,
    ERROR_TIMEOUT,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleDiscoveryClient:
    """Content client parameterized by config-owned provider identity."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        endpoint: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError(
                f"{provider} API key is not configured",
                error_code=ERROR_AUTH,
                retryable=False,
            )
        self.provider = provider
        self._api_key = api_key
        self._endpoint = endpoint
        self._transport = transport

    async def generate(self, request: DiscoveryRequest) -> DiscoveryResponse:
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": list(request.messages),
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=request.timeout_seconds,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    self._endpoint, json=payload, headers=headers
                )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise ProviderError(
                f"{self.provider} request timed out: {type(exc).__name__}",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"{self.provider} connection error: {type(exc).__name__}",
                error_code=ERROR_CONNECTION,
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            logger.warning(
                "content model call failed",
                extra={
                    "provider": self.provider,
                    "status": response.status_code,
                    "error_code": error_code,
                },
            )
            raise ProviderError(
                f"{self.provider} returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=parse_retry_after(
                    response.headers.get("retry-after")
                ),
            )
        try:
            body = response.json()
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.provider} returned an invalid completion",
                error_code=ERROR_PARSE,
                retryable=False,
            ) from exc
        if not isinstance(content, str):
            raise ProviderError(
                f"{self.provider} message content is not a string",
                error_code=ERROR_PARSE,
                retryable=False,
            )
        usage = body.get("usage") if isinstance(body, dict) else None
        return DiscoveryResponse(
            provider=self.provider,
            requested_model=request.model,
            returned_model=str(body.get("model") or request.model),
            output_text=content,
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=dict(usage) if isinstance(usage, dict) else {},
            latency_ms=latency_ms,
        )
