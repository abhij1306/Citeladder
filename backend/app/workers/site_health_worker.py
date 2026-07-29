# Site Health worker: the discover-task claim/lease execution loop (Task 3).
#
# A separate process (a dedicated ``site-health-worker`` compose service). It
# mirrors ``AuditWorker`` exactly on the queue mechanics — claim via
# ``PostgresTaskQueue`` (``FOR UPDATE SKIP LOCKED``, lease committed BEFORE any
# network I/O), ``mark_running`` before the fetch, heartbeat the lease while the
# (possibly slow) fetch runs, cooperative cancel at the task boundary, and a
# ``FOR UPDATE`` owner/liveness re-check before persisting any evidence so a
# lost-lease or cancelled task writes NOTHING (invariant 3, acceptance
# criterion 7).
#
# SCOPE (Task 3): this worker claims and executes ONLY ``discover`` tasks. It
# fetches the target through the SSRF-safe ``SecureFetcher`` (with an injected
# DNS resolver — tests inject a fake one, production a real one), extracts
# in-scope canonical links, admits them into the frontier via
# ``discovery.admit_candidates`` (Starter progressive inventory / Free
# workspace-wide stop-at-10 sample), and persists an immutable
# ``SiteUrlObservation`` + ``SiteFetchAttempt`` (+ ``SiteFetchArtifact``) in the
# SAME transaction as the admitted rows + counter bumps + child-task enqueues.
#
# The ``analyze`` / ``link_check`` branches are EXPLICIT reserved dispatch cases
# for Task 5 — they are never claimed by this worker (the claim is filtered to
# ``discover`` so Free's auto-enqueued ``analyze`` tasks wait untouched in the
# queue rather than being force-failed), and ``_execute_discover``'s dispatch
# raises ``NotImplementedError`` if one is ever routed here, which the crash
# handler records as a failure. Task 5 extends THIS SAME worker (no second
# owner of this file).
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.site_health.finalize import (
    evaluate_broken_internal_link,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
)
from app.analysis.site_health.page_types import classify
from app.analysis.site_health.parser import extract_page_facts
from app.analysis.site_health.rules import RuleEvaluation, evaluate_all
from app.analysis.site_health.scoring import (
    score_analysis,
)
from app.connectors.web_evidence.contracts import (
    DnsResolver,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
)
from app.connectors.web_evidence.fetcher import SecureFetcher, is_bot_block_result
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.sitemaps import (
    SitemapCollector,
    SitemapParseError,
)
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    is_admissible,
    split_host_port,
)
from app.core.config.site_health import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_ALLOW,
    AI_CRAWLER_STANCE_BLOCK,
    ANALYSIS_STATUS_CANCELLED,
    ANALYSIS_STATUS_COMPLETED,
    ANALYSIS_STATUS_FAILED,
    ANALYSIS_STATUS_PARTIALLY_COMPLETED,
    ANALYSIS_STATUS_PENDING,
    ANALYSIS_STATUS_RUNNING,
    ANALYZER_VERSION,
    APPLICABILITY_CRAWL_FINALIZE,
    CRAWL_ACTIVE_STATUSES,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    ERROR_BOT_BLOCKED,
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
    EVENT_ANALYSIS_PROGRESS,
    EVENT_CRAWL_COMPLETED,
    EVENT_DISCOVERY_PROGRESS,
    EXTRACTOR_VERSION,
    FETCH_ENGINE_CURL_CFFI,
    FETCH_ENGINE_HTTPX,
    FETCH_MODE_AUTO,
    FETCH_MODE_HTTP_ONLY,
    FETCH_PURPOSE_ANALYZE,
    FETCH_PURPOSE_DISCOVER,
    FETCH_PURPOSE_LINK_CHECK,
    FETCH_PURPOSE_LLMS,
    FETCH_PURPOSE_ROBOTS,
    FETCH_PURPOSE_SITEMAP,
    HTML_CONTENT_TYPES,
    LINK_KIND_ANCHOR,
    LLMS_TXT_PATH,
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    ROBOTS_TXT_PATH,
    RULE_OUTCOME_FAIL,
    SCORING_VERSION,
    SITE_CRAWL_QUEUE_SPEC,
    SITE_HEALTH_RULES_BY_ID,
    SITE_HEALTH_USER_AGENT,
    SITEMAP_CONTENT_TYPES,
    SITEMAP_DEFAULT_PATHS,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging
from app.domain.site_health.discovery import (
    _enqueue_task as _enqueue_discovery_task,
)
from app.domain.site_health.discovery import (
    admit_candidates,
    build_frontier_candidates,
    extract_discovery_links,
)
from app.domain.site_health.normalization import (
    canonical_identity,
)
from app.domain.site_health.schemas import (
    DiscoveryOutput,
    FrontierCandidate,
)
from app.domain.site_health.selection import (
    crawl_is_active,
    evaluate_task_guard,
    lease_is_owned,
)
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.domain.site_health.state_events import (
    apply_analysis_status,
    apply_crawl_status,
    apply_discovery_status,
    record_crawl_event,
)
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteFetchAttempt,
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
    WorkspaceSiteHealthEntitlement,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue

logger = logging.getLogger("app.workers.site_health_worker")

# Outcome tokens for the append-only ``SiteFetchAttempt.outcome`` column.
_OUTCOME_SUCCESS = "success"
_OUTCOME_ERROR = "error"


@dataclass(slots=True)
class _DiscoverOutcome:
    """Bounded, in-memory result of a single discover fetch+parse.

    Holds either a success (``result`` + parsed ``output``) or a classified
    failure (``error_code`` + ``retryable``), never both, so the persist step
    can branch on ``output is not None``. ``result`` is present for HTTP
    4xx/5xx (the fetcher returns them) so an artifact can still be written.
    The v2 P2 site-setup fields are populated only by the depth-0 (root)
    task: ``site_facts`` for the crawl row, plus the sitemap-ingested URL /
    file lists (empty on Free sample crawls — sitemap page ingestion is a
    Starter behavior).
    """

    result: FetchResult | None = None
    output: DiscoveryOutput | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    # The fetcher's per-network-call trace (T7/T8): one entry per REAL call
    # (both rungs, every redirect hop), carried from ``FetchResult.attempts``
    # or ``FetchError.attempts`` so persistence writes one attempt ROW per
    # call. Empty when no network call happened (robots short-circuit).
    attempts: tuple[FetchCallTrace, ...] = ()
    site_facts: dict | None = None
    sitemap_urls: tuple[str, ...] = ()
    sitemap_files: tuple[str, ...] = ()


@dataclass(slots=True)
class _AnalyzeOutcome:
    """Bounded, in-memory result of a single analyze fetch+parse.

    Holds either a success (``result`` + parsed ``facts``) or a classified
    failure (``error_code`` + ``retryable``). ``result`` is present for HTTP
    4xx/5xx so an artifact/attempt can still be recorded on a hard failure.
    """

    result: FetchResult | None = None
    facts: dict | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    # The fetcher's per-network-call trace (T7/T8), as on ``_DiscoverOutcome``.
    attempts: tuple[FetchCallTrace, ...] = ()


@dataclass(frozen=True, slots=True)
class _LinkProbeOutcome:
    """Observable inputs captured by a bounded link probe."""

    reachable: bool
    method: str
    status_code: int | None
    # True when the target's own robots.txt policy denied the probe (no
    # request was made — recorded as policy-skipped, never a fetch failure).
    skipped_by_policy: bool = False


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _classify_http_error(status: int) -> tuple[str, bool] | None:
    """Map an HTTP status the fetcher returned (not raised) to (code, retry).

    Returns ``None`` for a non-error status. A 4xx is terminal except 429
    (rate limit, retryable); every 5xx is retryable. Shared by the discover
    and analyze fetch paths so the classification stays in one place.
    """
    if 400 <= status < 500:
        return ERROR_HTTP_4XX, status == 429
    if status >= 500:
        return ERROR_HTTP_5XX, True
    return None


def _fetch_engine_for_rung(rung_number: int | None) -> str:
    """Map a trace rung number to its config ``FETCH_ENGINE_*`` token (T8)."""
    if rung_number == 2:
        return FETCH_ENGINE_CURL_CFFI
    return FETCH_ENGINE_HTTPX


def _result_fetch_engine(result: FetchResult) -> str:
    """The engine that PRODUCED ``result``: its last trace entry's rung.

    The trace contract guarantees the entry describing a returned result is
    always last (an escalation continues the ordinal sequence), so the last
    entry's rung is the winning call's engine. A trace-less result (built
    directly by a test/caller) defaults to rung 1's engine.
    """
    if result.attempts:
        return _fetch_engine_for_rung(result.attempts[-1].rung_number)
    return FETCH_ENGINE_HTTPX


def _is_exhausted_bot_block(result: FetchResult) -> bool:
    """True ONLY when BOTH fetch-ladder rungs returned signature blocks (T8).

    Rung 2 fires exclusively on a rung-1 bot-block signature, so a trace
    containing a rung-2 entry proves rung 1 was signature-blocked; the
    returned result (which is then rung 2's terminal response) matching the
    signature proves rung 2 was too. Anything else — a plain returned 403 on
    rung 1 with no escalation, or an escalated rung-2 200 — is NOT an
    exhausted bot block and keeps its normal classification.
    """
    return any(entry.rung_number == 2 for entry in result.attempts) and (
        is_bot_block_result(result)
    )


def _count_disclosure(crawl: SiteCrawl) -> bool:
    """Whether this crawl opted into exact-count disclosure in its config."""
    return bool((crawl.configuration or {}).get("count_disclosure", False))


def _is_crawl_finalize_rule(rule_id: str) -> bool:
    """Whether a catalog rule is scoped ``crawl_finalize`` (finalize-owned)."""
    rule = SITE_HEALTH_RULES_BY_ID.get(rule_id)
    return rule is not None and rule.applicability_key == APPLICABILITY_CRAWL_FINALIZE


