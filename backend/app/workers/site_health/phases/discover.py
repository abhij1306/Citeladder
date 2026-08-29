"""Phase 1 — DISCOVER: build the crawl's URL inventory.

Fetches the root, resolves and caches the per-authority robots.txt policy,
reads the well-known AI-crawler files, ingests sitemaps, and seeds the frontier
with admissible candidates. The depth-0 (root) task additionally performs site
setup, writing the crawl's site_facts.

Split out of SiteHealthWorker for readability only — see the package
docstring; this is a mixin on the one worker class, not a separate process.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from app.analysis.site_health.parser import extract_page_facts
from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health_acquisition import (
    ERROR_BOT_BLOCKED,
    FETCH_PURPOSE_DISCOVER,
    FETCH_PURPOSE_ROBOTS,
    ROBOTS_TXT_PATH,
    SITE_HEALTH_USER_AGENT,
)
from app.core.config.site_health_contracts import (
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import DOCUMENT_MEDIA_TYPES
from app.core.config.site_health_rules import (
    HTML_CONTENT_TYPES,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
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
from app.workers.site_health.outcomes import DiscoverOutcome as _DiscoverOutcome
from app.workers.site_health.phases.discover_stages import (
    DiscoverPersistenceMixin,
)
from app.workers.site_health.urls import authority_key as _authority_key


class DiscoverPhaseMixin(DiscoverPersistenceMixin):
    """TASK_KIND_DISCOVER handling."""

    async def _run_discover(self, task_id: uuid.UUID, crawl_id: uuid.UUID) -> None:
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
        persisted_artifact_id = await self._persisted_discover_artifact_id(task_id)
        if persisted_artifact_id is not None:
            await self._queue.succeed(
                task_id=task_id,
                owner=self.owner,
                result_artifact_id=persisted_artifact_id,
            )
            return

        async with self._session_factory() as session:
            task = await session.get(SiteCrawlTask, task_id)
            crawl = await session.get(SiteCrawl, crawl_id)
            if task is None or crawl is None:
                return
            kind = task.task_kind
            requested_url = task.requested_url
            depth = task.depth
            sample_mode = bool(crawl.sample_mode)
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
        async with self._leased(task_id):
            outcome = await self._fetch_discover(
                requested_url=requested_url,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                depth=depth,
                sample_mode=sample_mode,
            )
            await self._persist_discover(
                task_id=task_id,
                crawl_id=crawl_id,
                requested_url=requested_url,
                depth=depth,
                outcome=outcome,
            )

    async def _fetch_discover(
        self,
        *,
        requested_url: str,
        root_registrable_domain: str,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        depth: int,
        sample_mode: bool,
    ) -> _DiscoverOutcome:
        """Fetch + parse one target into a bounded ``_DiscoverOutcome``.

        Returns the discovery output on success (2xx/3xx-final), a classified
        error token on an HTTP 4xx/5xx or a ``FetchError`` (SSRF, redirect
        limit, oversize, timeout, DNS). Never raises for an expected fetch
        failure — the caller persists an attempt row either way.

        v2 P2: enforces the per-authority robots.txt policy before fetching
        (a denied URL short-circuits to ``ERROR_ROBOTS_DENIED`` without a
        request), and the depth-0 (root) task additionally runs the one-shot
        site setup — AI-crawler stance, llms.txt probe, and (Starter only)
        sitemap ingestion — whose bounded results ride the outcome into
        ``_persist_discover``.

        A response carrying a challenge-platform marker classifies as
        ``ERROR_BOT_BLOCKED`` (terminal; presentation maps it to ``blocked``),
        never the generic ``ERROR_HTTP_4XX``.
        """
        authority = _authority_key(requested_url)
        policy: RobotsPolicy | None = None
        robots_body: str | None = None
        robots_status: int | None = None
        if authority:
            policy, robots_body, robots_status = await self._ensure_robots_policy(
                authority
            )

        # Site setup runs at depth 0 even when the root page itself is
        # robots-denied or fails: the AI-crawler stance / llms.txt result is
        # site-level evidence the dashboard shows regardless (spec §5.3).
        site_facts: dict | None = None
        sitemap_urls: tuple[str, ...] = ()
        sitemap_files: tuple[str, ...] = ()
        if depth == 0:
            (
                site_facts,
                sitemap_urls,
                sitemap_files,
            ) = await self._site_setup(
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

        if policy is not None and not policy.can_fetch(requested_url):
            error_code, error_detail = _robots_denial_error(policy)
            return _DiscoverOutcome(
                error_code=error_code,
                error_detail=error_detail,
                retryable=False,
                site_facts=site_facts,
                sitemap_urls=sitemap_urls,
                sitemap_files=sitemap_files,
            )

        request = FetchRequest(
            url=requested_url,
            purpose=FETCH_PURPOSE_DISCOVER,
            allowed_content_types=HTML_CONTENT_TYPES | DOCUMENT_MEDIA_TYPES,
        )
        started = time.monotonic()
        try:
            async with self._new_fetcher() as fetcher:
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
                site_facts=site_facts,
                sitemap_urls=sitemap_urls,
                sitemap_files=sitemap_files,
            )

        return self._parse_discover_result(
            result,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            site_facts=site_facts,
            sitemap_urls=sitemap_urls,
            sitemap_files=sitemap_files,
        )

    def _parse_discover_result(
        self,
        result: FetchResult,
        *,
        root_registrable_domain: str,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        site_facts: dict | None,
        sitemap_urls: tuple[str, ...],
        sitemap_files: tuple[str, ...],
    ) -> _DiscoverOutcome:
        """Classify and parse one completed discovery response."""
        outcome = _DiscoverOutcome(
            result=result,
            attempts=result.attempts,
            site_facts=site_facts,
            sitemap_urls=sitemap_urls,
            sitemap_files=sitemap_files,
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

    def _cached_robots_entry(
        self, authority: str
    ) -> tuple[RobotsPolicy, str | None, int | None] | None:
        """The cached entry when present AND still within the config TTL."""
        cached = self._robots_cache.get(authority)
        if cached is None:
            return None
        fetched_at = self._robots_cache_ts.get(authority, 0.0)
        ttl = site_health_settings.robots_cache_ttl_seconds
        if time.monotonic() - fetched_at >= ttl:
            return None
        return cached

    async def _ensure_robots_policy(
        self, authority: str
    ) -> tuple[RobotsPolicy, str | None, int | None]:
        """Fetch + cache the per-authority robots.txt policy (fail-open).

        Returns ``(policy, body, status_code)``: the parsed policy for the
        crawler user-agent (allow-all on any fetch failure — standard
        crawler behavior, per ``RobotsPolicy``; a 5xx response is the
        RFC 9309 complete-temporary-disallow stance, a deny-all
        ``RobotsPolicy.deny_all``), the raw body (for the per-bot AI-crawler
        stance in site setup), and the HTTP status. The fetch goes through
        the SSRF-safe fetcher with a tight decoded-byte cap; a per-authority
        lock dedupes concurrent first fetches. Entries expire after
        ``robots_cache_ttl_seconds`` and are then EVICTED, with a hard
        ``robots_cache_max_authorities`` ceiling on top (see
        ``_prune_robots_cache``) so a long-lived worker retains bounded state.
        """
        cached = self._cached_robots_entry(authority)
        if cached is not None:
            return cached
        lock = self._robots_locks.setdefault(authority, asyncio.Lock())
        async with lock:
            cached = self._cached_robots_entry(authority)
            if cached is not None:
                return cached
            body_text: str | None = None
            status: int | None = None
            robots_url = f"{authority}{ROBOTS_TXT_PATH}"
            try:
                result = await self._fetch_well_known(
                    robots_url,
                    purpose=FETCH_PURPOSE_ROBOTS,
                    max_bytes=site_health_settings.robots_max_decoded_bytes,
                )
                if result is not None:
                    status = result.status_code
                    if 200 <= result.status_code < 300:
                        body_text = (result.body or b"").decode(
                            "utf-8", errors="replace"
                        )
            except Exception:  # noqa: BLE001 - robots fetch must never break a crawl
                body_text = None
                status = None
            if status is not None and 500 <= status < 600:
                # RFC 9309: a 5xx robots.txt is a complete (temporary)
                # disallow — deny fetches until the TTL re-read.
                policy = RobotsPolicy.deny_all(user_agent=SITE_HEALTH_USER_AGENT)
            else:
                # 2xx parses its body; 4xx / unfetchable is allow-all
                # (RFC 9309: no robots.txt == no restrictions).
                policy = RobotsPolicy.parse(
                    body_text or "", user_agent=SITE_HEALTH_USER_AGENT
                )
            entry = (policy, body_text, status)
            self._robots_cache[authority] = entry
            self._robots_cache_ts[authority] = time.monotonic()
            self._prune_robots_cache()
            return entry

    def _forget_robots(self, authority: str) -> None:
        """Drop one authority from all three robots maps.

        The lock is only released when it is NOT held: an in-flight fetch is
        still awaiting it, and replacing it mid-flight would let a second
        fetch for the same authority run concurrently.
        """
        self._robots_cache.pop(authority, None)
        self._robots_cache_ts.pop(authority, None)
        lock = self._robots_locks.get(authority)
        if lock is not None and not lock.locked():
            self._robots_locks.pop(authority, None)

    def _prune_robots_cache(self) -> None:
        """Evict TTL-expired authorities, then enforce the size ceiling.

        Expiry alone was only ever *checked* (``_cached_robots_entry`` returned
        None for a stale entry) and never removed, so all three maps grew for
        the life of the process.
        """
        now = time.monotonic()
        ttl = site_health_settings.robots_cache_ttl_seconds
        for authority in [
            a for a, ts in self._robots_cache_ts.items() if now - ts >= ttl
        ]:
            self._forget_robots(authority)

        cap = site_health_settings.robots_cache_max_authorities
        if cap <= 0 or len(self._robots_cache_ts) <= cap:
            return
        # Oldest first — the freshly written entry is the newest, so a prune
        # triggered by its own insert never evicts it.
        oldest = sorted(self._robots_cache_ts.items(), key=lambda kv: kv[1])
        for authority, _ts in oldest[: len(self._robots_cache_ts) - cap]:
            self._forget_robots(authority)

    async def _fetch_well_known(
        self, url: str, *, purpose: str, max_bytes: int
    ) -> FetchResult | None:
        """One bounded well-known-file fetch (robots/llms); None on failure.

        4xx/5xx responses are RETURNED (the caller reads the status) while
        ANY failure collapses to ``None`` — a missing or unfetchable well-known
        file is never a crawl error.

        The broad guard lives here rather than at each call site: it only ever
        caught ``FetchError``, so the robots caller wrapped it in its own
        ``except Exception`` while the llms.txt probe had no guard at all — an
        unexpected error there (a malformed authority reaching ``urlsplit``,
        say) aborted the whole depth-0 discover, losing site setup AND the root
        fetch. One boundary that actually keeps the docstring's promise.
        """
        request = FetchRequest(
            url=url,
            purpose=purpose,
            max_wire_bytes=max_bytes,
            max_decoded_bytes=max_bytes,
        )
        try:
            async with self._new_fetcher() as fetcher:
                return await fetcher.fetch(request, enforce_scope=False)
        except Exception:  # noqa: BLE001 - not BaseException: cancellation still propagates
            # Not BaseException: cancellation must still propagate.
            return None
