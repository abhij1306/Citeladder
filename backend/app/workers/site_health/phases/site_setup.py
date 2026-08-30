"""Durable Site Health site-setup branch.

One task per crawl resolves robots and AI-crawler stance, probes llms.txt, walks
the bounded sitemap tree, and atomically persists site facts plus sitemap
admission. Root page acquisition proceeds independently on the same queue.
"""

from __future__ import annotations

import uuid

from app.core.config.site_health_contracts import TASK_KIND_SITE_SETUP
from app.core.config.site_health_crawl_policy import INPUT_MODE_EXACT_URLS
from app.domain.site_health.discovery import admit_candidates
from app.domain.site_health.entitlements import lock_runtime
from app.domain.site_health.task_guards import task_can_persist
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.phases.contracts import PhaseContext
from app.workers.site_health.phases.discover_stages import (
    build_sitemap_candidates,
    collect_site_setup,
    write_sitemap_observations,
)
from app.workers.site_health.urls import authority_key


async def run(ctx: PhaseContext, claimed: SiteCrawlTask) -> None:
    """Execute and persist the crawl's one idempotent setup branch."""
    task_id = claimed.id
    crawl_id = claimed.crawl_id
    async with ctx.session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        crawl = await session.get(SiteCrawl, crawl_id)
        if task is None or crawl is None:
            return
        if task.task_kind != TASK_KIND_SITE_SETUP:
            raise NotImplementedError(f"unexpected task kind '{task.task_kind}'")
        if crawl.site_facts is not None:
            await session.rollback()
            await ctx.queue.succeed(task_id=task_id, owner=ctx.owner)
            return
        requested_url = task.requested_url
        config = dict(crawl.configuration or {})
        root_registrable_domain = str(config.get("root_registrable_domain") or "")
        include_globs = config.get("include_globs")
        exclude_globs = config.get("exclude_globs")
        sample_mode = bool(crawl.sample_mode)

    async with ctx.leased(task_id):
        authority = authority_key(requested_url)
        policy = None
        robots_body: str | None = None
        robots_status: int | None = None
        if authority:
            policy, robots_body, robots_status = await ctx.robots.ensure(authority)
        site_facts, sitemap_urls = await collect_site_setup(
            ctx,
            requested_url=requested_url,
            authority=authority,
            robots_policy=policy,
            robots_body=robots_body,
            robots_status=robots_status,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            sample_mode=sample_mode,
        )
        persisted = await _persist_site_setup(
            ctx,
            task_id=task_id,
            crawl_id=crawl_id,
            site_facts=site_facts,
            sitemap_urls=sitemap_urls,
        )
    if persisted:
        await ctx.queue.succeed(task_id=task_id, owner=ctx.owner)


async def _persist_site_setup(
    ctx: PhaseContext,
    *,
    task_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_facts: dict,
    sitemap_urls: tuple[str, ...],
) -> bool:
    """Commit setup evidence and sitemap admission behind the final task guard."""
    async with ctx.session_factory() as session:
        task_hint = await session.get(SiteCrawlTask, task_id)
        crawl_hint = await session.get(SiteCrawl, crawl_id)
        if not task_can_persist(task_hint, crawl_hint, owner=ctx.owner):
            await session.rollback()
            return False
        assert task_hint is not None and crawl_hint is not None  # noqa: S101 - narrows for the type checker; not a runtime check

        admitted_delta = 0
        input_mode = (crawl_hint.configuration or {}).get("input_mode", "auto")
        if (
            sitemap_urls
            and not crawl_hint.sample_mode
            and input_mode != INPUT_MODE_EXACT_URLS
        ):
            runtime = await lock_runtime(session, crawl_hint.workspace_id)
            await session.refresh(crawl_hint, attribute_names=["admitted_url_count"])
            admitted_before = int(crawl_hint.admitted_url_count or 0)
            candidates = build_sitemap_candidates(sitemap_urls)
            admission = await admit_candidates(
                session,
                crawl=crawl_hint,
                candidates=candidates,
                runtime=runtime,
            )
            await write_sitemap_observations(
                session,
                crawl=crawl_hint,
                candidates=candidates,
                admission=admission,
            )
            admitted_delta = int(crawl_hint.admitted_url_count or 0) - admitted_before

        locked = await ctx.lock_owned_running_task(
            session, task_id=task_id, crawl_id=crawl_id
        )
        if locked is None:
            await session.rollback()
            return False
        task, crawl = locked
        crawl.site_facts = site_facts
        crawl.admitted_url_count += admitted_delta
        task.attempt_count += 1
        await session.commit()
        return True
