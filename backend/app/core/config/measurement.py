# Offline answer-engine measurement configuration (invariant 1: config lives in
# core/config, never inline in script/domain code).
#
# Owns every knob the measurement harness reads: the fixed prompt fixture path,
# the recorded route-fixture layout, the output directory + artifact filenames,
# the matrix dimensions (routes x retrieval x reasoning effort x output
# treatment x repetitions), the prompt-safety rules, the output-length quantiles
# and the candidate gate thresholds.
#
# IMPORTANT — measurement honesty rules encoded here:
#   * No number in this module is a measurement. The gate thresholds are
#     REQUIREMENTS a future live run must beat; they are not observations.
#   * ``UNSET_PRICING`` names the pricing inputs that are deliberately absent.
#     Anything reading them must fail closed rather than substitute zero.
#   * Fixture-derived runs are labelled ``fixture_derived=true`` and can never
#     satisfy a live gate (see ``app/domain/measurement/harness.py``).
from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    REASONING_EFFORT_LOW,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
)

# backend/app/core/config/measurement.py -> parents[3] == backend/
_BASE_DIR: Final[Path] = Path(__file__).resolve().parents[3]

# --- Artifact identity ----------------------------------------------------
# Bumped whenever the emitted artifact shape changes so an old run file is
# never silently reinterpreted under new field semantics.
MEASUREMENT_ARTIFACT_SCHEMA_VERSION: Final = "measurement-artifact-v1"
# Bumped whenever the sweep/derivation logic changes.
MEASUREMENT_SCRIPT_VERSION: Final = "measure-answer-engine-matrix-v1"

# --- Sources --------------------------------------------------------------
SOURCE_FIXTURES: Final = "fixtures"
SOURCE_LIVE: Final = "live"
MEASUREMENT_SOURCES: Final[tuple[str, ...]] = (SOURCE_FIXTURES, SOURCE_LIVE)
DEFAULT_MEASUREMENT_SOURCE: Final = SOURCE_FIXTURES
# A live run needs BOTH ``--live`` and this token typed verbatim. Two
# independent opt-ins so no CLI default, alias, or shell history can spend real
# provider credits by accident.
LIVE_CONFIRMATION_TOKEN: Final = "RUN-LIVE-MEASUREMENT"

# --- Paths ----------------------------------------------------------------
MEASUREMENT_FIXTURE_DIR: Final[Path] = (
    _BASE_DIR / "tests" / "fixtures" / "answer_engines"
)
MEASUREMENT_PROMPTS_PATH: Final[Path] = (
    MEASUREMENT_FIXTURE_DIR / "measurement_prompts.json"
)
# Live/local sweep output. Gitignored: only the committed manifest under
# ``backend/docs/measurements/`` is reviewed.
MEASUREMENT_OUTPUT_DIR: Final[Path] = _BASE_DIR / "var" / "measurements"
COMMITTED_MANIFEST_PATH: Final[Path] = (
    _BASE_DIR / "docs" / "measurements" / "v8" / "slice1-fixture-run.json"
)

EXECUTIONS_FILENAME: Final = "executions.jsonl"
ROUTE_COSTS_FILENAME: Final = "route-costs.json"
OUTPUT_DISTRIBUTION_FILENAME: Final = "output-length-distribution.json"
RUN_MANIFEST_FILENAME: Final = "run-manifest.json"

# --- Matrix dimensions ----------------------------------------------------
# Route keys are the logical engines; the transport/model provenance triple is
# resolved from ``provider_catalog.MEASUREMENT_ROUTES`` at sweep time.
MEASUREMENT_ROUTE_KEYS: Final[tuple[str, ...]] = (
    ENGINE_CHATGPT,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
)
# Recorded-fixture subdirectory per route (named by transport, matching the
# adapter modules).
MEASUREMENT_ROUTE_FIXTURE_DIRS: Final[dict[str, str]] = {
    ENGINE_CHATGPT: TRANSPORT_OPENAI,
    ENGINE_CLAUDE: TRANSPORT_ANTHROPIC,
    ENGINE_GEMINI: TRANSPORT_GOOGLE,
}

