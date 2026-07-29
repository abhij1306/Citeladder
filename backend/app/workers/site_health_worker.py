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
import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.contracts import (
    DnsResolver,
    FetchResult,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.url_policy import (
    split_host_port,
)
from app.core.config.site_health import (
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    EXTRACTOR_VERSION,
    FETCH_PURPOSE_DISCOVER,
    OBSERVATION_SOURCE_LINK,
    OBSERVATION_SOURCE_ROOT,
    SITE_CRAWL_QUEUE_SPEC,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_CHECK,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_RUNNING,
)
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging
from app.domain.site_health.normalization import (
    canonical_identity,
)
from app.domain.site_health.schemas import (
    DiscoveryOutput,
)
from app.domain.site_health.selection import (
    crawl_is_active,
    lease_is_owned,
)
from app.domain.site_health.state_events import (
    apply_crawl_status,
)
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteFetchAttempt,
    SiteUrl,
    SiteUrlObservation,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.drain import DrainableWorkerMixin
from app.workers.site_health import CrawlLifecycle, HostGate
from app.workers.site_health.helpers import (
    _fetch_engine_for_rung,
    _result_fetch_engine,
    _serialize_redirect_chain,
    _utcnow,
)
from app.workers.site_health.outcomes import AnalyzeOutcome as _AnalyzeOutcome
from app.workers.site_health.outcomes import DiscoverOutcome as _DiscoverOutcome
from app.workers.site_health.phases import (
    AnalyzePhaseMixin,
    DiscoverPhaseMixin,
    LinkCheckPhaseMixin,
)
from app.workers.site_health.urls import authority_key as _authority_key

logger = logging.getLogger("app.workers.site_health_worker")

# Outcome tokens for the append-only ``SiteFetchAttempt.outcome`` column.
_OUTCOME_SUCCESS = "success"
_OUTCOME_ERROR = "error"

# Floor for the heartbeat cadence. The configured interval is the operative
# value (validated positive and strictly below the lease TTL); this only stops
# a pathological setting from spinning the loop, and is low enough that a test
# can drive the loop with a sub-second interval instead of real seconds.
_MIN_HEARTBEAT_INTERVAL_SECONDS = 0.05


class SiteHealthWorker(
    DiscoverPhaseMixin,
    AnalyzePhaseMixin,
    LinkCheckPhaseMixin,
    DrainableWorkerMixin,
):
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
        # Per-host politeness (concurrency cap + start pacing + eviction). The
        # robots-declared crawl-delay is injected as a lookup so the gate never
        # fetches anything itself.
        self._host_gate = HostGate(delay_for=self._robots_crawl_delay)
        # Crawl terminalization (reconcile + finalize pass + snapshot).
        self._lifecycle = CrawlLifecycle(self._session_factory)
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
        self._host_gate.evict_idle()
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
        async with self._host_gate.slot(
            host,
            task.requested_url,
            on_wait=lambda: self._leased(task.id),
        ):
            await self._execute_task(task)

    def _robots_crawl_delay(self, url: str) -> float:
        """A robots-declared crawl-delay for ``url`` from the CACHE ONLY.

        Never fetches robots.txt: the first request to an authority goes with
        the config default, and once the fetch path has cached the policy later
        requests honor the (already config-clamped) declared delay.
        """
        cached = self._robots_cache.get(_authority_key(url))
        return cached[0].crawl_delay() if cached is not None else 0.0

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

    # --- v2 P2: robots policy cache + site setup ---------------------------

    async def _heartbeat_loop(
        self, task_id: uuid.UUID
    ) -> None:  # pragma: no cover - timing loop
        interval = max(
            _MIN_HEARTBEAT_INTERVAL_SECONDS,
            site_health_settings.heartbeat_interval_seconds,
        )
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

    # --- link-check flow ---------------------------------------------------

    # --- crawl terminalization (delegated) ---------------------------------
    # The exactly-once lifecycle lives in ``CrawlLifecycle``; these thin
    # forwarders keep the worker's own call sites (task finalize, sweeper
    # reclaim, stalled backstop) reading as before.

    async def _reconcile_crawl_status(self, crawl_id: uuid.UUID) -> None:
        await self._lifecycle.reconcile(crawl_id)

    async def _reconcile_stalled_crawls(self) -> int:
        return await self._lifecycle.reconcile_stalled()


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    worker = SiteHealthWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