def _serialize_redirect_chain(result: FetchResult) -> list[dict]:
    """Serialize a fetch result's redirect hops to plain JSON-safe dicts."""
    return [
        {
            "from_url": hop.from_url,
            "to_url": hop.to_url,
            "status_code": hop.status_code,
        }
        for hop in result.redirect_chain
    ]


def _authority_key(url: str) -> str:
    """The ``scheme://host:port`` authority a robots.txt policy is keyed by.

    Robots policies are per (scheme, host, port); the default port is filled
    in so ``https://example.com`` and ``https://example.com:443`` share one
    policy. Returns ``""`` for an unparseable URL (the caller then skips
    robots enforcement — the URL policy will reject it downstream anyway).
    """
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        try:
            port = parts.port
        except ValueError:
            port = None
    except Exception:
        return ""
    if not scheme or not host:
        return ""
    if port is None:
        port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}:{port}"


def _robots_denial_error(policy: RobotsPolicy) -> tuple[str, str]:
    """The (error_code, detail) for a robots-denied fetch.

    A 5xx robots.txt (RFC 9309 complete/temporary disallow) surfaces as
    ``robots_unavailable`` — distinct from a real robots-rule disallow so the
    UI can explain the site is misbehaving rather than blocking crawlers.
    """
    if policy.unavailable:
        return (
            ERROR_ROBOTS_UNAVAILABLE,
            "robots.txt responded 5xx; fetches paused for this site",
        )
    return (
        ERROR_ROBOTS_DENIED,
        "robots.txt disallows the crawler user-agent for this URL",
    )


def _canonical_or_empty(url: str) -> str:
    """The canonical form of ``url``, or ``""`` when it fails normalization.

    The finalize pass canonicalizes persisted URLs (link targets, hreflang
    alternates, sitemap observations) that may no longer parse — an
    unnormalizable URL simply contributes nothing.
    """
    try:
        return canonical_identity(url)[0]
    except UrlPolicyError:
        return ""


def _crawl_root_identity(crawl: SiteCrawl) -> tuple[str, str]:
    """``(canonical, url_hash)`` of the crawl root, or ``("", "")``."""
    try:
        return canonical_identity(crawl.root_url)
    except UrlPolicyError:
        return "", ""


