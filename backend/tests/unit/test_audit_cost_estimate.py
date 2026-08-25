"""Unit tests for the provider-free audit cost estimator.

``app/domain/audits/cost_estimate.py`` sat at 25% line coverage: the arithmetic
a user sees before authorising spend, and — more importantly — the rules that
keep an UNVERIFIED rate from being quietly treated as zero, were almost entirely
unexecuted.

The estimator performs no I/O, so everything except the two persistence helpers
is exercised here directly against the real pricing catalogue. No fixtures, no
database, no network.
"""

from __future__ import annotations

import math

import pytest

from app.core.config.audits import audit_execution_policy
from app.core.config.costs import (
    ESTIMATE_SEARCH_CALLS,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
    PROJECTION_STATUS_PARTIAL,
    PROJECTION_STATUS_UNKNOWN,
    TOKENS_PER_MILLION,
    RouteIdentity,
    route_pricing_for,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    measurement_route,
)
from app.domain.audits.cost_estimate import (
    _combined_token_cost,
    _cost_status,
    _estimate_engine,
    _estimated_searches,
    _known_total,
    _line_cost,
    _overall_cost_status,
    _search_cost,
    _search_count,
)
from app.domain.audits.estimate_errors import AuditEstimateError
from app.domain.audits.schemas import AuditEngineEstimate


def _policy_with(**overrides: object):
    from dataclasses import replace

    return replace(audit_execution_policy(), **overrides)


def _engine_row(engine: str, status: str) -> AuditEngineEstimate:
    return AuditEngineEstimate(
        logical_engine=engine,
        transport_provider="p",
        transport_model="m",
        retrieval_enabled=False,
        prompt_count=1,
        repetition_count=1,
        execution_count=1,
        maximum_attempt_count=1,
        estimated_input_tokens=1,
        estimated_output_tokens=1,
        estimated_search_calls=None,
        estimated_token_cost_microusd=None,
        estimated_search_cost_microusd=None,
        estimated_total_cost_microusd=None,
        cost_status=status,
        pricing_version=PRICING_CATALOG_VERSION,
    )


# --- line arithmetic ------------------------------------------------------


def test_line_cost_is_none_when_the_rate_is_unverified() -> None:
    # A null rate is UNVERIFIED, never zero: coercing it would understate the
    # bill the user is being asked to authorise.
    assert _line_cost(1_000_000, None) is None


def test_line_cost_rounds_a_partial_million_up() -> None:
    # Rounding down would let a run cost more than the quote it was approved
    # against.
    assert _line_cost(1, 3_000_000) == math.ceil(3_000_000 / TOKENS_PER_MILLION)
    assert _line_cost(1_500_000, 3_000_000) == 4_500_000


def test_line_cost_of_zero_tokens_is_zero_not_none() -> None:
    assert _line_cost(0, 3_000_000) == 0


def test_combined_token_cost_is_none_when_either_side_is_unverified() -> None:
    assert _combined_token_cost(None, 5) is None
    assert _combined_token_cost(5, None) is None
    assert _combined_token_cost(2, 3) == 5


def test_search_cost_is_none_when_either_the_count_or_the_rate_is_missing() -> None:
    assert _search_cost(None, 10) is None
    assert _search_cost(4, None) is None
    assert _search_cost(4, 10) == 40


def test_known_total_sums_only_verified_lines() -> None:
    # A partially known estimate still reports the known portion; the status
    # field is what tells the caller it is incomplete.
    assert _known_total([3, None, 4]) == 7


def test_known_total_is_none_when_no_line_is_verified() -> None:
    assert _known_total([None, None]) is None
    assert _known_total([]) is None


# --- search-call estimates ------------------------------------------------


@pytest.mark.parametrize(
    ("engine", "per_execution"), sorted(ESTIMATE_SEARCH_CALLS.items())
)
def test_estimated_searches_scale_with_executions(
    engine: str, per_execution: int
) -> None:
    assert _estimated_searches(engine, 7) == 7 * per_execution


def test_an_engine_with_no_search_estimate_fails_closed() -> None:
    with pytest.raises(AuditEstimateError, match="Search-call estimate is unavailable"):
        _estimated_searches("perplexity", 1)


def test_search_count_is_none_when_retrieval_is_disabled() -> None:
    # Not zero: with retrieval off there is no search line at all, so it must
    # not appear as a verified zero-cost one.
    assert _search_count(ENGINE_CLAUDE, executions=5, retrieval_enabled=False) is None


def test_search_count_is_estimated_when_retrieval_is_enabled() -> None:
    assert _search_count(ENGINE_CLAUDE, executions=5, retrieval_enabled=True) == (
        5 * ESTIMATE_SEARCH_CALLS[ENGINE_CLAUDE]
    )


# --- status vocabulary ----------------------------------------------------


def test_cost_status_is_complete_only_when_every_line_is_verified() -> None:
    assert _cost_status(required=[1, 2]) == PROJECTION_STATUS_COMPLETE


def test_cost_status_is_partial_when_some_lines_are_verified() -> None:
    assert _cost_status(required=[1, None]) == PROJECTION_STATUS_PARTIAL


def test_cost_status_is_unknown_when_no_line_is_verified() -> None:
    assert _cost_status(required=[None, None]) == PROJECTION_STATUS_UNKNOWN


