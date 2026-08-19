"""Post-crawl deterministic change-intelligence task handling."""

import uuid

from sqlalchemy import select

from app.core.config.site_health_contracts import (
    TASK_KIND_CHANGE_INTEL,
)
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.domain.site_health.change_intel import build_change_snapshot
from app.domain.site_health.task_guards import lease_is_owned
from app.domain.site_health.terminal_refresh import enqueue_terminal_analytics_refresh
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.phases.support import PhaseSupport


class ChangeIntelPhaseMixin(PhaseSupport):
    """Run one persisted comparison without network I/O."""

    async def _run_change_intel(
        self, task_id: uuid.UUID, crawl_id: uuid.UUID, workspace_id: uuid.UUID
    ) -> None:
        async with self._leased(task_id):
            async with self._session_factory() as session:
                crawl = await session.scalar(
                    select(SiteCrawl)
                    .where(
                        SiteCrawl.id == crawl_id,
                        SiteCrawl.workspace_id == workspace_id,
                    )
                    .with_for_update()
                )
                task = await session.scalar(
                    select(SiteCrawlTask)
                    .where(
                        SiteCrawlTask.id == task_id,
                        SiteCrawlTask.crawl_id == crawl_id,
                        SiteCrawlTask.workspace_id == workspace_id,
                        SiteCrawlTask.task_kind == TASK_KIND_CHANGE_INTEL,
                    )
                    .with_for_update()
                )
                if (
                    crawl is None
                    or task is None
                    or task.status != TASK_STATUS_RUNNING
                    or not lease_is_owned(task, owner=self.owner)
                ):
                    await session.rollback()
                    return
                snapshot = await build_change_snapshot(session, crawl_b=crawl)
                await enqueue_terminal_analytics_refresh(
                    session,
                    crawl=crawl,
                    change_snapshot_id=snapshot.id,
                )
                await session.commit()
            await self._queue.succeed(task_id=task_id, owner=self.owner)
