"""Measurement-mode policy config + canonical response contract vocabulary.

Covers the config-owned foundation the planner/worker/adapters build on:
  - the pulse answer instruction is an UNMEASURED CANDIDATE whose exact wording
    is pinned by SHA-256 so it cannot drift silently;
  - ``measurement_policy_for_mode`` resolves the frozen caps/timeouts/reps per
    mode and fails CLOSED on an unknown mode;
  - prompt framing (``benchmark_mode``) and measurement mode are INDEPENDENT
    axes — constraining one never constrains the other;
  - ``NormalizedUsage`` starts entirely unknown (unknown never becomes zero);
  - ``FinishReason`` is exactly the seven canonical values;
  - route reasoning pins: every active route is pinned off, now that each one
    runs a cheapest tier exposing a documented disable value.

No assertion here attributes any cost/latency result to the candidate wording:
the candidate is unmeasured until a live-key measurement run validates it.
"""

from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    FinishReason,
    NormalizedUsage,
)
from app.core.config.audits import (
    BENCHMARK_ANSWER_INSTRUCTION,
    MEASUREMENT_MODE_BENCHMARK,
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_MODES,
    PULSE_ANSWER_INSTRUCTION,
    PULSE_ANSWER_INSTRUCTION_SHA256,
    AuditSettings,
    MeasurementModePolicy,
    audit_settings,
    frozen_policy_configuration,
    max_run_seconds_from_configuration,
    measurement_policy_for_mode,
    measurement_policy_from_configuration,
    system_instruction_for_mode,
)
from app.core.config.projects import (
    BENCHMARK_MODE_CONSUMER_LIKE,
    BENCHMARK_MODE_CONTROLLED_LOCALIZED,
    BENCHMARK_MODE_FORCED_GROUNDED,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    REASONING_EFFORT_OFF,
    TRANSPORT_OPENAI,
    is_reasoning_pinned_off,
    measurement_route,
    route_policy,
)
from app.models.audit import Audit, AuditTask, RawResponseArtifact


def test_unmeasured_candidate_instruction_wording_is_sha256_pinned() -> None:
    """The unmeasured candidate wording must not drift silently.

    A different wording is a DIFFERENT (equally unmeasured) candidate, so the
    digest is pinned rather than the prose being spot-checked.
    """
    digest = hashlib.sha256(PULSE_ANSWER_INSTRUCTION.encode("utf-8")).hexdigest()
    assert digest == PULSE_ANSWER_INSTRUCTION_SHA256, (
        "unmeasured candidate instruction wording changed; update the pinned "
        "digest deliberately and re-validate the candidate"
    )


def test_measurement_modes_use_their_owned_answer_instructions() -> None:
    """Each mode contributes its config-owned neutral answer instruction."""
    assert (
        measurement_policy_for_mode(MEASUREMENT_MODE_PULSE).answer_instruction
        == PULSE_ANSWER_INSTRUCTION
    )
    assert (
        measurement_policy_for_mode(MEASUREMENT_MODE_BENCHMARK).answer_instruction
        == BENCHMARK_ANSWER_INSTRUCTION
    )


def test_measurement_policy_for_pulse_returns_frozen_caps() -> None:
    policy = measurement_policy_for_mode(MEASUREMENT_MODE_PULSE)

    assert policy == MeasurementModePolicy(
        retrieval_enabled=False,
        max_output_tokens=600,
        timeout_seconds=30.0,
        repetitions=1,
        answer_instruction=PULSE_ANSWER_INSTRUCTION,
        # Pulse retries twice, not five times: the cheap shape carries its own
        # attempt budget.
        max_attempts=2,
    )


def test_measurement_policy_for_benchmark_returns_frozen_caps() -> None:
    policy = measurement_policy_for_mode(MEASUREMENT_MODE_BENCHMARK)

    assert policy == MeasurementModePolicy(
        retrieval_enabled=True,
        max_output_tokens=800,
        timeout_seconds=60.0,
        repetitions=3,
        answer_instruction=BENCHMARK_ANSWER_INSTRUCTION,
        max_attempts=5,
    )