def test_overall_status_is_complete_only_when_every_engine_is_complete() -> None:
    rows = [
        _engine_row(ENGINE_CLAUDE, PROJECTION_STATUS_COMPLETE),
        _engine_row(ENGINE_GEMINI, PROJECTION_STATUS_COMPLETE),
    ]

    assert _overall_cost_status(rows) == PROJECTION_STATUS_COMPLETE


def test_overall_status_is_unknown_only_when_every_engine_is_unknown() -> None:
    rows = [
        _engine_row(ENGINE_CHATGPT, PROJECTION_STATUS_UNKNOWN),
        _engine_row(ENGINE_GEMINI, PROJECTION_STATUS_UNKNOWN),
    ]

    assert _overall_cost_status(rows) == PROJECTION_STATUS_UNKNOWN


def test_one_unknown_engine_makes_the_whole_estimate_partial() -> None:
    # The mixed case is the one that matters: a complete Claude line beside an
    # unverified ChatGPT line must not read as a complete total.
    rows = [
        _engine_row(ENGINE_CLAUDE, PROJECTION_STATUS_COMPLETE),
        _engine_row(ENGINE_CHATGPT, PROJECTION_STATUS_UNKNOWN),
    ]

    assert _overall_cost_status(rows) == PROJECTION_STATUS_PARTIAL


# --- whole-engine estimate ------------------------------------------------


def test_engine_estimate_multiplies_prompts_repetitions_and_attempts() -> None:
    policy = _policy_with(
        retrieval_enabled=False, max_output_tokens=100, max_attempts=3
    )

    row = _estimate_engine(
        ENGINE_CLAUDE,
        policy=policy,
        prompt_count=4,
        repetitions=2,
        per_execution_input=50,
    )

    assert row.execution_count == 8
    assert row.maximum_attempt_count == 24
    assert row.estimated_input_tokens == 100
    assert row.estimated_output_tokens == 800
    assert row.repetition_count == 2
    assert row.prompt_count == 4


def test_engine_estimate_carries_the_exact_route_and_pricing_version() -> None:
    route = measurement_route(ENGINE_GEMINI)

    row = _estimate_engine(
        ENGINE_GEMINI,
        policy=_policy_with(retrieval_enabled=False),
        prompt_count=1,
        repetitions=1,
        per_execution_input=10,
    )

    # Provenance: a persisted estimate names the exact route and rate catalogue
    # it was computed from.
    assert row.transport_provider == route.transport_provider
    assert row.transport_model == route.transport_model
    assert row.pricing_version == PRICING_CATALOG_VERSION


def test_a_verified_engine_with_retrieval_off_has_no_search_line() -> None:
    row = _estimate_engine(
        ENGINE_GEMINI,
        policy=_policy_with(retrieval_enabled=False),
        prompt_count=1,
        repetitions=1,
        per_execution_input=10,
    )

    assert row.retrieval_enabled is False
    assert row.estimated_search_calls is None
    assert row.estimated_search_cost_microusd is None
    assert row.cost_status == PROJECTION_STATUS_COMPLETE
    assert row.estimated_total_cost_microusd == row.estimated_token_cost_microusd


def test_a_verified_engine_with_retrieval_on_prices_the_search_line() -> None:
    policy = _policy_with(retrieval_enabled=True, max_output_tokens=100)
    pricing = route_pricing_for(
        RouteIdentity(
            ENGINE_GEMINI,
            measurement_route(ENGINE_GEMINI).transport_provider,
            measurement_route(ENGINE_GEMINI).transport_model,
        ),
        PRICING_CATALOG_VERSION,
    )
    assert pricing is not None and pricing.search_fee_microusd is not None

    row = _estimate_engine(
        ENGINE_GEMINI,
        policy=policy,
        prompt_count=2,
        repetitions=3,
        per_execution_input=10,
    )

    expected_searches = 6 * ESTIMATE_SEARCH_CALLS[ENGINE_GEMINI]
    assert row.estimated_search_calls == expected_searches
    assert row.estimated_search_cost_microusd == (
        expected_searches * pricing.search_fee_microusd
    )
    assert row.cost_status == PROJECTION_STATUS_COMPLETE
    assert row.estimated_total_cost_microusd == (
        row.estimated_token_cost_microusd + row.estimated_search_cost_microusd
    )


def test_an_unverified_engine_reports_unknown_rather_than_a_zero_bill() -> None:
    # ChatGPT's rate card is deliberately unverified in the catalogue. The
    # estimate must say so instead of quoting a free run.
    row = _estimate_engine(
        ENGINE_CHATGPT,
        policy=_policy_with(retrieval_enabled=False),
        prompt_count=2,
        repetitions=2,
        per_execution_input=10,
    )

    assert row.estimated_token_cost_microusd is None
    assert row.estimated_total_cost_microusd is None
    assert row.cost_status == PROJECTION_STATUS_UNKNOWN
    # Token volumes are still known even when the price is not.
    assert row.execution_count == 4
    assert row.estimated_input_tokens == 20


def test_an_engine_with_no_measurement_route_fails_closed() -> None:
    with pytest.raises(AuditEstimateError, match="no measurement route"):
        _estimate_engine(
            "not-an-engine",
            policy=_policy_with(retrieval_enabled=False),
            prompt_count=1,
            repetitions=1,
            per_execution_input=1,
        )
