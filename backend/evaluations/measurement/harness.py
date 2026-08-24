"""Offline-first answer-engine measurement harness.

Expands a deterministic sweep (route x retrieval x route-supported reasoning
effort x output treatment x repetition x prompt), runs it through a pluggable
runner, and writes JSONL execution rows plus route-cost and output-length
summaries.

Honesty contract — read before changing anything here:

* **Nothing in this module produces a measurement.** The only runner shipped in
  this commit is :class:`FixtureMeasurementRunner`, which replays committed
  SYNTHETIC envelopes. Every run it produces is stamped ``fixture_derived=true``
  and :func:`satisfies_live_gate` returns ``False`` for it, so a fixture run can
  never promote a candidate.
* **Absent means null, never zero.** Token classes, reasoning tokens,
  provider-reported cost, per-search fees and TTFT are all nullable. A
  no-retrieval execution has a *known* ``search_call_count=0``; that never
  implies a zero provider search fee.
* **Wall time is never relabelled TTFT.** ``ttft_ms`` stays ``None`` unless the
  envelope carried a real first-token timestamp.
* Mention/citation counts come from the existing deterministic scorer
  (``app/analysis/scoring.py``); no second scoring implementation exists here
  (invariant 2).

All thresholds, dimensions, paths and vocabularies live in
``app/core/config/measurement.py`` (invariant 1).
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from app.analysis.scoring import ScoringConfig, score_execution
from app.core.config.measurement import (
    COST_STATUS_COMPLETE,
    COST_STATUS_PARTIAL,
    COST_STATUS_UNKNOWN,
    EXECUTIONS_FILENAME,
    FINISH_REASON_NOT_EXECUTED,
    FORBIDDEN_PROMPT_PATTERNS,
    FORBIDDEN_PROMPT_TERMS,
    GATE_REQUIRES_LIVE_SOURCE,
    MEASUREMENT_ARTIFACT_SCHEMA_VERSION,
    MEASUREMENT_OUTPUT_TREATMENTS,
    MEASUREMENT_PROMPT_MAX_CHARS,
    MEASUREMENT_PROMPT_MAX_COUNT,
    MEASUREMENT_PROMPT_MIN_COUNT,
    MEASUREMENT_PROMPTS_PATH,
    MEASUREMENT_ROUTE_KEYS,
    MEASUREMENT_SCORING_SUBJECT,
    MEASUREMENT_SCRIPT_VERSION,
    MEASUREMENT_SEARCH_STATES,
    OBSERVATION_STATUS_OK,
    OBSERVATION_STATUS_UNSUPPORTED,
    OUTPUT_DISTRIBUTION_FILENAME,
    OUTPUT_LENGTH_QUANTILES,
    ROUTE_COSTS_FILENAME,
    RUN_MANIFEST_FILENAME,
    SOURCE_FIXTURES,
    SOURCE_LIVE,
    UNSET_PRICING,
    is_reasoning_effort_supported,
    measurement_settings,
    route_fixture_path,
    route_reasoning_efforts,
)
from app.core.config.provider_catalog import measurement_route

_FORBIDDEN_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN_PROMPT_PATTERNS
)


class MeasurementConfigurationError(ValueError):
    """A sweep input (prompt set, fixture, or dimension) is unusable."""


class LiveExecutionNotEnabledError(RuntimeError):
    """Live provider execution is not wired in this commit.

    Raised instead of silently degrading to fixtures so an operator who asked
    for a live run never receives synthetic numbers labelled as real ones.
    """


# --- Value objects --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeasurementPrompt:
    prompt_id: str
    text: str
    intent: str = ""


@dataclass(frozen=True, slots=True)
class MeasurementCase:
    route_key: str
    search_enabled: bool
    reasoning_effort: str
    output_treatment: str
    repetition: int


@dataclass(frozen=True, slots=True)
class MeasurementObservation:
    """One sweep cell outcome.

    Nullable fields are ``None`` when the provider did not report them; readers
    must not coalesce them to zero.
    """

    case: MeasurementCase
    prompt_id: str
    status: str
    transport_provider: str
    transport_model: str
    # Non-null: known regardless of provider usage reporting.
    search_call_count: int
    wall_time_ms: int
    queue_wait_ms: int
    finish_reason: str
    mention_count: int
    citation_count: int
    extracted_queries: tuple[str, ...]
    # Nullable: absent/invalid provider reporting stays unknown.
    uncached_input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    provider_reported_cost_microusd: int | None = None
    search_fee_microusd: int | None = None
    ttft_ms: int | None = None
    fixture_id: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class MeasurementRun:
    run_id: str
    source: str
    fixture_derived: bool
    generated_at: str
    schema_version: str
    script_version: str
    prompt_fixture_sha256: str
    fixture_sha256: dict[str, str]
    unset_pricing: tuple[str, ...]
    observations: tuple[MeasurementObservation, ...]
    prompt_count: int
    case_count: int
    notes: tuple[str, ...] = field(default_factory=tuple)


class MeasurementRunner(Protocol):
    """Executes one sweep cell."""

    source: str
    fixture_derived: bool

    def fixture_hashes(self) -> dict[str, str]:
        """SHA-256 of every artifact this runner replayed (empty when live)."""
        ...

    async def observe(
        self, case: MeasurementCase, prompt: MeasurementPrompt
    ) -> MeasurementObservation: ...


# --- Prompt loading + safety --------------------------------------------


def _reject_unsafe_prompt(text: str) -> None:
    lowered = text.lower()
    for term in FORBIDDEN_PROMPT_TERMS:
        if term in lowered:
            raise MeasurementConfigurationError(
                f"measurement prompt contains forbidden term {term!r}"
            )
    for pattern in _FORBIDDEN_PATTERNS:
        if pattern.search(text):
            raise MeasurementConfigurationError(
                "measurement prompt matches forbidden pattern "
                f"{pattern.pattern!r} (domain/email/url/credential)"
            )
    if len(text) > MEASUREMENT_PROMPT_MAX_CHARS:
        raise MeasurementConfigurationError(
            f"measurement prompt exceeds {MEASUREMENT_PROMPT_MAX_CHARS} chars"
        )


def prompt_fixture_digest(path: Path | None = None) -> str:
    """SHA-256 of the prompt artifact :func:`load_measurement_prompts` reads.

    Resolves ``path`` exactly the way the loader does, so a run that measured a
    custom prompt set can stamp the manifest with the digest of THAT file
    rather than of the default one it never opened.
    """
    return sha256_file(path or MEASUREMENT_PROMPTS_PATH)


def load_measurement_prompts(
    path: Path | None = None,
) -> tuple[MeasurementPrompt, ...]:
    """Load and validate the fixed generic prompt set.

    Rejects a prompt set outside the configured 10-20 count, and any prompt
    carrying project brand identity, a domain, an email address, a URL, or a
    credential-shaped token (invariant 6).
    """
    source = path or MEASUREMENT_PROMPTS_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    raw_prompts = payload.get("prompts") if isinstance(payload, dict) else payload
    if not isinstance(raw_prompts, list):
        raise MeasurementConfigurationError(f"{source} has no 'prompts' list")
    count = len(raw_prompts)
    if not MEASUREMENT_PROMPT_MIN_COUNT <= count <= MEASUREMENT_PROMPT_MAX_COUNT:
        raise MeasurementConfigurationError(
            f"measurement prompt set must hold "
            f"{MEASUREMENT_PROMPT_MIN_COUNT}-{MEASUREMENT_PROMPT_MAX_COUNT} "
            f"prompts, found {count}"
        )
    prompts: list[MeasurementPrompt] = []
    seen: set[str] = set()
    for entry in raw_prompts:
        if not isinstance(entry, dict):
            # A bare string (or number, or list) in the array is a malformed
            # prompt set, which is the CLI's MeasurementConfigurationError
            # path — not an AttributeError out of ``entry.get``.
            raise MeasurementConfigurationError(
                "each measurement prompt must be an object, found "
                f"{type(entry).__name__}"
            )
        prompt_id = str(entry.get("prompt_id") or "").strip()
        text = str(entry.get("text") or "").strip()
        if not prompt_id or not text:
            raise MeasurementConfigurationError(
                "each measurement prompt needs a prompt_id and text"
            )
        if prompt_id in seen:
            raise MeasurementConfigurationError(f"duplicate prompt_id {prompt_id!r}")
        seen.add(prompt_id)
        _reject_unsafe_prompt(text)
        prompts.append(
            MeasurementPrompt(
                prompt_id=prompt_id,
                text=text,
                intent=str(entry.get("intent") or ""),
            )
        )
    return tuple(prompts)


# --- Matrix expansion ----------------------------------------------------


def expand_matrix(
    *,
    route_keys: Sequence[str] = MEASUREMENT_ROUTE_KEYS,
    repetitions: int | None = None,
) -> tuple[MeasurementCase, ...]:
    """Deterministically expand the full sweep.

    Every route is swept against every reasoning-effort value in the sweep
    vocabulary, including ones the route does not support: those cells are
    emitted as ``unsupported`` observations by :func:`run_matrix` rather than
    silently dropped, so the artifact records what was NOT measured.
    """
    reps = measurement_settings.repetitions if repetitions is None else repetitions
    if reps < 1:
        raise MeasurementConfigurationError("repetitions must be >= 1")
    cases: list[MeasurementCase] = []
    for route_key in route_keys:
        for search_enabled in MEASUREMENT_SEARCH_STATES:
            for reasoning_effort in _sweep_reasoning_efforts(route_keys):
                for output_treatment in MEASUREMENT_OUTPUT_TREATMENTS:
                    cases.extend(
                        MeasurementCase(
                            route_key=route_key,
                            search_enabled=search_enabled,
                            reasoning_effort=reasoning_effort,
                            output_treatment=output_treatment,
                            repetition=repetition,
                        )
                        for repetition in range(1, reps + 1)
                    )
    return tuple(cases)


def _sweep_reasoning_efforts(route_keys: Sequence[str]) -> tuple[str, ...]:
    """Union of every route's supported efforts, in stable catalog order."""
    ordered: list[str] = []
    for route_key in route_keys:
        for effort in route_reasoning_efforts(route_key):
            if effort not in ordered:
                ordered.append(effort)
    return tuple(ordered)


