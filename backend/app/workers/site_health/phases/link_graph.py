"""Post-terminal crawl-scoped link-graph task handling."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.core.config.site_health import TASK_KIND_LINK_GRAPH
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.domain.site_health.link_graph import build_link_graph_snapshot
from app.domain.site_health.selection import lease_is_owned
from app.domain.site_health.terminal_refresh import enqueue_post_graph_refresh
from app.models.site_health import SiteCrawl, SiteCrawlTask
from app.workers.site_health.phases.support import PhaseSupport


class LinkGraphPhaseMixin(PhaseSupport):
    """TASK_KIND_LINK_GRAPH handling without network I/O."""

    async def _run_link_graph(
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
                        SiteCrawlTask.task_kind == TASK_KIND_LINK_GRAPH,
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
                snapshot = await build_link_graph_snapshot(session, crawl=crawl)
                if snapshot is None:
                    await session.rollback()
                    await self._queue.fail(
                        task_id=task_id,
                        owner=self.owner,
                        error_code="link_graph_unavailable",
                        error_detail=(
                            "No current successful HTML analyses were available."
                        ),
                    )
                    return
                await enqueue_post_graph_refresh(
                    session, crawl=crawl, graph_snapshot_id=snapshot.id
                )
                await session.commit()
            await self._queue.succeed(task_id=task_id, owner=self.owner)
