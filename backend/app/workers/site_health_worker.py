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
# The same queue owns discovery, analysis, and the post-terminal change,
# link-metric, and architecture derivations. Network tasks use the SSRF-safe
# fetcher; derived tasks read only persisted evidence. Each phase commits its
# evidence and successor admission atomically.
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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.contracts import (
    AcquisitionTransport,
    DnsResolver,
    FetchResult,
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
    POST_TERMINAL_SITE_TASK_KINDS,
    SITE_TASK_KINDS,
    TASK_KIND_ANALYZE,
    TASK_KIND_ARCHITECTURE,
    TASK_KIND_CHANGE_INTEL,
    TASK_KIND_DISCOVER,
    TASK_KIND_LINK_METRICS,
)
from app.core.config.site_health_runtime import (
    SITE_CRAWL_QUEUE_SPEC,
    site_health_settings,
)
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.site_health.phase_common import lock_crawl_for_evidence_commit
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
from app.workers.site_health.db_conflicts import (
    is_transient_db_conflict,
    requeue_conflicted_task,
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
    ArchitecturePhaseMixin,
    ChangeIntelPhaseMixin,
    DiscoverPhaseMixin,
    LinkMetricsPhaseMixin,
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
    LinkMetricsPhaseMixin,
    ArchitecturePhaseMixin,
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
        transport: AcquisitionTransport | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue: PostgresTaskQueue[SiteCrawlTask] = PostgresTaskQueue(
            self._session_factory, SITE_CRAWL_QUEUE_SPEC
        )
        self.owner = owner or f"site-worker-{uuid.uuid4().hex[:12]}"
        self._resolver = resolver or SystemDnsResolver()
        # Tests inject the same bounded transport contract used by curl-cffi.
        # Production leaves this empty so ``SecureFetcher`` constructs curl.
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

    def _new_fetcher(self) -> SecureFetcher:
        """Build the sole curl fetcher (or the injected offline test transport)."""
        return SecureFetcher(
            resolver=self._resolver,
            transport=self._transport,
        )

    async def aclose(self) -> None:
        """The production curl transport owns no long-lived worker resource."""

    async def run_once(self) -> int:
        """Sweep expired leases, claim a batch of all task kinds, execute it.

        Claims discovery, analysis, and post-crawl change tasks.
        """
        await self._maintenance()
        claim_limit = min(
            site_health_settings.worker_concurrency,
            site_health_settings.global_concurrency,
        )
        tasks = await self._queue.claim(
            owner=self.owner, limit=claim_limit, kinds=sorted(SITE_TASK_KINDS)
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

    async def _maintenance(self) -> None:
        """Lease sweep, stalled-crawl reconcile, and host-gate eviction."""
        sweep = await self._queue.release_expired_detailed(
            batch_size=site_health_settings.lease_reclaim_batch_size
        )
        for crawl_id in sweep.failed_parent_ids:
            await self._reconcile_crawl_status(crawl_id)
        await self._reconcile_stalled_crawls()
        self._host_gate.evict_idle()

    async def _claim_one(self) -> SiteCrawlTask | None:
        """Claim a single task for one pipeline slot, or ``None`` if idle."""
        try:
            claimed = await self._queue.claim(
                owner=self.owner,
                limit=1,
                kinds=sorted(SITE_TASK_KINDS),
            )
        except Exception:  # a DB blip must not kill the slot
            logger.exception("site health claim failed")
            return None
        return claimed[0] if claimed else None

    async def run_pipelined(self, *, drain: bool) -> int:
        """Keep ``worker_concurrency`` tasks in flight, refilling as each lands.

        ``run_once`` claims N tasks, gathers ALL of them, then claims the next
        N, so a batch costs its SLOWEST member while finished slots idle. Crawl
        latency is wildly uneven -- one measured 150-page crawl spent 91.7s of
        network time inside a 46.2s window, an effective concurrency of 2.0
        against a configured 6 -- so the spread within a batch is the common
        case, not the exception. A refilling pool turns the run's cost from
        ``sum(slowest per batch)`` into ``sum(all) / concurrency``.

        This is the same convoy fix the audit worker already carries; see
        ``AuditWorker.run_pipelined``. Each slot claims exactly one task, so
        in-flight work never exceeds the configured concurrency, and the
        per-host politeness gate still bounds what any single host sees.
        """
        concurrency = max(
            1,
            min(
                site_health_settings.worker_concurrency,
                site_health_settings.global_concurrency,
            ),
        )
        completed = 0

        async def slot() -> None:
            # Each slot decides for ITSELF when to stop: one slot seeing an
            # empty queue must not make its siblings skip their next claim.
            nonlocal completed
            while True:
                task = await self._claim_one()
                if task is None:
                    if drain:
                        return
                    await asyncio.sleep(
                        max(0.05, site_health_settings.poll_interval_seconds)
                    )
                    continue
                try:
                    await self._execute_claimed(task)
                except Exception:  # keep siblings running
                    logger.exception(
                        "site health task failed",
                        extra={"task_id": str(task.id)},
                    )
                completed += 1

        await asyncio.gather(*(slot() for _ in range(concurrency)))
        return completed

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

    async def _maintenance_forever(self) -> None:  # pragma: no cover
        """Run lease/reconcile maintenance on its own cadence.

        The pipelined pool never returns, so maintenance can no longer ride on
        the top of each batch the way it did in ``run_once``.
        """
        while True:
            try:
                await self._maintenance()
            except Exception:  # maintenance must not kill the worker
                logger.exception("site health maintenance failed")
            await asyncio.sleep(max(0.05, site_health_settings.poll_interval_seconds))

    async def run_forever(self) -> None:  # pragma: no cover - long-running loop
        logger.info("site health worker started", extra={"owner": self.owner})
        try:
            maintenance = asyncio.create_task(self._maintenance_forever())
            try:
                await self.run_pipelined(drain=False)
            finally:
                maintenance.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maintenance
        finally:
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
                select(SiteCrawl).where(
                    SiteCrawl.id == crawl_id,
                    SiteCrawl.workspace_id == workspace_id,
                )
            )
            if task is None or crawl is None:
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                return False
            terminal_refresh = (
                kind in POST_TERMINAL_SITE_TASK_KINDS
                and crawl.status in CRAWL_TERMINAL_STATUSES
            )
            # Once the crawl is running, preparation is a read-only liveness
            # check. Avoid taking its shared FOR UPDATE serialization point:
            # root discovery can legitimately hold that row while admitting a
            # sitemap batch, and a sibling analysis used to hit the database
            # lock timeout here and get terminally mislabeled as a crashed page.
            # The persist boundary still locks and re-checks crawl/task
            # ownership, so cancellation cannot write evidence after this read.
            if crawl.status == CRAWL_STATUS_RUNNING or terminal_refresh:
                await session.rollback()
                return True
            if not crawl_is_active(crawl) and not terminal_refresh:
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                await self._reconcile_crawl_status(crawl_id)
                return False

            # Only the first task needs to advance the crawl to running. Lock
            # and refresh that transition path so concurrent starters remain
            # serialized without making every later page contend on the row.
            crawl = await session.scalar(
                select(SiteCrawl)
                .where(
                    SiteCrawl.id == crawl_id,
                    SiteCrawl.workspace_id == workspace_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if crawl is None or not crawl_is_active(crawl):
                await session.rollback()
                await self._queue.cancel(task_id=task_id)
                return False
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
        elif kind == TASK_KIND_LINK_METRICS:
            await self._run_link_metrics(
                claimed.id, claimed.crawl_id, claimed.workspace_id
            )
        elif kind == TASK_KIND_ARCHITECTURE:
            await self._run_architecture(
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
            if kind not in POST_TERMINAL_SITE_TASK_KINDS:
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

        The persist phase writes the artifact, page analysis, evaluations,
        issues, and downstream tasks before its short final lock/commit. Ending
        the heartbeat when the fetch returned would leave that work running
        against the remaining lease and let the sweeper reclaim a task still
        writing. One heartbeat spans both phases; never two loops for one task.
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
        """Lock the crawl + task for final validation and verify ownership.

        Guards invariant 3/acceptance-criterion 7 (single writer, no artifact
        for a cancelled/lost-lease task). Between the fetch finishing and this
        write the lease could have expired (sweeper -> another worker) or the
        crawl could have been cancelled. Callers acquire these locks after
        preparing persistence writes but before commit, so a failed check rolls
        the whole transaction back. Returns ``(task, crawl)`` only when the task
        is still leased to THIS worker, still ``running``, and the crawl is
        still active.

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
        crawl = await lock_crawl_for_evidence_commit(
            session, workspace_id=task_hint.workspace_id, crawl_id=crawl_id
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
        # A 429 is a host-level signal, so back the whole host off here rather
        # than letting each task rediscover the limit through its own retries.
        if getattr(outcome, "status_code", None) == 429:
            try:
                host, _port = split_host_port(requested_url)
            except Exception:
                host = requested_url
            self._host_gate.note_rate_limited(
                host, getattr(outcome, "retry_after_seconds", None)
            )
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
        """Fail the task terminally, unless the database asked us to try again.

        A deadlock or serialization failure is Postgres declining to order two
        concurrent transactions, NOT a statement about the page: discovery
        admits child URLs while analyze finalizes a sibling, and each holds a
        row the other wants. Failing terminally on that turned a transient
        lock conflict into a permanently unanalyzed page and a crawl stuck at
        ``partially_completed`` -- which is what left real product URLs
        (e.g. a retailer's /dhoti detail page) missing from the catalog while
        every downstream screen showed "some pages could not be analyzed".
        Re-queue it with the normal backoff and attempt budget instead.
        """
        detail = f"{type(exc).__name__}: {exc}"
        if is_transient_db_conflict(exc) and await requeue_conflicted_task(
            self._queue,
            self._session_factory,
            owner=self.owner,
            task_id=task_id,
            detail=detail,
        ):
            return
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
