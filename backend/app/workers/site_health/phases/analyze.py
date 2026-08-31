"""Phase 2 — ANALYZE: fetch one monitored URL and persist its evidence.

The heart of the crawl. Fetches through the SSRF-safe ladder, extracts bounded
page facts, evaluates the per-page rule catalog, and writes ONE immutable
artifact plus derived evidence in a transaction finalized by locked guard checks.
The queue row is acknowledged after the durable analysis write.

The worker invokes this module through its explicit ``run(ctx, task)`` seam;
this remains in-process and does not own claiming or terminalization.
"""

from __future__ import annotations

import time
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.parser import extract_page_facts
from app.connectors.web_evidence.fetcher import FetchError, FetchRequest
from app.core.config.site_health_acquisition import (
    CLASSIFICATION_BODYLESS_STATUS_CODES,
    ERROR_BOT_BLOCKED,
    FETCH_PURPOSE_ANALYZE,
)
from app.core.config.site_health_contracts import (
    EVENT_ANALYSIS_PROGRESS,
    PAGE_ANALYSIS_STATUS_COMPLETED,
)
from app.core.config.site_health_rules import (
    HTML_CONTENT_TYPES,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.domain.commerce.service import enqueue_catalog_projection
from app.domain.site_health.state_events import record_crawl_event
from app.domain.site_health.task_guards import (
    evaluate_task_guard,
    lease_is_owned,
    lock_crawl_for_evidence_commit,
)
from app.models.site_health.analysis import (
    SitePageAnalysis,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from app.models.site_health.urls import MonitoredSiteUrl
from app.workers.site_health.acquisition import (
    reusable_discover_artifact,
    root_site_setup_pending,
)
from app.workers.site_health.helpers import (
    _classify_http_error,
    _count_disclosure,
    _is_bot_block,
    _robots_denial_error,
)
from app.workers.site_health.phases.analyze_rows import _write_page_analysis
from app.workers.site_health.phases.contracts import (
    AnalyzeOutcome as _AnalyzeOutcome,
)
from app.workers.site_health.phases.contracts import (
    PhaseContext,
)
from app.workers.site_health.urls import authority_key as _authority_key


def _has_analyzable_outcome(outcome: _AnalyzeOutcome) -> bool:
    return outcome.facts is not None and (
        outcome.result is not None or outcome.reused_artifact_id is not None
    )


async def _mark_classification_expected(
    ctx: PhaseContext, *, task_id: uuid.UUID
) -> bool:
    """Commit the supported-HTML classification cohort before parsing."""
    async with ctx.session_factory() as session:
        task = await session.get(
            SiteCrawlTask,
            task_id,
            populate_existing=True,
            with_for_update=True,
        )
        if task is None or not lease_is_owned(task, owner=ctx.owner):
            await session.rollback()
            return False
        task.classification_expected = True
        await session.commit()
        return True


async def run(ctx: PhaseContext, claimed: SiteCrawlTask) -> None:
    """Fetch + deep-analyze one monitored URL, persisting evidence atomically.

    Mirrors the discover flow: load config in one short session, fetch the
    URL through the SSRF-safe fetcher (heartbeating the lease), parse the
    bounded page facts, then persist ONE immutable artifact + attempt +
    page analysis + rule evaluations + issues + scores in a single
    transaction finalized by a ``FOR UPDATE`` owner/liveness re-check. The queue
    row is succeeded / retried / failed OUTSIDE that transaction.
    """
    # If evidence committed but the out-of-transaction queue acknowledgement
    # failed, a reclaimed task must acknowledge that durable result instead
    # of fetching and attempting the unique inserts again.
    task_id = claimed.id
    crawl_id = claimed.crawl_id
    workspace_id = claimed.workspace_id
    persisted_artifact_id = await _persisted_analysis_artifact_id(
        ctx, task_id, workspace_id
    )
    if persisted_artifact_id is not None:
        await _acknowledge_persisted_analysis(
            ctx, task_id=task_id, artifact_id=persisted_artifact_id
        )
        return

    async with ctx.session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        crawl = await session.get(SiteCrawl, crawl_id)
        if task is None or crawl is None:
            return
        guard = await _evaluate_analyze_guard(
            ctx, session, task=task, crawl=crawl, lock=False
        )
        if not guard.ok:
            await session.rollback()
            await ctx.queue.cancel(task_id=task_id)
            return
        requested_url = task.requested_url
        config = dict(crawl.configuration or {})
        root_registrable_domain = config.get("root_registrable_domain") or ""
        reusable, discover_pending = await reusable_discover_artifact(
            session, crawl=crawl, task=task
        )
        setup_pending = await root_site_setup_pending(session, crawl=crawl, task=task)

    if discover_pending or setup_pending:
        await ctx.queue.defer(
            task_id=task_id,
            owner=ctx.owner,
            delay_seconds=site_health_settings.analysis_dependency_retry_seconds,
        )
        return

    # One heartbeat across fetch + persist (see ``_leased``).
    async with ctx.leased(task_id):
        outcome = await _acquire_analyze_outcome(
            ctx,
            task_id=task_id,
            requested_url=requested_url,
            root_registrable_domain=root_registrable_domain,
            reusable=reusable,
        )
        if outcome is None:
            return
        await _persist_analyze(
            ctx,
            task_id=task_id,
            crawl_id=crawl_id,
            requested_url=requested_url,
            outcome=outcome,
        )


async def _acknowledge_persisted_analysis(
    ctx: PhaseContext, *, task_id: uuid.UUID, artifact_id: uuid.UUID
) -> None:
    """Acknowledge durable evidence only while this worker still owns the task."""
    if not await ctx.queue.mark_running(task_id=task_id, owner=ctx.owner):
        return
    await ctx.queue.succeed(
        task_id=task_id,
        owner=ctx.owner,
        result_artifact_id=artifact_id,
    )


async def _acquire_analyze_outcome(
    ctx: PhaseContext,
    *,
    task_id: uuid.UUID,
    requested_url: str,
    root_registrable_domain: str,
    reusable: tuple[uuid.UUID, dict] | None,
) -> _AnalyzeOutcome | None:
    """Reuse local evidence or acquire under host pacing after lease ownership."""
    if reusable is not None:
        if not await ctx.queue.mark_running(task_id=task_id, owner=ctx.owner):
            return None
        artifact_id, facts = reusable
        if facts.get("has_html"):
            await _mark_classification_expected(ctx, task_id=task_id)
        return _AnalyzeOutcome(facts=facts, reused_artifact_id=artifact_id)
    # Host politeness belongs to actual acquisition, not the task kind.
    async with ctx.host_slot(requested_url):
        if not await ctx.queue.mark_running(task_id=task_id, owner=ctx.owner):
            return None
        return await _fetch_analyze(
            ctx,
            task_id=task_id,
            requested_url=requested_url,
            root_registrable_domain=root_registrable_domain,
        )


async def _persisted_analysis_artifact_id(
    ctx: PhaseContext, task_id: uuid.UUID, workspace_id: uuid.UUID
) -> uuid.UUID | None:
    """Return durable analyze evidence for an idempotently reclaimed task."""
    async with ctx.session_factory() as session:
        return await session.scalar(
            select(SiteCrawlTask.result_artifact_id)
            .join(
                SitePageAnalysis,
                SitePageAnalysis.artifact_id == SiteCrawlTask.result_artifact_id,
            )
            .where(
                SiteCrawlTask.id == task_id,
                SiteCrawlTask.workspace_id == workspace_id,
                SitePageAnalysis.workspace_id == workspace_id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            )
            .limit(1)
        )


async def _evaluate_analyze_guard(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    task: SiteCrawlTask,
    crawl: SiteCrawl,
    lock: bool,
):
    """Evaluate Task 4's live membership/runtime guard from DB rows."""
    monitored_stmt = select(MonitoredSiteUrl).where(
        MonitoredSiteUrl.project_id == crawl.project_id,
        MonitoredSiteUrl.site_url_id == task.site_url_id,
    )
    runtime_stmt = select(WorkspaceSiteHealthRuntime).where(
        WorkspaceSiteHealthRuntime.workspace_id == crawl.workspace_id
    )
    if lock:
        monitored_stmt = monitored_stmt.with_for_update()
        runtime_stmt = runtime_stmt.with_for_update()
    monitored = (await session.execute(monitored_stmt)).scalar_one_or_none()
    runtime = (await session.execute(runtime_stmt)).scalar_one_or_none()
    return evaluate_task_guard(
        crawl=crawl,
        task=task,
        monitored=monitored,
        runtime=runtime,
        owner=ctx.owner,
    )


async def _lock_guarded_analyze_task(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    crawl_id: uuid.UUID,
) -> tuple[tuple[SiteCrawlTask, SiteCrawl] | None, bool]:
    """Lock live runtime/membership and the owned task before writes.

    The runtime row is the selection flow's serialization point, so lock it
    before membership/task rows to follow that flow's lock order and avoid
    deadlocks with a concurrent monitored-set replacement.

    Returns ``(locked_rows, guard_denied)``. ``guard_denied`` is true only
    while this worker still owns the task but live crawl/membership/
    runtime state blocks analysis; a lost lease is not ours to cancel.
    """
    task_hint = await session.get(SiteCrawlTask, task_id)
    crawl_hint = await session.get(SiteCrawl, crawl_id)
    if task_hint is None or crawl_hint is None:
        return None, False

    runtime = (
        await session.execute(
            select(WorkspaceSiteHealthRuntime)
            .where(WorkspaceSiteHealthRuntime.workspace_id == crawl_hint.workspace_id)
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    monitored = (
        await session.execute(
            select(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.project_id == crawl_hint.project_id,
                MonitoredSiteUrl.site_url_id == task_hint.site_url_id,
            )
            .execution_options(populate_existing=True)
            .with_for_update()
        )
    ).scalar_one_or_none()
    # Refresh identity-map rows under lock or stale counters lose increments.
    crawl = await lock_crawl_for_evidence_commit(
        session, workspace_id=crawl_hint.workspace_id, crawl_id=crawl_id
    )
    task = await session.get(
        SiteCrawlTask, task_id, with_for_update=True, populate_existing=True
    )
    decision = evaluate_task_guard(
        crawl=crawl,
        task=task,
        monitored=monitored,
        runtime=runtime,
        owner=ctx.owner,
    )
    if not decision.ok:
        still_owned = lease_is_owned(task, owner=ctx.owner)
        return None, still_owned
    if task is None or crawl is None:  # unreachable: guard checked both
        return None, False
    return (task, crawl), False


async def _fetch_analyze(
    ctx: PhaseContext,
    *,
    task_id: uuid.UUID,
    requested_url: str,
    root_registrable_domain: str,
) -> _AnalyzeOutcome:
    """Fetch + parse one monitored URL into a bounded ``_AnalyzeOutcome``.

    Returns parsed page facts on success (2xx), a classified error token on
    an HTTP 4xx/5xx or a ``FetchError``. Never raises for an expected fetch
    failure — the caller records an attempt row either way.

    v2 P2: enforces the per-authority robots.txt policy before fetching —
    a denied URL short-circuits to ``ERROR_ROBOTS_DENIED`` (non-retryable;
    presentation maps it to ``blocked`` via POLICY_BLOCKING_ERROR_CODES).

    A response carrying a challenge-platform marker classifies as terminal
    ``ERROR_BOT_BLOCKED`` (presentation: ``blocked``).
    """
    authority = _authority_key(requested_url)
    if authority:
        policy, _, _ = await ctx.robots.ensure(authority)
        if not policy.can_fetch(requested_url):
            error_code, error_detail = _robots_denial_error(policy)
            return _AnalyzeOutcome(
                error_code=error_code,
                error_detail=error_detail,
                retryable=False,
            )
    request = FetchRequest(
        url=requested_url,
        purpose=FETCH_PURPOSE_ANALYZE,
        allowed_content_types=HTML_CONTENT_TYPES,
    )
    started = time.monotonic()
    try:
        async with ctx.new_fetcher() as fetcher:
            result = await fetcher.fetch(
                request,
                root_registrable_domain=root_registrable_domain or None,
                enforce_scope=False,
            )
    except FetchError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _AnalyzeOutcome(
            error_code=exc.error_code,
            error_detail=str(exc),
            retryable=exc.retryable,
            latency_ms=latency,
            status_code=exc.status_code,
            retry_after_seconds=exc.retry_after_seconds,
            attempts=exc.attempts,
        )

    status = result.status_code
    # A challenge marker -> terminal ERROR_BOT_BLOCKED (see
    # ``_fetch_discover``); checked before status classification.
    if _is_bot_block(result):
        return _AnalyzeOutcome(
            result=result,
            error_code=ERROR_BOT_BLOCKED,
            retryable=False,
            latency_ms=result.latency_ms,
            status_code=status,
            attempts=result.attempts,
        )
    classified = _classify_http_error(status)
    if classified is not None:
        error_code, retryable = classified
        return _AnalyzeOutcome(
            result=result,
            error_code=error_code,
            retryable=retryable,
            latency_ms=result.latency_ms,
            status_code=status,
            attempts=result.attempts,
        )
    if status not in CLASSIFICATION_BODYLESS_STATUS_CODES:
        await _mark_classification_expected(ctx, task_id=task_id)

    facts = extract_page_facts(
        result.body,
        final_url=result.final_url or requested_url,
        content_type=result.content_type,
        charset=result.charset,
        status_code=status,
        redacted_headers=result.redacted_headers,
        http_version=result.http_version,
        ttfb_ms=result.ttfb_ms,
        latency_ms=result.latency_ms,
        wire_bytes=result.wire_bytes,
        decoded_bytes=result.decoded_bytes,
    )
    return _AnalyzeOutcome(
        result=result,
        facts=facts,
        status_code=status,
        latency_ms=result.latency_ms,
        attempts=result.attempts,
    )


async def _persist_analyze(
    ctx: PhaseContext,
    *,
    task_id: uuid.UUID,
    crawl_id: uuid.UUID,
    requested_url: str,
    outcome: _AnalyzeOutcome,
) -> None:
    """Persist the analyze result atomically, then finalize the queue row."""
    should_retry = False
    retry_attempt = 0
    succeeded_artifact_id: uuid.UUID | None = None
    guard_denied = False
    abandon = False
    async with ctx.session_factory() as session:
        context, guard_denied = await _analyze_preflight(
            ctx, session, task_id=task_id, crawl_id=crawl_id
        )
        if context is None:
            await session.rollback()
            abandon = not guard_denied
        else:
            task_hint, crawl_hint = context
            artifact_id: uuid.UUID | None = None
            if _has_analyzable_outcome(outcome):
                artifact_id = await _persist_successful_analysis(
                    ctx,
                    session,
                    crawl=crawl_hint,
                    task=task_hint,
                    requested_url=requested_url,
                    outcome=outcome,
                )
                succeeded_artifact_id = artifact_id

            # The final guard rolls staged writes back if liveness changed.
            locked, guard_denied = await _lock_guarded_analyze_task(
                ctx, session, task_id=task_id, crawl_id=crawl_id
            )
            if locked is None:
                await session.rollback()
                succeeded_artifact_id = None
                abandon = not guard_denied
            else:
                task, crawl = locked
                if artifact_id is None:
                    retry_attempt = task.attempt_count + 1
                    should_retry = (
                        outcome.retryable and retry_attempt < task.max_attempts
                    )
                if outcome.reused_artifact_id is None:
                    ctx.write_attempt(
                        session,
                        crawl=crawl,
                        task=task,
                        outcome=outcome,
                        succeeded=outcome.facts is not None,
                        requested_url=requested_url,
                        artifact_id=artifact_id,
                    )
                task.attempt_count += 1
                if artifact_id is not None:
                    task.result_artifact_id = artifact_id
                    crawl.analyzed_url_count += 1
                    record_crawl_event(
                        session,
                        crawl_id=crawl.id,
                        event_type=EVENT_ANALYSIS_PROGRESS,
                        message="analysis progress",
                        payload={"analyzed": crawl.analyzed_url_count},
                        count_disclosure=_count_disclosure(crawl),
                    )
                await session.commit()

    if guard_denied:
        await ctx.queue.cancel(task_id=task_id)
    elif not abandon:
        await ctx.finalize_queue_row(
            task_id=task_id,
            succeeded=succeeded_artifact_id is not None,
            succeeded_artifact_id=succeeded_artifact_id,
            should_retry=should_retry,
            retry_attempt=retry_attempt,
            error_code=outcome.error_code,
            error_detail=outcome.error_detail,
            retry_after_seconds=outcome.retry_after_seconds,
        )


async def _analyze_preflight(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    crawl_id: uuid.UUID,
) -> tuple[tuple[SiteCrawlTask, SiteCrawl] | None, bool]:
    """Load an unlocked snapshot and reject work that is already stale."""
    task = await session.get(SiteCrawlTask, task_id)
    crawl = await session.get(SiteCrawl, crawl_id)
    if task is None or crawl is None:
        return None, False
    guard = await _evaluate_analyze_guard(
        ctx, session, task=task, crawl=crawl, lock=False
    )
    if not guard.ok:
        return None, lease_is_owned(task, owner=ctx.owner)
    return (task, crawl), False


async def _persist_successful_analysis(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    requested_url: str,
    outcome: _AnalyzeOutcome,
) -> uuid.UUID:
    """Persist one successful fresh or artifact-reusing analysis."""
    artifact_id = outcome.reused_artifact_id
    if artifact_id is None and outcome.result is not None:
        artifact_id = await ctx.write_artifact(
            session,
            crawl=crawl,
            task=task,
            result=outcome.result,
            fetch_purpose=FETCH_PURPOSE_ANALYZE,
            normalized_facts=outcome.facts,
        )
    assert artifact_id is not None and outcome.facts is not None  # noqa: S101 - narrows for the type checker; not a runtime check
    analysis_id, page_kind = await _write_page_analysis(
        ctx,
        session,
        crawl=crawl,
        task=task,
        artifact_id=artifact_id,
        facts=outcome.facts,
    )
    if page_kind in {"category", "product"}:
        await enqueue_catalog_projection(
            session,
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            source_analysis_id=analysis_id,
        )
    return artifact_id
