"""Offline answer-engine measurement domain.

Owns the measurement sweep (matrix expansion, fixture replay, summary
derivation). No module here performs live provider I/O in this commit; the
committed runner replays synthetic fixtures and every run it emits is labelled
``fixture_derived=true``.
"""

from evaluations.measurement.harness import (
    FixtureMeasurementRunner,
    LiveExecutionNotEnabledError,
    MeasurementCase,
    MeasurementConfigurationError,
    MeasurementObservation,
    MeasurementPrompt,
    MeasurementRun,
    MeasurementRunner,
    expand_matrix,
    load_measurement_prompts,
    run_manifest,
    run_matrix,
    satisfies_live_gate,
    summarize_output_lengths,
    summarize_route_costs,
    write_measurement_outputs,
)

__all__ = [
    "FixtureMeasurementRunner",
    "LiveExecutionNotEnabledError",
    "MeasurementCase",
    "MeasurementConfigurationError",
    "MeasurementObservation",
    "MeasurementPrompt",
    "MeasurementRun",
    "MeasurementRunner",
    "expand_matrix",
    "load_measurement_prompts",
    "run_manifest",
    "run_matrix",
    "satisfies_live_gate",
    "summarize_output_lengths",
    "summarize_route_costs",
    "write_measurement_outputs",
]
