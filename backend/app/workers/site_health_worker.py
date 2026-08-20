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
# Discovery and analysis share this one worker so their lifecycle can be
# terminalized from a single durable queue owner.
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.browser_transport import PatchrightTransport
from app.connectors.web_evidence.contracts import (
    DnsResolver,
    FetchResult,
    ResolvedTarget,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.url_policy import (
    split_host_port,
)
from app.core.config.site_health_acquisition import FETCH_PURPOSE_DISCOVER
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_RUNNING,
    CRAWL_TERMINAL_STATUSES,
    EXTRACTOR_VERSION,
    TASK_KIND_ANALYZE,
    TASK_KIND_CHANGE_INTEL,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_runtime import (
    SITE_CRAWL_QUEUE_SPEC,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.site_health.schemas import (
    DiscoveryOutput,
)
from app.domain.site_health.state_events import (
    apply_crawl_status,
)
from app.domain.site_health.task_guards import (
    crawl_is_active,
    lease_is_owned,
)
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.drain import DrainableWorkerMixin
from app.workers.site_health import CrawlLifecycle, HostGate
from app.workers.site_health.attempt_rows import (
    acquisition_values,
    diagnostic_attempt,
    traced_attempt,
)
from app.workers.site_health.helpers import (
    _serialize_redirect_chain,
    _utcnow,
)
from app.workers.site_health.observation_rows import write_observation
from app.workers.site_health.outcomes import AnalyzeOutcome as _AnalyzeOutcome
from app.workers.site_health.outcomes import DiscoverOutcome as _DiscoverOutcome
from app.workers.site_health.phases import (
    AnalyzePhaseMixin,
    ChangeIntelPhaseMixin,
    DiscoverPhaseMixin,
)
from app.workers.site_health.urls import authority_key as _authority_key

logger = logging.getLogger("app.workers.site_health_worker")

# Floor for the heartbeat cadence. The configured interval is the operative
# value (validated positive and strictly below the lease TTL); this only stops
# a pathological setting from spinning the loop, and is low enough that a test
# can drive the loop with a sub-second interval instead of real seconds.
_MIN_HEARTBEAT_INTERVAL_SECONDS = 0.05


class SiteHealthWorker(
    DiscoverPhaseMixin,
    AnalyzePhaseMixin,
    ChangeIntelPhaseMixin,
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
        # One browser process per WORKER, not per task (see ``_new_fetcher``).
        self._browser_transport: PatchrightTransport | None = None
        # Reuse secure httpx sessions by original origin. Requests dial a
        # validated IP literal, so pooling only by that rewritten URL could
        # reuse one hostname's TLS connection for another hostname on the same
        # IP without a fresh SNI/certificate check.
        self._http_clients: dict[tuple[str, str, int], httpx.AsyncClient] = {}

    def _new_fetcher(self) -> SecureFetcher:
        """Build a fetcher with the worker's injected transport seams.

        The resolver and httpx transport are injected together so offline
        tests never touch the network.

        The browser rung and secure httpx client are created ONCE per worker
        and injected, never left to the fetcher. ``_new_fetcher`` runs per
        task, and a fetcher-owned transport would launch and tear down a
        Chromium PROCESS for every page —
        seconds of startup per URL, and a leaked process for any fetcher whose
        close path did not run. Injected transports are not closed by the
        fetcher (see ``SecureFetcher.aclose``), so ``aclose`` below owns it.
        """
        return SecureFetcher(
            resolver=self._resolver,
            transport=self._transport,
            client_provider=self._shared_http_client,
            browser_transport=self._shared_browser_transport(),
        )

    def _shared_http_client(self, target: ResolvedTarget) -> httpx.AsyncClient:
        """Return the worker's secure pool for one original URL origin."""
        origin = (target.scheme, target.host, target.port)
        client = self._http_clients.get(origin)
        if client is None or client.is_closed:
            client = SecureFetcher.build_client(transport=self._transport)
            self._http_clients[origin] = client
        return client

    def _shared_browser_transport(self) -> PatchrightTransport | None:
        """The worker's one browser transport, created on first use."""
        if not site_health_settings.browser_enabled:
            return None
        if self._browser_transport is None:
            self._browser_transport = PatchrightTransport(settings=site_health_settings)
        return self._browser_transport

    async def _close_resource(self, resource, *, name: str) -> None:
        """Close a shared worker resource without masking worker shutdown."""
        try:
            await resource.aclose()
        except Exception:  # noqa: BLE001
            logger.warning("%s teardown failed", name, exc_info=True)

    async def aclose(self) -> None:
        """Release the worker's shared OS-level resources.

        Teardown NEVER raises one of its OWN. This runs on the shutdown path,
        where the caller is usually already unwinding ``run_forever``'s own
        exception or a ``CancelledError`` — letting a dying browser process
        raise here would replace the reason the worker is shutting down with a
        footnote about cleanup, and the transport is dropped either way.
        """
        resources = [
            *((client, "http client") for client in self._http_clients.values()),
            (self._browser_transport, "browser transport"),
        ]
        self._http_clients = {}
        self._browser_transport = None
        resources = [
            (resource, name) for resource, name in resources if resource is not None
        ]
        if not resources:
            return
        # ``CancelledError`` derives from ``BaseException``, so the guard in
        # ``_close_resource`` cannot see it: a cancel landing while the close
        # is in flight would abandon a live Chromium process for the
        # container's lifetime — exactly what ``run_forever``'s ``finally``
        # exists to prevent. Shield the close from that cancel, then wait it
        # out so the process is actually gone before the cancellation resumes
        # unwinding; the cancellation itself is re-raised, never swallowed.
        closing = asyncio.gather(
            *(self._close_resource(resource, name=name) for resource, name in resources)
        )
        try:
            await asyncio.shield(closing)
        except asyncio.CancelledError:
            await closing
            raise

    async def run_once(self) -> int:
        """Sweep expired leases, claim a batch of all task kinds, execute it.

        Claims discovery, analysis, and post-crawl change tasks.
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
                TASK_KIND_CHANGE_INTEL,
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
        fetch heartbeats are owned by ``_run_discover`` / ``_run_analyze`` —
        one loop per active fetch, never two.
        """
        if task.task_kind == TASK_KIND_CHANGE_INTEL:
            await self._execute_task(task)
            return
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
        try:
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
        finally:
            # A cancelled worker still owns a browser process; leaving it to the
            # interpreter strands it for the container's lifetime.
            await self.aclose()

    async def _prepare_claimed_task(
        self,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
        workspace_id: uuid.UUID,
        kind: str,
    ) -> bool:
        async with self._session_factory() as session:
            task = await session.scalar(
                select(SiteCrawlTask).where(
                    SiteCrawlTask.id == task_id,
                    SiteCrawlTask.crawl_id == crawl_id,
                    SiteCrawlTask.workspace_id == workspace_id,
                )
            )
            crawl = await session.scalar(
                select(SiteCrawl)
                .where(
                    SiteCrawl.id == crawl_id,
                    SiteCrawl.workspace_id == workspace_id,
                )
                .with_for_update()
            )
            if task is None or crawl is None:
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                return False
            terminal_refresh = (
                kind == TASK_KIND_CHANGE_INTEL
                and crawl.status in CRAWL_TERMINAL_STATUSES
            )
            if not crawl_is_active(crawl) and not terminal_refresh:
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                await self._reconcile_crawl_status(crawl_id)
                return False
            if not terminal_refresh:
                self._ensure_running(crawl)
            await session.commit()
        return True

    async def _dispatch_task(self, claimed: SiteCrawlTask) -> None:
        kind = claimed.task_kind
        if kind == TASK_KIND_DISCOVER:
            await self._run_discover(claimed.id, claimed.crawl_id)
        elif kind == TASK_KIND_ANALYZE:
            await self._run_analyze(claimed.id, claimed.crawl_id, claimed.workspace_id)
        elif kind == TASK_KIND_CHANGE_INTEL:
            await self._run_change_intel(
                claimed.id, claimed.crawl_id, claimed.workspace_id
            )
        else:
            raise NotImplementedError(f"unknown task kind '{kind}'")

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
            if not await self._prepare_claimed_task(
                task_id=task_id,
                crawl_id=crawl_id,
                workspace_id=claimed.workspace_id,
                kind=kind,
            ):
                return

            # Mark the queue row running (still owned) before the fetch.
            if not await self._queue.mark_running(task_id=task_id, owner=self.owner):
                # Lease lost (sweeper reclaimed it); another worker will retry.
                return
            await self._dispatch_task(claimed)
        except Exception as exc:  # defensive: never let one task kill the loop
            logger.exception(
                "site health task crashed",
                extra={"task_id": str(task_id), "task_kind": kind},
            )
            await self._record_crash(task_id, exc)
        finally:
            # Change intelligence runs after terminalization; acquisition and
            # analysis task completion is what reconciles the crawl itself.
            if kind != TASK_KIND_CHANGE_INTEL:
                await self._reconcile_crawl_status(crawl_id)

    def _ensure_running(self, crawl: SiteCrawl) -> None:
        if crawl.status == CRAWL_STATUS_RUNNING:
            return
        if crawl.started_at is None:
            crawl.started_at = _utcnow()
        apply_crawl_status(crawl, CRAWL_STATUS_RUNNING)

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
        """Lock the crawl + task FOR UPDATE and verify we still own it.

        Guards invariant 3/acceptance-criterion 7 (single writer, no artifact
        for a cancelled/lost-lease task). Between the fetch finishing and this
        write the lease could have expired (sweeper -> another worker) or the
        crawl could have been cancelled. Returns ``(task, crawl)`` only when the
        task is still leased to THIS worker, still ``running``, and the crawl is
        still active; otherwise ``None`` and the fetch result is discarded.

        CANONICAL LOCK HIERARCHY — every Site Health write path takes these in
        exactly this order, and none may invert a pair:

            workspace entitlement -> monitored membership -> crawl -> task

        This path needs only the last two. It used to take task THEN crawl,
        which is the inverse of ``_lock_guarded_analyze_task`` (and of
        ``replace_monitored_set``, which serializes on the entitlement first):
        a concurrent analyze holding the crawl and waiting on the task, against
        a discover/link-check holding the task and waiting on the crawl, is a
        textbook ABBA deadlock that Postgres resolves by killing one of them.

        The unlocked hint read keeps the common "lease already lost" case from
        taking any lock at all; ownership is re-checked under the lock, because
        the hint is not authoritative. ``populate_existing`` is required for the
        same reason it is in the analyze path: a plain locked ``get()`` will not
        overwrite attributes already loaded into the identity map, so a caller
        would read pre-lock values and lose concurrent updates.
        """
        # Cheap unlocked pre-check — bail before touching any lock.
        task_hint = await session.get(SiteCrawlTask, task_id)
        if not lease_is_owned(task_hint, owner=self.owner):
            return None
        if task_hint.status != TASK_STATUS_RUNNING:
            return None
        # Crawl BEFORE task. A concurrent cancellation/terminalization must not
        # be able to commit between the active check and the evidence commit
        # (invariant 3: a cancelled task writes NOTHING).
        crawl = await session.get(
            SiteCrawl, crawl_id, with_for_update=True, populate_existing=True
        )
        if not crawl_is_active(crawl):
            return None
        task = await session.get(
            SiteCrawlTask, task_id, with_for_update=True, populate_existing=True
        )
        # Re-verify under the lock: the hint above was read without one.
        if not lease_is_owned(task, owner=self.owner):
            return None
        if task.status != TASK_STATUS_RUNNING:
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
        """
        content_hash = hashlib.sha256(result.body or b"").hexdigest()
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=crawl.id,
            workspace_id=crawl.workspace_id,
            fetch_purpose=fetch_purpose,
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
            **acquisition_values(result.acquisition),
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
        await write_observation(
            session,
            crawl=crawl,
            task=task,
            output=output,
            depth=depth,
            artifact_id=artifact_id,
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
        every redirect hop gets its own row sharing the QUEUE-attempt number
        (``attempt_number``) and distinguished by the deterministic per-call
        ``request_ordinal`` — order/uniqueness key
        ``(task_id, attempt_number, request_ordinal)``. Each row records the
        per-call host/status/latency/byte counts, and a per-call outcome:
        ``error`` when the call itself failed (transport error token), when it
        received an HTTP error status, or when it is the terminal call of an
        unsuccessful fetch; otherwise ``success``. ONLY the successful
        terminal call links the artifact — a blocked call is an attempt only,
        never an artifact generation.

        When the trace is empty (no network call happened — a robots/policy
        short-circuit — or a trace-less result built by a caller), the
        historical single diagnostic row for the queue attempt is kept, with
        ``request_ordinal=0``.

        Shared by discover and analyze; ``succeeded`` is decided by the caller
        (a discover success has a parsed ``output``, an analyze success has
        parsed ``facts``) so this stays agnostic to the outcome payload shape.
        """
        attempt_number = task.attempt_count + 1
        trace = outcome.attempts
        if not trace:
            session.add(
                diagnostic_attempt(
                    crawl=crawl,
                    task=task,
                    outcome=outcome,
                    succeeded=succeeded,
                    requested_url=requested_url,
                    artifact_id=artifact_id,
                    attempt_number=attempt_number,
                )
            )
            return

        last_index = len(trace) - 1
        for index, entry in enumerate(trace):
            is_final = index == last_index
            session.add(
                traced_attempt(
                    crawl=crawl,
                    task=task,
                    outcome=outcome,
                    entry=entry,
                    succeeded=succeeded,
                    is_final=is_final,
                    artifact_id=artifact_id,
                    attempt_number=attempt_number,
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

    async def _reconcile_crawl_status(self, crawl_id: uuid.UUID) -> None:
        await self._lifecycle.reconcile(crawl_id)

    async def _reconcile_stalled_crawls(self) -> int:
        return await self._lifecycle.reconcile_stalled()


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    instrument_worker("site-health-worker")
    worker = SiteHealthWorker()
    asyncio.run(worker.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
