"""Audit execution guardrails: retry backoff + the hard per-call ceiling.

Adapted from the reference ``tests/unit/test_ai_visibility_{retry,guardrails}``.
Covers the provider-agnostic knobs that bound a run in time and attempts:
  - ``retry_delay`` prefers a provider ``Retry-After`` (clamped to the cap),
    else exponential backoff capped + deterministic jitter (the QUEUE's
    retry/backoff is the sole retry loop, bounded by the frozen
    ``task.max_attempts``);
  - ``call_provider_once`` makes exactly ONE external call per queue attempt
    (never retries) and cuts a stalled provider off at the frozen
    ``timeout_seconds``, surfacing a retryable timeout.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
)
from app.connectors.answer_engines.errors import ProviderError
from app.core.config import settings
from app.core.config.audits import (
    audit_execution_policy,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ENGINE_GEMINI,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
    TRANSPORT_GOOGLE,
    measurement_route,
    route_policy,
)
from app.workers import audit_worker_support as audit_support


def _request() -> AnswerEngineRequest:
    return AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="Answer for Australia.",
        model=measurement_route("claude").transport_model,
        timeout_seconds=30,
        retrieval_enabled=False,
        max_output_tokens=600,
        reasoning_effort="off",
    )


def test_retry_delay_prefers_retry_after_clamped_to_cap() -> None:
    cap = audit_settings.retry_max_delay_seconds
    # Provider-advised wait honored under the cap...
    assert audit_settings.retry_delay(0, 12.0) == 12.0
    # ...and clamped when it exceeds the cap.
    assert audit_settings.retry_delay(0, cap + 100) == cap


def test_retry_delay_exponential_backoff_grows_and_caps() -> None:
    base = audit_settings.retry_base_delay_seconds
    cap = audit_settings.retry_max_delay_seconds
    # attempt 0 -> base (jitter is zero, since (0 * 0.37) % 1 == 0).
    assert audit_settings.retry_delay(0) == base
    for attempt in range(1, 8):
        delay = audit_settings.retry_delay(attempt)
        assert delay >= min(base * (2**attempt), cap)
        assert delay <= cap + audit_settings.retry_jitter_seconds


class _StallingAdapter:
    """Adapter whose call never returns; the wait_for ceiling must cut it off."""

    transport_provider = TRANSPORT_GOOGLE

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest):  # pragma: no cover
        self.calls += 1
        await asyncio.sleep(3600)


@pytest.mark.asyncio
async def test_call_provider_once_cuts_off_a_stalled_provider() -> None:
    adapter = _StallingAdapter()

    attempt = await audit_support.call_provider_once(
        adapter,
        _request(),
        timeout_seconds=0.01,
        pace_request=lambda _provider: asyncio.sleep(0),
    )

    # Exactly ONE external call, cut off at the frozen timeout ceiling.
    assert adapter.calls == 1
    assert attempt.response is None
    error = attempt.error
    assert isinstance(error, ProviderError)
    # A stall surfaces as a retryable timeout, not a hang.
    assert error.error_code == ERROR_TIMEOUT
    assert error.retryable is True


class _FlakyAdapter:
    """Fails with a retryable error N times, then returns a success."""

    transport_provider = TRANSPORT_GOOGLE

    def __init__(self, *, fail_times: int) -> None:
        self._fail_times = fail_times
        self.calls = 0

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        self.calls += 1
        if self.calls <= self._fail_times:
            raise ProviderError(
                "temporary rate limit",
                error_code=ERROR_RATE_LIMIT,
                retryable=True,
            )
        return AnswerEngineResponse(
            logical_engine=ENGINE_GEMINI,
            transport_provider=TRANSPORT_GOOGLE,
            transport_model=request.model,
            answer_text="ok",
            search_used=False,
            search_events=(),
            citations=(),
        )


@pytest.mark.asyncio
async def test_call_provider_once_never_retries_internally() -> None:
    """A retryable failure returns immediately: the QUEUE owns every retry.

    One queue attempt must make ONE external call, so a retryable error comes
    back as the attempt's outcome instead of being retried inline — the old
    nested retry loop would have made a second call right here.
    """
    adapter = _FlakyAdapter(fail_times=2)

    attempt = await audit_support.call_provider_once(
        adapter,
        _request(),
        timeout_seconds=30.0,
        pace_request=lambda _provider: asyncio.sleep(0),
    )

    assert adapter.calls == 1  # no nested retry, even though budget remained
    assert attempt.succeeded is False
    assert attempt.error is not None
    assert attempt.error.error_code == ERROR_RATE_LIMIT
    assert attempt.error.retryable is True


@pytest.mark.asyncio
async def test_call_provider_once_returns_the_single_success() -> None:
    adapter = _FlakyAdapter(fail_times=0)

    attempt = await audit_support.call_provider_once(
        adapter,
        _request(),
        timeout_seconds=30.0,
        pace_request=lambda _provider: asyncio.sleep(0),
    )

    assert adapter.calls == 1
    assert attempt.succeeded is True
    assert attempt.response is not None
    assert attempt.error is None


def test_build_request_passes_every_frozen_policy_field_explicitly() -> None:
    """The adapter request is driven by the frozen policy, not by defaults.

    Each field is mandatory and asserted against the planned policy value.
    """
    policy = audit_execution_policy()
    request = audit_support.build_request(
        prompt_text="cheap baby clothes",
        system_instruction="Answer for Australia.",
        transport_model="gemini-3-pro",
        logical_engine=ENGINE_GEMINI,
        policy=policy,
    )

    assert request.timeout_seconds == policy.timeout_seconds
    assert request.retrieval_enabled == policy.retrieval_enabled
    assert request.max_output_tokens == policy.max_output_tokens
    assert request.reasoning_effort == (route_policy(ENGINE_GEMINI).reasoning_effort)
    # Every audit freezes retrieval on for citation-capable execution.
    assert request.retrieval_enabled is True


def test_build_request_snapshot_records_policy_and_omits_the_brand_list() -> None:
    """The snapshot reproduces the call; it never carries a secret or the brand.

    Invariant 6: the API key and the brand/competitor list are excluded from
    every snapshot.
    """
    policy = audit_execution_policy()
    request = audit_support.build_request(
        prompt_text="cheap baby clothes",
        system_instruction="Answer for Australia. " + policy.answer_instruction,
        transport_model="gemini-3-pro",
        logical_engine=ENGINE_GEMINI,
        policy=policy,
    )
    snapshot = audit_support.build_request_snapshot(
        logical_engine=ENGINE_GEMINI,
        transport_provider=TRANSPORT_GOOGLE,
        transport_model="gemini-3-pro",
        request=request,
        configuration={
            "benchmark_mode": "solo_brand",
            "country_code": "AU",
            "language_code": "en",
            # A planner-frozen configuration also carries the brand identity;
            # it must NOT be copied into the request snapshot.
            "brand_names": ["Acme"],
        },
        answer_instruction=policy.answer_instruction,
    )

    assert snapshot["retrieval_enabled"] == policy.retrieval_enabled
    assert snapshot["max_output_tokens"] == policy.max_output_tokens
    assert snapshot["timeout_seconds"] == policy.timeout_seconds
    assert snapshot["answer_instruction"] == policy.answer_instruction
    assert snapshot["reasoning_effort"] == (
        route_policy(ENGINE_GEMINI).reasoning_effort
    )
    assert snapshot["stateless"] is True
    assert "brand_names" not in snapshot
    assert "api_key" not in snapshot
    assert "Acme" not in str(snapshot)


def _pool_demand() -> int:
    return (
        audit_settings.worker_max_inflight * audit_settings.worker_db_sessions_per_task
        + audit_settings.operational_headroom
    )


def test_assert_worker_pool_capacity_raises_when_undersized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-T4 pool shape (4+2) cannot cover peak demand: startup RAISES."""
    monkeypatch.setattr(settings, "db_pool_size", 4)
    monkeypatch.setattr(settings, "db_max_overflow", 2)
    assert 4 + 2 < _pool_demand()  # the configuration under test IS undersized
    with pytest.raises(RuntimeError, match="db pool undersized"):
        audit_support.assert_worker_pool_capacity()


def test_assert_worker_pool_capacity_passes_at_exact_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """pool_size + max_overflow == exact demand is ENOUGH (>=, not >)."""
    monkeypatch.setattr(settings, "db_pool_size", _pool_demand())
    monkeypatch.setattr(settings, "db_max_overflow", 0)
    audit_support.assert_worker_pool_capacity()  # must not raise


def test_assert_worker_pool_capacity_passes_with_shipped_defaults() -> None:
    """The shipped pool defaults exactly cover the frozen T4 worker demand."""
    assert settings.db_pool_size + settings.db_max_overflow == _pool_demand()
    audit_support.assert_worker_pool_capacity()  # must not raise