def route_identity(route_key: str) -> tuple[str, str]:
    """Resolve the approved ``(transport_provider, transport_model)`` pair."""
    try:
        route = measurement_route(route_key)
    except ValueError as exc:
        raise MeasurementConfigurationError(
            f"route {route_key!r} is not approved"
        ) from exc
    return route.transport_provider, route.transport_model


def _unsupported_observation(
    case: MeasurementCase, prompt: MeasurementPrompt
) -> MeasurementObservation:
    transport_provider, transport_model = route_identity(case.route_key)
    return MeasurementObservation(
        case=case,
        prompt_id=prompt.prompt_id,
        status=OBSERVATION_STATUS_UNSUPPORTED,
        transport_provider=transport_provider,
        transport_model=transport_model,
        search_call_count=0,
        wall_time_ms=0,
        queue_wait_ms=0,
        finish_reason=FINISH_REASON_NOT_EXECUTED,
        mention_count=0,
        citation_count=0,
        extracted_queries=(),
        note=(
            f"route {case.route_key} does not expose reasoning effort "
            f"{case.reasoning_effort!r}; cell not executed"
        ),
    )


async def run_matrix(
    *,
    cases: Sequence[MeasurementCase],
    prompts: Sequence[MeasurementPrompt],
    runner: MeasurementRunner,
    prompt_fixture_sha256: str | None = None,
) -> MeasurementRun:
    """Execute the sweep through ``runner`` and collect the run artifact.

    ``prompt_fixture_sha256`` is the digest of the artifact that produced
    ``prompts`` (see :func:`prompt_fixture_digest`). A caller that loaded a
    custom prompt file passes its digest; omitting it means the default
    fixture, which is then hashed here.
    """
    planned = len(cases) * len(prompts)
    if planned > measurement_settings.max_observations:
        raise MeasurementConfigurationError(
            f"sweep would emit {planned} observations, above the configured "
            f"ceiling {measurement_settings.max_observations}"
        )
    observations: list[MeasurementObservation] = []
    for case in cases:
        supported = is_reasoning_effort_supported(case.route_key, case.reasoning_effort)
        for prompt in prompts:
            if not supported:
                observations.append(_unsupported_observation(case, prompt))
                continue
            observations.append(await runner.observe(case, prompt))
    return MeasurementRun(
        run_id=uuid.uuid4().hex,
        source=runner.source,
        fixture_derived=bool(runner.fixture_derived),
        generated_at=datetime.now(UTC).isoformat(),
        schema_version=MEASUREMENT_ARTIFACT_SCHEMA_VERSION,
        script_version=MEASUREMENT_SCRIPT_VERSION,
        prompt_fixture_sha256=(
            prompt_fixture_sha256
            if prompt_fixture_sha256 is not None
            else prompt_fixture_digest()
        ),
        fixture_sha256=runner.fixture_hashes(),
        unset_pricing=UNSET_PRICING,
        observations=tuple(observations),
        prompt_count=len(prompts),
        case_count=len(cases),
        notes=_run_notes(runner),
    )


