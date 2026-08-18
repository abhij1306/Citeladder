"""Honest bounded coverage metadata for Site Health-derived Opportunities."""

from __future__ import annotations

from app.core.config.site_health_contracts import (
    CRAWL_STATUS_COMPLETED,
)
from app.models.site_health.crawl import SiteCrawl


def site_coverage(crawl: SiteCrawl | None) -> tuple[dict, list[str]]:
    """Describe exactly how much of a terminal crawl feeds detection."""
    if crawl is None:
        return {}, []
    summary = crawl.score_summary or {}
    selected = int(
        summary.get("selected_count", crawl.analysis_requested_count or 0) or 0
    )
    analyzed = int(crawl.analyzed_url_count or 0)
    failed = int(crawl.failed_url_count or 0)
    coverage = {
        "crawl_status": crawl.status,
        "selected_url_count": selected,
        "analyzed_url_count": analyzed,
        "failed_url_count": failed,
        "analysis_ratio": round(analyzed / selected, 4) if selected else None,
    }
    limitations: list[str] = []
    if crawl.status != CRAWL_STATUS_COMPLETED:
        limitations.append(
            f"Site Health evidence is partial ({crawl.status}); "
            "only completed analyses are included."
        )
    if selected > analyzed:
        limitations.append(
            f"Coverage: {analyzed} of {selected} selected URLs analyzed."
        )
    return coverage, limitations