class SiteHealthWorker:
    """Owns a claim/lease loop over ``SiteCrawlTask`` discover rows.

    Claims a bounded batch from PostgreSQL and executes it concurrently, each
    task in its own short-lived session (never one held open across the fetch).
    A per-host semaphore and start-delay gate retain crawler politeness while
    unrelated hosts use the full in-process concurrency budget.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
        resolver: DnsResolver | None = None,
        transport=None,
        curl_session_factory=None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue: PostgresTaskQueue[SiteCrawlTask] = PostgresTaskQueue(
            self._session_factory, SITE_CRAWL_QUEUE_SPEC
        )
        self.owner = owner or f"site-worker-{uuid.uuid4().hex[:12]}"
        self._resolver = resolver or SystemDnsResolver()
        # An injected httpx transport (tests pass ``httpx.MockTransport``);
        # None in production so the fetcher pins the validated connection IP.
        self._transport = transport
        # An injected curl session factory for the fetcher's rung-2
        # escalation (tests pass a fake session builder); None in production
        # so the fetcher uses its real impersonated-curl factory.
        self._curl_session_factory = curl_session_factory
        self._host_semaphores: dict[str, asyncio.Semaphore] = {}
        self._host_start_locks: dict[str, asyncio.Lock] = {}
        self._host_last_started: dict[str, float] = {}
        # Waiters + holders per host: the three maps above are only evicted
        # once this drops to zero AND the polite start-delay window has
        # elapsed, so cleanup can never race active crawling of the host.
        self._host_refcounts: dict[str, int] = {}
        # v2 P2: per-authority robots cache — one (policy, raw body, status)
        # triple per authority (the raw body feeds the per-bot AI-crawler
        # stance in site setup) — plus a per-authority lock so concurrent
        # tasks never duplicate the fetch. Entries expire after
        # ``robots_cache_ttl_seconds`` (RFC 9309 ~24h guidance) so a
        # long-lived worker re-reads changed policies; the maps are bounded
        # by the number of distinct authorities a worker crawls (a crawl is
        # scoped to one registrable domain), so they stay tiny.
        self._robots_cache: dict[str, tuple[RobotsPolicy, str | None, int | None]] = {}
        self._robots_cache_ts: dict[str, float] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    def _new_fetcher(self) -> SecureFetcher:
        """Build a fetcher with the worker's injected transport seams.

        The resolver, httpx transport (rung 1), and curl session factory
        (rung 2 escalation) are all injected together so offline tests never
        touch the network on EITHER rung.
        """
        return SecureFetcher(
            resolver=self._resolver,
            transport=self._transport,
            curl_session_factory=self._curl_session_factory,
        )

    async def run_once(self) -> int:
        """Sweep expired leases, claim a batch of all task kinds, execute it.

        Claims ``discover``, ``analyze``, and ``link_check`` tasks (Task 5): a
        widened claim + the routed dispatch in ``_run_discover`` must change
        together — claiming a kind we do not route would force-fail it, and
        routing a kind we do not claim would leave it queued forever.
        """
        sweep = await self._queue.release_expired_detailed(
            batch_size=site_health_settings.lease_reclaim_batch_size
        )
        # A task the sweeper failed at max attempts never runs ``_execute_task``,
        # so its ``finally`` reconcile never fires. If that was a crawl's last
        # outstanding task the crawl would stay non-terminal forever; reconcile
        # the affected crawls here. Idempotent — reconcile no-ops on a crawl
        # that is already terminal.
        for crawl_id in sweep.failed_parent_ids:
            await self._reconcile_crawl_status(crawl_id)
        await self._reconcile_stalled_crawls()
        self._evict_idle_hosts()
        claim_limit = min(
            site_health_settings.worker_concurrency,
            site_health_settings.global_concurrency,
        )
        tasks = await self._queue.claim(
            owner=self.owner,
            limit=claim_limit,
            kinds=[
                TASK_KIND_DISCOVER,
                TASK_KIND_ANALYZE,
                TASK_KIND_LINK_CHECK,
            ],
        )
        if tasks:
            # ``return_exceptions`` waits for EVERY claimed task before any
            # failure propagates: a plain gather would re-raise on the first
            # crash and abandon still-running siblings mid-lease.
            results = await asyncio.gather(
                *(self._execute_claimed(task) for task in tasks),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        return len(tasks)

    async def _execute_claimed(self, task: SiteCrawlTask) -> None:
        """Heartbeat a claimed lease while it waits for its polite host slot.

        The heartbeat here covers ONLY the wait for the host slot; once the
        slot is secured it stops before ``_execute_task`` runs, because the
        fetch heartbeats are owned by ``_run_discover`` / ``_run_analyze`` /
        ``_run_link_check`` — one loop per active fetch, never two.
        """
        try:
            host, _port = split_host_port(task.requested_url)
        except Exception:
            host = task.requested_url
        self._host_refcounts[host] = self._host_refcounts.get(host, 0) + 1
        semaphore = self._host_semaphores.setdefault(
            host,
            asyncio.Semaphore(site_health_settings.per_host_concurrency),
        )
        start_lock = self._host_start_locks.setdefault(host, asyncio.Lock())
        heartbeat = asyncio.create_task(self._heartbeat_loop(task.id))
        try:
            async with semaphore:
                async with start_lock:
                    delay = max(0.0, site_health_settings.per_host_delay_seconds)
                    # v2 P2: honor a robots-declared crawl-delay (clamped by
                    # the config max inside RobotsPolicy) from the CACHE ONLY
                    # — never fetch robots.txt here. The first request to an
                    # authority goes with the default delay; once the fetch
                    # path has cached the policy, later requests honor it.
                    cached = self._robots_cache.get(_authority_key(task.requested_url))
                    if cached is not None:
                        delay = max(delay, cached[0].crawl_delay())
                    elapsed = time.monotonic() - self._host_last_started.get(host, 0.0)
                    if elapsed < delay:
                        await asyncio.sleep(delay - elapsed)
                    self._host_last_started[host] = time.monotonic()
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
                await self._execute_task(task)
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
            self._release_host_gate(host)

    def _release_host_gate(self, host: str) -> None:
        """Drop one waiter/holder reference; evict idle per-host state at zero.

        Eviction requires BOTH a zero refcount and the politeness window
        having elapsed, so cleanup never races active crawling and a task
        claimed inside the delay window still honors the delay. A host still
        inside its window at refcount zero is swept by ``_evict_idle_hosts``
        on a later ``run_once``.
        """
        remaining = self._host_refcounts.get(host, 1) - 1
        if remaining > 0:
            self._host_refcounts[host] = remaining
            return
        self._host_refcounts.pop(host, None)
        delay = max(0.0, site_health_settings.per_host_delay_seconds)
        if time.monotonic() - self._host_last_started.get(host, 0.0) < delay:
            return
        self._evict_host(host)

    def _evict_idle_hosts(self) -> None:
        """Sweep per-host state whose refcount is zero and delay window passed."""
        delay = max(0.0, site_health_settings.per_host_delay_seconds)
        now = time.monotonic()
        hosts = (
            self._host_semaphores.keys()
            | self._host_start_locks.keys()
            | self._host_last_started.keys()
        )
        for host in list(hosts):
            if (
                self._host_refcounts.get(host, 0) == 0
                and now - self._host_last_started.get(host, 0.0) >= delay
            ):
                self._evict_host(host)

    def _evict_host(self, host: str) -> None:
        self._host_semaphores.pop(host, None)
        self._host_start_locks.pop(host, None)
        self._host_last_started.pop(host, None)

    async def run_until_idle(self, *, max_batches: int = 1000) -> int:
        """Drain the discover queue until a claim returns nothing (test mode)."""
        total = 0
        for _ in range(max_batches):
            ran = await self.run_once()
            if ran == 0:
                break
            total += ran
        return total

    async def run_forever(self) -> None:  # pragma: no cover - long-running loop
        logger.info("site health worker started", extra={"owner": self.owner})
        while True:
            try:
                ran = await self.run_once()
            except Exception:  # defensive: a bad task must not kill the loop
                logger.exception("site health worker loop iteration failed")
                ran = 0
            if ran == 0:
                await asyncio.sleep(
                    max(0.05, site_health_settings.poll_interval_seconds)
                )

    # --- per-task execution ------------------------------------------------

    async def _execute_task(self, claimed: SiteCrawlTask) -> None:
        """Run one claimed task end to end inside short-lived sessions.

        Honors cooperative cancel at the boundary (before the fetch),
        ``mark_running`` before network I/O, heartbeats the lease during the
        fetch, and finalizes discovery when the queue drains. Never raises — a
        crash is caught and recorded as a queue failure so the lease is always
        released.
        """
        task_id = claimed.id
        crawl_id = claimed.crawl_id
        kind = claimed.task_kind
        try:
            # Cooperative cancel: stop at this boundary if the crawl was
            # cancelled/terminalized since the claim, rather than fetching.
            async with self._session_factory() as session:
                task = await session.get(SiteCrawlTask, task_id)
                crawl = await session.get(SiteCrawl, crawl_id, with_for_update=True)
                if task is None or crawl is None:
                    await session.rollback()
                    await self._queue.cancel(task_id=task_id)
                    return
                if not crawl_is_active(crawl):
                    await session.rollback()
                    await self._queue.cancel(task_id=task_id)
                    await self._reconcile_crawl_status(crawl_id)
                    return
                # The first task moves the crawl QUEUED -> RUNNING.
                self._ensure_running(crawl)
                await session.commit()

            # Mark the queue row running (still owned) before the fetch.
            if not await self._queue.mark_running(task_id=task_id, owner=self.owner):
                # Lease lost (sweeper reclaimed it); another worker will retry.
                return

            if kind == TASK_KIND_DISCOVER:
                await self._run_discover(task_id, crawl_id)
            elif kind == TASK_KIND_ANALYZE:
                await self._run_analyze(task_id, crawl_id)
            elif kind == TASK_KIND_LINK_CHECK:
                await self._run_link_check(task_id, crawl_id)
            else:
                raise NotImplementedError(f"unknown task kind '{kind}'")
        except Exception as exc:  # defensive: never let one task kill the loop
            logger.exception(
                "site health task crashed",
                extra={"task_id": str(task_id), "task_kind": kind},
            )
            await self._record_crash(task_id, exc)
        finally:
            # ONE shared finalize for every kind: it terminalizes the crawl only
            # when EVERY non-terminal task (all kinds) is drained, so a completing
            # discover task never drives the crawl terminal while analyze/
            # link_check work is still queued (which would make a later analysis
            # finalize raise InvalidSiteCrawlTransition from a terminal state).
            await self._reconcile_crawl_status(crawl_id)

    def _ensure_running(self, crawl: SiteCrawl) -> None:
        if crawl.status == CRAWL_STATUS_RUNNING:
            return
        if crawl.started_at is None:
            crawl.started_at = _utcnow()
        apply_crawl_status(crawl, CRAWL_STATUS_RUNNING)

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

    # --- v2 P2: robots policy cache + site setup ---------------------------

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

    async def _heartbeat_loop(
        self, task_id: uuid.UUID
    ) -> None:  # pragma: no cover - timing loop
        interval = max(1.0, site_health_settings.heartbeat_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._queue.heartbeat(task_id=task_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dead heartbeat loop silently expires the lease and lets the
                # sweeper hand the task to another worker mid-fetch; keep
                # beating through transient failures instead.
                logger.exception(
                    "heartbeat failed; retrying", extra={"task_id": str(task_id)}
                )

    @contextlib.asynccontextmanager
    async def _leased(self, task_id: uuid.UUID) -> AsyncIterator[None]:
        """Heartbeat ``task_id``'s lease for the whole body, fetch AND persist.

        The persist phase is NOT cheap — it takes the crawl row ``FOR UPDATE``
        (contending with every sibling task's finalize), writes the artifact,
        page analysis, rule evaluations, issues and the link-check enqueue, and
        only then acknowledges the queue row. Ending the heartbeat when the
        fetch returned left that whole window running against the remaining
        lease: a slow persist expired the lease, the sweeper reclaimed the task
        and (at max attempts) failed it terminally, which is what stalls a
        crawl. One heartbeat spans both phases; never two loops for one task.
        """
        heartbeat = asyncio.create_task(self._heartbeat_loop(task_id))
        try:
            yield
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _lock_owned_running_task(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
    ) -> tuple[SiteCrawlTask, SiteCrawl] | None:
        """Lock the task FOR UPDATE and verify we still own it before writing.

        Guards invariant 3/acceptance-criterion 7 (single writer, no artifact
        for a cancelled/lost-lease task). Between the fetch finishing and this
        write the lease could have expired (sweeper -> another worker) or the
        crawl could have been cancelled. Returns ``(task, crawl)`` only when the
        task is still leased to THIS worker, still ``running``, and the crawl is
        still active; otherwise ``None`` and the fetch result is discarded.
        """
        task = await session.get(SiteCrawlTask, task_id, with_for_update=True)
        if not lease_is_owned(task, owner=self.owner):
            return None
        if task.status != TASK_STATUS_RUNNING:
            return None
        # Lock the crawl row too: a concurrent cancellation/terminalization must
        # not be able to commit between this active check and the evidence
        # commit (invariant 3: a cancelled task writes NOTHING).
        crawl = await session.get(SiteCrawl, crawl_id, with_for_update=True)
        if not crawl_is_active(crawl):
            return None
        return task, crawl

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

    async def _write_artifact(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        result: FetchResult,
        fetch_purpose: str = FETCH_PURPOSE_DISCOVER,
        normalized_facts: dict | None = None,
    ) -> uuid.UUID:
        """Write the immutable per-task fetch artifact (unique ``task_id``).

        Reused by both discover and analyze; ``fetch_purpose`` records why the
        fetch happened and ``normalized_facts`` carries the bounded parsed page
        facts for an analyze artifact (there is NO raw body column anywhere).
        ``fetch_engine`` records the engine that produced the winning call
        (the result's last trace entry), so the artifact's provenance matches
        the per-call attempt rows (invariant 4).
        """
        content_hash = hashlib.sha256(result.body or b"").hexdigest()
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            fetch_purpose=fetch_purpose,
            fetch_engine=_result_fetch_engine(result),
            requested_url=result.requested_url,
            final_url=result.final_url,
            redirect_chain=_serialize_redirect_chain(result),
            status_code=result.status_code,
            redacted_headers=dict(result.redacted_headers or {}),
            content_type=result.content_type,
            content_hash=content_hash,
            http_version=result.http_version,
            ttfb_ms=result.ttfb_ms,
            latency_ms=result.latency_ms,
            wire_bytes=result.wire_bytes,
            decoded_bytes=result.decoded_bytes,
            extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
            normalized_facts=normalized_facts,
        )
        session.add(artifact)
        await session.flush()
        return artifact.id

    async def _write_observation(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        output: DiscoveryOutput,
        depth: int,
        artifact_id: uuid.UUID | None,
    ) -> None:
        """Write the immutable per-crawl observation for the fetched URL.

        Conflict-safe on the unique ``(crawl_id, site_url_id)`` — a URL can be
        observed more than once in a crawl, so a plain insert would raise an
        ``IntegrityError`` and poison this transaction. Resolves the SiteUrl
        identity (creating it conflict-safely for the root, which has no
        pre-created inventory row) and refreshes its lightweight state.
        """
        # The observation's own URL identity: the requested URL's SiteUrl row.
        site_url_id = await self._resolve_site_url_id(
            session, crawl=crawl, url=output.requested_url, depth=depth
        )
        if site_url_id is None:
            return
        # Refresh the lightweight discovery state on the identity row.
        site_url = await session.get(SiteUrl, site_url_id)
        if site_url is not None:
            site_url.latest_title = (output.title or "")[:1024]
            site_url.latest_content_type = (output.content_type or "")[:128]
            site_url.last_seen_crawl_id = crawl.id
            site_url.discovery_status = DISCOVERY_STATUS_COMPLETED
        await session.execute(
            pg_insert(SiteUrlObservation)
            .values(
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                site_url_id=site_url_id,
                source_kind=(
                    OBSERVATION_SOURCE_ROOT if depth == 0 else OBSERVATION_SOURCE_LINK
                ),
                parent_site_url_id=task.parent_site_url_id,
                source_artifact_id=artifact_id,
                depth=depth,
                observed_url=output.requested_url,
                final_url=output.final_url,
                status_code=output.status_code,
                content_type=(output.content_type or "")[:128],
                title=(output.title or "")[:1024],
            )
            .on_conflict_do_nothing(index_elements=["crawl_id", "site_url_id"])
        )

    async def _resolve_site_url_id(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        url: str,
        depth: int,
    ) -> uuid.UUID | None:
        """Return the SiteUrl id for ``url``, creating it conflict-safely.

        Child URLs already have an identity from admission, but the root's
        identity is created here on its first (depth 0) fetch. Uses the same
        ``ON CONFLICT (project_id, url_hash) DO NOTHING`` pattern as admission.
        """
        try:
            canonical, url_hash_value = canonical_identity(url)
        except Exception:
            return None
        try:
            host, _port = split_host_port(canonical)
        except Exception:
            host = ""
        now = _utcnow()
        inserted_id = await session.scalar(
            pg_insert(SiteUrl)
            .values(
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                normalized_url=canonical,
                url_hash=url_hash_value,
                display_url=canonical,
                host=host[:255],
                depth=depth,
                discovery_status=DISCOVERY_STATUS_RUNNING,
                latest_source_kind=(
                    OBSERVATION_SOURCE_ROOT if depth == 0 else OBSERVATION_SOURCE_LINK
                ),
                first_seen_crawl_id=crawl.id,
                last_seen_crawl_id=crawl.id,
                first_seen_at=now,
                last_seen_at=now,
            )
            .on_conflict_do_nothing(index_elements=["project_id", "url_hash"])
            .returning(SiteUrl.id)
        )
        if inserted_id is not None:
            return inserted_id
        return await session.scalar(
            select(SiteUrl.id).where(
                SiteUrl.project_id == crawl.project_id,
                SiteUrl.url_hash == url_hash_value,
            )
        )

    def _write_attempt(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        outcome: _DiscoverOutcome | _AnalyzeOutcome,
        succeeded: bool,
        requested_url: str,
        artifact_id: uuid.UUID | None,
    ) -> None:
        """Append ONE attempt row per REAL network call (invariant 3, T8).

        The fetcher's per-call trace (``outcome.attempts``) drives the rows:
        every redirect hop and every ladder rung gets its own row sharing the
        QUEUE-attempt number (``attempt_number``) and distinguished by the
        deterministic per-call ``request_ordinal`` — order/uniqueness key
        ``(task_id, attempt_number, request_ordinal)``. Each row records the
        engine that made the call (``fetch_engine`` from the entry's rung),
        the per-call host/status/latency/byte counts, and a per-call outcome:
        ``error`` when the call itself failed (transport error token), when it
        received an HTTP error status, or when it is the terminal call of an
        unsuccessful fetch; otherwise ``success``. ONLY the successful
        terminal call links the artifact — a blocked rung is an attempt only,
        never an artifact generation.

        When the trace is empty (no network call happened — a robots/policy
        short-circuit — or a trace-less result built by a caller), the
        historical single diagnostic row for the queue attempt is kept, with
        ``request_ordinal=0`` and ``rung_number=NULL``.

        Shared by discover and analyze; ``succeeded`` is decided by the caller
        (a discover success has a parsed ``output``, an analyze success has
        parsed ``facts``) so this stays agnostic to the outcome payload shape.
        """
        attempt_number = task.attempt_count + 1
        trace = outcome.attempts
        if not trace:
            try:
                host, _port = split_host_port(requested_url)
            except Exception:
                host = ""
            session.add(
                SiteFetchAttempt(
                    task_id=task.id,
                    crawl_id=crawl.id,
                    workspace_id=crawl.workspace_id,
                    attempt_number=attempt_number,
                    request_ordinal=0,
                    rung_number=None,
                    method="GET",
                    target_host=host[:255],
                    outcome=_OUTCOME_SUCCESS if succeeded else _OUTCOME_ERROR,
                    error_code=outcome.error_code,
                    status_code=outcome.status_code,
                    latency_ms=outcome.latency_ms,
                    wire_bytes=(
                        outcome.result.wire_bytes
                        if outcome.result is not None
                        else None
                    ),
                    decoded_bytes=(
                        outcome.result.decoded_bytes
                        if outcome.result is not None
                        else None
                    ),
                    artifact_id=artifact_id,
                )
            )
            return

        last_index = len(trace) - 1
        for index, entry in enumerate(trace):
            is_final = index == last_index
            if entry.error_code:
                # The call itself failed (timeout / cap abort / transport).
                row_outcome = _OUTCOME_ERROR
                row_error = entry.error_code
            elif is_final and not succeeded:
                # The terminal call of an unsuccessful fetch carries the
                # classified task-level token (e.g. http_4xx / bot_blocked).
                row_outcome = _OUTCOME_ERROR
                row_error = outcome.error_code
            elif entry.status_code is not None and entry.status_code >= 400:
                # A non-terminal call that received an HTTP error status
                # (e.g. the blocked rung-1 response before escalation).
                row_outcome = _OUTCOME_ERROR
                row_error = ""
            else:
                row_outcome = _OUTCOME_SUCCESS
                row_error = ""
            try:
                host, _port = split_host_port(entry.url)
            except Exception:
                host = ""
            session.add(
                SiteFetchAttempt(
                    task_id=task.id,
                    crawl_id=crawl.id,
                    workspace_id=crawl.workspace_id,
                    attempt_number=attempt_number,
                    request_ordinal=entry.request_ordinal,
                    rung_number=entry.rung_number,
                    fetch_engine=_fetch_engine_for_rung(entry.rung_number),
                    method=(entry.method or "GET")[:8],
                    target_host=host[:255],
                    outcome=row_outcome,
                    error_code=row_error,
                    status_code=entry.status_code,
                    latency_ms=entry.latency_ms,
                    wire_bytes=entry.wire_bytes,
                    decoded_bytes=entry.decoded_bytes,
                    # ONLY the successful terminal call links the artifact.
                    artifact_id=(artifact_id if (is_final and succeeded) else None),
                )
            )

    async def _record_crash(self, task_id: uuid.UUID, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        await self._queue.fail(
            task_id=task_id,
            owner=self.owner,
            error_code="crawl_task_crashed",
            error_detail=detail,
        )

    async def _finalize_queue_row(
        self,
        *,
        task_id: uuid.UUID,
        succeeded: bool,
        succeeded_artifact_id: uuid.UUID | None,
        should_retry: bool,
        retry_attempt: int,
        error_code: str,
        error_detail: str,
        retry_after_seconds: float | None,
    ) -> None:
        """Succeed / retry / fail the queue row OUTSIDE the evidence txn.

        Shared by the discover and analyze persist flows: a success acks with
        the immutable artifact id, a retryable failure re-queues with the
        deterministic backoff, and everything else fails terminally.
        """
        if succeeded:
            await self._queue.succeed(
                task_id=task_id,
                owner=self.owner,
                result_artifact_id=succeeded_artifact_id,
            )
        elif should_retry:
            await self._queue.retry(
                task_id=task_id,
                owner=self.owner,
                delay_seconds=site_health_settings.retry_delay(
                    retry_attempt, retry_after_seconds
                ),
                error_code=error_code,
                error_detail=error_detail,
            )
        else:
            await self._queue.fail(
                task_id=task_id,
                owner=self.owner,
                error_code=error_code,
                error_detail=error_detail,
            )

    # --- analyze flow ------------------------------------------------------

    async def _run_analyze(self, task_id: uuid.UUID, crawl_id: uuid.UUID) -> None:
        """Fetch + deep-analyze one monitored URL, persisting evidence atomically.

        Mirrors the discover flow: load config in one short session, fetch the
        URL through the SSRF-safe fetcher (heartbeating the lease), parse the
        bounded page facts, then persist ONE immutable artifact + attempt +
        page analysis + rule evaluations + issues + scores in a single
        transaction gated by a ``FOR UPDATE`` owner/liveness re-check. The queue
        row is succeeded / retried / failed OUTSIDE that transaction.
        """
        # If evidence committed but the out-of-transaction queue acknowledgement
        # failed, a reclaimed task must acknowledge that durable result instead
        # of fetching and attempting the unique inserts again.
        persisted_artifact_id = await self._persisted_analysis_artifact_id(task_id)
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
            guard = await self._evaluate_analyze_guard(
                session, task=task, crawl=crawl, lock=False
            )
            if not guard.ok:
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                return
            requested_url = task.requested_url
            config = dict(crawl.configuration or {})
            root_registrable_domain = config.get("root_registrable_domain") or ""
            # The crawl's frozen fetch-ladder mode (v2 P3), as in discover.
            fetch_mode = config.get("fetch_mode") or FETCH_MODE_AUTO

        # One heartbeat across fetch + persist (see ``_leased``).
        async with self._leased(task_id):
            outcome = await self._fetch_analyze(
                requested_url=requested_url,
                root_registrable_domain=root_registrable_domain,
                fetch_mode=fetch_mode,
            )
            await self._persist_analyze(
                task_id=task_id,
                crawl_id=crawl_id,
                requested_url=requested_url,
                outcome=outcome,
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

    async def _persisted_analysis_artifact_id(
        self, task_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Return durable analyze evidence for an idempotently reclaimed task."""
        async with self._session_factory() as session:
            return await session.scalar(
                select(SiteFetchArtifact.id)
                .join(
                    SitePageAnalysis,
                    SitePageAnalysis.artifact_id == SiteFetchArtifact.id,
                )
                .where(
                    SiteFetchArtifact.task_id == task_id,
                    SiteFetchArtifact.fetch_purpose == FETCH_PURPOSE_ANALYZE,
                    SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                )
                .limit(1)
            )

    async def _persisted_link_check_done(self, task_id: uuid.UUID) -> bool:
        """Return True if this link-check task already persisted references.

        The presence of any ``SiteLinkReference`` row tagged with this task's
        ``target_task_id`` is the durable evidence that the task committed its
        probe results before the (possibly lost) queue acknowledgement — so a
        reclaimed run can ack the durable result instead of re-probing links.
        """
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(SiteLinkReference.id)
                .where(SiteLinkReference.target_task_id == task_id)
                .limit(1)
            )
            return existing is not None

    async def _evaluate_analyze_guard(
        self,
        session: AsyncSession,
        *,
        task: SiteCrawlTask,
        crawl: SiteCrawl,
        lock: bool,
    ):
        """Evaluate Task 4's live membership/entitlement guard from DB rows."""
        monitored_stmt = select(MonitoredSiteUrl).where(
            MonitoredSiteUrl.project_id == crawl.project_id,
            MonitoredSiteUrl.site_url_id == task.site_url_id,
        )
        entitlement_stmt = select(WorkspaceSiteHealthEntitlement).where(
            WorkspaceSiteHealthEntitlement.workspace_id == crawl.workspace_id
        )
        if lock:
            monitored_stmt = monitored_stmt.with_for_update()
            entitlement_stmt = entitlement_stmt.with_for_update()
        monitored = (await session.execute(monitored_stmt)).scalar_one_or_none()
        entitlement = (await session.execute(entitlement_stmt)).scalar_one_or_none()
        return evaluate_task_guard(
            crawl=crawl,
            task=task,
            monitored=monitored,
            entitlement=entitlement,
            owner=self.owner,
        )

    async def _lock_guarded_analyze_task(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
    ) -> tuple[tuple[SiteCrawlTask, SiteCrawl] | None, bool]:
        """Lock live entitlement/membership and the owned task before writes.

        The entitlement is the selection flow's serialization point, so lock it
        before membership/task rows to follow that flow's lock order and avoid
        deadlocks with a concurrent monitored-set replacement.

        Returns ``(locked_rows, guard_denied)``. ``guard_denied`` is true only
        while this worker still owns the task but live crawl/membership/
        entitlement state blocks analysis; a lost lease is not ours to cancel.
        """
        task_hint = await session.get(SiteCrawlTask, task_id)
        crawl_hint = await session.get(SiteCrawl, crawl_id)
        if task_hint is None or crawl_hint is None:
            return None, False

        entitlement = (
            await session.execute(
                select(WorkspaceSiteHealthEntitlement)
                .where(
                    WorkspaceSiteHealthEntitlement.workspace_id
                    == crawl_hint.workspace_id
                )
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
                .with_for_update()
            )
        ).scalar_one_or_none()
        crawl = await session.get(SiteCrawl, crawl_id, with_for_update=True)
        task = await session.get(SiteCrawlTask, task_id, with_for_update=True)
        decision = evaluate_task_guard(
            crawl=crawl,
            task=task,
            monitored=monitored,
            entitlement=entitlement,
            owner=self.owner,
        )
        if not decision.ok:
            still_owned = lease_is_owned(task, owner=self.owner)
            return None, still_owned
        if task is None or crawl is None:  # unreachable: guard checked both
            return None, False
        return (task, crawl), False

    async def _fetch_analyze(
        self,
        *,
        requested_url: str,
        root_registrable_domain: str,
        fetch_mode: str = FETCH_MODE_AUTO,
    ) -> _AnalyzeOutcome:
        """Fetch + parse one monitored URL into a bounded ``_AnalyzeOutcome``.

        Returns parsed page facts on success (2xx), a classified error token on
        an HTTP 4xx/5xx or a ``FetchError``. Never raises for an expected fetch
        failure — the caller records an attempt row either way.

        v2 P2: enforces the per-authority robots.txt policy before fetching —
        a denied URL short-circuits to ``ERROR_ROBOTS_DENIED`` (non-retryable;
        presentation maps it to ``blocked`` via POLICY_BLOCKING_ERROR_CODES).

        v2 P3: ``fetch_mode`` is the crawl's frozen fetch-ladder mode
        (``http_only`` disables the impersonated rung-2 escalation); when BOTH
        rungs returned signature-detected bot blocks the outcome classifies as
        terminal ``ERROR_BOT_BLOCKED`` (presentation: ``blocked``).
        """
        authority = _authority_key(requested_url)
        if authority:
            policy, _, _ = await self._ensure_robots_policy(authority)
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
            allow_escalation=fetch_mode != FETCH_MODE_HTTP_ONLY,
        )
        started = time.monotonic()
        try:
            async with self._new_fetcher() as fetcher:
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
        # v2 P3: both rungs signature-blocked -> terminal ERROR_BOT_BLOCKED
        # (see ``_fetch_discover``); checked before status classification.
        if _is_exhausted_bot_block(result):
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
        self,
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
        async with self._session_factory() as session:
            locked, guard_denied = await self._lock_guarded_analyze_task(
                session, task_id=task_id, crawl_id=crawl_id
            )
            if locked is None:
                await session.rollback()
                if not guard_denied:
                    return
            else:
                task, crawl = locked
                artifact_id: uuid.UUID | None = None
                if outcome.facts is not None and outcome.result is not None:
                    artifact_id = await self._write_artifact(
                        session,
                        crawl=crawl,
                        task=task,
                        result=outcome.result,
                        fetch_purpose=FETCH_PURPOSE_ANALYZE,
                        normalized_facts=outcome.facts,
                    )
                    await self._write_page_analysis(
                        session,
                        crawl=crawl,
                        task=task,
                        artifact_id=artifact_id,
                        facts=outcome.facts,
                    )
                    crawl.analyzed_url_count += 1
                    task.result_artifact_id = artifact_id
                    succeeded_artifact_id = artifact_id
                    # Automatically enqueue the link-check task for this URL in
                    # the same transaction as the completed analysis, so the
                    # worker's own ``TASK_KIND_LINK_CHECK`` handling is ever
                    # reached for a normal crawl. Conflict-safe (``ON CONFLICT
                    # DO NOTHING`` on the unique
                    # ``(crawl_id, task_kind, url_hash, generation)`` slot) so
                    # a reclaimed/retried analyze task never double-enqueues.
                    await _enqueue_discovery_task(
                        session,
                        crawl=crawl,
                        site_url_id=task.site_url_id,
                        url=requested_url,
                        url_hash_value=task.url_hash,
                        task_kind=TASK_KIND_LINK_CHECK,
                        depth=task.depth,
                        generation=task.generation,
                        parent_site_url_id=task.parent_site_url_id,
                    )
                    record_crawl_event(
                        session,
                        crawl_id=crawl_id,
                        event_type=EVENT_ANALYSIS_PROGRESS,
                        message="analysis progress",
                        payload={"analyzed": crawl.analyzed_url_count},
                        count_disclosure=_count_disclosure(crawl),
                    )
                else:
                    exhausted = task.attempt_count + 1 >= task.max_attempts
                    should_retry = outcome.retryable and not exhausted
                    retry_attempt = task.attempt_count + 1

                self._write_attempt(
                    session,
                    crawl=crawl,
                    task=task,
                    outcome=outcome,
                    succeeded=outcome.facts is not None,
                    requested_url=requested_url,
                    artifact_id=artifact_id,
                )
                task.attempt_count += 1
                await session.commit()

        if guard_denied:
            await self._queue.cancel(task_id=task_id)
            return

        await self._finalize_queue_row(
            task_id=task_id,
            succeeded=succeeded_artifact_id is not None,
            succeeded_artifact_id=succeeded_artifact_id,
            should_retry=should_retry,
            retry_attempt=retry_attempt,
            error_code=outcome.error_code,
            error_detail=outcome.error_detail,
            retry_after_seconds=outcome.retry_after_seconds,
        )

    async def _write_page_analysis(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        artifact_id: uuid.UUID,
        facts: dict,
    ) -> uuid.UUID:
        """Create the page analysis + rule evaluations + issues + scores.

        One ``SitePageAnalysis`` (unique ``artifact_id``), one
        ``SiteRuleEvaluation`` per rule (unique ``(analysis_id, rule_id)``), a
        ``SiteIssue`` snapshot per FAIL (unique ``evaluation_id``), and the
        deterministic Technical/AEO/overall scores stamped with the versions.
        """
        site_url_id = await self._resolve_analysis_site_url_id(
            session, crawl=crawl, task=task
        )
        # v2 P1: classify the page type and inject it into the facts dict
        # BEFORE rule evaluation, so page_type applicability tokens, per-type
        # thin-content minimums, and weight overrides resolve against it
        # (spec §5.1 pipeline slot; evaluate_all keeps its pure (facts)
        # signature). The type + classifier version persist on the analysis
        # row for provenance (invariant 4).
        assessment = classify(
            str((facts.get("delivery") or {}).get("final_url") or ""), facts
        )
        facts["page_type"] = assessment.page_type
        facts["page_type_evidence"] = assessment.to_evidence()
        # v2 P2 (spec §5.3): inside the crawl ROOT's own analysis only, inject
        # the crawl's site_facts so site_root-scoped rules (AI-crawler access,
        # llms.txt) evaluate exactly once per crawl, anchored on this analysis.
        # The injection happens after the artifact flush, so the persisted
        # normalized_facts deliberately do NOT carry it (same as page_type).
        if crawl.site_facts:
            _root_canonical, root_hash = _crawl_root_identity(crawl)
            if root_hash and root_hash == task.url_hash:
                facts["site"] = crawl.site_facts
        evaluations: list[RuleEvaluation] = [
            ev
            for ev in evaluate_all(facts)
            # The analyze writer NEVER persists crawl_finalize-scoped
            # evaluations (no placeholder not_applicable rows): the unique
            # (analysis_id, rule_id) slot stays free for the finalize pass,
            # which solely owns those rules' rows (single-writer per scope).
            if not _is_crawl_finalize_rule(ev.rule_id)
        ]
        scores = score_analysis(evaluations)
        # Refresh the lightweight identity/observation state from the analyze
        # fetch. A Free sample URL is fetched ONLY by its analyze task (no
        # per-URL discover runs), so its admission-time observation row is
        # sparse (no title/status) until enriched here; without this the pages
        # table shows blank titles for 9 of 10 sampled URLs.
        site_url = await session.get(SiteUrl, site_url_id)
        if site_url is not None:
            title = str(facts.get("title") or "")
            if title:
                site_url.latest_title = title[:1024]
            site_url.latest_content_type = str(facts.get("content_type") or "")[:128]
            site_url.last_seen_crawl_id = crawl.id
            site_url.discovery_status = DISCOVERY_STATUS_COMPLETED
        observation = await session.scalar(
            select(SiteUrlObservation).where(
                SiteUrlObservation.crawl_id == crawl.id,
                SiteUrlObservation.site_url_id == site_url_id,
            )
        )
        if observation is not None and observation.status_code is None:
            observation.status_code = facts.get("status_code")
            observation.final_url = str(facts.get("final_url") or "")[:2048]
            observation.content_type = str(facts.get("content_type") or "")[:128]
            observation.title = str(facts.get("title") or "")[:1024]
            observation.source_artifact_id = artifact_id
        analysis = SitePageAnalysis(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            site_url_id=site_url_id,
            artifact_id=artifact_id,
            status=PAGE_ANALYSIS_STATUS_COMPLETED,
            technical_score=scores.technical_score,
            aeo_score=scores.aeo_score,
            overall_score=scores.overall_score,
            analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
            scoring_version=crawl.scoring_version or SCORING_VERSION,
            page_type=assessment.page_type,
            classifier_version=assessment.classifier_version,
            # Persist the bounded classifier evidence with the row (the facts-
            # dict copy above never survives the artifact flush, by design).
            page_type_evidence=assessment.to_evidence(),
            source_artifact_ids=[artifact_id],
            finalized_at=_utcnow(),
        )
        session.add(analysis)
        await session.flush()

        evaluation_ids: list[uuid.UUID] = []
        for ev in evaluations:
            evaluation = SiteRuleEvaluation(
                workspace_id=crawl.workspace_id,
                analysis_id=analysis.id,
                source_artifact_id=artifact_id,
                rule_id=ev.rule_id,
                dimension=ev.dimension,
                category=ev.category,
                severity=ev.severity,
                weight=ev.weight,
                outcome=ev.outcome,
                evidence=ev.evidence,
                supporting_artifact_ids=[artifact_id],
                extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                rule_version=ev.rule_version,
            )
            session.add(evaluation)
            await session.flush()
            evaluation_ids.append(evaluation.id)
            if ev.outcome == RULE_OUTCOME_FAIL:
                session.add(
                    SiteIssue(
                        workspace_id=crawl.workspace_id,
                        project_id=crawl.project_id,
                        crawl_id=crawl.id,
                        site_url_id=site_url_id,
                        analysis_id=analysis.id,
                        evaluation_id=evaluation.id,
                        source_artifact_id=artifact_id,
                        rule_id=ev.rule_id,
                        dimension=ev.dimension,
                        category=ev.category,
                        severity=ev.severity,
                        evidence=ev.evidence,
                        remediation=ev.remediation,
                        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                        rule_version=ev.rule_version,
                    )
                )
        analysis.source_evaluation_ids = evaluation_ids
        return analysis.id

    async def _resolve_analysis_site_url_id(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
    ) -> uuid.UUID:
        """Resolve the SiteUrl identity for an analyze task's URL.

        Prefers the task's own ``site_url_id`` (set at admission for monitored
        URLs); falls back to a lookup / conflict-safe create keyed on the
        canonical url hash so an analyze task never fails for a missing row.
        """
        if task.site_url_id is not None:
            return task.site_url_id
        resolved = await self._resolve_site_url_id(
            session, crawl=crawl, url=task.requested_url, depth=task.depth
        )
        if resolved is not None:
            return resolved
        # Last resort: create/lookup by hash directly (depth 0).
        fallback = await self._resolve_site_url_id(
            session, crawl=crawl, url=task.requested_url, depth=0
        )
        if fallback is None:
            # Only reachable when the URL cannot be canonicalized at all —
            # admission already canonicalized it, so treat as a hard bug.
            raise RuntimeError(
                f"could not resolve SiteUrl identity for {task.requested_url!r}"
            )
        return fallback

    # --- link-check flow ---------------------------------------------------

    async def _run_link_check(self, task_id: uuid.UUID, crawl_id: uuid.UUID) -> None:
        """Deduped HEAD-first + bounded GET-fallback link check for one page.

        Reads the source page's persisted analyze artifact facts, dedupes the
        referenced links (bounded by ``max_link_checks_per_page``), probes each
        HEAD-first with a bounded GET fallback (best-effort, offline-safe under
        test), and writes deduped ``SiteLinkReference`` rows. Independent of the
        discovery fast path. The queue row is always finalized.
        """
        # Durable-ack recovery (mirrors discover/analyze). Link references are
        # committed BEFORE the out-of-transaction ``_queue.succeed()``. If that
        # acknowledgement is lost (crash/restart between commit and ack) the
        # lease is reclaimed and this task re-runs. Without a durable check a
        # reclaimed run would re-probe every referenced link over the network —
        # wasteful and observable to third-party sites. If this task already
        # persisted its link references, acknowledge the durable result and
        # return before any network I/O instead of re-probing.
        if await self._persisted_link_check_done(task_id):
            await self._queue.succeed(task_id=task_id, owner=self.owner)
            return

        async with self._session_factory() as session:
            task = await session.get(SiteCrawlTask, task_id)
            crawl = await session.get(SiteCrawl, crawl_id)
            if task is None or crawl is None:
                return
            requested_url = task.requested_url
            source = await self._load_link_check_source(
                session, crawl=crawl, requested_url=requested_url
            )

        if source is None:
            # No source analysis/artifact to check against — nothing to do, but
            # the task still succeeds so the queue drains and reconcile runs.
            await self._queue.succeed(task_id=task_id, owner=self.owner)
            return

        analysis_id, artifact_id, source_final_url, facts = source
        targets = self._link_check_targets(facts, source_final_url=source_final_url)

        # One heartbeat across the probes + the write (see ``_leased``).
        async with self._leased(task_id):
            for target in targets:
                target["probe"] = await self._probe_link(target["url"])

            async with self._session_factory() as session:
                locked = await self._lock_owned_running_task(
                    session, task_id=task_id, crawl_id=crawl_id
                )
                if locked is None:
                    await session.rollback()
                    return
                _task, crawl = locked
                for target in targets:
                    await self._write_link_reference(
                        session,
                        crawl=crawl,
                        analysis_id=analysis_id,
                        artifact_id=artifact_id,
                        task_id=task_id,
                        target=target,
                    )
                await session.commit()

            await self._queue.succeed(task_id=task_id, owner=self.owner)

    async def _load_link_check_source(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        requested_url: str,
    ) -> tuple[uuid.UUID, uuid.UUID, str, dict] | None:
        """Find the latest analyze artifact + analysis + facts for the URL."""
        try:
            _canonical, url_hash_value = canonical_identity(requested_url)
        except Exception:
            return None
        site_url_id = await session.scalar(
            select(SiteUrl.id).where(
                SiteUrl.project_id == crawl.project_id,
                SiteUrl.url_hash == url_hash_value,
            )
        )
        if site_url_id is None:
            return None
        row = (
            await session.execute(
                select(SitePageAnalysis.id, SitePageAnalysis.artifact_id)
                .where(
                    SitePageAnalysis.crawl_id == crawl.id,
                    SitePageAnalysis.site_url_id == site_url_id,
                )
                .order_by(SitePageAnalysis.created_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        analysis_id, artifact_id = row
        artifact = await session.get(SiteFetchArtifact, artifact_id)
        if artifact is None:
            return None
        facts = dict(artifact.normalized_facts or {})
        return analysis_id, artifact_id, artifact.final_url, facts

    def _link_check_targets(self, facts: dict, *, source_final_url: str) -> list[dict]:
        """Return a bounded, deduped list of link targets from page facts.

        Deduplicates on ``(kind, target_hash)`` so a page linking the same URL
        twice checks it once, and caps at ``max_link_checks_per_page``.
        """
        links = facts.get("links") or {}
        collected: list[dict] = []
        seen: set[tuple[str, str]] = set()
        limit = site_health_settings.max_link_checks_per_page
        for kind in ("anchors", "images", "scripts", "stylesheets"):
            for entry in links.get(kind) or []:
                if len(collected) >= limit:
                    return collected
                raw_url = str(entry.get("url") or "").strip()
                if not raw_url:
                    continue
                url = urljoin(source_final_url, raw_url)
                target_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()[:64]
                entry_kind = str(entry.get("kind") or kind)
                key = (entry_kind, target_hash)
                if key in seen:
                    continue
                seen.add(key)
                collected.append(
                    {
                        "url": url,
                        "kind": entry_kind,
                        "target_hash": target_hash,
                        "is_internal": bool(entry.get("is_internal")),
                        "rel": str(entry.get("rel") or "")[:128],
                        "anchor_text": str(entry.get("anchor_text") or "")[:1024],
                    }
                )
        return collected

    async def _probe_link(self, url: str) -> _LinkProbeOutcome:
        """Best-effort HEAD-first + GET-fallback reachability probe.

        Returns method/status/reachability evidence. Never raises — link
        checking must not crash the task. Honors the target authority's
        robots.txt (shared policy cache): a denied target is NOT probed and
        comes back policy-skipped instead of a fabricated fetch failure.
        """
        authority = _authority_key(url)
        if authority:
            policy, _, _ = await self._ensure_robots_policy(authority)
            if not policy.can_fetch(url):
                return _LinkProbeOutcome(
                    reachable=False,
                    method="-",
                    status_code=None,
                    skipped_by_policy=True,
                )
        timeout = site_health_settings.link_check_timeout_seconds
        for method in ("HEAD", "GET"):
            request = FetchRequest(
                url=url,
                purpose=FETCH_PURPOSE_LINK_CHECK,
                method=method,
                timeout_seconds=timeout,
            )
            try:
                async with self._new_fetcher() as fetcher:
                    result = await fetcher.fetch(request, enforce_scope=False)
            except FetchError:
                continue
            status = result.status_code
            if status in (405, 501) and method == "HEAD":
                # Method not allowed on HEAD: fall back to GET.
                continue
            return _LinkProbeOutcome(
                reachable=status < 400,
                method=method,
                status_code=status,
            )
        return _LinkProbeOutcome(
            reachable=False,
            method="GET",
            status_code=None,
        )

    async def _write_link_reference(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        analysis_id: uuid.UUID,
        artifact_id: uuid.UUID,
        task_id: uuid.UUID,
        target: dict,
    ) -> None:
        """Write one deduped ``SiteLinkReference`` (ON CONFLICT DO NOTHING)."""
        probe: _LinkProbeOutcome = target["probe"]
        evidence_digest = hashlib.sha256(
            (
                f"{target['kind']}|{target['rel']}|{target['anchor_text']}|"
                f"{target['url']}|{probe.method}|{probe.status_code}|"
                f"reachable={probe.reachable}|skipped={probe.skipped_by_policy}"
            ).encode()
        ).hexdigest()
        # Outcome prefixes: reachable:/unreachable: feed the finalize pass's
        # broken_internal_link evidence; policy_skipped: records a
        # robots-denied probe distinctly (never counted as checked — no
        # reachability was observed).
        if probe.skipped_by_policy:
            outcome_prefix = "policy_skipped:"
        else:
            outcome_prefix = "reachable:" if probe.reachable else "unreachable:"
        fingerprint = outcome_prefix + evidence_digest[: 64 - len(outcome_prefix)]
        await session.execute(
            pg_insert(SiteLinkReference)
            .values(
                workspace_id=crawl.workspace_id,
                source_analysis_id=analysis_id,
                source_artifact_id=artifact_id,
                kind=target["kind"],
                target_url=target["url"][:2048],
                target_hash=target["target_hash"],
                is_internal=target["is_internal"],
                rel=target["rel"],
                anchor_text=target["anchor_text"],
                evidence_fingerprint=fingerprint,
                # Existing schema has no explicit status/reachability fields.
                # This is the task provenance for the probe; the evidence
                # fingerprint carries an observable outcome prefix and hashes
                # method/status evidence without overloading rel, anchor text,
                # kind, or another semantic field.
                target_task_id=task_id,
                analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "source_artifact_id",
                    "kind",
                    "target_hash",
                    "evidence_fingerprint",
                ]
            )
        )

    # --- shared reconcile --------------------------------------------------

    async def _reconcile_crawl_status(self, crawl_id: uuid.UUID) -> None:
        """Reconcile the crawl's overall status from discovery AND analysis.

        The single shared finalize for every task kind. It:
          - terminalizes the DISCOVERY sub-state once discover tasks drain
            (progressively, even while analyze/link_check work remains);
          - drives the independent ANALYSIS lifecycle (pending -> running ->
            completed/partially_completed/failed) from the analyze task
            outcomes;
          - terminalizes the OVERALL crawl ONLY when EVERY non-terminal task of
            ALL kinds is drained, classifying completed / partially_completed /
            failed and (on analysis terminalization) persisting the aggregate
            ``SiteHealthSnapshot`` + a ``crawl.completed`` event.

        Keeping the crawl row ``FOR UPDATE`` and terminalizing exactly once (a
        completed crawl short-circuits) is what prevents a late analyze finalize
        from calling ``apply_crawl_status`` out of a terminal state (which would
        raise ``InvalidSiteCrawlTransition`` — all terminal states are empty
        sets in the transition tables).
        """
        async with self._session_factory() as session:
            crawl = await session.get(SiteCrawl, crawl_id, with_for_update=True)
            if crawl is None or not crawl_is_active(crawl):
                if crawl is not None:
                    await session.rollback()
                return

            counts = await self._task_counts(session, crawl_id)
            discover_remaining = counts["discover_non_terminal"]
            analyze_remaining = counts["analyze_non_terminal"]
            link_remaining = counts["link_non_terminal"]
            analyze_total = counts["analyze_total"]
            analyze_succeeded = counts["analyze_succeeded"]
            analyze_cancelled = counts["analyze_cancelled"]
            analyze_applicable = analyze_total - analyze_cancelled

            # Discovery sub-state: terminalize progressively once discover
            # tasks drain, independent of analyze/link_check work.
            fully_failed = crawl.discovered_url_count == 0
            discovery_partial = (
                crawl.discovered_url_count > 0 and crawl.failed_url_count > 0
            )
            if discover_remaining == 0:
                if crawl.discovery_status == DISCOVERY_STATUS_RUNNING:
                    if fully_failed:
                        apply_discovery_status(crawl, DISCOVERY_STATUS_FAILED)
                    else:
                        apply_discovery_status(crawl, DISCOVERY_STATUS_COMPLETED)
                crawl.inventory_complete = not fully_failed

            # Analysis lifecycle: move pending -> running once any analyze task
            # exists (work has been admitted), so a later terminal transition
            # is legal.
            if analyze_total > 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
                apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)

            all_drained = (
                discover_remaining == 0
                and analyze_remaining == 0
                and link_remaining == 0
            )
            if not all_drained:
                await session.commit()
                return

            # Every task of every kind is terminal: terminalize analysis + the
            # overall crawl exactly once.
            analysis_terminalized = False
            if analyze_total == 0 and crawl.analysis_status == ANALYSIS_STATUS_PENDING:
                # An empty analysis plan is a successful, terminal lifecycle,
                # not a crawl left permanently "pending". Traverse the legal
                # state machine and persist the corresponding empty snapshot.
                apply_analysis_status(crawl, ANALYSIS_STATUS_RUNNING)
            if crawl.analysis_status == ANALYSIS_STATUS_RUNNING:
                if analyze_total > 0 and analyze_applicable == 0:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_CANCELLED)
                elif analyze_succeeded == analyze_applicable:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_COMPLETED)
                elif analyze_succeeded > 0:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_PARTIALLY_COMPLETED)
                else:
                    apply_analysis_status(crawl, ANALYSIS_STATUS_FAILED)
                analysis_terminalized = True

            if analysis_terminalized:
                # v2 P2 (spec §5.3): the crawl_finalize-scoped rules run as a
                # second evaluation pass here — after analysis terminalization
                # (all link_check evidence is terminal) and BEFORE the snapshot
                # so their issues land in the severity/category rollups.
                await self._run_crawl_finalize_pass(session, crawl=crawl)
                await self._persist_snapshot(session, crawl=crawl)

            if crawl.status == CRAWL_STATUS_RUNNING:
                crawl.completed_at = _utcnow()
                if fully_failed:
                    apply_crawl_status(crawl, CRAWL_STATUS_FAILED)
                elif discovery_partial or (
                    analyze_applicable > 0 and analyze_succeeded < analyze_applicable
                ):
                    apply_crawl_status(crawl, CRAWL_STATUS_PARTIALLY_COMPLETED)
                else:
                    apply_crawl_status(crawl, CRAWL_STATUS_COMPLETED)
                record_crawl_event(
                    session,
                    crawl_id=crawl_id,
                    event_type=EVENT_CRAWL_COMPLETED,
                    message="crawl completed",
                    payload={"status": crawl.status},
                    count_disclosure=_count_disclosure(crawl),
                )
            await session.commit()

    async def _reconcile_stalled_crawls(self) -> int:
        """Force-reconcile active crawls that have no outstanding work left.

        The backstop for the whole terminalization path. ``_reconcile_crawl_status``
        is normally reached from a task's ``finally``, so ANY route that drains a
        crawl's last non-terminal task without running a worker's finalize
        (sweeper reclaim, an out-of-band status write, a process killed between
        the queue ack and the finalize) strands the crawl in an active status
        forever: no snapshot, no ``crawl.completed`` event, and clients polling
        it indefinitely.

        Rather than enumerate those routes, this asks the terminal question
        directly — active crawl, zero non-terminal tasks, untouched for longer
        than the stall threshold — and reconciles. Idempotent and safe to run
        every loop: reconcile short-circuits on terminal crawls, and requiring
        BOTH an empty queue and a quiet period keeps it clear of live crawls
        that are merely between tasks.
        """
        threshold = site_health_settings.stalled_crawl_reconcile_seconds
        if threshold <= 0:  # disabled
            return 0
        cutoff = _utcnow() - timedelta(seconds=threshold)
        async with self._session_factory() as session:
            outstanding = (
                select(SiteCrawlTask.id)
                .where(SiteCrawlTask.crawl_id == SiteCrawl.id)
                .where(SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
            )
            stalled = list(
                (
                    await session.scalars(
                        select(SiteCrawl.id)
                        .where(SiteCrawl.status.in_(list(CRAWL_ACTIVE_STATUSES)))
                        .where(SiteCrawl.updated_at < cutoff)
                        .where(~outstanding.exists())
                        .order_by(SiteCrawl.updated_at.asc())
                        .limit(site_health_settings.stalled_crawl_reconcile_batch)
                    )
                ).all()
            )
        for crawl_id in stalled:
            logger.warning(
                "reconciling stalled crawl with no outstanding tasks",
                extra={"crawl_id": str(crawl_id)},
            )
            await self._reconcile_crawl_status(crawl_id)
        return len(stalled)

    async def _task_counts(
        self, session: AsyncSession, crawl_id: uuid.UUID
    ) -> dict[str, int]:
        """Aggregate per-kind terminal/non-terminal task counts for a crawl."""

        async def _non_terminal(kind: str) -> int:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(SiteCrawlTask)
                    .where(SiteCrawlTask.crawl_id == crawl_id)
                    .where(SiteCrawlTask.task_kind == kind)
                    .where(SiteCrawlTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
                )
                or 0
            )

        analyze_total = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
            )
            or 0
        )
        analyze_succeeded = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
                .where(SiteCrawlTask.status == TASK_STATUS_SUCCEEDED)
            )
            or 0
        )
        analyze_cancelled = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == crawl_id)
                .where(SiteCrawlTask.task_kind == TASK_KIND_ANALYZE)
                .where(SiteCrawlTask.status == TASK_STATUS_CANCELLED)
            )
            or 0
        )
        return {
            "discover_non_terminal": await _non_terminal(TASK_KIND_DISCOVER),
            "analyze_non_terminal": await _non_terminal(TASK_KIND_ANALYZE),
            "link_non_terminal": await _non_terminal(TASK_KIND_LINK_CHECK),
            "analyze_total": analyze_total,
            "analyze_succeeded": analyze_succeeded,
            "analyze_cancelled": analyze_cancelled,
        }

    # --- v2 P2: crawl_finalize evaluation pass -----------------------------

    async def _run_crawl_finalize_pass(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        """Evaluate the crawl_finalize-scoped rules from cross-page evidence.

        Runs under the crawl ``FOR UPDATE`` lock that already guarantees
        exactly-once terminalization (spec §5.3). Writes NEW
        ``SiteRuleEvaluation`` rows — one per (analysis, crawl_finalize rule),
        ``ON CONFLICT DO NOTHING`` on the unique slot — plus one ``SiteIssue``
        per fail. Never mutates existing rows (invariant 3); this writer is
        the sole owner of crawl_finalize-scope rows (the analyze writer
        filtered them out, so the unique slots are free). Anchors:

          - ``technical.broken_internal_link`` / ``technical.hreflang_conflict``:
            every latest-completed analysis in this crawl (their evidence is
            per-page: link probes / hreflang alternates).
          - ``technical.sitemap_orphan``: the crawl ROOT's latest completed
            analysis only (a site-wide condition, like the site_root rules);
            simply absent when the root has no completed analysis.

        All URL normalization happens here via ``canonical_identity`` — the
        pure evaluators in ``analysis/site_health/finalize.py`` only receive
        pre-normalized, bounded inputs.
        """
        # Latest completed analysis per URL in this crawl (the same ranking
        # rule the snapshot aggregator uses, minus its active-membership join:
        # finalize evidence attaches to the URL's own latest analysis).
        ranked = (
            select(
                SitePageAnalysis.id.label("id"),
                SitePageAnalysis.site_url_id.label("site_url_id"),
                SitePageAnalysis.artifact_id.label("artifact_id"),
                func.row_number()
                .over(
                    partition_by=SitePageAnalysis.site_url_id,
                    order_by=(
                        SitePageAnalysis.created_at.desc(),
                        SitePageAnalysis.id.desc(),
                    ),
                )
                .label("latest_rank"),
            )
            .where(
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
            )
            .subquery()
        )
        rows = (
            await session.execute(
                select(ranked.c.id, ranked.c.site_url_id, ranked.c.artifact_id).where(
                    ranked.c.latest_rank == 1
                )
            )
        ).all()
        if not rows:
            return
        analysis_ids = [row.id for row in rows]
        artifact_by_analysis = {row.id: row.artifact_id for row in rows}
        site_url_by_analysis = {row.id: row.site_url_id for row in rows}

        evaluations: list[tuple[uuid.UUID, RuleEvaluation]] = []

        # --- broken_internal_link: per analysis, from its link probes. -----
        # Reachability rides the evidence_fingerprint prefix written by
        # ``_write_link_reference`` ("reachable:" / "unreachable:"); ALL link
        # kinds count as internal targets. ``policy_skipped:`` rows (a
        # robots-denied target that was never probed) are excluded: no
        # reachability was observed, so they are neither checked nor broken.
        link_rows = (
            await session.execute(
                select(
                    SiteLinkReference.source_analysis_id,
                    SiteLinkReference.target_url,
                    SiteLinkReference.evidence_fingerprint,
                ).where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.is_internal.is_(True),
                )
            )
        ).all()
        checked: dict[uuid.UUID, int] = {}
        broken: dict[uuid.UUID, list[str]] = {}
        for source_analysis_id, target_url, fingerprint in link_rows:
            fp = str(fingerprint or "")
            if fp.startswith("policy_skipped:"):
                continue
            checked[source_analysis_id] = checked.get(source_analysis_id, 0) + 1
            if fp.startswith("unreachable:"):
                bucket = broken.setdefault(source_analysis_id, [])
                if target_url not in bucket:
                    bucket.append(target_url)
        for analysis_id in analysis_ids:
            evaluations.append(
                (
                    analysis_id,
                    evaluate_broken_internal_link(
                        checked_count=checked.get(analysis_id, 0),
                        broken_urls=broken.get(analysis_id, []),
                    ),
                )
            )

        # --- hreflang_conflict: per analysis, from artifact facts. ----------
        artifacts = (
            await session.execute(
                select(
                    SiteFetchArtifact.id,
                    SiteFetchArtifact.final_url,
                    SiteFetchArtifact.normalized_facts,
                )
                .where(SiteFetchArtifact.id.in_(artifact_by_analysis.values()))
                .order_by(SiteFetchArtifact.id)
            )
        ).all()
        analysis_by_artifact = {row.artifact_id: row.id for row in rows}
        # canonical identity of each analyzed page's final URL -> alternates.
        alternates_by_page: dict[str, list[dict]] = {}
        canonical_by_artifact: dict[uuid.UUID, str] = {}
        for artifact_id, final_url, facts in artifacts:
            canonical = _canonical_or_empty(str(final_url or ""))
            if not canonical:
                continue
            canonical_by_artifact[artifact_id] = canonical
            alternates_by_page.setdefault(
                canonical,
                list((facts or {}).get("hreflang_alternates") or []),
            )
        for artifact_id, _final_url, facts in artifacts:
            analysis_id = analysis_by_artifact[artifact_id]
            alternates = list((facts or {}).get("hreflang_alternates") or [])
            source_canonical = canonical_by_artifact.get(artifact_id)
            if not alternates or not source_canonical:
                evaluations.append(
                    (
                        analysis_id,
                        evaluate_hreflang_conflict(
                            alternate_count=0,
                            checked_count=0,
                            unchecked_count=0,
                            missing_return_tags=[],
                        ),
                    )
                )
                continue
            checked_count = 0
            unchecked_count = 0
            missing: list[str] = []
            for alternate in alternates:
                target_url = str(alternate.get("url") or "")
                target_canonical = _canonical_or_empty(target_url)
                if not target_canonical:
                    unchecked_count += 1
                    continue
                # A self-referencing alternate is always fine.
                if target_canonical == source_canonical:
                    continue
                target_alternates = alternates_by_page.get(target_canonical)
                if target_alternates is None:
                    # The target was not analyzed in this crawl: it cannot be
                    # verified, so it neither passes nor fails (spec §5.3).
                    unchecked_count += 1
                    continue
                checked_count += 1
                return_tag_found = any(
                    _canonical_or_empty(str(back.get("url") or "")) == source_canonical
                    for back in target_alternates
                )
                if not return_tag_found and target_url not in missing:
                    missing.append(target_url)
            evaluations.append(
                (
                    analysis_id,
                    evaluate_hreflang_conflict(
                        alternate_count=len(alternates),
                        checked_count=checked_count,
                        unchecked_count=unchecked_count,
                        missing_return_tags=missing,
                    ),
                )
            )

        # --- sitemap_orphan: crawl-wide, anchored on the root analysis. -----
        root_canonical, root_hash = _crawl_root_identity(crawl)
        if root_hash:
            site_url_rows = (
                await session.execute(
                    select(SiteUrl.id, SiteUrl.url_hash).where(
                        SiteUrl.id.in_(site_url_by_analysis.values())
                    )
                )
            ).all()
            # Built by index rather than dict(rows): a SQLAlchemy Row is not a
            # 2-tuple to the type checker, so dict() infers dict[Never, Never].
            hash_by_site_url: dict[uuid.UUID, str] = {
                row[0]: row[1] for row in site_url_rows
            }
            root_analysis_id = next(
                (
                    row.id
                    for row in rows
                    if hash_by_site_url.get(row.site_url_id) == root_hash
                ),
                None,
            )
            if root_analysis_id is not None:
                sitemap_rows = (
                    await session.execute(
                        select(
                            SiteUrlObservation.site_url_id,
                            SiteUrlObservation.observed_url,
                        ).where(
                            SiteUrlObservation.crawl_id == crawl.id,
                            SiteUrlObservation.source_kind
                            == OBSERVATION_SOURCE_SITEMAP,
                        )
                    )
                ).all()
                # Internal anchor targets observed anywhere in this crawl: a
                # sitemap URL that no analyzed page links to is an orphan.
                anchor_rows = (
                    await session.execute(
                        select(SiteLinkReference.target_url).where(
                            SiteLinkReference.source_analysis_id.in_(analysis_ids),
                            SiteLinkReference.is_internal.is_(True),
                            SiteLinkReference.kind == LINK_KIND_ANCHOR,
                        )
                    )
                ).all()
                linked_targets: set[str] = set()
                for (target_url,) in anchor_rows:
                    target_canonical = _canonical_or_empty(str(target_url))
                    if target_canonical:
                        linked_targets.add(target_canonical)
                orphans: list[str] = []
                for _site_url_id, observed_url in sitemap_rows:
                    observed = str(observed_url or "")
                    observed_canonical = _canonical_or_empty(observed)
                    if not observed_canonical:
                        continue
                    # The crawl root is definitionally reachable (it seeds the
                    # crawl), never an orphan.
                    if observed_canonical == root_canonical:
                        continue
                    if observed_canonical not in linked_targets:
                        if observed not in orphans:
                            orphans.append(observed)
                evaluations.append(
                    (
                        root_analysis_id,
                        evaluate_sitemap_orphan(
                            sitemap_url_count=len(sitemap_rows),
                            orphan_urls=orphans,
                        ),
                    )
                )

        # Persist: new rows only, conflict-safe on the unique
        # (analysis_id, rule_id) slot; one issue per fail.
        for analysis_id, ev in evaluations:
            artifact_id = artifact_by_analysis[analysis_id]
            inserted_id = await session.scalar(
                pg_insert(SiteRuleEvaluation)
                .values(
                    workspace_id=crawl.workspace_id,
                    analysis_id=analysis_id,
                    source_artifact_id=artifact_id,
                    rule_id=ev.rule_id,
                    dimension=ev.dimension,
                    category=ev.category,
                    severity=ev.severity,
                    weight=ev.weight,
                    outcome=ev.outcome,
                    evidence=ev.evidence,
                    supporting_artifact_ids=[artifact_id],
                    extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                    analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                    rule_version=ev.rule_version,
                )
                .on_conflict_do_nothing(index_elements=["analysis_id", "rule_id"])
                .returning(SiteRuleEvaluation.id)
            )
            if inserted_id is None:
                continue
            if ev.outcome == RULE_OUTCOME_FAIL:
                session.add(
                    SiteIssue(
                        workspace_id=crawl.workspace_id,
                        project_id=crawl.project_id,
                        crawl_id=crawl.id,
                        site_url_id=site_url_by_analysis[analysis_id],
                        analysis_id=analysis_id,
                        evaluation_id=inserted_id,
                        source_artifact_id=artifact_id,
                        rule_id=ev.rule_id,
                        dimension=ev.dimension,
                        category=ev.category,
                        severity=ev.severity,
                        evidence=ev.evidence,
                        remediation=ev.remediation,
                        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                        rule_version=ev.rule_version,
                    )
                )

    async def _persist_snapshot(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        """Compute + persist the crawl aggregate snapshot (unique per crawl).

        Delegates to the canonical ``persist_crawl_snapshot`` domain helper so
        the worker and ``service.cancel_crawl`` share ONE aggregation algorithm
        (no duplicate scoring/rollup logic). ``persist_empty=True`` because a
        clean terminalization (including an empty analysis plan) must always
        write a canonical snapshot — an empty/null-score one when nothing was
        aggregated — unlike a cancel, which leaves ``score_summary`` null.
        """
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    worker = SiteHealthWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
