"""Post-link-metric deterministic observed architecture task handling."""

from __future__ import annotations

from sqlalchemy import select

from app.core.config.site_health_contracts import TASK_KIND_ARCHITECTURE
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.domain.site_health.architecture import persist_observed_architecture
from app.domain.site_health.task_guards import lease_is_owned
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.phases.contracts import PhaseContext


async def run(ctx: PhaseContext, claimed: SiteCrawlTask) -> None:
    """Persist architecture without network I/O or crawl-finalize coupling."""
    task_id = claimed.id
    crawl_id = claimed.crawl_id
    workspace_id = claimed.workspace_id
    async with ctx.leased(task_id):
        async with ctx.session_factory() as session:
            crawl = await session.scalar(
                select(SiteCrawl)
                .where(SiteCrawl.id == crawl_id, SiteCrawl.workspace_id == workspace_id)
                .with_for_update()
            )
            task = await session.scalar(
                select(SiteCrawlTask)
                .where(
                    SiteCrawlTask.id == task_id,
                    SiteCrawlTask.crawl_id == crawl_id,
                    SiteCrawlTask.workspace_id == workspace_id,
                    SiteCrawlTask.task_kind == TASK_KIND_ARCHITECTURE,
                )
                .with_for_update()
            )
            if (
                crawl is None
                or task is None
                or task.status != TASK_STATUS_RUNNING
                or not lease_is_owned(task, owner=ctx.owner)
            ):
                await session.rollback()
                return
            await persist_observed_architecture(session, crawl=crawl)
            await session.commit()
        await ctx.queue.succeed(task_id=task_id, owner=ctx.owner)


__all__ = ["run"]
