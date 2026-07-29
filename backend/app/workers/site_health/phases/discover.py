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

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.sitemaps import SitemapCollector, SitemapParseError
from app.connectors.web_evidence.url_policy import UrlPolicyError, is_admissible
from app.core.config.site_health import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_ALLOW,
    AI_CRAWLER_STANCE_BLOCK,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    ERROR_BOT_BLOCKED,
    EVENT_DISCOVERY_PROGRESS,
    FETCH_MODE_AUTO,
    FETCH_MODE_HTTP_ONLY,
    FETCH_PURPOSE_DISCOVER,
    FETCH_PURPOSE_LLMS,
    FETCH_PURPOSE_ROBOTS,
    FETCH_PURPOSE_SITEMAP,
    HTML_CONTENT_TYPES,
    LLMS_TXT_PATH,
    OBSERVATION_SOURCE_ROOT,
    OBSERVATION_SOURCE_SITEMAP,
    ROBOTS_TXT_PATH,
    SITE_HEALTH_USER_AGENT,
    SITEMAP_CONTENT_TYPES,
    SITEMAP_DEFAULT_PATHS,
    TASK_KIND_DISCOVER,
    site_health_settings,
)
from app.domain.site_health.discovery import (
    admit_candidates,
    build_frontier_candidates,
    extract_discovery_links,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import DiscoveryOutput, FrontierCandidate
from app.domain.site_health.state_events import (
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteUrlObservation,
)
from app.workers.site_health.helpers import (
    _classify_http_error,
    _count_disclosure,
    _is_exhausted_bot_block,
    _robots_denial_error,
    _serialize_redirect_chain,
)
from app.workers.site_health.outcomes import DiscoverOutcome as _DiscoverOutcome
from app.workers.site_health.phases.support import PhaseSupport
from app.workers.site_health.urls import authority_key as _authority_key


class DiscoverPhaseMixin(PhaseSupport):
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
            # The crawl's frozen fetch-ladder mode (v2 P3); absent on crawls
            # created before the freeze — default to the escalation ladder.
            fetch_mode = config.get("fetch_mode") or FETCH_MODE_AUTO

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
                fetch_mode=fetch_mode,
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
        fetch_mode: str = FETCH_MODE_AUTO,
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

        v2 P3: ``fetch_mode`` is the crawl's frozen fetch-ladder mode —
        ``http_only`` disables the impersonated rung-2 escalation. When BOTH
        rungs returned signature-detected bot blocks the outcome classifies
        as ``ERROR_BOT_BLOCKED`` (terminal; presentation maps it to
        ``blocked``), never the generic ``ERROR_HTTP_4XX``.
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
            allowed_content_types=HTML_CONTENT_TYPES,
            allow_escalation=fetch_mode != FETCH_MODE_HTTP_ONLY,
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

        status = result.status_code
        # v2 P3: an escalated fetch whose rung-2 response is ITSELF a
        # signature-detected block means both rungs were bot-blocked —
        # terminal ``ERROR_BOT_BLOCKED`` (presentation: ``blocked``), not the
        # generic 4xx token. Checked BEFORE status classification because a
        # challenge interstitial can even ride a 200.
        if _is_exhausted_bot_block(result):
            return _DiscoverOutcome(
                result=result,
                error_code=ERROR_BOT_BLOCKED,
                retryable=False,
                latency_ms=result.latency_ms,
                status_code=status,
                attempts=result.attempts,
                site_facts=site_facts,
                sitemap_urls=sitemap_urls,
                sitemap_files=sitemap_files,
            )
        # A 4xx/5xx is returned by the fetcher (not raised); classify it.
        classified = _classify_http_error(status)
        if classified is not None:
            error_code, retryable = classified
            return _DiscoverOutcome(
                result=result,
                error_code=error_code,
                retryable=retryable,
                latency_ms=result.latency_ms,
                status_code=status,
                attempts=result.attempts,
                site_facts=site_facts,
                sitemap_urls=sitemap_urls,
                sitemap_files=sitemap_files,
            )

        # Success: parse in-scope canonical links (HTML only; empty otherwise).
        title, links = extract_discovery_links(
            result.body,
            base_url=result.final_url or requested_url,
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
        return _DiscoverOutcome(
            result=result,
            output=output,
            attempts=result.attempts,
            site_facts=site_facts,
            sitemap_urls=sitemap_urls,
            sitemap_files=sitemap_files,
        )

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
        ``robots_cache_ttl_seconds``; the cache maps are bounded by distinct
        authorities per worker process (a crawl is scoped to one registrable
        domain).
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
            except Exception:  # defensive: robots must never break a crawl
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
            return entry

    async def _fetch_well_known(
        self, url: str, *, purpose: str, max_bytes: int
    ) -> FetchResult | None:
        """One bounded well-known-file fetch (robots/llms); None on failure.

        4xx/5xx responses are RETURNED (the caller reads the status) while
        transport/policy failures collapse to ``None`` — a missing or
        unfetchable well-known file is never a crawl error.
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
        except FetchError:
            return None

    async def _site_setup(
        self,
        *,
        requested_url: str,
        authority: str,
        robots_policy: RobotsPolicy | None,
        robots_body: str | None,
        robots_status: int | None,
        root_registrable_domain: str,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        sample_mode: bool,
    ) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
        """The one-shot site crawl setup run by the depth-0 discover task.

        Builds the bounded ``site_facts`` display/injection copy (robots
        AI-crawler stance + llms.txt result + sitemap file list — NO
        discovered totals, so Free non-disclosure holds), probes llms.txt,
        and (Starter only — Free sample crawls skip sitemap page ingestion so
        un-admitted URLs never leak into inventory) ingests the sitemap tree
        into a bounded, in-scope URL list. Network I/O only; the caller
        persists under the crawl lock.
        """
        # AI-crawler stance: re-parse the SAME raw robots body per bot and
        # ask whether that bot may fetch the root URL. A missing/failed
        # robots fetch is allow-all (fail-open).
        stance: dict[str, str] = {}
        for bot in AI_CRAWLER_BOTS:
            allowed = True
            if robots_body:
                allowed = RobotsPolicy.parse(robots_body, user_agent=bot).can_fetch(
                    requested_url
                )
            stance[bot] = (
                AI_CRAWLER_STANCE_ALLOW if allowed else AI_CRAWLER_STANCE_BLOCK
            )
        declared_sitemaps: list[str] = []
        if robots_policy is not None:
            declared_sitemaps = [
                str(url)[:2048] for url in robots_policy.sitemaps()[:16]
            ]

        # llms.txt probe (honors the same robots policy — a good citizen).
        llms_url = f"{authority}{LLMS_TXT_PATH}" if authority else ""
        llms_fetched = False
        llms_status: int | None = None
        llms_present = False
        if llms_url and (robots_policy is None or robots_policy.can_fetch(llms_url)):
            result = await self._fetch_well_known(
                llms_url,
                purpose=FETCH_PURPOSE_LLMS,
                max_bytes=site_health_settings.llms_txt_max_decoded_bytes,
            )
            if result is not None:
                llms_fetched = True
                llms_status = result.status_code
                llms_present = 200 <= result.status_code < 300 and bool(
                    (result.body or b"").strip()
                )

        # Sitemap ingestion: Starter crawls only (Free sample crawls record
        # no sitemap URLs — see the docstring above).
        sitemap_urls: tuple[str, ...] = ()
        sitemap_files: tuple[str, ...] = ()
        if not sample_mode and authority:
            seeds = declared_sitemaps or [
                f"{authority}{path}" for path in SITEMAP_DEFAULT_PATHS
            ]
            sitemap_urls, sitemap_files = await self._ingest_sitemaps(
                seeds,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
            )

        site_facts = {
            "robots": {
                "fetched": robots_body is not None,
                "url": f"{authority}{ROBOTS_TXT_PATH}" if authority else "",
                "status_code": robots_status,
                "ai_crawlers": stance,
                "sitemaps": declared_sitemaps,
            },
            "llms_txt": {
                "fetched": llms_fetched,
                "url": llms_url,
                "status_code": llms_status,
                "present": llms_present,
            },
            "sitemap": {
                "fetched": bool(sitemap_files),
                "files": list(sitemap_files)[
                    : site_health_settings.max_sitemap_documents
                ],
            },
        }
        return site_facts, sitemap_urls, sitemap_files

    async def _ingest_sitemaps(
        self,
        seeds: list[str],
        *,
        root_registrable_domain: str,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Bounded, loop-safe sitemap-tree walk into in-scope canonical URLs.

        Fetches up to ``max_sitemap_documents`` sitemap documents BFS-style
        (robots-honored per authority, sitemap-index recursion capped by the
        ``SitemapCollector``), then canonicalizes, scope-filters
        (``is_admissible``), de-duplicates, and caps the extracted page URLs
        at ``max_sitemap_admitted_urls``. Returns ``(page_urls, file_urls)``,
        both deterministically ordered. Every fetch/parse failure simply
        skips that document — sitemap ingestion is best-effort evidence.
        """
        settings = site_health_settings
        collector = SitemapCollector()
        files: list[str] = []
        queue: list[tuple[str, int]] = [(seed, 0) for seed in seeds]
        queued = {seed for seed in seeds}
        async with self._new_fetcher() as fetcher:
            while queue and len(files) < settings.max_sitemap_documents:
                url, depth = queue.pop(0)
                if url in files:
                    continue
                authority = _authority_key(url)
                if authority:
                    policy, _, _ = await self._ensure_robots_policy(authority)
                    if not policy.can_fetch(url):
                        continue
                try:
                    result = await fetcher.fetch(
                        FetchRequest(
                            url=url,
                            purpose=FETCH_PURPOSE_SITEMAP,
                            allowed_content_types=SITEMAP_CONTENT_TYPES,
                            max_decoded_bytes=settings.max_sitemap_decoded_bytes,
                        ),
                        enforce_scope=False,
                    )
                except FetchError:
                    continue
                if not (200 <= result.status_code < 300):
                    continue
                files.append(url)
                try:
                    child_refs = collector.add_document(
                        url,
                        result.body,
                        content_type=result.content_type,
                        depth=depth,
                    )
                except SitemapParseError:
                    continue
                for ref in child_refs:
                    if ref not in queued:
                        queued.add(ref)
                        queue.append((ref, depth + 1))

        page_urls: list[str] = []
        seen_hashes: set[str] = set()
        for raw in collector.urls:
            if len(page_urls) >= settings.max_sitemap_admitted_urls:
                break
            try:
                canonical, url_hash_value = canonical_identity(raw)
            except UrlPolicyError:
                continue
            if url_hash_value in seen_hashes:
                continue
            if not is_admissible(
                canonical,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
            ):
                continue
            seen_hashes.add(url_hash_value)
            page_urls.append(canonical)
        return tuple(page_urls), tuple(files)

    async def _persist_discover(
        self,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
        requested_url: str,
        depth: int,
        outcome: _DiscoverOutcome,
    ) -> None:
        """Persist the discover result atomically, then finalize the queue row.

        All evidence (observation + attempt + optional artifact) and inventory
        mutations (admitted rows, counter bumps, child enqueues) commit in ONE
        transaction, gated by a ``FOR UPDATE`` owner/liveness re-check so a
        lost-lease or cancelled task persists nothing. The queue row is then
        succeeded / retried / failed OUTSIDE that transaction.
        """
        should_retry = False
        should_fail = False
        retry_attempt = 0
        succeeded_artifact_id: uuid.UUID | None = None
        async with self._session_factory() as session:
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, crawl_id=crawl_id
            )
            if locked is None:
                # Lease lost or crawl cancelled/terminal: discard everything.
                await session.rollback()
                return
            task, crawl = locked

            # v2 P2: the root task's site setup persists its bounded facts
            # even when the root page fetch itself failed — the AI-crawler
            # stance / llms.txt result is site-level evidence that stays
            # visible on the dashboard (spec §5.3).
            if depth == 0 and outcome.site_facts is not None:
                crawl.site_facts = outcome.site_facts

            artifact_id: uuid.UUID | None = None
            if outcome.output is not None and outcome.result is not None:
                # Success: write the immutable artifact + observation, admit the
                # frontier, and bump counters — all in this one transaction.
                artifact_id = await self._write_artifact(
                    session,
                    crawl=crawl,
                    task=task,
                    result=outcome.result,
                )
                await self._write_observation(
                    session,
                    crawl=crawl,
                    task=task,
                    output=outcome.output,
                    depth=depth,
                    artifact_id=artifact_id,
                )
                admission = await admit_candidates(
                    session,
                    crawl=crawl,
                    candidates=self._candidates_for(outcome.output, depth),
                )
                # v2 P2 (Starter only): admit the sitemap-ingested URLs AFTER
                # the root's own admission, so the root's frontier priority
                # holds and admission order stays deterministic; then write
                # their sparse admission-time observation rows (mirrors
                # ``_add_free_sample``) so sitemap-sourced URLs appear in
                # inventory. Free sample crawls never ingest sitemaps, so
                # un-admitted URLs never leak into a Free inventory.
                if depth == 0 and outcome.sitemap_urls and not crawl.sample_mode:
                    sitemap_candidates = self._sitemap_candidates(outcome.sitemap_urls)
                    sitemap_admission = await admit_candidates(
                        session,
                        crawl=crawl,
                        candidates=sitemap_candidates,
                    )
                    await self._write_sitemap_observations(
                        session,
                        crawl=crawl,
                        candidates=sitemap_candidates,
                        admission=sitemap_admission,
                    )
                crawl.discovered_url_count += 1
                # Link the queue row to its immutable artifact (mirrors the
                # audit worker's result_artifact_id contract).
                task.result_artifact_id = artifact_id
                succeeded_artifact_id = artifact_id
                if admission.sample_capped:
                    # Free stop-at-10: terminate discovery at the cap. No
                    # total-bearing value is computed or persisted.
                    apply_discovery_status(crawl, DISCOVERY_STATUS_SAMPLE_COMPLETED)
                record_crawl_event(
                    session,
                    crawl_id=crawl_id,
                    event_type=EVENT_DISCOVERY_PROGRESS,
                    message="discovery progress",
                    payload={
                        "admitted": admission.admitted,
                        "depth": depth,
                    },
                    count_disclosure=_count_disclosure(crawl),
                )
            else:
                # Failure path: append the attempt, bump the failed counter, and
                # decide retry vs. terminal fail from the retry budget.
                exhausted = task.attempt_count + 1 >= task.max_attempts
                should_retry = outcome.retryable and not exhausted
                should_fail = not should_retry
                # Attempt number this failure represents (1-based), used to
                # grow the backoff deterministically across retries.
                retry_attempt = task.attempt_count + 1
                if should_fail:
                    crawl.failed_url_count += 1

            self._write_attempt(
                session,
                crawl=crawl,
                task=task,
                outcome=outcome,
                succeeded=outcome.output is not None,
                requested_url=requested_url,
                artifact_id=artifact_id,
            )
            task.attempt_count += 1
            await session.commit()

        await self._finalize_queue_row(
            task_id=task_id,
            succeeded=outcome.output is not None,
            succeeded_artifact_id=succeeded_artifact_id,
            should_retry=should_retry,
            retry_attempt=retry_attempt,
            error_code=outcome.error_code,
            error_detail=outcome.error_detail,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    def _candidates_for(
        self, output: DiscoveryOutput, depth: int
    ) -> list[FrontierCandidate]:
        # The discover task's own position is its randomized_position; children
        # inherit deterministic order via (parent_position, link_ordinal, hash).
        candidates = build_frontier_candidates(output, parent_position=0, depth=depth)
        if depth == 0:
            # The root/fetched identity itself must also go through admission
            # (not just its extracted child links): a Free crawl's sample
            # allowance is filled from admitted identities, and the root's
            # SiteUrl identity is created lazily on its first fetch (it has no
            # pre-existing inventory row), so skipping it here would leave
            # Free crawls with no or an undersized sample and would exclude
            # the root from ``free_sample`` monitoring/auto-analysis.
            root_url_hash = canonical_identity(output.requested_url)[1]
            candidates.append(
                FrontierCandidate(
                    url=output.requested_url,
                    url_hash=root_url_hash,
                    depth=depth,
                    source_kind=OBSERVATION_SOURCE_ROOT,
                    parent_position=-1,
                    link_ordinal=-1,
                )
            )
        return candidates

    def _sitemap_candidates(self, urls: tuple[str, ...]) -> list[FrontierCandidate]:
        """Turn ingested sitemap URLs into deterministically-ordered candidates.

        Depth 1 keeps sitemap-sourced URLs within the max-depth ceiling;
        ``link_ordinal`` is the ingestion order so frontier admission order
        reproduces exactly from the sitemap document order (invariant 9).
        """
        candidates: list[FrontierCandidate] = []
        for ordinal, url in enumerate(urls):
            try:
                canonical, url_hash_value = canonical_identity(url)
            except UrlPolicyError:
                continue
            candidates.append(
                FrontierCandidate(
                    url=canonical,
                    url_hash=url_hash_value,
                    depth=1,
                    source_kind=OBSERVATION_SOURCE_SITEMAP,
                    parent_position=0,
                    link_ordinal=ordinal,
                )
            )
        return candidates

    async def _write_sitemap_observations(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        candidates: list[FrontierCandidate],
        admission,
    ) -> None:
        """Sparse admission-time observations for sitemap-sourced URLs.

        Mirrors ``_add_free_sample``'s observation row: the pages/inventory
        read paths scope strictly through ``SiteUrlObservation``, so a URL
        admitted only via the sitemap needs this row to be visible before
        its own discover task runs. Conflict-safe on ``(crawl_id,
        site_url_id)`` — a richer discover-path observation wins if it ran
        first.
        """
        for candidate in candidates:
            site_url_id = admission.site_url_ids.get(candidate.url_hash)
            if site_url_id is None:
                continue
            await session.execute(
                pg_insert(SiteUrlObservation)
                .values(
                    workspace_id=crawl.workspace_id,
                    project_id=crawl.project_id,
                    crawl_id=crawl.id,
                    site_url_id=site_url_id,
                    source_kind=OBSERVATION_SOURCE_SITEMAP,
                    depth=candidate.depth,
                    observed_url=candidate.url,
                    final_url=candidate.url,
                )
                .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
            )

    async def _persisted_discover_artifact_id(
        self, task_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Return durable discover evidence for an idempotently reclaimed task."""
        async with self._session_factory() as session:
            return await session.scalar(
                select(SiteFetchArtifact.id)
                .where(
                    SiteFetchArtifact.task_id == task_id,
                    SiteFetchArtifact.fetch_purpose == FETCH_PURPOSE_DISCOVER,
                )
                .limit(1)
            )
