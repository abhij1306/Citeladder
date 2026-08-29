"""Phase 1 — DISCOVER: acquire one page and expand the URL frontier.

Each task resolves the shared robots policy, securely fetches its page, and
persists admissible link candidates. The crawl's independent ``site_setup``
task owns well-known files and sitemap ingestion.

The worker invokes this module through its explicit ``run(ctx, task)`` seam;
this remains in-process and does not own claiming or terminalization.
"""

from __future__ import annotations

import time

from app.analysis.site_health.parser import extract_page_facts
from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.core.config.site_health_acquisition import (
    ERROR_BOT_BLOCKED,
    FETCH_PURPOSE_DISCOVER,
)
from app.core.config.site_health_contracts import (
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import DOCUMENT_MEDIA_TYPES
from app.core.config.site_health_rules import (
    HTML_CONTENT_TYPES,
)
from app.domain.site_health.discovery import (
    extract_discovery_links,
)
from app.domain.site_health.schemas import (
    DiscoveryOutput,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.helpers import (
    _classify_http_error,
    _is_bot_block,
    _robots_denial_error,
    _serialize_redirect_chain,
)
from app.workers.site_health.phases.contracts import (
    DiscoverOutcome as _DiscoverOutcome,
)
from app.workers.site_health.phases.contracts import (
    PhaseContext,
)
from app.workers.site_health.phases.discover_stages import (
    _persist_discover,
    _persisted_discover_artifact_id,
)
from app.workers.site_health.urls import authority_key as _authority_key


async def run(ctx: PhaseContext, claimed: SiteCrawlTask) -> None:
    """Fetch + parse the target, then persist observation/admission atomically.

    Loads the crawl config in one short session, closes it before the fetch
    (no txn held across network I/O), fetches through the SSRF-safe fetcher
    while heartbeating the lease, and hands the bounded result to the
    persistence step, which re-checks ownership under a row lock.
    """
    # Discover evidence (artifact + observation + admission) commits before
    # ``_queue.succeed()``. If that out-of-transaction acknowledgement
    # fails, a reclaimed task must acknowledge the durable result instead
    # of refetching and colliding with the existing unique
    # ``(task_id, fetch_purpose)`` artifact row (mirrors the analyze flow).
    task_id = claimed.id
    crawl_id = claimed.crawl_id
    persisted_artifact_id = await _persisted_discover_artifact_id(ctx, task_id)
    if persisted_artifact_id is not None:
        await ctx.queue.succeed(
            task_id=task_id,
            owner=ctx.owner,
            result_artifact_id=persisted_artifact_id,
        )
        return

    async with ctx.session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        crawl = await session.get(SiteCrawl, crawl_id)
        if task is None or crawl is None:
            return
        kind = task.task_kind
        requested_url = task.requested_url
        depth = task.depth
        config = dict(crawl.configuration or {})
        root_registrable_domain = config.get("root_registrable_domain") or ""
        include_globs = config.get("include_globs")
        exclude_globs = config.get("exclude_globs")

    if kind != TASK_KIND_DISCOVER:
        # Routing is done in ``_execute_task``; a mis-routed kind here is a
        # wiring bug (never a silent no-op).
        raise NotImplementedError(f"unexpected task kind '{kind}'")

    # Heartbeat the lease across BOTH the slow fetch and the persist that
    # follows it (see ``_leased``): the write phase contends for the crawl
    # row, so leaving it unheartbeated is what let the sweeper reclaim a
    # task that was still writing.
    async with ctx.leased(task_id):
        outcome = await _fetch_discover(
            ctx,
            requested_url=requested_url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        )
        await _persist_discover(
            ctx,
            task_id=task_id,
            crawl_id=crawl_id,
            requested_url=requested_url,
            depth=depth,
            outcome=outcome,
        )


async def _fetch_discover(
    ctx: PhaseContext,
    *,
    requested_url: str,
    root_registrable_domain: str,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
) -> _DiscoverOutcome:
    """Fetch + parse one target into a bounded ``_DiscoverOutcome``.

    Returns the discovery output on success (2xx/3xx-final), a classified
    error token on an HTTP 4xx/5xx or a ``FetchError`` (SSRF, redirect
    limit, oversize, timeout, DNS). Never raises for an expected fetch
    failure — the caller persists an attempt row either way.

    Enforces the per-authority robots.txt policy before fetching (a denied URL
    short-circuits to ``ERROR_ROBOTS_DENIED`` without a request).

    A response carrying a challenge-platform marker classifies as
    ``ERROR_BOT_BLOCKED`` (terminal; presentation maps it to ``blocked``),
    never the generic ``ERROR_HTTP_4XX``.
    """
    authority = _authority_key(requested_url)
    policy = None
    if authority:
        policy, _, _ = await ctx.robots.ensure(authority)

    if policy is not None and not policy.can_fetch(requested_url):
        error_code, error_detail = _robots_denial_error(policy)
        return _DiscoverOutcome(
            error_code=error_code,
            error_detail=error_detail,
            retryable=False,
        )

    request = FetchRequest(
        url=requested_url,
        purpose=FETCH_PURPOSE_DISCOVER,
        allowed_content_types=HTML_CONTENT_TYPES | DOCUMENT_MEDIA_TYPES,
    )
    started = time.monotonic()
    try:
        async with ctx.new_fetcher() as fetcher:
            result = await fetcher.fetch(
                request,
                root_registrable_domain=root_registrable_domain or None,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=bool(root_registrable_domain),
            )
    except FetchError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return _DiscoverOutcome(
            error_code=exc.error_code,
            error_detail=str(exc),
            retryable=exc.retryable,
            latency_ms=latency,
            status_code=exc.status_code,
            retry_after_seconds=exc.retry_after_seconds,
            attempts=exc.attempts,
        )

    return _parse_discover_result(
        result,
        root_registrable_domain=root_registrable_domain,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
    )


def _parse_discover_result(
    result: FetchResult,
    *,
    root_registrable_domain: str,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
) -> _DiscoverOutcome:
    """Classify and parse one completed discovery response."""
    outcome = _DiscoverOutcome(
        result=result,
        attempts=result.attempts,
    )
    status = result.status_code
    if _is_bot_block(result):
        outcome.error_code = ERROR_BOT_BLOCKED
        outcome.latency_ms = result.latency_ms
        outcome.status_code = status
        return outcome
    classified = _classify_http_error(status)
    if classified is not None:
        outcome.error_code, outcome.retryable = classified
        outcome.latency_ms = result.latency_ms
        outcome.status_code = status
        return outcome
    if result.content_type in DOCUMENT_MEDIA_TYPES:
        outcome.output = DiscoveryOutput(
            requested_url=result.requested_url,
            final_url=result.final_url,
            status_code=status,
            content_type=result.content_type,
            title="",
            links=(),
            redirect_chain=tuple(_serialize_redirect_chain(result)),
        )
        return outcome

    facts = extract_page_facts(
        result.body,
        final_url=result.final_url or result.requested_url,
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
    # Success: parse in-scope canonical links (HTML only; empty otherwise).
    title, links = extract_discovery_links(
        result.body,
        base_url=result.final_url or result.requested_url,
        root_registrable_domain=root_registrable_domain,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        charset=result.charset,
    )
    output = DiscoveryOutput(
        requested_url=result.requested_url,
        final_url=result.final_url,
        status_code=status,
        content_type=result.content_type,
        title=title,
        links=tuple(links),
        redirect_chain=tuple(_serialize_redirect_chain(result)),
    )
    outcome.output = output
    outcome.facts = facts
    return outcome
