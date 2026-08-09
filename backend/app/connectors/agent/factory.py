"""Configuration-only selection of an approved model gateway adapter."""

from __future__ import annotations

import httpx

from app.connectors.agent.client import DefaultAgentClient
from app.connectors.agent.gateway import ModelGateway
from app.connectors.agent.native_openai import NativeOpenAIClient
from app.core.config.agent import DefaultAgentSettings, default_agent_settings


def create_model_gateway(
    settings: DefaultAgentSettings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ModelGateway:
    selected = settings or default_agent_settings
    if selected.adapter == "openai_responses":
        return NativeOpenAIClient(selected, transport=transport)
    return DefaultAgentClient(selected, transport=transport)
