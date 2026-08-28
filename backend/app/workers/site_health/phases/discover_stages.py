"""Site setup and sitemap ingestion/persistence stage for discovery."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.contracts import FetchError, FetchRequest, FetchResult
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.robots import RobotsPolicy
from app.connectors.web_evidence.sitemaps import SitemapCollector, SitemapParseError
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    classify_url_admission,
)
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    AI_CRAWLER_STANCE_ALLOW,
    AI_CRAWLER_STANCE_BLOCK,
    FETCH_PURPOSE_DISCOVER,
    FETCH_PURPOSE_LLMS,
    FETCH_PURPOSE_SITEMAP,
    LLMS_TXT_PATH,
    ROBOTS_FETCH_STATUS_FETCH_FAILED,
    ROBOTS_FETCH_STATUS_FETCHED,
    ROBOTS_FETCH_STATUS_NOT_FOUND,
    ROBOTS_TXT_PATH,
    SITEMAP_DEFAULT_PATHS,
)
from app.core.config.site_health_contracts import (
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    EVENT_DISCOVERY_PROGRESS,
    OBSERVATION_SOURCE_ROOT,
    OBSERVATION_SOURCE_SITEMAP,
)
from app.core.config.site_health_crawl_policy import (
    DOCUMENT_MEDIA_TYPES,
    INPUT_MODE_EXACT_URLS,
)
from app.core.config.site_health_rules import SITEMAP_CONTENT_TYPES
from app.core.config.site_health_runtime import site_health_settings
from app.core.config.task_queue import TASK_STATUS_RUNNING
from app.domain.site_health.discovery import admit_candidates, build_frontier_candidates
from app.domain.site_health.entitlements import lock_runtime
from app.domain.site_health.frontier_support import (
    enqueue_analysis_for_discovered_url,
    mark_duplicate_url,
    mark_inventory_document,
    resolve_duplicate_of_admitted_page,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import (
    AdmissionResult,
    DiscoveryOutput,
    FrontierCandidate,
)
from app.domain.site_health.state_events import (
    apply_discovery_status,
    record_crawl_event,
)
from app.domain.site_health.task_guards import crawl_is_active, lease_is_owned
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from app.models.site_health.urls import SiteUrlObservation
from app.workers.site_health.helpers import _count_disclosure
from app.workers.site_health.outcomes import DiscoverOutcome as _DiscoverOutcome
from app.workers.site_health.phases.support import PhaseSupport
from app.workers.site_health.urls import authority_key as _authority_key


def _classify_robots_fetch(body: str | None, status: int | None) -> str:
    """SH-1 (B2): classify the robots.txt fetch for the UI.

    Distinguishes "the site has NO robots.txt we must honor" (any non-5xx
    response — fail-open, the AI-crawler stance defaults to allow) from
    "robots.txt could not be fetched" (network error / 5xx — the stance is
    genuinely unknown, and per RFC 9309 a 5xx is a temporary complete
    disallow).

    EVERY non-5xx status is ``not_found``, not just 404: a 401 / 403 / 429
    robots.txt is treated by ``_ensure_robots_policy`` exactly like a 404
    (allow-all, RFC 9309 "unavailable status" — no restrictions), so
    labelling it ``fetch_failed`` told the UI the stance was unknown while
    the crawl proceeded fail-open on it.
    """
    if body is not None:
        return ROBOTS_FETCH_STATUS_FETCHED
    if status is not None and not (500 <= status < 600):
        return ROBOTS_FETCH_STATUS_NOT_FOUND
    return ROBOTS_FETCH_STATUS_FETCH_FAILED


def _crawler_stance(requested_url: str, robots_body: str | None) -> dict[str, str]:
    stance: dict[str, str] = {}
    for bot in AI_CRAWLER_BOTS:
        allowed = not robots_body or RobotsPolicy.parse(
            robots_body, user_agent=bot
        ).can_fetch(requested_url)
        stance[bot] = AI_CRAWLER_STANCE_ALLOW if allowed else AI_CRAWLER_STANCE_BLOCK
    return stance


def _discover_task_is_viable(
    task: SiteCrawlTask | None,
    crawl: SiteCrawl | None,
    *,
    owner: str,
) -> bool:
    """Cheap preflight before staging discovery writes."""
    return bool(
        task is not None
        and crawl is not None
        and lease_is_owned(task, owner=owner)
        and task.status == TASK_STATUS_RUNNING
        and crawl_is_active(crawl)
    )


def _llms_url(authority: str) -> str:
    """The well-known llms.txt URL for an authority ("" when there is none).

    One owner for the spelling: site facts state the URL even on the crawls
    that never fetch it, so ``fetched`` stays the discriminator between "not
    attempted" and "attempted and absent" (invariant 7).
    """
    return f"{authority}{LLMS_TXT_PATH}" if authority else ""


def _admitted_sitemap_urls(
    collector: SitemapCollector,
    *,
    root_registrable_domain: str,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
) -> tuple[str, ...]:
    admitted: list[str] = []
    seen_hashes: set[str] = set()
    for raw in collector.urls:
        if len(admitted) >= site_health_settings.max_sitemap_admitted_urls:
            break
        decision = classify_url_admission(
            raw,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        )
        if not decision.accepted or not decision.canonical_url:
            continue
        try:
            canonical, url_hash_value = canonical_identity(decision.canonical_url)
        except UrlPolicyError:
            continue
        if url_hash_value in seen_hashes:
            continue
        seen_hashes.add(url_hash_value)
        admitted.append(canonical)
    return tuple(admitted)


class DiscoverPersistenceMixin(PhaseSupport):
    """Own site setup, bounded sitemap ingestion, and discover persistence."""

    async def _fetch_well_known(
        self, url: str, *, purpose: str, max_bytes: int
    ) -> FetchResult | None:
        """Implemented by the acquisition-facing discover owner."""
        raise NotImplementedError

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
        """Build bounded site facts and ingest the optional sitemap tree."""
        stance = _crawler_stance(requested_url, robots_body)
        declared_sitemaps: list[str] = []
        if robots_policy is not None:
            declared_sitemaps = [
                str(url)[:2048] for url in robots_policy.sitemaps()[:16]
            ]

        # Both well-known probes sit behind the same guard. A sample crawl is
        # the free, automatic shape; it does not ingest the sitemap tree, so
        # paying for an llms.txt fetch it will not act on is a request the
        # site owner never asked us to make.
        llms_url = _llms_url(authority)
        llms_fetched = False
        llms_status: int | None = None
        llms_present = False
        sitemap_urls: tuple[str, ...] = ()
        sitemap_files: tuple[str, ...] = ()
        if not sample_mode and authority:
            llms_url, llms_fetched, llms_status, llms_present = await self._llms_facts(
                authority, robots_policy
            )
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
                "status": _classify_robots_fetch(robots_body, robots_status),
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

    async def _llms_facts(
        self, authority: str, robots_policy: RobotsPolicy | None
    ) -> tuple[str, bool, int | None, bool]:
        llms_url = _llms_url(authority)
        if not llms_url or (
            robots_policy is not None and not robots_policy.can_fetch(llms_url)
        ):
            return llms_url, False, None, False
        result = await self._fetch_well_known(
            llms_url,
            purpose=FETCH_PURPOSE_LLMS,
            max_bytes=site_health_settings.llms_txt_max_decoded_bytes,
        )
        if result is None:
            return llms_url, False, None, False
        present = 200 <= result.status_code < 300 and bool((result.body or b"").strip())
        return llms_url, True, result.status_code, present

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
        attempted: set[str] = set()
        async with self._new_fetcher() as fetcher:
            while queue and len(attempted) < settings.max_sitemap_documents:
                if collector.url_count >= settings.max_sitemap_urls:
                    # The collector is full: no further document can add a URL,
                    # so every remaining fetch and parse is pure cost. A large
                    # index used to burn all 32 document fetches to produce
                    # nothing past this point.
                    break
                url, depth = queue.pop(0)
                if url in attempted:
                    continue
                # Bound network attempts, not only successful documents. A
                # sitemap index can contain thousands of stale or blocked
                # children; counting only successful responses lets one root
                # discovery monopolize every crawl worker indefinitely.
                attempted.add(url)
                result = await self._fetch_sitemap_document(fetcher, url)
                if result is None:
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

        page_urls = _admitted_sitemap_urls(
            collector,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        )
        return page_urls, tuple(files)

    async def _fetch_sitemap_document(
        self, fetcher: SecureFetcher, url: str
    ) -> FetchResult | None:
        authority = _authority_key(url)
        if authority:
            policy, _, _ = await self._ensure_robots_policy(authority)
            if not policy.can_fetch(url):
                return None
        try:
            result = await fetcher.fetch(
                FetchRequest(
                    url=url,
                    purpose=FETCH_PURPOSE_SITEMAP,
                    allowed_content_types=SITEMAP_CONTENT_TYPES,
                    max_decoded_bytes=site_health_settings.max_sitemap_decoded_bytes,
                ),
                enforce_scope=False,
            )
        except FetchError:
            return None
        return result if 200 <= result.status_code < 300 else None

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
        retry_attempt = 0
        succeeded_artifact_id: uuid.UUID | None = None
        admission: AdmissionResult | None = None
        admitted_delta = 0
        async with self._session_factory() as session:
            task_hint = await session.get(SiteCrawlTask, task_id)
            crawl_hint = await session.get(SiteCrawl, crawl_id)
            if not _discover_task_is_viable(task_hint, crawl_hint, owner=self.owner):
                await session.rollback()
                return
            assert task_hint is not None and crawl_hint is not None
            task = task_hint
            crawl = crawl_hint

            artifact_id: uuid.UUID | None = None
            if outcome.output is not None and outcome.result is not None:
                (
                    artifact_id,
                    admission,
                    admitted_delta,
                ) = await self._persist_discover_success(
                    session,
                    crawl=crawl,
                    task=task,
                    outcome=outcome,
                    depth=depth,
                )
                succeeded_artifact_id = artifact_id

            # Validate ownership/crawl liveness after the heavy writes. Any
            # cancellation or lease loss rolls the transaction back, while the
            # crawl row itself is held only for the final counters and commit.
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, crawl_id=crawl_id
            )
            if locked is None:
                await session.rollback()
                return
            task, crawl = locked
            if depth == 0 and outcome.site_facts is not None:
                crawl.site_facts = outcome.site_facts
            if succeeded_artifact_id is not None:
                assert admission is not None
                self._apply_discover_success(
                    session,
                    crawl=crawl,
                    task=task,
                    artifact_id=succeeded_artifact_id,
                    admission=admission,
                    admitted_delta=admitted_delta,
                    depth=depth,
                )
            else:
                should_retry, retry_attempt = self._failure_retry_state(task, outcome)

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

    @staticmethod
    def _apply_discover_success(
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        artifact_id: uuid.UUID,
        admission: AdmissionResult,
        admitted_delta: int,
        depth: int,
    ) -> None:
        if admission.sample_capped:
            apply_discovery_status(crawl, DISCOVERY_STATUS_SAMPLE_COMPLETED)
        crawl.admitted_url_count += admitted_delta
        crawl.discovered_url_count += 1
        task.result_artifact_id = artifact_id
        record_crawl_event(
            session,
            crawl_id=crawl.id,
            event_type=EVENT_DISCOVERY_PROGRESS,
            message="discovery progress",
            payload={"admitted": admission.admitted, "depth": depth},
            count_disclosure=_count_disclosure(crawl),
        )

    async def _persist_discover_success(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        outcome: _DiscoverOutcome,
        depth: int,
    ) -> tuple[uuid.UUID, AdmissionResult, int]:
        assert outcome.output is not None and outcome.result is not None
        artifact_id = await self._write_artifact(
            session,
            crawl=crawl,
            task=task,
            result=outcome.result,
            normalized_facts=outcome.facts,
        )
        await self._write_observation(
            session,
            crawl=crawl,
            task=task,
            output=outcome.output,
            depth=depth,
            artifact_id=artifact_id,
        )
        # Taken HERE, not at the top of the transaction. Hoisting it above the
        # artifact/observation writes does make the lock order total, but it
        # then serializes every discover persist in the workspace for the whole
        # write -- measured, that turned 2 self-healing deadlocks per crawl into
        # 3 tasks killed outright by `lock_timeout`, and the crawl finalized
        # `partially_completed`. The narrow hold plus transient requeue is the
        # cheaper trade; `is_transient_db_conflict` covers both lock races.
        runtime = await lock_runtime(session, crawl.workspace_id)
        await session.refresh(crawl, attribute_names=["admitted_url_count"])
        admitted_before = int(crawl.admitted_url_count or 0)
        input_mode = (crawl.configuration or {}).get("input_mode", "auto")
        admission = await admit_candidates(
            session,
            crawl=crawl,
            candidates=self._candidates_for(
                outcome.output, depth, input_mode=input_mode
            ),
            enqueue_children=input_mode != INPUT_MODE_EXACT_URLS,
            phase_run_id=task.phase_run_id,
            runtime=runtime,
        )
        await self._persist_sitemap_candidates(
            session,
            crawl=crawl,
            outcome=outcome,
            depth=depth,
            input_mode=input_mode,
            phase_run_id=task.phase_run_id,
            runtime=runtime,
        )
        # This page may be an alias of one the crawl already owns -- the same
        # product reached through six collection paths, all declaring one
        # `rel=canonical`. Analyzing each alias produced duplicate analyses,
        # duplicate catalog rows, and spent budget on pages already covered.
        is_document = outcome.result.content_type in DOCUMENT_MEDIA_TYPES
        if is_document:
            await mark_inventory_document(
                session,
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                url_hash_value=task.url_hash,
            )
        duplicate_of = await resolve_duplicate_of_admitted_page(
            session,
            crawl=crawl,
            url_hash_value=task.url_hash,
            declared_canonical=str((outcome.facts or {}).get("canonical_url") or ""),
        )
        if duplicate_of:
            await mark_duplicate_url(
                session,
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                url_hash_value=task.url_hash,
            )
        elif not is_document:
            # Hand this page's analysis over now that its artifact is committed.
            # Admission deliberately does NOT queue the analyze task for a URL it
            # is also queuing for discovery: created up front, that task woke while
            # the fetch was still in flight and deferred, pushing its own
            # availability back every time until analysis was starved behind the
            # entire discovery tree. Queued here it always finds the artifact, so
            # the task is claimed once and reuses that artifact, rather than
            # burning a claim to discover it must wait.
            await enqueue_analysis_for_discovered_url(
                session,
                crawl=crawl,
                # The seeded root discover carries no site_url_id -- its identity
                # is created lazily by the admission just above -- so resolve by
                # hash rather than skipping the page the crawl most needs.
                site_url_id=task.site_url_id,
                url=task.requested_url,
                url_hash_value=task.url_hash,
                depth=depth,
                value_priority=task.priority,
                phase_run_id=task.phase_run_id,
            )
        admitted_delta = int(crawl.admitted_url_count or 0) - admitted_before
        return artifact_id, admission, admitted_delta

    async def _persist_sitemap_candidates(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        outcome: _DiscoverOutcome,
        depth: int,
        input_mode: str,
        phase_run_id: uuid.UUID | None,
        runtime: WorkspaceSiteHealthRuntime | None = None,
    ) -> None:
        if (
            depth != 0
            or not outcome.sitemap_urls
            or crawl.sample_mode
            or input_mode == INPUT_MODE_EXACT_URLS
        ):
            return
        candidates = self._sitemap_candidates(outcome.sitemap_urls)
        admission = await admit_candidates(
            session,
            crawl=crawl,
            candidates=candidates,
            phase_run_id=phase_run_id,
            runtime=runtime,
        )
        await self._write_sitemap_observations(
            session,
            crawl=crawl,
            candidates=candidates,
            admission=admission,
            phase_run_id=phase_run_id,
        )

    def _failure_retry_state(
        self, task: SiteCrawlTask, outcome: _DiscoverOutcome
    ) -> tuple[bool, int]:
        retry_attempt = task.attempt_count + 1
        exhausted = retry_attempt >= task.max_attempts
        return outcome.retryable and not exhausted, retry_attempt

    def _candidates_for(
        self, output: DiscoveryOutput, depth: int, *, input_mode: str
    ) -> list[FrontierCandidate]:
        # The discover task's own position is its randomized_position; children
        # inherit deterministic order via (parent_position, link_ordinal, hash).
        if input_mode == INPUT_MODE_EXACT_URLS:
            return []
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
                FrontierCandidate.from_admission(
                    classify_url_admission(output.requested_url),
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
                FrontierCandidate.from_admission(
                    classify_url_admission(canonical),
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
        phase_run_id: uuid.UUID | None,
    ) -> None:
        """Sparse admission-time observations for sitemap-sourced URLs.

        Mirrors ``_add_free_sample``'s observation row: the pages/inventory
        read paths scope strictly through ``SiteUrlObservation``, so a URL
        admitted only via the sitemap needs this row to be visible before
        its own discover task runs. Conflict-safe on ``(crawl_id,
        site_url_id)`` — a richer discover-path observation wins if it ran
        first.
        """
        rows: list[dict] = []
        for candidate in candidates:
            site_url_id = admission.site_url_ids.get(candidate.url_hash)
            if site_url_id is None:
                continue
            rows.append(
                {
                    "workspace_id": crawl.workspace_id,
                    "project_id": crawl.project_id,
                    "crawl_id": crawl.id,
                    "site_url_id": site_url_id,
                    "phase_run_id": phase_run_id,
                    "source_kind": OBSERVATION_SOURCE_SITEMAP,
                    "depth": candidate.depth,
                    "observed_url": candidate.url,
                    "final_url": candidate.url,
                }
            )

        batch_size = max(int(site_health_settings.admission_batch_size), 1)
        for offset in range(0, len(rows), batch_size):
            await session.execute(
                pg_insert(SiteUrlObservation)
                .values(rows[offset : offset + batch_size])
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
