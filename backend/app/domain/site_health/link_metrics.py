"""Load persisted anchor evidence and write versioned per-page link metrics."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.link_graph import LinkPageInput, build_link_metrics
from app.core.config.site_health_contracts import PAGE_ANALYSIS_STATUS_COMPLETED
from app.core.config.site_health_link_metrics import (
    LINK_METRIC_FORMULA_VERSION,
    LINK_METRIC_TOP_NEIGHBOUR_LIMIT,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.urls import SiteUrl, SiteUrlObservation


async def _observation_aliases(
    session: AsyncSession, *, crawl: SiteCrawl
) -> dict[uuid.UUID, tuple[str, ...]]:
    rows = (
        await session.execute(
            select(
                SiteUrlObservation.site_url_id,
                SiteUrlObservation.observed_url,
                SiteUrlObservation.final_url,
            ).where(
                SiteUrlObservation.workspace_id == crawl.workspace_id,
                SiteUrlObservation.project_id == crawl.project_id,
                SiteUrlObservation.crawl_id == crawl.id,
            )
        )
    ).all()
    values: dict[uuid.UUID, set[str]] = defaultdict(set)
    for site_url_id, observed_url, final_url in rows:
        values[site_url_id].update(
            value for value in (observed_url, final_url) if value
        )
    return {
        site_url_id: tuple(sorted(aliases)) for site_url_id, aliases in values.items()
    }


async def _link_pages(
    session: AsyncSession, *, crawl: SiteCrawl
) -> list[LinkPageInput]:
    aliases = await _observation_aliases(session, crawl=crawl)
    rows = (
        await session.execute(
            select(SitePageAnalysis, SiteUrl, SiteFetchArtifact)
            .join(
                SiteUrl,
                SiteUrl.id == SitePageAnalysis.site_url_id,
            )
            .join(
                SiteFetchArtifact,
                SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
            )
            .where(
                SitePageAnalysis.workspace_id == crawl.workspace_id,
                SitePageAnalysis.project_id == crawl.project_id,
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                SitePageAnalysis.is_current.is_(True),
                SiteUrl.workspace_id == crawl.workspace_id,
                SiteUrl.project_id == crawl.project_id,
                SiteFetchArtifact.workspace_id == crawl.workspace_id,
                SiteFetchArtifact.crawl_id == crawl.id,
            )
            .order_by(SitePageAnalysis.site_url_id)
        )
    ).all()
    return [
        LinkPageInput(
            site_url_id=analysis.site_url_id,
            normalized_url=site_url.normalized_url,
            # The artifact is the acquired response and therefore owns the
            # redirect result. Early immutable observations can predate it.
            final_url=artifact.final_url or site_url.normalized_url,
            artifact_id=artifact.id,
            facts=dict(artifact.normalized_facts or {}),
            aliases=aliases.get(analysis.site_url_id, ()),
        )
        for analysis, site_url, artifact in rows
    ]


async def persist_link_metrics(session: AsyncSession, *, crawl: SiteCrawl) -> int:
    """Build the transient graph and insert one idempotent metric per page."""
    pages = await _link_pages(session, crawl=crawl)
    metrics = build_link_metrics(
        pages,
        home_url=crawl.root_url,
        neighbour_limit=LINK_METRIC_TOP_NEIGHBOUR_LIMIT,
    )
    if not metrics:
        return 0
    values = [
        {
            "workspace_id": crawl.workspace_id,
            "project_id": crawl.project_id,
            "crawl_id": crawl.id,
            "site_url_id": metric.site_url_id,
            "inbound_count": metric.inbound_count,
            "outbound_count": metric.outbound_count,
            "main_content_inbound_count": metric.main_content_inbound_count,
            "main_content_outbound_count": metric.main_content_outbound_count,
            "nofollow_inbound_count": metric.nofollow_inbound_count,
            "depth_from_home": metric.depth_from_home,
            "source_page_count": metric.source_page_count,
            "top_inbound": metric.top_inbound,
            "top_outbound": metric.top_outbound,
            "source_artifact_ids": metric.source_artifact_ids,
            "extractor_version": crawl.extractor_version,
            "formula_version": LINK_METRIC_FORMULA_VERSION,
        }
        for metric in metrics
    ]
    result = await session.execute(
        pg_insert(SitePageLinkMetric)
        .values(values)
        .on_conflict_do_nothing(constraint="uq_site_page_link_metric")
        .returning(SitePageLinkMetric.id)
    )
    return len(result.scalars().all())


__all__ = ["persist_link_metrics"]
