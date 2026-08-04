"""T1 measurement harness: deterministic offline sweep contract.

Covers the honesty guarantees the harness exists to enforce:
  - fixtures are the default source and perform ZERO network I/O;
  - matrix expansion is deterministic and emits unsupported reasoning cells
    instead of silently dropping them;
  - absent/invalid provider usage stays NULL, never zero, while known
    non-nullable fields are always present;
  - TTFT stays null when no streaming timestamp exists and is never wall time;
  - fixture-derived runs are labelled and can never satisfy a live gate;
  - a live run needs both flags plus the typed confirmation token.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import measurement as measurement_config
from app.core.config.measurement import (
    COST_STATUS_PARTIAL,
    COST_STATUS_UNKNOWN,
    LIVE_CONFIRMATION_TOKEN,
    MEASUREMENT_OUTPUT_TREATMENTS,
    MEASUREMENT_PROMPTS_PATH,
    MEASUREMENT_ROUTE_KEYS,
    MEASUREMENT_SEARCH_STATES,
    OBSERVATION_STATUS_OK,
    OBSERVATION_STATUS_UNSUPPORTED,
    REASONING_EFFORT_UNSET,
    UNSET_PRICING,
    route_fixture_path,
    route_reasoning_efforts,
)
from app.domain.measurement.harness import (
    FixtureMeasurementRunner,
    LiveExecutionNotEnabledError,
    MeasurementCase,
    MeasurementConfigurationError,
    MeasurementPrompt,
    expand_matrix,
    load_measurement_prompts,
    run_manifest,
    run_matrix,
    satisfies_live_gate,
    sha256_file,
    summarize_output_lengths,
    summarize_route_costs,
    write_measurement_outputs,
)
from scripts import measure_answer_engine_matrix as cli

REPETITIONS = 2


@pytest.fixture(name="prompts")
def prompts_fixture() -> tuple[MeasurementPrompt, ...]:
    return load_measurement_prompts()


async def _fixture_run(prompts, *, repetitions: int = REPETITIONS):
    cases = expand_matrix(repetitions=repetitions)
    return await run_matrix(
        cases=cases, prompts=prompts, runner=FixtureMeasurementRunner()
    )


# --- prompt set -----------------------------------------------------------


def test_prompt_set_has_twelve_safe_generic_prompts(prompts) -> None:
    assert len(prompts) == 12
    assert len({prompt.prompt_id for prompt in prompts}) == 12
    blob = " ".join(prompt.text for prompt in prompts).lower()
    for term in measurement_config.FORBIDDEN_PROMPT_TERMS:
        assert term not in blob


@pytest.mark.parametrize(
    "text",
    [
        "How does CiteLadder rank answers?",
        "Email support at help@example.org for details.",
        "Read https://example.com/guide first.",
        "Compare kettles on kmart.com.au today.",
        "Use api_ABCDEF123456 to authenticate.",
    ],
)
def test_prompt_set_rejects_unsafe_prompt(tmp_path: Path, text: str) -> None:
    payload = {
        "prompts": [
            {"prompt_id": f"p{index:02d}", "text": f"Generic question {index}?"}
            for index in range(1, 12)
        ]
        + [{"prompt_id": "p12", "text": text}]
    }
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MeasurementConfigurationError):
        load_measurement_prompts(path)


@pytest.mark.parametrize("count", [9, 21])
def test_prompt_set_rejects_out_of_range_count(tmp_path: Path, count: int) -> None:
    payload = {
        "prompts": [
            {"prompt_id": f"p{index:02d}", "text": f"Generic question {index}?"}
            for index in range(1, count + 1)
        ]
    }
    path = tmp_path / "prompts.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MeasurementConfigurationError):
        load_measurement_prompts(path)


# --- matrix expansion ----------------------------------------------------


def test_matrix_expansion_is_deterministic_and_complete() -> None:
    first = expand_matrix(repetitions=REPETITIONS)
    assert first == expand_matrix(repetitions=REPETITIONS)
    efforts = {
        effort
        for route_key in MEASUREMENT_ROUTE_KEYS
        for effort in route_reasoning_efforts(route_key)
    }
    expected = (
        len(MEASUREMENT_ROUTE_KEYS)
        * len(MEASUREMENT_SEARCH_STATES)
        * len(efforts)
        * len(MEASUREMENT_OUTPUT_TREATMENTS)
        * REPETITIONS
    )
    assert len(first) == expected
    assert len(set(first)) == expected


def test_matrix_expansion_rejects_zero_repetitions() -> None:
    with pytest.raises(MeasurementConfigurationError):
        expand_matrix(repetitions=0)


async def test_unsupported_reasoning_is_emitted_not_skipped(prompts) -> None:
    run = await _fixture_run(prompts)
    unsupported = [
        observation
        for observation in run.observations
        if observation.status == OBSERVATION_STATUS_UNSUPPORTED
    ]
    assert unsupported, "unsupported reasoning cells must appear in the artifact"
    # Claude/Gemini expose no explicit reasoning knob: every explicit effort is
    # recorded as unsupported rather than dropped.
    assert {observation.case.route_key for observation in unsupported} == {
        route_key
        for route_key in MEASUREMENT_ROUTE_KEYS
        if route_reasoning_efforts(route_key) == (REASONING_EFFORT_UNSET,)
    }
    for observation in unsupported:
        assert observation.case.reasoning_effort != REASONING_EFFORT_UNSET
        assert observation.finish_reason == (
            measurement_config.FINISH_REASON_NOT_EXECUTED
        )
    assert len(run.observations) == run.case_count * run.prompt_count


# --- observation field contract ------------------------------------------


async def test_observations_carry_required_non_null_fields(prompts) -> None:
    run = await _fixture_run(prompts)
    executed = [
        observation
        for observation in run.observations
        if observation.status == OBSERVATION_STATUS_OK
    ]
    assert executed
    for observation in executed:
        assert isinstance(observation.search_call_count, int)
        assert observation.wall_time_ms > 0
        assert isinstance(observation.queue_wait_ms, int)
        assert observation.finish_reason
        assert isinstance(observation.mention_count, int)
        assert isinstance(observation.citation_count, int)
        assert isinstance(observation.extracted_queries, tuple)
        assert len(observation.extracted_queries) == observation.search_call_count


async def test_absent_or_invalid_usage_stays_null_never_zero(prompts) -> None:
    run = await _fixture_run(prompts)
    absent = [
        observation
        for observation in run.observations
        if observation.fixture_id == "openai-off-3-usage-absent"
    ]
    assert absent
    for observation in absent:
        assert observation.uncached_input_tokens is None
        assert observation.output_tokens is None
        assert observation.reasoning_tokens is None
        assert observation.provider_reported_cost_microusd is None
    invalid = [
        observation
        for observation in run.observations
        if observation.fixture_id == "google-on-2-invalid-usage"
    ]
    assert invalid
    for observation in invalid:
        # negative int and non-numeric string both normalize to unknown
        assert observation.uncached_input_tokens is None
        assert observation.output_tokens is None


async def test_no_search_never_implies_a_zero_search_fee(prompts) -> None:
    run = await _fixture_run(prompts)
    no_search = [
        observation
        for observation in run.observations
        if observation.status == OBSERVATION_STATUS_OK
        and not observation.case.search_enabled
    ]
    assert no_search
    for observation in no_search:
        assert observation.search_call_count == 0
        assert observation.search_fee_microusd is None


async def test_ttft_is_null_without_streaming_metadata_and_never_wall_time(
    prompts,
) -> None:
    run = await _fixture_run(prompts)
    openai_rows = [
        observation
        for observation in run.observations
        if observation.status == OBSERVATION_STATUS_OK
        and observation.transport_provider == "openai"
    ]
    assert openai_rows
    assert all(observation.ttft_ms is None for observation in openai_rows)
    streaming = [
        observation
        for observation in run.observations
        if observation.ttft_ms is not None
    ]
    assert streaming
    for observation in streaming:
        assert observation.ttft_ms < observation.wall_time_ms


async def test_extracted_queries_and_citation_counts_use_the_shared_scorer(
    prompts,
) -> None:
    run = await _fixture_run(prompts)
    searched = [
        observation
        for observation in run.observations
        if observation.status == OBSERVATION_STATUS_OK
        and observation.case.search_enabled
    ]
    assert searched
    sample = searched[0]
    assert sample.search_call_count > 0
    assert all(query for query in sample.extracted_queries)
    assert sample.citation_count > 0
    assert sample.mention_count > 0


async def test_gate_input_is_canonical_finish_reason_only(prompts) -> None:
    run = await _fixture_run(prompts)
    payload = json.loads(
        (route_fixture_path(MEASUREMENT_ROUTE_KEYS[0], search_enabled=False)).read_text(
            encoding="utf-8"
        )
    )
    allowed = {str(envelope["finish_reason"]) for envelope in payload["envelopes"]} | {
        measurement_config.FINISH_REASON_NOT_EXECUTED
    }
    chatgpt_no_search = {
        observation.finish_reason
        for observation in run.observations
        if observation.case.route_key == MEASUREMENT_ROUTE_KEYS[0]
        and not observation.case.search_enabled
    }
    assert chatgpt_no_search <= allowed


async def test_missing_finish_reason_is_rejected(prompts) -> None:
    class BadFixtureRunner(FixtureMeasurementRunner):
        def _pick(self, case, prompt):  # type: ignore[override]
            envelope = dict(super()._pick(case, prompt))
            envelope["finish_reason"] = ""
            return envelope

    case = MeasurementCase(
        route_key=MEASUREMENT_ROUTE_KEYS[0],
        search_enabled=False,
        reasoning_effort=REASONING_EFFORT_UNSET,
        output_treatment=MEASUREMENT_OUTPUT_TREATMENTS[0],
        repetition=1,
    )
    with pytest.raises(MeasurementConfigurationError):
        await BadFixtureRunner().observe(case, prompts[0])


# --- summaries -----------------------------------------------------------


async def test_route_costs_keep_reasoning_and_search_lines_separate(prompts) -> None:
    run = await _fixture_run(prompts)
    summary = summarize_route_costs(run)
    assert summary["fixture_derived"] is True
    assert summary["unset_pricing"] == list(UNSET_PRICING)
    assert summary["cells"]
    for cell in summary["cells"]:
        lines = cell["lines"]
        assert "reasoning_tokens" in lines
        assert "search_fee_microusd" in lines
        # Per-search fees are unset everywhere, so no cell can claim a total.
        assert lines["search_fee_microusd"] is None
        assert cell["total_cost_microusd"] is None
        assert cell["cost_status"] in {COST_STATUS_PARTIAL, COST_STATUS_UNKNOWN}


async def test_route_costs_report_partial_when_some_lines_known(prompts) -> None:
    run = await _fixture_run(prompts)
    summary = summarize_route_costs(run)
    claude_cells = [cell for cell in summary["cells"] if cell["route_key"] == "claude"]
    assert claude_cells
    assert any(
        cell["lines"]["provider_reported_cost_microusd"] is not None
        and cell["cost_status"] == COST_STATUS_PARTIAL
        for cell in claude_cells
    )


async def test_output_distribution_reports_quantiles_and_unknown_counts(
    prompts,
) -> None:
    run = await _fixture_run(prompts)
    summary = summarize_output_lengths(run)
    assert summary["quantiles"] == list(measurement_config.OUTPUT_LENGTH_QUANTILES)
    buckets = {
        (bucket["route_key"], bucket["output_treatment"]): bucket
        for bucket in summary["buckets"]
    }
    assert set(MEASUREMENT_ROUTE_KEYS) == {key[0] for key in buckets}
    for bucket in buckets.values():
        assert bucket["observation_count"] == (
            bucket["known_output_token_count"] + bucket["unknown_output_token_count"]
        )
        for value in bucket["quantiles"].values():
            assert value is None or value > 0
    chatgpt_baseline = buckets[("chatgpt", "baseline")]
    assert chatgpt_baseline["unknown_output_token_count"] > 0


# --- provenance + gating -------------------------------------------------


async def test_manifest_records_fixture_hashes_and_versions(prompts) -> None:
    run = await _fixture_run(prompts)
    manifest = run_manifest(run)
    assert manifest["schema_version"] == (
        measurement_config.MEASUREMENT_ARTIFACT_SCHEMA_VERSION
    )
    assert manifest["script_version"] == measurement_config.MEASUREMENT_SCRIPT_VERSION
    assert manifest["prompt_fixture_sha256"] == sha256_file(MEASUREMENT_PROMPTS_PATH)
    assert manifest["fixture_sha256"]
    for name, digest in manifest["fixture_sha256"].items():
        assert "/" in name
        assert len(digest) == 64
    assert manifest["unset_pricing"] == list(UNSET_PRICING)
    assert manifest["unsupported_observation_count"] > 0


async def test_fixture_run_is_labelled_and_cannot_satisfy_a_live_gate(
    prompts,
) -> None:
    run = await _fixture_run(prompts)
    assert run.fixture_derived is True
    assert run.source == measurement_config.SOURCE_FIXTURES
    assert satisfies_live_gate(run) is False
    assert run_manifest(run)["gate_eligible"] is False
    assert any("SYNTHETIC" in note for note in run.notes)


async def test_write_measurement_outputs_emits_three_artifacts(
    prompts, tmp_path: Path
) -> None:
    run = await _fixture_run(prompts, repetitions=1)
    executions, route_costs, distribution = write_measurement_outputs(run, tmp_path)
    assert executions.name == measurement_config.EXECUTIONS_FILENAME
    assert route_costs.name == measurement_config.ROUTE_COSTS_FILENAME
    assert distribution.name == measurement_config.OUTPUT_DISTRIBUTION_FILENAME
    rows = [
        json.loads(line)
        for line in executions.read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(rows) == len(run.observations)
    assert rows[0]["case"]["route_key"] in MEASUREMENT_ROUTE_KEYS
    manifest_path = executions.parent / measurement_config.RUN_MANIFEST_FILENAME
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["fixture_derived"]


async def test_sweep_ceiling_rejects_an_oversized_matrix(prompts, monkeypatch) -> None:
    monkeypatch.setattr(measurement_config.measurement_settings, "max_observations", 5)
    with pytest.raises(MeasurementConfigurationError):
        await _fixture_run(prompts, repetitions=1)


# --- CLI safety ---------------------------------------------------------


def test_cli_defaults_to_fixture_source() -> None:
    args = cli.build_parser().parse_args([])
    assert args.source == measurement_config.DEFAULT_MEASUREMENT_SOURCE
    assert args.live is False
    runner = cli.resolve_runner(args)
    assert isinstance(runner, FixtureMeasurementRunner)
    assert runner.fixture_derived is True


def test_cli_rejects_live_without_both_opt_ins() -> None:
    parser = cli.build_parser()
    with pytest.raises(MeasurementConfigurationError):
        cli.resolve_runner(parser.parse_args(["--source", "live"]))
    with pytest.raises(MeasurementConfigurationError):
        cli.resolve_runner(parser.parse_args(["--source", "live", "--live"]))
    with pytest.raises(MeasurementConfigurationError):
        cli.resolve_runner(
            parser.parse_args(["--source", "live", "--live", "--confirm", "please-run"])
        )
    with pytest.raises(MeasurementConfigurationError):
        cli.resolve_runner(parser.parse_args(["--source", "fixtures", "--live"]))


def test_cli_live_never_degrades_to_fixtures() -> None:
    args = cli.build_parser().parse_args(
        ["--source", "live", "--live", "--confirm", LIVE_CONFIRMATION_TOKEN]
    )
    with pytest.raises(LiveExecutionNotEnabledError):
        cli.resolve_runner(args)


async def test_offline_run_makes_no_network_call(prompts, monkeypatch) -> None:
    import socket

    def _forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("offline measurement attempted network I/O")

    monkeypatch.setattr(socket.socket, "connect", _forbidden)
    monkeypatch.setattr(socket, "create_connection", _forbidden)
    run = await _fixture_run(prompts, repetitions=1)
    assert run.observations
