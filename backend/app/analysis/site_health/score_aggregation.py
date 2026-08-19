"""Crawl-level page-kind score projection."""

from __future__ import annotations

from collections.abc import Iterable

from app.analysis.site_health.scoring import PageKindScoreInput
from app.core.config.site_health_taxonomy import PAGE_KINDS


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _row_rollup(
    rows: list[PageKindScoreInput],
) -> dict[str, float | int | None]:
    return {
        "analyzed_count": len(rows),
        "technical_score": _mean(
            [
                float(row.technical_score)
                for row in rows
                if row.technical_score is not None
            ]
        ),
        "aeo_score": _mean(
            [float(row.aeo_score) for row in rows if row.aeo_score is not None]
        ),
        "overall_score": _mean(
            [float(row.overall_score) for row in rows if row.overall_score is not None]
        ),
    }


def aggregate_by_page_kind(
    analyses: Iterable[PageKindScoreInput],
) -> dict[str, dict[str, float | int | None]]:
    """Aggregate latest analysis scores in deterministic taxonomy order."""
    grouped: dict[str, list[PageKindScoreInput]] = {}
    for analysis in analyses:
        page_kind = str(analysis.page_kind)
        grouped.setdefault(page_kind, []).append(analysis)
    ordered = [kind for kind in PAGE_KINDS if kind in grouped]
    ordered += sorted(kind for kind in grouped if kind not in PAGE_KINDS)
    return {page_kind: _row_rollup(grouped[page_kind]) for page_kind in ordered}
