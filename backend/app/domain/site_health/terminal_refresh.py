"""Exactly-once downstream refresh DAG for usable terminal crawl evidence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.traffic import TRAFFIC_GRANULARITY_DAY
from app.domain.analytics.enqueue import enqueue_demand_snapshot_refresh
from app.domain.opportunities.service import enqueue_opportunity_refresh
from app.domain.opportunities.verification import enqueue_implementation_verification
from app.models.site_health.crawl import SiteCrawl
from app.models.traffic import TrafficSnapshot


async def enqueue_terminal_analytics_refresh(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    change_snapshot_id: uuid.UUID | None,
) -> None:
    """Enqueue analytics after change persistence or crawl-evidence abstention.

    Every enqueue is transactionally idempotent on the crawl identity. Traffic
    evidence selects Demand as the predecessor and carries the crawl trigger
    through to Demand's eventual Opportunity enqueue. Site-only projects enqueue
    Opportunities directly. A terminal crawl with no usable HTML analysis uses
    its crawl identity so prior Site Opportunities can be superseded without
    inventing a graph snapshot.
    """
    trigger_kind = "site_change" if change_snapshot_id else "site_crawl"
    trigger_id = change_snapshot_id or crawl.id
    await enqueue_implementation_verification(
        session,
        workspace_id=crawl.workspace_id,
        project_id=crawl.project_id,
        trigger_kind="site_crawl",
        trigger_id=crawl.id,
    )
    traffic = await session.scalar(
        select(TrafficSnapshot)
        .where(
            TrafficSnapshot.workspace_id == crawl.workspace_id,
            TrafficSnapshot.project_id == crawl.project_id,
            TrafficSnapshot.granularity == TRAFFIC_GRANULARITY_DAY,
        )
        .order_by(
            TrafficSnapshot.window_end.desc(),
            TrafficSnapshot.created_at.desc(),
            TrafficSnapshot.id.desc(),
        )
        .limit(1)
    )
    if traffic is not None:
        await enqueue_demand_snapshot_refresh(
            session,
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            window_start=traffic.window_start,
            window_end=traffic.window_end,
            source_revision=f"{trigger_kind}:{trigger_id}",
            downstream_trigger_kind=trigger_kind,
            downstream_trigger_id=trigger_id,
        )
        return
    await enqueue_opportunity_refresh(
        session,
        workspace_id=crawl.workspace_id,
        project_id=crawl.project_id,
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
    )


__all__ = ["enqueue_terminal_analytics_refresh"]
