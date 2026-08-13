"""Deterministic provider cost and token-usage aggregation."""

from __future__ import annotations

from typing import Any

from app.core.config.costs import (
    APPROVED_ROUTE_IDENTITIES,
    MICRO_USD_PER_USD,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
    PROJECTION_STATUS_PARTIAL,
    PROJECTION_STATUS_UNKNOWN,
    TOKENS_PER_MILLION,
    route_pricing_for,
)


def reported_cost_usd(usage: dict[str, Any]) -> float | None:
    """Return one provider-reported canonical micro-USD value in dollars."""
    if usage.get("provider_cost_microusd") is None:
        return None
    try:
        return float(usage["provider_cost_microusd"]) / MICRO_USD_PER_USD
    except (TypeError, ValueError):
        return None


def provider_reported_cost(
    completed: list[dict[str, Any]],
) -> tuple[float | None, int]:
    reported = [
        value
        for execution in completed
        if (value := reported_cost_usd(execution.get("usage") or {})) is not None
    ]
    return (sum(reported) if reported else None, len(reported))


def token_line_estimate(tokens: int, rate: int | None) -> int | None:
    if tokens == 0:
        return 0
    return tokens * rate if rate is not None else None


def token_cost_estimate(
    token_usage: dict[str, int], pricing: Any | None
) -> float | None:
    token_lines = (
        token_line_estimate(
            token_usage["uncached_input_tokens"],
            pricing.uncached_input_microusd_per_million if pricing else None,
        ),
        token_line_estimate(
            token_usage["cached_input_tokens"],
            pricing.cached_input_microusd_per_million if pricing else None,
        ),
        token_line_estimate(
            token_usage["output_tokens"],
            pricing.output_microusd_per_million if pricing else None,
        ),
    )
    if any(line is None for line in token_lines):
        return None
    return sum(line for line in token_lines if line is not None) / (
        TOKENS_PER_MILLION * MICRO_USD_PER_USD
    )


def search_cost_estimate(
    grounded_requests: int, search_rate_microusd: int | None
) -> float | None:
    if not grounded_requests:
        return 0.0
    if search_rate_microusd is None:
        return None
    return grounded_requests * search_rate_microusd / MICRO_USD_PER_USD


def cost_estimate_status(known_lines: int) -> str:
    if known_lines == 2:
        return PROJECTION_STATUS_COMPLETE
    if known_lines:
        return PROJECTION_STATUS_PARTIAL
    return PROJECTION_STATUS_UNKNOWN


def paid_list_cost_estimate(
    token_usage: dict[str, int],
    config: Any,
    grounded_requests: int,
) -> tuple[float | None, float | None, str]:
    identity = next(
        (
            route
            for route in APPROVED_ROUTE_IDENTITIES
            if route.logical_engine == config.provider
            and route.transport_model == config.model
        ),
        None,
    )
    pricing = route_pricing_for(identity, PRICING_CATALOG_VERSION) if identity else None
    token_estimate = token_cost_estimate(token_usage, pricing)
    search_estimate = search_cost_estimate(
        grounded_requests, pricing.search_fee_microusd if pricing else None
    )
    known = sum(value is not None for value in (token_estimate, search_estimate))
    return token_estimate, search_estimate, cost_estimate_status(known)


def aggregate_cost(
    completed: list[dict[str, Any]],
    token_usage: dict[str, int],
    config: Any,
) -> dict[str, Any]:
    grounded_requests = sum(
        1 for execution in completed if execution["score"].get("search_used")
    )
    token_estimate, grounding_if_billable, cost_status = paid_list_cost_estimate(
        token_usage, config, grounded_requests
    )
    reported_cost, reported_executions = provider_reported_cost(completed)
    return {
        "currency": "USD",
        "grounded_requests": grounded_requests,
        "paid_list_token_estimate_usd": (
            round(token_estimate, 6) if token_estimate is not None else None
        ),
        "grounding_cost_if_billable_usd": (
            round(grounding_if_billable, 6)
            if grounding_if_billable is not None
            else None
        ),
        "cost_status": cost_status,
        "pricing_version": PRICING_CATALOG_VERSION,
        "provider_reported_cost_usd": (
            round(reported_cost, 6) if reported_cost is not None else None
        ),
        "provider_reported_cost_coverage": {
            "reported_executions": reported_executions,
            "total_executions": len(completed),
        },
        "free_allowance_applied": False,
        "note": (
            "Unknown official price lines remain null and are never inferred as zero."
        ),
    }


def usage_value(usage: dict[str, Any], key: str) -> int:
    try:
        return int(usage.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def aggregate_token_usage(completed: list[dict[str, Any]]) -> dict[str, int]:
    totals = {
        "uncached_input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    for execution in completed:
        usage = execution.get("usage") or {}
        for key in totals:
            totals[key] += usage_value(usage, key)
    return {
        "input_tokens": (
            totals["uncached_input_tokens"] + totals["cached_input_tokens"]
        ),
        **totals,
    }
