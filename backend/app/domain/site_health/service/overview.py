"""Cohesive persisted Site Health Overview projection."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    resolve_usable_crawl,
)
from app.models.site_health.snapshot import SiteHealthSnapshot


def _stored(value: object, fallback: object) -> object:
    return fallback if value is None else value


def _overview_limitations(snapshot: SiteHealthSnapshot) -> list[str]:
    limitations: list[str] = []
    if snapshot.aeo_measurement_state != "measured":
        limitations.append(
            "AEO Readiness has limited evidence; broader page-purpose "
            "coverage is needed."
        )
    if snapshot.coverage_state != "complete":
        limitations.append(
            f"AEO Readiness describes {snapshot.analyzed_url_count} audited pages, "
            "not the whole site."
        )
    return limitations


async def get_overview(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    crawl = await resolve_usable_crawl(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
    )
    if crawl is None:
        raise SiteHealthNotFoundError("Site Health Overview is not available")
    snapshot = await session.scalar(
        select(SiteHealthSnapshot).where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
            SiteHealthSnapshot.crawl_id == crawl.id,
        )
    )
    if snapshot is None:
        raise SiteHealthNotFoundError("Site Health Overview is not available")
    return {
        "project_id": project_id,
        "crawl_id": crawl.id,
        "snapshot_id": snapshot.id,
        "search_eligibility": snapshot.search_eligibility,
        "eligibility_totals": _stored(snapshot.eligibility_totals, {}),
        "eligibility_reasons": _stored(snapshot.eligibility_reasons, []),
        "technical_integrity_score": snapshot.technical_integrity_score,
        "technical_integrity_coverage": snapshot.technical_integrity_coverage,
        "technical_integrity_state": snapshot.technical_integrity_state,
        "aeo_readiness_score": snapshot.aeo_readiness_score,
        "aeo_measurement_coverage": snapshot.aeo_measurement_coverage,
        "aeo_measurement_state": snapshot.aeo_measurement_state,
        "crawl_coverage": {
            "state": snapshot.coverage_state,
            "evidence": _stored(snapshot.coverage_evidence, {}),
            "denominator_kind": "selected_intended_public_urls",
        },
        "audited_page_count": snapshot.analyzed_url_count,
        "selected_page_count": snapshot.selected_url_count,
        "status_counts": _stored(snapshot.status_counts, {}),
        "aeo_dimensions": _stored(snapshot.readiness_dimensions, []),
        "top_issues": _stored(snapshot.top_issues, []),
        "web_fundamentals": _stored(
            snapshot.web_fundamentals,
            {
                "state": "not_measured",
                "areas": [],
                "field_data": {
                    "state": "unavailable",
                    "reason": "provider_not_configured",
                    "lcp": None,
                    "inp": None,
                    "cls": None,
                },
                "source_analysis_ids": [],
                "source_artifact_ids": [],
                "source_evaluation_ids": [],
                "limitations": [],
            },
        ),
        "trend": _stored(
            snapshot.trend,
            {"state": "unavailable", "reason": "projection_unavailable"},
        ),
        "change_summary": _stored(
            snapshot.change_summary,
            {"state": "unavailable", "reason": "projection_unavailable"},
        ),
        "limitations": _overview_limitations(snapshot),
    }


__all__ = ["get_overview"]