def _run_notes(runner: MeasurementRunner) -> tuple[str, ...]:
    if runner.fixture_derived:
        return (
            "SYNTHETIC: every value in this run is replayed from committed "
            "fixtures. It is NOT a measurement of any provider and cannot "
            "satisfy a promotion gate.",
        )
    return ()


def satisfies_live_gate(run: MeasurementRun) -> bool:
    """True only when this run may be used for a promotion gate decision.

    Fixture-derived output is never gate-eligible.
    """
    if run.fixture_derived:
        return False
    if GATE_REQUIRES_LIVE_SOURCE and run.source != SOURCE_LIVE:
        return False
    return True


# --- Fixture runner ------------------------------------------------------


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stable_index(key: str, modulus: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulus


def _optional_int(value: object) -> int | None:
    """Absent, malformed, non-finite, or negative -> ``None`` (never zero)."""
    if isinstance(value, bool) or value is None:
        return None
    if not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _required_int(value: object, *, label: str) -> int:
    parsed = _optional_int(value)
    if parsed is None:
        raise MeasurementConfigurationError(f"fixture envelope needs {label}")
    return parsed


class FixtureMeasurementRunner:
    """Replays committed SYNTHETIC envelopes; performs zero network I/O."""

    source = SOURCE_FIXTURES
    fixture_derived = True

    def __init__(self, *, fixture_dir_resolver=route_fixture_path) -> None:
        self._resolve = fixture_dir_resolver
        self._loaded: dict[tuple[str, bool], dict[str, Any]] = {}
        self._hashes: dict[str, str] = {}
        self._scoring = ScoringConfig.from_project(dict(MEASUREMENT_SCORING_SUBJECT))

    def fixture_hashes(self) -> dict[str, str]:
        return dict(self._hashes)

    def _fixture(self, route_key: str, *, search_enabled: bool) -> dict[str, Any]:
        cache_key = (route_key, search_enabled)
        cached = self._loaded.get(cache_key)
        if cached is not None:
            return cached
        path = self._resolve(route_key, search_enabled=search_enabled)
        payload = json.loads(path.read_text(encoding="utf-8"))
        envelopes = payload.get("envelopes")
        if not isinstance(envelopes, list) or not envelopes:
            raise MeasurementConfigurationError(f"{path} has no envelopes")
        self._loaded[cache_key] = payload
        # Route-qualified key so two routes' identically named files stay
        # distinguishable in the manifest.
        self._hashes[f"{path.parent.name}/{path.name}"] = sha256_file(path)
        return payload

    def _pick(self, case: MeasurementCase, prompt: MeasurementPrompt) -> dict[str, Any]:
        payload = self._fixture(case.route_key, search_enabled=case.search_enabled)
        envelopes: list[dict[str, Any]] = payload["envelopes"]
        key = "|".join(
            (
                case.route_key,
                str(case.search_enabled),
                case.reasoning_effort,
                case.output_treatment,
                str(case.repetition),
                prompt.prompt_id,
            )
        )
        return envelopes[_stable_index(key, len(envelopes))]

    async def observe(
        self, case: MeasurementCase, prompt: MeasurementPrompt
    ) -> MeasurementObservation:
        envelope = self._pick(case, prompt)
        return build_observation(
            case=case,
            prompt=prompt,
            envelope=envelope,
            scoring=self._scoring,
            note="synthetic fixture replay; not a provider measurement",
        )


def build_observation(
    *,
    case: MeasurementCase,
    prompt: MeasurementPrompt,
    envelope: dict[str, Any],
    scoring: ScoringConfig,
    note: str = "",
) -> MeasurementObservation:
    """Derive one observation from a normalized provider envelope."""
    transport_provider, transport_model = route_identity(case.route_key)
    search_events = list(envelope.get("search_events") or [])
    citations = list(envelope.get("citations") or [])
    timing = dict(envelope.get("timing") or {})
    usage = dict(envelope.get("usage") or {})
    score = score_execution(
        answer_text=str(envelope.get("answer_text") or ""),
        search_events=search_events,
        citations=citations,
        search_used=case.search_enabled and bool(search_events),
        config=scoring,
        prompt_text=prompt.text,
    )
    finish_reason = str(envelope.get("finish_reason") or "").strip()
    if not finish_reason:
        raise MeasurementConfigurationError(
            "envelope needs a canonical finish_reason; gates never read raw "
            "provider stop metadata"
        )
    return MeasurementObservation(
        case=case,
        prompt_id=prompt.prompt_id,
        status=OBSERVATION_STATUS_OK,
        transport_provider=transport_provider,
        transport_model=transport_model,
        search_call_count=len(search_events),
        wall_time_ms=_required_int(timing.get("wall_time_ms"), label="wall_time_ms"),
        queue_wait_ms=_required_int(timing.get("queue_wait_ms"), label="queue_wait_ms"),
        finish_reason=finish_reason,
        mention_count=_mention_count(score),
        citation_count=int(score["citation_count"]),
        extracted_queries=tuple(
            str(event.get("query") or "") for event in search_events
        ),
        uncached_input_tokens=_optional_int(usage.get("uncached_input_tokens")),
        cached_input_tokens=_optional_int(usage.get("cached_input_tokens")),
        output_tokens=_optional_int(usage.get("output_tokens")),
        reasoning_tokens=_optional_int(usage.get("reasoning_tokens")),
        provider_reported_cost_microusd=_optional_int(
            envelope.get("provider_reported_cost_microusd")
        ),
        # Never inferred from ``search_call_count``: a known zero search count
        # does not imply a known zero fee.
        search_fee_microusd=_optional_int(envelope.get("search_fee_microusd")),
        # Wall time is never relabelled TTFT.
        ttft_ms=_optional_int(timing.get("ttft_ms")),
        fixture_id=str(envelope.get("envelope_id") or ""),
        note=note,
    )


def _mention_count(score: dict[str, Any]) -> int:
    brand = 1 if score.get("brand_mentioned") else 0
    return brand + len(score.get("competitors_mentioned") or [])


# --- Summaries + output writing -----------------------------------------


def _observation_row(observation: MeasurementObservation) -> dict[str, Any]:
    row = asdict(observation)
    row["case"] = asdict(observation.case)
    row["extracted_queries"] = list(observation.extracted_queries)
    return row


def _sum_optional(values: Iterable[int | None]) -> int | None:
    """Sum only when EVERY input is known; one unknown makes the total null."""
    total = 0
    seen = False
    for value in values:
        if value is None:
            return None
        total += value
        seen = True
    return total if seen else None


def _cell_key(observation: MeasurementObservation) -> tuple[str, bool, str, str]:
    case = observation.case
    return (
        case.route_key,
        case.search_enabled,
        case.reasoning_effort,
        case.output_treatment,
    )


def summarize_route_costs(run: MeasurementRun) -> dict[str, Any]:
    """Per-cell cost lines, reporting known items separately.

    Reasoning and search lines are kept apart from token cost, and an unknown
    rate or usage leaves ``total_cost_microusd`` null rather than zero.
    """
    cells: dict[tuple[str, bool, str, str], list[MeasurementObservation]] = {}
    for observation in run.observations:
        if observation.status != OBSERVATION_STATUS_OK:
            continue
        cells.setdefault(_cell_key(observation), []).append(observation)
    return {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "source": run.source,
        "fixture_derived": run.fixture_derived,
        "unset_pricing": list(run.unset_pricing),
        "cells": [_cost_cell(key, rows) for key, rows in sorted(cells.items())],
        "unsupported_cells": sorted(
            {
                _cell_key(observation)[0] + ":" + _cell_key(observation)[2]
                for observation in run.observations
                if observation.status == OBSERVATION_STATUS_UNSUPPORTED
            }
        ),
    }


def _cost_cell(
    key: tuple[str, bool, str, str], rows: list[MeasurementObservation]
) -> dict[str, Any]:
    route_key, search_enabled, reasoning_effort, output_treatment = key
    provider_cost = _sum_optional(row.provider_reported_cost_microusd for row in rows)
    search_fee = _sum_optional(row.search_fee_microusd for row in rows)
    lines = {
        "uncached_input_tokens": _sum_optional(
            row.uncached_input_tokens for row in rows
        ),
        "cached_input_tokens": _sum_optional(row.cached_input_tokens for row in rows),
        "output_tokens": _sum_optional(row.output_tokens for row in rows),
        "reasoning_tokens": _sum_optional(row.reasoning_tokens for row in rows),
        "provider_reported_cost_microusd": provider_cost,
        "search_fee_microusd": search_fee,
    }
    known = provider_cost is not None and search_fee is not None
    return {
        "route_key": route_key,
        "search_enabled": search_enabled,
        "reasoning_effort": reasoning_effort,
        "output_treatment": output_treatment,
        "observation_count": len(rows),
        "search_call_count": sum(row.search_call_count for row in rows),
        "lines": lines,
        "cost_status": _cost_status(lines, known),
        "total_cost_microusd": (
            (provider_cost or 0) + (search_fee or 0) if known else None
        ),
    }


def _cost_status(lines: dict[str, int | None], known_total: bool) -> str:
    if known_total:
        return COST_STATUS_COMPLETE
    if any(value is not None for value in lines.values()):
        return COST_STATUS_PARTIAL
    return COST_STATUS_UNKNOWN


def _quantile(sorted_values: list[int], fraction: float) -> int | None:
    if not sorted_values:
        return None
    index = min(
        len(sorted_values) - 1,
        max(0, round(fraction * (len(sorted_values) - 1))),
    )
    return sorted_values[index]


def summarize_output_lengths(run: MeasurementRun) -> dict[str, Any]:
    """Output-token quantiles per (route, output treatment).

    Rows with unknown ``output_tokens`` are counted as unknown, never as zero.
    """
    buckets: dict[tuple[str, str], list[MeasurementObservation]] = {}
    for observation in run.observations:
        if observation.status != OBSERVATION_STATUS_OK:
            continue
        bucket = (observation.case.route_key, observation.case.output_treatment)
        buckets.setdefault(bucket, []).append(observation)
    return {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "source": run.source,
        "fixture_derived": run.fixture_derived,
        "quantiles": list(OUTPUT_LENGTH_QUANTILES),
        "buckets": [
            _length_bucket(bucket, rows) for bucket, rows in sorted(buckets.items())
        ],
    }


def _length_bucket(
    bucket: tuple[str, str], rows: list[MeasurementObservation]
) -> dict[str, Any]:
    route_key, output_treatment = bucket
    known = sorted(row.output_tokens for row in rows if row.output_tokens is not None)
    return {
        "route_key": route_key,
        "output_treatment": output_treatment,
        "observation_count": len(rows),
        "known_output_token_count": len(known),
        "unknown_output_token_count": len(rows) - len(known),
        "quantiles": {
            f"p{int(fraction * 100)}": _quantile(known, fraction)
            for fraction in OUTPUT_LENGTH_QUANTILES
        },
    }


def run_manifest(run: MeasurementRun) -> dict[str, Any]:
    """Provenance manifest: hashes, versions, summary, and unset pricing."""
    return {
        "schema_version": run.schema_version,
        "script_version": run.script_version,
        "run_id": run.run_id,
        "source": run.source,
        "fixture_derived": run.fixture_derived,
        "gate_eligible": satisfies_live_gate(run),
        "generated_at": run.generated_at,
        "prompt_fixture_sha256": run.prompt_fixture_sha256,
        "fixture_sha256": dict(sorted(run.fixture_sha256.items())),
        "unset_pricing": list(run.unset_pricing),
        "case_count": run.case_count,
        "prompt_count": run.prompt_count,
        "observation_count": len(run.observations),
        "unsupported_observation_count": sum(
            1
            for observation in run.observations
            if observation.status == OBSERVATION_STATUS_UNSUPPORTED
        ),
        "notes": list(run.notes),
        "route_costs": summarize_route_costs(run),
        "output_length_distribution": summarize_output_lengths(run),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )


def write_measurement_outputs(
    run: MeasurementRun, output_dir: Path
) -> tuple[Path, Path, Path]:
    """Write the three sweep artifacts (plus the provenance manifest).

    Returns ``(executions.jsonl, route-costs.json,
    output-length-distribution.json)``.
    """
    target = output_dir / run.run_id
    target.mkdir(parents=True, exist_ok=True)
    executions_path = target / EXECUTIONS_FILENAME
    with executions_path.open("w", encoding="utf-8") as handle:
        for observation in run.observations:
            handle.write(json.dumps(_observation_row(observation)) + "\n")
    route_costs_path = target / ROUTE_COSTS_FILENAME
    _write_json(route_costs_path, summarize_route_costs(run))
    distribution_path = target / OUTPUT_DISTRIBUTION_FILENAME
    _write_json(distribution_path, summarize_output_lengths(run))
    _write_json(target / RUN_MANIFEST_FILENAME, run_manifest(run))
    return executions_path, route_costs_path, distribution_path
