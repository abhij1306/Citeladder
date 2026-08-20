#!/usr/bin/env python
# Offline answer-engine measurement sweep.
#
# Expands the measurement matrix (route x retrieval x route-supported reasoning
# effort x output treatment x repetition x fixed prompt), runs it, and writes
# ``executions.jsonl``, ``route-costs.json`` and
# ``output-length-distribution.json`` (plus a provenance manifest) under the
# output directory.
#
# SAFETY: the default source is ``fixtures`` and fixtures perform ZERO network
# I/O. A live run needs BOTH ``--live`` and ``--confirm <token>`` typed
# verbatim, and live execution is NOT implemented in this commit — it raises
# rather than degrading to fixtures, so an operator asking for live numbers can
# never be handed synthetic ones.
#
# Usage (from ``backend/``):
#
#     uv run python -m scripts.measure_answer_engine_matrix \
#         --source fixtures --output-dir var/measurements/test
#
# All dimensions, paths, thresholds and vocabularies live in
# ``app/core/config/measurement.py`` (invariant 1).
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path

from app.core.config.measurement import (
    DEFAULT_MEASUREMENT_SOURCE,
    LIVE_CONFIRMATION_TOKEN,
    MEASUREMENT_OUTPUT_DIR,
    MEASUREMENT_SOURCES,
    SOURCE_FIXTURES,
    SOURCE_LIVE,
    measurement_settings,
)
from evaluations.measurement.harness import (
    FixtureMeasurementRunner,
    LiveExecutionNotEnabledError,
    MeasurementConfigurationError,
    MeasurementRunner,
    expand_matrix,
    load_measurement_prompts,
    run_manifest,
    run_matrix,
    write_measurement_outputs,
)

logger = logging.getLogger("scripts.measure_answer_engine_matrix")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the answer-engine measurement matrix. Offline against "
            "committed synthetic fixtures by default; fixture output is "
            "labelled fixture_derived=true and can never satisfy a live gate."
        )
    )
    parser.add_argument(
        "--source",
        choices=sorted(MEASUREMENT_SOURCES),
        default=DEFAULT_MEASUREMENT_SOURCE,
        help="Where observations come from (default: fixtures, no network).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Second, explicit opt-in required alongside --source live. Live "
            "execution is not implemented in this commit."
        ),
    )
    parser.add_argument(
        "--confirm",
        default="",
        help=(
            "Typed confirmation token required for a live run "
            f"(exactly {LIVE_CONFIRMATION_TOKEN!r})."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(MEASUREMENT_OUTPUT_DIR),
        help="Directory to write the run subdirectory into.",
    )
    parser.add_argument(
        "--repetitions",
        type=int,
        default=measurement_settings.repetitions,
        help="Repetitions per matrix cell.",
    )
    return parser


def resolve_runner(args: argparse.Namespace) -> MeasurementRunner:
    """Pick the runner, failing closed on any partial live opt-in."""
    if args.source == SOURCE_FIXTURES:
        if args.live:
            raise MeasurementConfigurationError(
                "--live is meaningless with --source fixtures; drop one"
            )
        return FixtureMeasurementRunner()
    if not args.live:
        raise MeasurementConfigurationError(
            "--source live also requires the explicit --live flag"
        )
    if args.confirm != LIVE_CONFIRMATION_TOKEN:
        raise MeasurementConfigurationError(
            f"--source live requires --confirm {LIVE_CONFIRMATION_TOKEN}"
        )
    raise LiveExecutionNotEnabledError(
        "live provider measurement is not enabled in this commit; no live run "
        "has been performed and no measured number exists yet"
    )


async def _run(args: argparse.Namespace) -> int:
    runner = resolve_runner(args)
    prompts = load_measurement_prompts()
    cases = expand_matrix(repetitions=args.repetitions)
    run = await run_matrix(cases=cases, prompts=prompts, runner=runner)
    executions, route_costs, distribution = write_measurement_outputs(
        run, Path(args.output_dir)
    )
    manifest = run_manifest(run)
    logger.info(
        "measurement.run.complete run_id=%s source=%s fixture_derived=%s "
        "gate_eligible=%s cases=%s prompts=%s observations=%s unsupported=%s",
        run.run_id,
        run.source,
        run.fixture_derived,
        manifest["gate_eligible"],
        run.case_count,
        run.prompt_count,
        manifest["observation_count"],
        manifest["unsupported_observation_count"],
    )
    for path in (executions, route_costs, distribution):
        logger.info("measurement.run.artifact path=%s", path)
    logger.info(
        "measurement.run.unset_pricing %s", json.dumps(manifest["unset_pricing"])
    )
    if run.fixture_derived:
        logger.warning(
            "measurement.run.synthetic every value in this run is replayed "
            "from committed fixtures; it is NOT a provider measurement"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.source == SOURCE_LIVE:
        logger.warning("measurement.run.live_requested source=live")
    try:
        return asyncio.run(_run(args))
    except (MeasurementConfigurationError, LiveExecutionNotEnabledError) as error:
        parser.error(str(error))
        return 2


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
