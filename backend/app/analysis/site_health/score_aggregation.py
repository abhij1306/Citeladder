"""Crawl-level page-kind measurement projection."""

from __future__ import annotations

from collections.abc import Iterable

from app.analysis.site_health.scoring import (
    AnalysisMeasurementInput,
    RuleMeasurementInput,
    aggregate_measurements,
)
from app.core.config.site_health_rule_types import RULE_SCOPE_PAGE
from app.core.config.site_health_taxonomy import PAGE_KINDS


def aggregate_by_page_kind(
    analyses: Iterable[AnalysisMeasurementInput],
    rule_inputs: Iterable[RuleMeasurementInput],
) -> dict[str, dict]:
    rules = list(rule_inputs)
    grouped: dict[str, list[AnalysisMeasurementInput]] = {}
    for analysis in analyses:
        grouped.setdefault(analysis.page_kind, []).append(analysis)
    ordered = [kind for kind in PAGE_KINDS if kind in grouped]
    ordered += sorted(kind for kind in grouped if kind not in PAGE_KINDS)
    result: dict[str, dict] = {}
    for page_kind in ordered:
        kind_analyses = grouped[page_kind]
        analysis_ids = {row.analysis_id for row in kind_analyses}
        aggregate = aggregate_measurements(
            kind_analyses,
            (
                rule
                for rule in rules
                if rule.scope == RULE_SCOPE_PAGE and rule.analysis_id in analysis_ids
            ),
        )
        result[page_kind] = {
            "analyzed_count": aggregate.analyzed_url_count,
            "web_fundamentals_score": aggregate.web_fundamentals_score,
            "web_fundamentals_coverage": aggregate.web_fundamentals_coverage,
            "web_fundamentals_state": aggregate.web_fundamentals_state,
            "aeo_readiness_score": aggregate.aeo_readiness_score,
            "aeo_measurement_coverage": aggregate.aeo_measurement_coverage,
            "aeo_measurement_state": aggregate.aeo_measurement_state,
        }
    return result
