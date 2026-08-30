"""Crawl-level page-kind measurement projection."""

from __future__ import annotations

from collections.abc import Iterable

from app.analysis.site_health.scoring import (
    AnalysisMeasurementInput,
    aggregate_measurements,
)
from app.core.config.site_health_taxonomy import PAGE_KINDS


def aggregate_by_page_kind(
    analyses: Iterable[AnalysisMeasurementInput],
) -> dict[str, dict]:
    grouped: dict[str, list[AnalysisMeasurementInput]] = {}
    for analysis in analyses:
        grouped.setdefault(analysis.page_kind, []).append(analysis)
    ordered = [kind for kind in PAGE_KINDS if kind in grouped]
    ordered += sorted(kind for kind in grouped if kind not in PAGE_KINDS)
    result: dict[str, dict] = {}
    for page_kind in ordered:
        aggregate = aggregate_measurements(grouped[page_kind])
        result[page_kind] = {
            "analyzed_count": aggregate.analyzed_url_count,
            "technical_integrity_score": aggregate.technical_integrity_score,
            "technical_integrity_coverage": aggregate.technical_integrity_coverage,
            "technical_integrity_state": aggregate.technical_integrity_state,
            "aeo_readiness_score": aggregate.aeo_readiness_score,
            "aeo_measurement_coverage": aggregate.aeo_measurement_coverage,
            "aeo_measurement_state": aggregate.aeo_measurement_state,
        }
    return result
