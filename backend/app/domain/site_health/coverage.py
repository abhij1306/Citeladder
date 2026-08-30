"""Conservative crawl-coverage assessment over persisted discovery state."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    DISCOVERY_STATUS_CANCELLED,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    DISCOVERY_STATUS_STOPPED,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    FRONTIER_PENDING,
    INPUT_MODE_AUTO,
)
from app.core.config.site_health_link_metrics import (
    COVERAGE_STATE_COMPLETE,
    COVERAGE_STATE_PARTIAL,
    COVERAGE_STATE_UNKNOWN,
)
from app.core.config.task_queue import TASK_STATUS_FAILED
from app.models.site_health.crawl import SiteCrawl, SiteDiscoveryFrontier
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrlObservation


@dataclass(frozen=True, slots=True)
class CoverageSignals:
    sample_mode: bool
    input_mode: str
    cancelled: bool
    discovery_status: str
    requested_page_limit: int
    frontier_limit: int
    admitted_url_count: int
    observation_count: int
    pending_frontier_count: int
    discovery_task_count: int
    failed_discovery_task_count: int


@dataclass(frozen=True, slots=True)
class CoverageAssessment:
    state: str
    evidence: dict[str, object]


def _partial_reasons(signals: CoverageSignals) -> list[str]:
    budget_hit = (
        signals.requested_page_limit > 0
        and signals.admitted_url_count >= signals.requested_page_limit
    )
    frontier_cap_hit = (
        signals.frontier_limit > 0
        and signals.admitted_url_count >= signals.frontier_limit
    )
    explicitly_bounded = (
        signals.sample_mode
        or signals.input_mode != INPUT_MODE_AUTO
        or signals.cancelled
        or signals.discovery_status
        in {
            DISCOVERY_STATUS_CANCELLED,
            DISCOVERY_STATUS_SAMPLE_COMPLETED,
            DISCOVERY_STATUS_STOPPED,
        }
        or signals.discovery_task_count == 0
    )
    reasons: list[str] = []
    if budget_hit:
        reasons.append("requested_page_limit_reached")
    if frontier_cap_hit:
        reasons.append("frontier_limit_reached")
    if signals.pending_frontier_count > 0:
        reasons.append("frontier_not_exhausted")
    if explicitly_bounded:
        reasons.append("discovery_bounded_or_stopped")
    return reasons


def _unknown_reasons(signals: CoverageSignals) -> list[str]:
    reasons: list[str] = []
    if signals.failed_discovery_task_count > 0:
        reasons.append("discovery_failed")
    if signals.observation_count == 0:
        reasons.append("no_observed_urls")
    if signals.discovery_status != DISCOVERY_STATUS_COMPLETED:
        reasons.append("discovery_not_completed")
    return reasons


def assess_coverage(signals: CoverageSignals) -> CoverageAssessment:
    """Return the safest coverage state supported by the frozen crawl facts."""
    reasons = _partial_reasons(signals)

    if reasons:
        state = COVERAGE_STATE_PARTIAL
    elif unknown_reasons := _unknown_reasons(signals):
        state = COVERAGE_STATE_UNKNOWN
        reasons.extend(unknown_reasons)
    else:
        state = COVERAGE_STATE_COMPLETE
        reasons.append("frontier_exhausted")

    return CoverageAssessment(
        state=state,
        evidence={
            "reasons": reasons,
            "requested_page_limit": signals.requested_page_limit,
            "frontier_limit": signals.frontier_limit,
            "admitted_url_count": signals.admitted_url_count,
            "observation_count": signals.observation_count,
            "pending_frontier_count": signals.pending_frontier_count,
            "discovery_task_count": signals.discovery_task_count,
            "failed_discovery_task_count": signals.failed_discovery_task_count,
        },
    )


async def crawl_coverage(
    session: AsyncSession, *, crawl: SiteCrawl
) -> CoverageAssessment:
    """Load crawl-scoped signals and assess coverage without live acquisition."""
    counts = (
        await session.execute(
            select(
                func.count(SiteCrawlTask.id).label("discovery_tasks"),
                func.count(SiteCrawlTask.id)
                .filter(SiteCrawlTask.status == TASK_STATUS_FAILED)
                .label("failed_discovery_tasks"),
            ).where(
                SiteCrawlTask.workspace_id == crawl.workspace_id,
                SiteCrawlTask.crawl_id == crawl.id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            )
        )
    ).one()
    pending_frontier_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SiteDiscoveryFrontier)
            .where(
                SiteDiscoveryFrontier.workspace_id == crawl.workspace_id,
                SiteDiscoveryFrontier.crawl_id == crawl.id,
                SiteDiscoveryFrontier.status == FRONTIER_PENDING,
            )
        )
        or 0
    )
    observation_count = int(
        await session.scalar(
            select(func.count())
            .select_from(SiteUrlObservation)
            .where(
                SiteUrlObservation.workspace_id == crawl.workspace_id,
                SiteUrlObservation.project_id == crawl.project_id,
                SiteUrlObservation.crawl_id == crawl.id,
            )
        )
        or 0
    )
    configuration = dict(crawl.configuration or {})
    requested_page_limit = int(
        crawl.discovery_requested_count
        or configuration.get("requested_page_limit")
        or 0
    )
    frontier_limit = int(configuration.get("max_frontier_urls") or 0)
    return assess_coverage(
        CoverageSignals(
            sample_mode=bool(crawl.sample_mode),
            input_mode=str(configuration.get("input_mode") or INPUT_MODE_AUTO),
            cancelled=crawl.status == CRAWL_STATUS_CANCELLED,
            discovery_status=crawl.discovery_status,
            requested_page_limit=requested_page_limit,
            frontier_limit=frontier_limit,
            admitted_url_count=int(crawl.admitted_url_count),
            observation_count=observation_count,
            pending_frontier_count=pending_frontier_count,
            discovery_task_count=int(counts.discovery_tasks or 0),
            failed_discovery_task_count=int(counts.failed_discovery_tasks or 0),
        )
    )


__all__ = [
    "CoverageAssessment",
    "CoverageSignals",
    "assess_coverage",
    "crawl_coverage",
]
