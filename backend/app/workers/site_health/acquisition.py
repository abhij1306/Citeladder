"""Persisted per-crawl host acquisition preference over attempt evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_acquisition import (
    ACQUISITION_TRIGGER_INITIAL,
    FETCH_ATTEMPT_OUTCOME_SUCCESS,
    FETCH_PURPOSE_DISCOVER,
)
from app.core.config.site_health_contracts import (
    ACQUISITION_TRIGGER_HOST_PREFERENCE,
    ACQUISITION_TRIGGER_HOST_PROBE,
    EXTRACTOR_VERSION,
    HOST_RUNG_BLOCK_THRESHOLD,
    HOST_RUNG_OBSERVATION_LIMIT,
    HOST_RUNG_PREFERENCE_WINDOW,
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import TASK_ACTIVE_STATUSES
from app.models.site_health.acquisition import SiteFetchArtifact, SiteFetchAttempt
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask

_BLOCKING_STATUSES = frozenset({403, 429})


@dataclass(frozen=True, slots=True)
class AcquisitionPlan:
    preferred_rung: int = 1
    trigger: str = ACQUISITION_TRIGGER_INITIAL


def plan_from_observations(rows: list[SiteFetchAttempt]) -> AcquisitionPlan:
    """Apply the fixed block/window/probe policy to newest-first observations."""
    rung_one = [row for row in rows if row.acquisition_rung == 1]
    if len(rung_one) < HOST_RUNG_BLOCK_THRESHOLD:
        return AcquisitionPlan()
    recent = rung_one[:HOST_RUNG_BLOCK_THRESHOLD]
    if any(row.status_code not in _BLOCKING_STATUSES for row in recent):
        return AcquisitionPlan()
    interval_start = recent[0].created_at
    preferred_tasks = {
        row.task_id
        for row in rows
        if row.acquisition_rung == 2
        and row.outcome == FETCH_ATTEMPT_OUTCOME_SUCCESS
        and row.created_at > interval_start
    }
    if len(preferred_tasks) >= HOST_RUNG_PREFERENCE_WINDOW:
        return AcquisitionPlan(trigger=ACQUISITION_TRIGGER_HOST_PROBE)
    return AcquisitionPlan(
        preferred_rung=2,
        trigger=ACQUISITION_TRIGGER_HOST_PREFERENCE,
    )


async def plan_host_acquisition(
    session: AsyncSession, *, crawl_id: uuid.UUID, url: str
) -> AcquisitionPlan:
    """Choose rung 1, rung 2, or the recovery probe from persisted attempts."""
    host = (urlsplit(url).hostname or "").casefold()
    if not host:
        return AcquisitionPlan()
    rows = list(
        (
            await session.scalars(
                select(SiteFetchAttempt)
                .where(
                    SiteFetchAttempt.crawl_id == crawl_id,
                    SiteFetchAttempt.target_host == host,
                    SiteFetchAttempt.acquisition_rung.in_((1, 2)),
                )
                .order_by(
                    SiteFetchAttempt.created_at.desc(), SiteFetchAttempt.id.desc()
                )
                .limit(HOST_RUNG_OBSERVATION_LIMIT)
            )
        ).all()
    )
    return plan_from_observations(rows)


async def reusable_discover_artifact(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
) -> tuple[tuple[uuid.UUID, dict] | None, bool]:
    """Resolve reusable discover facts or an in-flight prerequisite."""
    if task.site_url_id is None:
        return None, False
    row = (
        await session.execute(
            select(SiteFetchArtifact.id, SiteFetchArtifact.normalized_facts)
            .join(SiteCrawlTask, SiteCrawlTask.id == SiteFetchArtifact.task_id)
            .where(
                SiteFetchArtifact.crawl_id == crawl.id,
                SiteFetchArtifact.fetch_purpose == FETCH_PURPOSE_DISCOVER,
                SiteFetchArtifact.extractor_version
                == (crawl.extractor_version or EXTRACTOR_VERSION),
                SiteFetchArtifact.normalized_facts.is_not(None),
                SiteCrawlTask.url_hash == task.url_hash,
            )
            .order_by(SiteFetchArtifact.fetched_at.desc())
            .limit(1)
        )
    ).one_or_none()
    if row is not None:
        return (row[0], dict(row[1])), False
    pending = await session.scalar(
        select(SiteCrawlTask.id)
        .where(
            SiteCrawlTask.crawl_id == crawl.id,
            SiteCrawlTask.url_hash == task.url_hash,
            SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            SiteCrawlTask.status.in_(sorted(TASK_ACTIVE_STATUSES)),
        )
        .limit(1)
    )
    return None, pending is not None
