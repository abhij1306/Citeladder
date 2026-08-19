"""Gemini Interactions API adapter (Google Search grounding, transport ``google``).

Each call is a fresh, stateless Interactions request:
  * ``store=false`` and no ``previous_interaction_id`` — no account/chat memory.
  * The tracked brand/competitor list is NEVER placed in the request; it is used
    only during scoring, after generation (invariant 6). The system instruction
    is fixed and neutral.

The API key is supplied by the caller (resolved from the decrypted
``ProviderConnection`` at execution time) — never read from env. Ported from the
reference ``ai_visibility/gemini.py`` and adapted to the shared error type +
provenance triple.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
)
from app.connectors.answer_engines.errors import (
    ProviderError,
    classify_provider_status,
    parse_retry_after,
)
from app.connectors.answer_engines.gemini_parser import parse_interaction
from app.connectors.answer_engines.http_client import shared_client
from app.connectors.answer_engines.normalization import output_token_cap
from app.core.config.provider_catalog import (
    ENGINE_GEMINI,
    ERROR_AUTH,
    ERROR_CONNECTION,
    ERROR_TIMEOUT,
    ERROR_UNKNOWN,
    REASONING_EFFORT_LOW,
    REASONING_EFFORT_MINIMAL,
    TRANSPORT_GOOGLE,
    is_approved_model,
    provider_catalog_settings,
)

logger = logging.getLogger(__name__)


def _quota_detail(detail: object) -> list[str]:
    if not isinstance(detail, dict):
        return []
    parts: list[str] = []
    retry_delay = str(detail.get("retryDelay") or "").strip()
    if retry_delay:
        parts.append(f"retry={retry_delay}")
    violations = detail.get("violations")
    if not isinstance(violations, list):
        return parts
    for violation in violations:
        if not isinstance(violation, dict):
            continue
        metric = str(violation.get("quotaMetric") or "").strip()
        quota_id = str(violation.get("quotaId") or "").strip()
        if metric:
            parts.append(f"quota={metric}")
        if quota_id:
            parts.append(f"quota_id={quota_id}")
    return parts


def safe_quota_detail(payload: object) -> str:
    """Extract provider quota identifiers without retaining echoed request text."""
    if not isinstance(payload, dict):
        return ""
    error = payload.get("error")
    if not isinstance(error, dict):
        return ""
    parts = [str(error.get("status") or "").strip()]
    details = error.get("details")
    if not isinstance(details, list):
        return "; ".join(part for part in parts if part)
    for detail in details:
        parts.extend(_quota_detail(detail))
    return "; ".join(part for part in parts if part)


def _build_payload(request: AnswerEngineRequest) -> dict[str, Any]:
    """Build the Interactions body from the FROZEN request policy only.

    ``retrieval_enabled`` decides whether the ``google_search`` grounding tool
    is attached at all (a pulse call omits it entirely, which is what makes it
    cheap); ``max_output_tokens`` is the output cap, falling back to the
    configured catalog cap when unsupplied (invariant 1). Nothing is re-read
    from live settings that the request already froze (invariant 9).

    Each mode pins an exact catalog identity and its explicit thinking level.
    """
    if not is_approved_model(ENGINE_GEMINI, TRANSPORT_GOOGLE, request.model):
        raise ProviderError(
            "Gemini route requires an exact catalog model",
            error_code=ERROR_UNKNOWN,
            retryable=False,
        )
    return {
        "model": request.model,
        "input": request.prompt,
        "system_instruction": request.system_instruction,
        "store": False,
        # Frozen per-call output cap so one generation cannot run away.
        "max_output_tokens": output_token_cap(request),
        **_thinking_fields(request),
        **_grounding_fields(request),
    }


def _grounding_fields(request: AnswerEngineRequest) -> dict[str, Any]:
    """The grounding-tool field, or no field at all when retrieval is off.

    A pulse call must OMIT the tool key entirely rather than send an empty
    list — that omission is what keeps it cheap.
    """
    if not request.retrieval_enabled:
        return {}
    return {"tools": [{"type": "google_search"}]}


def _thinking_fields(request: AnswerEngineRequest) -> dict[str, Any]:
    if request.reasoning_effort not in {
        REASONING_EFFORT_MINIMAL,
        REASONING_EFFORT_LOW,
    }:
        return {}
    return {"generation_config": {"thinking_level": request.reasoning_effort}}


class GeminiAnswerEngineAdapter:
    """Direct Google Gemini adapter. Serves the ``gemini`` logical engine."""

    logical_engine = ENGINE_GEMINI
    transport_provider = TRANSPORT_GOOGLE

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ProviderError(
                "Gemini API key is not configured",
                error_code=ERROR_AUTH,
                retryable=False,
            )
        self._api_key = api_key
        self._url = base_url or provider_catalog_settings.google_interactions_url
        # Injected only by tests; production uses the per-loop pooled client.
        self._client = client

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        payload = _build_payload(request)
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }
        started = time.monotonic()
        client = self._client or shared_client()
        try:
            response = await client.post(
                self._url,
                json=payload,
                headers=headers,
                timeout=request.timeout_seconds,
            )
        except (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.PoolTimeout,
        ) as exc:
            raise ProviderError(
                f"Gemini request timed out: {exc}",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Gemini connection error: {exc}",
                error_code=ERROR_CONNECTION,
                retryable=True,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            error_code, retryable = classify_provider_status(response.status_code)
            retry_after = parse_retry_after(response.headers.get("retry-after"))
            # Never log the response body verbatim (could echo the request),
            # only the status and a short reason token.
            logger.warning(
                "gemini call failed",
                extra={
                    "status": response.status_code,
                    "error_code": error_code,
                },
            )
            try:
                safe_detail = safe_quota_detail(response.json())
            except ValueError:
                safe_detail = ""
            suffix = f" ({safe_detail})" if safe_detail else ""
            raise ProviderError(
                f"Gemini returned HTTP {response.status_code}{suffix}",
                error_code=error_code,
                retryable=retryable,
                retry_after_seconds=retry_after,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                f"Gemini returned non-JSON response: {exc}",
                error_code=ERROR_UNKNOWN,
                retryable=False,
            ) from exc

        return parse_interaction(
            data,
            logical_engine=self.logical_engine,
            transport_provider=self.transport_provider,
            model=request.model,
            latency_ms=latency_ms,
        )
