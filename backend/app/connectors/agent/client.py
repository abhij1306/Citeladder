"""Default-agent client (OpenAI-compatible ``/chat/completions``).

The app-level general model that powers assisted features (prompt generation
now; content generation later). Configured entirely from env
(``config/agent.py``) — NVIDIA by default, but any OpenAI-compatible endpoint
works. This is the application-model boundary for non-measurement AI calls; it
is NOT a measurement engine and NOT a BYOK connection:
measurement engines are only ever measured (roadmap non-goal), and BYOK keys
belong to ``ProviderConnection``.

Secret handling mirrors the answer-engine adapters (invariant 6 spirit): the
key is sent only as a Bearer header, never logged, never echoed into any DTO,
snapshot, or error message.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Mapping
from typing import Any

import httpx

from app.connectors.agent.gateway import ModelCapabilities, ModelResult
from app.connectors.agent.json_utils import strip_json_fence
from app.connectors.answer_engines.errors import (
    ProviderError,
    classify_provider_status,
    parse_retry_after,
)
from app.core.config.agent import (
    STRUCTURED_OUTPUT_JSON_SCHEMA,
    DefaultAgentSettings,
    default_agent_settings,
)
from app.core.config.provider_catalog import (
    ERROR_CONNECTION,
    ERROR_PARSE,
    ERROR_TIMEOUT,
)

logger = logging.getLogger(__name__)


class AgentNotConfiguredError(RuntimeError):
    """Raised when no default-agent API key is configured in the environment."""


class DefaultAgentClient:
    """Thin JSON-mode chat client over an OpenAI-compatible endpoint."""

    def __init__(
        self,
        settings: DefaultAgentSettings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings or default_agent_settings
        self._transport = transport
        if not self._settings.configured:
            raise AgentNotConfiguredError(
                "No default agent API key configured "
                "(set DEFAULT_AGENT_API_KEY or the key for the configured provider)"
            )

    @property
    def adapter_name(self) -> str:
        return "openai_compatible"

    @property
    def model(self) -> str:
        return self._settings.model

    @property
    def base_url_host(self) -> str:
        """Credential-free endpoint host, safe for provenance records."""
        return httpx.URL(self._settings.base_url).host or ""

    def validate_configuration(self) -> None:
        """Fail early before a task is persisted or sent to a provider."""
        if not self._settings.configured:
            raise AgentNotConfiguredError("Default agent configuration is incomplete")

    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(
            structured_output=True,
            native_tool_calling=False,
            context_limit=self._settings.context_limit,
            output_limit=self._settings.max_output_tokens,
            streaming=False,
            usage_reporting=True,
            safety_metadata=False,
        )

    async def complete_text(self, *, system: str, user: str) -> ModelResult:
        return await self._complete_result(
            system=system, user=user, response_format=None
        )

    async def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> ModelResult:
        schema_payload = dict(schema)
        response_format: Mapping[str, Any]
        if self._settings.structured_output_mode == STRUCTURED_OUTPUT_JSON_SCHEMA:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema_payload,
                },
            }
        else:
            response_format = {"type": "json_object"}
        return await self._complete_result(
            system=system,
            user=(
                f"{user}\n\nReturn JSON that matches the {schema_name} "
                "schema exactly:\n"
                + json.dumps(schema_payload, ensure_ascii=False, separators=(",", ":"))
            ),
            response_format=response_format,
        )

    async def complete_json(self, *, system: str, user: str) -> str:
        """Run one JSON-mode completion and return normalized JSON content."""
        raw = await self._complete(
            system=system,
            user=user,
            response_format={"type": "json_object"},
        )
        return strip_json_fence(raw)

    async def complete_structured_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        schema: Mapping[str, Any],
    ) -> str:
        """Return JSON constrained to a caller-owned JSON Schema.

        The schema stays at the feature boundary; this shared transport never
        embeds feature-specific shapes. It is also included in the prompt
        because some OpenAI-compatible hosts accept but do not enforce the
        standard ``json_schema`` response format.
        """
        schema_payload = dict(schema)
        response_format: Mapping[str, Any]
        if self._settings.structured_output_mode == STRUCTURED_OUTPUT_JSON_SCHEMA:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": schema_payload,
                },
            }
        else:
            response_format = {"type": "json_object"}
        raw = await self._complete(
            system=system,
            user=(
                f"{user}\n\nReturn JSON that matches the {schema_name} schema "
                "exactly:\n"
                + json.dumps(schema_payload, ensure_ascii=False, separators=(",", ":"))
            ),
            response_format=response_format,
        )
        return strip_json_fence(raw)

    async def _complete(
        self,
        *,
        system: str,
        user: str,
        response_format: Mapping[str, Any] | None,
    ) -> str:
        """Run one OpenAI-compatible completion without logging prompt data."""
        result = await self._complete_result(
            system=system, user=user, response_format=response_format
        )
        return result.content

    async def _complete_result(
        self,
        *,
        system: str,
        user: str,
        response_format: Mapping[str, Any] | None,
    ) -> ModelResult:
        settings = self._settings
        payload: dict[str, Any] = {
            "model": settings.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": settings.max_output_tokens,
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        headers = {
            "Authorization": f"Bearer {settings.resolved_api_key}",
            "Content-Type": "application/json",
        }
        url = settings.base_url.rstrip("/") + "/chat/completions"
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(
                timeout=settings.timeout_seconds,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(url, json=payload, headers=headers)
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout) as exc:
            raise ProviderError(
                f"Default agent request timed out: {exc}",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Default agent connection error: {exc}",
                error_code=ERROR_CONNECTION,
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            # Status + reason token only — never the body (could echo input).
            logger.warning(
                "default agent call failed",
                extra={"status": response.status_code, "error_code": error_code},
            )
            raise ProviderError(
                f"Default agent returned HTTP {response.status_code}",
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
        except (ValueError, LookupError, TypeError) as exc:
            raise ProviderError(
                f"Default agent returned an unparseable response: {type(exc).__name__}",
                error_code=ERROR_PARSE,
                retryable=False,
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderError(
                "Default agent returned empty content",
                error_code=ERROR_PARSE,
                retryable=False,
            )
        logger.info(
            "default agent call ok",
            extra={"latency_ms": latency_ms, "model": settings.model},
        )
        usage = self.normalize_usage(body.get("usage"))
        return ModelResult(
            content=content,
            provider_adapter="openai_compatible",
            endpoint_host=self.base_url_host,
            requested_model=settings.model,
            returned_model=str(body.get("model") or settings.model),
            finish_status=str(choice.get("finish_reason") or "unknown"),
            usage=usage,
            latency_ms=latency_ms,
        )

    @staticmethod
    def normalize_usage(value: object) -> dict[str, int]:
        if not isinstance(value, Mapping):
            return {}
        aliases = {
            "input_tokens": ("input_tokens", "prompt_tokens"),
            "output_tokens": ("output_tokens", "completion_tokens"),
            "total_tokens": ("total_tokens",),
        }
        normalized: dict[str, int] = {}
        for target, keys in aliases.items():
            for key in keys:
                raw = value.get(key)
                if isinstance(raw, int) and raw >= 0:
                    normalized[target] = raw
                    break
        return normalized

    @staticmethod
    def classify_error(exc: Exception) -> dict[str, Any]:
        return {
            "code": str(getattr(exc, "error_code", ERROR_CONNECTION)),
            "retryable": bool(getattr(exc, "retryable", False)),
        }
