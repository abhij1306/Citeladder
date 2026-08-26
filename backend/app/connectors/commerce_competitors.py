"""Optional Tavily search transport; credentials never leave request headers."""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config.commerce_catalog import (
    COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT,
    commerce_settings,
)


class CompetitorProviderUnavailable(RuntimeError):
    pass


async def tavily_search(query: str, *, locale: str) -> list[dict[str, Any]]:
    if not commerce_settings.tavily_api_key:
        raise CompetitorProviderUnavailable("Tavily is not configured")
    payload = {
        "query": f"{query} {locale}".strip(),
        "search_depth": "basic",
        "max_results": COMMERCE_COMPETITOR_PROVIDER_RESULT_LIMIT,
        "include_answer": False,
        "include_raw_content": False,
    }
    headers = {"Authorization": f"Bearer {commerce_settings.tavily_api_key}"}
    async with httpx.AsyncClient(
        timeout=commerce_settings.tavily_timeout_seconds
    ) as client:
        response = await client.post(
            commerce_settings.tavily_endpoint, json=payload, headers=headers
        )
        response.raise_for_status()
        data = response.json()
    results = data.get("results") if isinstance(data, dict) else []
    if not isinstance(results, list):
        return []
    return [item for item in results if isinstance(item, dict)]