MEASUREMENT_SEARCH_STATES: Final[tuple[bool, ...]] = (False, True)

# Reasoning-effort sweep vocabulary. ``unset`` means "send no explicit effort
# and let the route default apply"; it is supported everywhere. Explicit
# efforts are swept only where the route exposes the knob today. The
# authoritative execution-time route policy is owned by
# ``config/provider_catalog.py`` (added by the route-policy commit); this map is
# the measurement sweep's view of it and exists so unsupported combinations are
# EMITTED as ``unsupported`` rather than silently dropped.
REASONING_EFFORT_UNSET: Final = "unset"
REASONING_EFFORT_MEDIUM: Final = "medium"
REASONING_EFFORT_HIGH: Final = "high"
MEASUREMENT_REASONING_EFFORTS: Final[tuple[str, ...]] = (
    REASONING_EFFORT_UNSET,
    REASONING_EFFORT_LOW,
    REASONING_EFFORT_MEDIUM,
    REASONING_EFFORT_HIGH,
)
ROUTE_REASONING_EFFORTS: Final[dict[str, tuple[str, ...]]] = {
    ENGINE_CHATGPT: MEASUREMENT_REASONING_EFFORTS,
    ENGINE_CLAUDE: (REASONING_EFFORT_UNSET,),
    ENGINE_GEMINI: (REASONING_EFFORT_UNSET,),
}

# --- Output treatments ----------------------------------------------------
OUTPUT_TREATMENT_BASELINE: Final = "baseline"
OUTPUT_TREATMENT_CONCISE: Final = "concise"
OUTPUT_TREATMENT_CAPPED_600: Final = "capped_600"
MEASUREMENT_OUTPUT_TREATMENTS: Final[tuple[str, ...]] = (
    OUTPUT_TREATMENT_BASELINE,
    OUTPUT_TREATMENT_CONCISE,
    OUTPUT_TREATMENT_CAPPED_600,
)
# Per-treatment output-token cap sent to the transport. ``None`` means "use the
# global ``provider_catalog_settings.max_output_tokens``".
OUTPUT_TREATMENT_MAX_TOKENS: Final[dict[str, int | None]] = {
    OUTPUT_TREATMENT_BASELINE: None,
    OUTPUT_TREATMENT_CONCISE: None,
    OUTPUT_TREATMENT_CAPPED_600: 600,
}

# --- Observation status vocabulary ---------------------------------------
OBSERVATION_STATUS_OK: Final = "ok"
OBSERVATION_STATUS_UNSUPPORTED: Final = "unsupported"
OBSERVATION_STATUS_ERROR: Final = "error"
# Placeholder finish reason for a row that never reached a provider.
FINISH_REASON_NOT_EXECUTED: Final = "not_executed"

# Cost roll-up status. ``unknown`` and ``partial`` both keep the total null.
COST_STATUS_COMPLETE: Final = "complete"
COST_STATUS_PARTIAL: Final = "partial"
COST_STATUS_UNKNOWN: Final = "unknown"

# --- Deterministic quality scoring ---------------------------------------
# Synthetic, non-project subject used only to exercise the deterministic
# scorer (``app/analysis/scoring.py``) against measurement answers. Never a real
# customer brand and never a project brand: the tracked brand/competitor list is
# never sent to a provider and never embedded in a committed fixture
# (invariant 6).
MEASUREMENT_SCORING_SUBJECT: Final[dict] = {
    "brand_name": "Northwind Robotics",
    "brand_aliases": ["Northwind"],
    "owned_domains": ["northwind-robotics.example"],
    "unintended_domains": [],
    "competitors": [
        {
            "name": "Contoso Systems",
            "aliases": ["Contoso"],
            "domains": ["contoso-systems.example"],
        },
    ],
}

