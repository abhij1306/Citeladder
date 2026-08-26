"""Discovery-model client factory (provider swap = one branch here).

Builds a fresh client per attempt, resolving the ``SecretStr`` key at call
time so a live env change applies and the key never lives on a long-lived
object. An unknown provider is an ``invalid_surface`` misconfiguration.
"""

from __future__ import annotations

import httpx

from app.connectors.answer_engines.errors import ProviderError
from app.connectors.discovery_models.contracts import DiscoveryModelClient
from app.connectors.discovery_models.openai_compatible import (
    OpenAICompatibleDiscoveryClient,
)
from app.core.config.content import CONTENT_KNOWN_PROVIDERS, content_settings
from app.core.config.provider_catalog import ERROR_INVALID_SURFACE


def build_discovery_client(
    *, transport: httpx.AsyncBaseTransport | None = None
) -> DiscoveryModelClient:
    """Build the configured content client (fresh per attempt).

    ``transport`` is a test seam (``httpx.MockTransport``); production passes
    nothing and the client uses the real network.
    """
    provider = content_settings.provider
    if provider in CONTENT_KNOWN_PROVIDERS:
        return OpenAICompatibleDiscoveryClient(
            provider=provider,
            api_key=content_settings.resolved_api_key,
            endpoint=content_settings.resolved_endpoint,
            transport=transport,
        )
    raise ProviderError(
        f"unknown content provider: {provider}",
        error_code=ERROR_INVALID_SURFACE,
        retryable=False,
    )
