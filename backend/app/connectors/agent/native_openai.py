"""Native OpenAI Responses API adapter for the provider-neutral gateway."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.connectors.agent.client import AgentNotConfiguredError
from app.connectors.agent.gateway import ModelCapabilities, ModelResult
from app.connectors.agent.json_utils import strip_json_fence
from app.connectors.answer_engines.errors import (
    ProviderError,
    classify_provider_status,
    parse_retry_after,
)
from app.core.config.agent import DefaultAgentSettings, default_agent_settings
from app.core.config.provider_catalog import (
    ERROR_CONNECTION,
    ERROR_PARSE,
    ERROR_TIMEOUT,
)


class NativeOpenAIClient:
    """OpenAI-native `/responses` adapter with the same compatibility helpers."""

    def __init__(
        self,
        settings: DefaultAgentSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or default_agent_settings
        self._transport = transport
        if not self._settings.configured:
            raise AgentNotConfiguredError("Default agent configuration is incomplete")

    @property
    def adapter_name(self) -> str:
        return "openai_responses"

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def base_url_host(self) -> str:
        return httpx.URL(self._settings.base_url).host or ""

    def validate_configuration(self) -> None:
        error = _configuration_error(self._settings)
        if error:
            raise AgentNotConfiguredError(error)

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            native_tool_calling=True,
            context_limit=self._settings.context_limit,
            output_limit=self._settings.max_output_tokens,
            streaming=True,
            usage_reporting=True,
            safety_metadata=False,
        )

    async def complete_text(self, *, system: str, user: str) -> ModelResult:
        return await self._complete(system=system, user=user, text_format=None)

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> ModelResult:
        return await self._complete(
            system=system,
            user=user,
            text_format={
                "type": "json_schema",
                "name": schema_name,
                "strict": True,
                "schema": dict(schema),
            },
        )

    async def complete_json(self, *, system: str, user: str) -> str:
        result = await self.complete_text(system=system, user=user)
        return strip_json_fence(result.content)

    async def complete_structured_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> str:
        result = await self.complete_structured(
            system=system,
            user=user,
            schema_name=schema_name,
            schema=schema,
        )
        return strip_json_fence(result.content)

    async def _complete(
        self,
        *,
        system: str,
        user: str,
        text_format: Mapping[str, Any] | None,
    ) -> ModelResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self._settings.max_output_tokens,
        }
        if text_format is not None:
            payload["text"] = {"format": dict(text_format)}
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=self._settings.timeout_seconds, transport=self._transport
            ) as client:
                response = await client.post(
                    self._settings.base_url.rstrip("/") + "/responses",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._settings.resolved_api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise ProviderError(
                "Native OpenAI request timed out",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                "Native OpenAI connection error",
                error_code=ERROR_CONNECTION,
                retryable=True,
            ) from exc
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            raise ProviderError(
                f"Native OpenAI returned HTTP {response.status_code}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=parse_retry_after(
                    response.headers.get("retry-after")
                ),
            )
        try:
            body = response.json()
            content = _first_output_text(body)
        except (ValueError, LookupError, TypeError) as exc:
            raise ProviderError(
                "Native OpenAI returned an unparseable response",
                error_code=ERROR_PARSE,
                retryable=False,
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError(
                "Native OpenAI returned empty content",
                error_code=ERROR_PARSE,
                retryable=False,
            )
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        return ModelResult(
            content=content,
            provider_adapter="openai_responses",
            endpoint_host=self.base_url_host,
            requested_model=self.model,
            returned_model=str(body.get("model") or self.model),
            finish_status=str(body.get("status") or "unknown"),
            usage=self.normalize_usage(usage),
            latency_ms=int((time.monotonic() - started) * 1000),
            safety={},
        )

    @staticmethod
    def normalize_usage(value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        return {
            key: int(value[key])
            for key in ("input_tokens", "output_tokens", "total_tokens")
            if isinstance(value.get(key), int)
        }

    @staticmethod
    def classify_error(exc: Exception) -> dict[str, Any]:
        return {
            "code": str(getattr(exc, "error_code", ERROR_CONNECTION)),
            "retryable": bool(getattr(exc, "retryable", False)),
        }


def native_response_debug_shape(result: ModelResult) -> str:
    """Credential-free stable shape used by adapter calibration fixtures."""
    return json.dumps(
        {
            "adapter": result.provider_adapter,
            "model": result.returned_model,
            "finish_status": result.finish_status,
            "usage": result.usage,
        },
        sort_keys=True,
    )


def _first_output_text(body: object) -> str:
    if not isinstance(body, Mapping):
        raise TypeError("response body is not an object")
    output = body.get("output")
    if not isinstance(output, list):
        raise TypeError("response output is not a list")
    for item in output:
        if not isinstance(item, Mapping) or item.get("type") != "message":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, Mapping) and part.get("type") == "output_text":
                text = part.get("text")
                if isinstance(text, str):
                    return text
    raise LookupError("response has no output_text content")


def _configuration_error(settings: DefaultAgentSettings) -> str:
    if not settings.configured:
        return "Default agent configuration is incomplete"
    if settings.adapter != "openai_responses":
        return "Native OpenAI adapter is not selected"
    return ""
