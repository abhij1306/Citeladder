"""Approved unexpected crawl regressions from persisted Change Intelligence."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.opportunities import SITE_GAP_FACTOR, SITE_VALUE_FACTOR
from app.core.config.site_change_intel import (
    CHANGE_ANALYZER_VERSION,
    CHANGE_CLASS_CRITICAL,
    CHANGE_CLASS_REGRESSION,
    CHANGE_MAX_OBSERVATIONS,
    CHANGE_STATE_AVAILABLE,
)
from app.models.site_changes import SiteChangeObservation, SiteChangeSnapshot
from app.models.site_health.crawl import SiteCrawl

_RULE_BY_CLASS = {
    CHANGE_CLASS_REGRESSION: "site_change_potential_regression",
    CHANGE_CLASS_CRITICAL: "site_change_critical_regression",
}


async def load_change_hits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    crawl: SiteCrawl,
) -> list[DetectorHit]:
    """Load only approved, unexpected regressions for this exact newer crawl."""
    snapshot = await session.scalar(
        select(SiteChangeSnapshot)
        .where(
            SiteChangeSnapshot.workspace_id == workspace_id,
            SiteChangeSnapshot.project_id == crawl.project_id,
            SiteChangeSnapshot.crawl_b_id == crawl.id,
            SiteChangeSnapshot.state == CHANGE_STATE_AVAILABLE,
            SiteChangeSnapshot.analyzer_version == CHANGE_ANALYZER_VERSION,
            SiteChangeSnapshot.page_analyzer_version == crawl.analyzer_version,
            SiteChangeSnapshot.extractor_version == crawl.extractor_version,
        )
        .order_by(SiteChangeSnapshot.created_at.desc(), SiteChangeSnapshot.id.desc())
        .limit(1)
    )
    if snapshot is None:
        return []
    rows = list(
        (
            await session.scalars(
                select(SiteChangeObservation)
                .where(
                    SiteChangeObservation.workspace_id == workspace_id,
                    SiteChangeObservation.snapshot_id == snapshot.id,
                    SiteChangeObservation.expected.is_(False),
                    SiteChangeObservation.change_class.in_(_RULE_BY_CLASS),
                )
                .order_by(
                    SiteChangeObservation.normalized_url,
                    SiteChangeObservation.field,
                    SiteChangeObservation.id,
                )
                .limit(CHANGE_MAX_OBSERVATIONS)
            )
        ).all()
    )
    return [
        DetectorHit(
            rule_id=_RULE_BY_CLASS[row.change_class],
            target_key=f"site-change:{row.site_url_id}:{row.field}",
            target_prompt_id=None,
            target_url=row.normalized_url,
            target_theme=None,
            evidence={
                "change_snapshot_id": str(snapshot.id),
                "change_observation_id": str(row.id),
                "crawl_a_id": str(snapshot.crawl_a_id),
                "crawl_b_id": str(snapshot.crawl_b_id),
                "field": row.field,
                "before_value": row.before_value,
                "after_value": row.after_value,
                "change_class": row.change_class,
                "complete_pair": snapshot.complete_pair,
                "coverage": dict(snapshot.coverage or {}),
            },
            source_analysis_ids=tuple(
                str(value)
                for value in (row.source_analysis_a_id, row.source_analysis_b_id)
                if value is not None
            ),
            source_issue_ids=(),
            source_metric_ids=(str(snapshot.id), str(row.id)),
            value_factor=SITE_VALUE_FACTOR,
            gap_factor=SITE_GAP_FACTOR,
        )
        for row in rows
    ]


__all__ = ["load_change_hits"]