# --- Prompt-set safety rules ---------------------------------------------
MEASUREMENT_PROMPT_MIN_COUNT: Final = 10
MEASUREMENT_PROMPT_MAX_COUNT: Final = 20
MEASUREMENT_PROMPT_MAX_CHARS: Final = 400
# Substrings that must never appear in a committed measurement prompt: project /
# customer brand identity. Matched case-insensitively.
FORBIDDEN_PROMPT_TERMS: Final[tuple[str, ...]] = (
    "citeladder",
    "northwind",
    "contoso",
    "best&less",
    "best & less",
    "best and less",
    "bestandless",
)
# Shapes that indicate a domain, an email address, a URL, or a credential leaked
# into a prompt. Matched as regular expressions, case-insensitively.
FORBIDDEN_PROMPT_PATTERNS: Final[tuple[str, ...]] = (
    r"[\w.+-]+@[\w-]+\.[\w.-]+",  # email address
    r"https?://",  # URL
    r"\b[\w-]+\.(?:com|net|org|io|ai|co|au|dev|app|example)\b",  # bare domain
    r"\b(?:sk|pk|rzp|api|secret|token|bearer)[-_][A-Za-z0-9]{6,}",  # credential
)

# --- Output-length distribution ------------------------------------------
OUTPUT_LENGTH_QUANTILES: Final[tuple[float, ...]] = (0.5, 0.9, 0.95)

# --- Candidate gate thresholds -------------------------------------------
# REQUIREMENTS, not observations. A pulse/concise candidate is only promoted
# once a LIVE run clears these. No value here is derived from, or evidence for,
# any figure quoted in the planning documents; those figures are UNVERIFIED.
GATE_MIN_COST_REDUCTION_PERCENT: Final = 25.0
GATE_MIN_LATENCY_REDUCTION_PERCENT: Final = 20.0
GATE_MAX_MENTION_RATE_REGRESSION_PERCENT: Final = 2.0
GATE_MAX_CITATION_RATE_REGRESSION_PERCENT: Final = 2.0
# A gate decision requires a live run: fixture-derived output can never satisfy
# it, however complete it looks.
GATE_REQUIRES_LIVE_SOURCE: Final = True

# --- Explicitly unset pricing -------------------------------------------
# Recorded verbatim in every run manifest. Consumers must fail closed on these
# rather than assume zero.
UNSET_PRICING: Final[tuple[str, ...]] = ("openai", "google", "all_per_search_fees")


class MeasurementSettings(BaseSettings):
    """Env-overridable measurement sweep knobs (invariant 1)."""

    model_config = SettingsConfigDict(env_prefix="MEASUREMENT_", extra="ignore")

    # Repetitions per (route, retrieval, reasoning, treatment, prompt) cell.
    repetitions: int = 3
    # Hard ceiling on emitted rows; a mis-specified sweep fails fast instead of
    # writing an unbounded artifact (or spending unbounded live credits).
    max_observations: int = 20_000


measurement_settings = MeasurementSettings()


def route_reasoning_efforts(route_key: str) -> tuple[str, ...]:
    """Reasoning-effort values the route supports in the measurement sweep."""
    return ROUTE_REASONING_EFFORTS.get(route_key, (REASONING_EFFORT_UNSET,))


def is_reasoning_effort_supported(route_key: str, reasoning_effort: str) -> bool:
    """True when the route exposes this explicit reasoning effort today."""
    return reasoning_effort in route_reasoning_efforts(route_key)


def output_treatment_max_tokens(output_treatment: str) -> int | None:
    """Output-token cap for a treatment, or ``None`` for the global default."""
    return OUTPUT_TREATMENT_MAX_TOKENS.get(output_treatment)


def route_fixture_dir(route_key: str) -> Path:
    """Directory holding the recorded fixtures for a route."""
    return MEASUREMENT_FIXTURE_DIR / MEASUREMENT_ROUTE_FIXTURE_DIRS.get(
        route_key, route_key
    )


def route_fixture_path(route_key: str, *, search_enabled: bool) -> Path:
    """Recorded fixture file for a (route, retrieval) pair."""
    state = "search_on" if search_enabled else "search_off"
    return route_fixture_dir(route_key) / f"measurement_{state}.json"