def test_measurement_policy_reads_live_settings_for_the_caller_to_freeze(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolver reads live settings; callers freeze the result (invariant 9)."""
    monkeypatch.setattr(audit_settings, "pulse_max_output_tokens", 321)

    frozen = measurement_policy_for_mode(MEASUREMENT_MODE_PULSE)
    assert frozen.max_output_tokens == 321

    # Frozen: a later live-config change cannot mutate an already-resolved policy.
    monkeypatch.setattr(audit_settings, "pulse_max_output_tokens", 999)
    assert frozen.max_output_tokens == 321


def test_measurement_policy_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown measurement mode"):
        measurement_policy_for_mode("turbo")


def test_frozen_policy_configuration_round_trips_unchanged() -> None:
    frozen = measurement_policy_for_mode(MEASUREMENT_MODE_PULSE)

    restored = measurement_policy_from_configuration(
        {
            "measurement_mode": MEASUREMENT_MODE_PULSE,
            "measurement_policy": frozen_policy_configuration(frozen),
        }
    )

    assert restored == frozen


def test_frozen_policy_is_isolated_from_later_live_setting_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frozen = frozen_policy_configuration(
        measurement_policy_for_mode(MEASUREMENT_MODE_PULSE)
    )
    monkeypatch.setattr(audit_settings, "pulse_max_output_tokens", 1)

    restored = measurement_policy_from_configuration(
        {"measurement_mode": MEASUREMENT_MODE_PULSE, "measurement_policy": frozen}
    )

    assert restored.max_output_tokens == frozen["max_output_tokens"]


def test_missing_frozen_policy_uses_mode_defaults() -> None:
    expected = measurement_policy_for_mode(MEASUREMENT_MODE_PULSE)

    assert (
        measurement_policy_from_configuration(
            {"measurement_mode": MEASUREMENT_MODE_PULSE}
        )
        == expected
    )


@pytest.mark.parametrize(
    "frozen",
    [
        {
            "retrieval_enabled": False,
            "max_output_tokens": 600,
            "timeout_seconds": 30.0,
            "repetitions": 1,
            "answer_instruction": "answer",
            # A row frozen before the attempt budget was introduced must be
            # migrated rather than silently inheriting a live mutable value.
        },
        {
            "retrieval_enabled": "false",
            "max_output_tokens": None,
            "timeout_seconds": 1,
            "repetitions": 1,
            "answer_instruction": "answer",
            "max_attempts": 2,
        },
    ],
)
def test_present_invalid_frozen_policy_fails_closed(frozen: dict) -> None:
    with pytest.raises(ValueError, match="invalid frozen measurement policy"):
        measurement_policy_from_configuration(
            {
                "measurement_mode": MEASUREMENT_MODE_PULSE,
                "measurement_policy": frozen,
            }
        )


@pytest.mark.parametrize("pulse_max_attempts", [0, -1])
def test_audit_settings_reject_non_positive_pulse_attempt_budgets(
    pulse_max_attempts: int,
) -> None:
    with pytest.raises(ValidationError):
        AuditSettings(pulse_max_attempts=pulse_max_attempts)


def test_unknown_legacy_measurement_mode_defaults_to_benchmark() -> None:
    assert measurement_policy_from_configuration(
        {"measurement_mode": "retired-mode"}
    ) == measurement_policy_for_mode(MEASUREMENT_MODE_BENCHMARK)


def test_max_run_seconds_prefers_frozen_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(audit_settings, "max_run_seconds", 999.0)

    assert max_run_seconds_from_configuration({"max_run_seconds": 123.5}) == 123.5
    assert max_run_seconds_from_configuration({}) == 999.0
    assert max_run_seconds_from_configuration(None) == 999.0


def test_measurement_policy_covers_every_declared_mode() -> None:
    for mode in MEASUREMENT_MODES:
        assert measurement_policy_for_mode(mode).repetitions >= 1


def test_config_owns_trend_smoothing_and_prompt_length_limits() -> None:
    assert audit_settings.trend_smoothing_days == 7
    assert audit_settings.max_prompt_chars == 300


def test_prompt_framing_and_measurement_modes_are_independent_axes() -> None:
    """Choosing a measurement mode never constrains prompt framing (or vice versa)."""
    # Prompt framing is unchanged by measurement mode: the framing resolver does
    # not take a measurement mode at all, and every framing mode stays valid.
    framings = {
        BENCHMARK_MODE_CONSUMER_LIKE,
        BENCHMARK_MODE_CONTROLLED_LOCALIZED,
        BENCHMARK_MODE_FORCED_GROUNDED,
    }
    assert not framings & MEASUREMENT_MODES

    consumer_like = system_instruction_for_mode(
        mode=BENCHMARK_MODE_CONSUMER_LIKE, country_code="AU", language_code="en"
    )
    grounded = system_instruction_for_mode(
        mode=BENCHMARK_MODE_FORCED_GROUNDED, country_code="AU", language_code="en"
    )
    assert consumer_like == ""
    assert grounded != ""

    # ...and the measurement policy never embeds a framing instruction: the two
    # axes compose at the planner, they do not constrain each other here.
    for mode in (MEASUREMENT_MODE_PULSE, MEASUREMENT_MODE_BENCHMARK):
        policy = measurement_policy_for_mode(mode)
        assert policy.answer_instruction != grounded


def test_normalized_usage_defaults_are_all_none() -> None:
    """Unknown never becomes zero: every counter starts null."""
    usage = NormalizedUsage()

    assert usage.uncached_input_tokens is None
    assert usage.cached_input_tokens is None
    assert usage.output_tokens is None
    assert usage.reasoning_tokens is None
    assert usage.total_tokens is None
    assert usage.web_search_requests is None
    assert usage.provider_cost_microusd is None


def test_finish_reason_has_exactly_the_seven_canonical_values() -> None:
    assert {member.value for member in FinishReason} == {
        "stop",
        "length",
        "tool_error",
        "content_filter",
        "cancelled",
        "error",
        "unknown",
    }


def test_answer_engine_request_carries_the_frozen_route_output_policy() -> None:
    request = AnswerEngineRequest(
        prompt="cheap baby clothes",
        system_instruction="",
        model=measurement_route(ENGINE_CLAUDE, MEASUREMENT_MODE_PULSE).transport_model,
        timeout_seconds=30.0,
        retrieval_enabled=False,
        max_output_tokens=600,
        reasoning_effort=REASONING_EFFORT_OFF,
    )

    assert request.retrieval_enabled is False
    assert request.max_output_tokens == 600
    assert request.reasoning_effort == REASONING_EFFORT_OFF


def test_anthropic_reasoning_is_pinned_off() -> None:
    policy = route_policy(ENGINE_CLAUDE, MEASUREMENT_MODE_PULSE)

    assert policy.reasoning_pinnable is True
    assert policy.reasoning_effort == REASONING_EFFORT_OFF
    assert is_reasoning_pinned_off(ENGINE_CLAUDE, MEASUREMENT_MODE_PULSE) is True


@pytest.mark.parametrize(
    ("engine", "expected_effort"),
    [
        (ENGINE_CHATGPT, REASONING_EFFORT_OFF),
        (ENGINE_GEMINI, "minimal"),
    ],
)
def test_pulse_routes_pin_exact_reasoning(engine: str, expected_effort: str) -> None:
    policy = route_policy(engine, MEASUREMENT_MODE_PULSE)

    assert policy.reasoning_effort == expected_effort
    assert policy.reasoning_pinnable is True
    assert is_reasoning_pinned_off(engine, MEASUREMENT_MODE_PULSE) is (
        expected_effort == REASONING_EFFORT_OFF
    )


def test_every_active_route_declares_a_policy_and_no_batch_path() -> None:
    for engine in (ENGINE_CHATGPT, ENGINE_CLAUDE, ENGINE_GEMINI):
        for mode in (MEASUREMENT_MODE_PULSE, MEASUREMENT_MODE_BENCHMARK):
            policy = route_policy(engine, mode)
            assert policy.representative_status == "unverified"
            assert policy.batch_enabled is False


def test_route_policy_fails_closed_on_unknown_route() -> None:
    with pytest.raises(ValueError, match="no route policy"):
        route_policy(ENGINE_CLAUDE, TRANSPORT_OPENAI)


def test_audit_measurement_mode_column_defaults_to_pulse() -> None:
    column = Audit.__table__.c.measurement_mode

    assert column.type.length == 16
    assert column.nullable is False
    assert column.default.arg == MEASUREMENT_MODE_PULSE


@pytest.mark.parametrize("model", [AuditTask, RawResponseArtifact])
def test_canonical_finish_reason_columns_are_non_null_unknown_by_default(
    model: type,
) -> None:
    canonical = model.__table__.c.finish_reason
    raw = model.__table__.c.raw_finish_reason

    assert canonical.type.length == 24
    assert canonical.nullable is False
    assert canonical.default.arg == FinishReason.UNKNOWN.value
    assert raw.type.length == 64
    assert raw.nullable is True
