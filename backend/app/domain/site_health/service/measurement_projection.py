"""Shared serializer fields for one persisted page measurement."""

from __future__ import annotations

from app.domain.site_health.service.presentation import _iso
from app.models.site_health.analysis import SitePageAnalysis


def page_measurement_fields(analysis: SitePageAnalysis | None) -> dict:
    if analysis is None:
        return {
            "page_kind": None,
            "web_fundamentals_score": None,
            "web_fundamentals_coverage": None,
            "web_fundamentals_state": "not_measured",
            "aeo_readiness_score": None,
            "aeo_measurement_coverage": None,
            "aeo_measurement_state": "not_measured",
            "main_content_indexable": None,
            "last_audited": None,
        }
    return {
        "page_kind": analysis.page_kind,
        "web_fundamentals_score": analysis.web_fundamentals_score,
        "web_fundamentals_coverage": analysis.web_fundamentals_coverage,
        "web_fundamentals_state": analysis.web_fundamentals_state,
        "aeo_readiness_score": analysis.aeo_readiness_score,
        "aeo_measurement_coverage": analysis.aeo_measurement_coverage,
        "aeo_measurement_state": analysis.aeo_measurement_state,
        "main_content_indexable": analysis.main_content_indexable,
        "last_audited": _iso(analysis.finalized_at),
    }


__all__ = ["page_measurement_fields"]
