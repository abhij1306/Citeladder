"""Greenfield route pricing and canonical usage projection contract."""

from __future__ import annotations

import uuid

from app.core.config.costs import (
    APPROVED_ROUTE_IDENTITIES,
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
    PROJECTION_STATUS_UNKNOWN,
    ROUTE_CHATGPT,
    ROUTE_CLAUDE,
    ROUTE_GEMINI,
    RouteIdentity,
    route_pricing_for,
)
from app.domain.audits.cost_projection import build_execution_cost_projection
from app.models.audit import RawResponseArtifact


def _artifact(
    usage: dict, route: RouteIdentity = ROUTE_CHATGPT
) -> RawResponseArtifact:
    return RawResponseArtifact(
        id=uuid.uuid4(),
        audit_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        logical_engine=route.logical_engine,
        transport_provider=route.transport_provider,
        transport_model=route.transport_model,
        answer_text="answer",
        usage=usage,
    )


def test_catalog_contains_only_three_exact_audit_routes() -> None:
    assert APPROVED_ROUTE_IDENTITIES == frozenset(
        {ROUTE_CHATGPT, ROUTE_CLAUDE, ROUTE_GEMINI}
    )
    assert ROUTE_CHATGPT.transport_model == "gpt-5.6-sol"
    assert ROUTE_CLAUDE.transport_model == "claude-sonnet-5"
    assert ROUTE_GEMINI.transport_model == "gemini-3.6-flash"


def test_unknown_official_price_lines_remain_null() -> None:
    pricing = route_pricing_for(ROUTE_CHATGPT, PRICING_CATALOG_VERSION)
    assert pricing is not None
    assert pricing.uncached_input_microusd_per_million is None
    assert pricing.output_microusd_per_million is None
    assert pricing.search_fee_microusd is None


def test_projection_accepts_only_canonical_usage_keys() -> None:
    pricing = route_pricing_for(ROUTE_CLAUDE, PRICING_CATALOG_VERSION)
    assert pricing is not None
    canonical = build_execution_cost_projection(
        _artifact(
            {"uncached_input_tokens": 1_000, "output_tokens": 500, "search_calls": 0},
            ROUTE_CLAUDE,
        ),
        pricing=pricing,
        formula_version=EXECUTION_COST_FORMULA_VERSION,
        attempt_count=1,
    )
    assert canonical.projection_status == PROJECTION_STATUS_COMPLETE
    assert canonical.projected_total_cost_microusd is not None

    retired_spellings = build_execution_cost_projection(
        _artifact(
            {"total_input_tokens": 1_000, "provider_cost_usd": 1.0},
            ROUTE_CLAUDE,
        ),
        pricing=pricing,
        formula_version=EXECUTION_COST_FORMULA_VERSION,
        attempt_count=1,
    )
    assert retired_spellings.projection_status == PROJECTION_STATUS_UNKNOWN
    assert retired_spellings.provider_reported_cost_microusd is None
