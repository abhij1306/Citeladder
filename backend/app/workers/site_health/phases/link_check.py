"""Phase 3 — LINK CHECK: probe a page's outbound links and record the results.

Runs after a URL's analyze task has persisted its facts: the probe targets come
from that stored analysis, so this phase never re-parses HTML. Results land as
SiteLinkReference rows, which the crawl_finalize pass later reads to decide
technical.broken_internal_link.

Split out of SiteHealthWorker for readability only — see the package
docstring; this is a mixin on the one worker class, not a separate process.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.fetcher import FetchError, FetchRequest
from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.site_health_acquisition import (
    FETCH_PURPOSE_LINK_CHECK,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.domain.site_health.normalization import canonical_identity
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import SiteLinkReference, SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl
from app.workers.site_health.outcomes import LinkProbeOutcome as _LinkProbeOutcome
from app.workers.site_health.phases.support import PhaseSupport
from app.workers.site_health.urls import authority_key as _authority_key

logger = logging.getLogger("app.workers.site_health.phases.link_check")


class LinkCheckPhaseMixin(PhaseSupport):
    """TASK_KIND_LINK_CHECK handling."""

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
            await self._probe_targets(targets)

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

    async def _probe_targets(self, targets: list[dict]) -> None:
        """Probe a page's link targets concurrently, in place.

        These probes used to run one at a time. Each one pays a host-gate slot
        acquisition plus ``per_host_delay_seconds``, and a typical page carries
        ~15 links, so a single link_check task cost ~10s and a 10-page crawl
        spent ~100s here — entirely after the UI had already shown every page
        analyzed. That gap is what made a finished crawl look hung.

        Concurrency is bounded by ``link_check_concurrency`` rather than
        unbounded ``gather``: ``max_link_checks_per_page`` allows up to 200
        targets, and firing 200 simultaneous probes at one host is exactly the
        behavior the politeness gate exists to prevent. The per-host gate and
        crawl-delay still serialize same-host probes underneath this — the win
        comes from overlapping the WAIT, and from cross-host targets no longer
        queueing behind each other.

        Order is irrelevant to correctness (each result is written back onto its
        own target dict, and the caller iterates ``targets`` in its original
        deterministic order afterwards), so results are placed by index rather
        than by completion.
        """
        if not targets:
            return
        limit = max(1, site_health_settings.link_check_concurrency)
        semaphore = asyncio.Semaphore(limit)

        async def probe(target: dict) -> None:
            async with semaphore:
                target["probe"] = await self._probe_link(target["url"])

        # ``_probe_link`` is already total — it converts fetch/policy failures
        # into an unreachable outcome — but gather defensively so one unexpected
        # crash cannot abandon the siblings mid-probe and strand the lease.
        results = await asyncio.gather(
            *(probe(target) for target in targets), return_exceptions=True
        )
        for target, result in zip(targets, results, strict=True):
            if isinstance(result, BaseException):
                if isinstance(result, asyncio.CancelledError):
                    raise result
                logger.warning(
                    "link probe failed unexpectedly",
                    exc_info=result,
                    extra={"target_url": target.get("url", "")},
                )
                target.setdefault(
                    "probe",
                    _LinkProbeOutcome(reachable=False, method="GET", status_code=None),
                )

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
        except UrlPolicyError as exc:
            # The task URL was canonicalized at admission, so a policy
            # rejection here is a defensive can't-happen — but never swallow
            # it silently into a misleading "nothing to do" success (ERR-6).
            logger.debug(
                "link-check source lookup skipped: task URL failed canonicalization",
                exc_info=True,
                extra={"error_type": type(exc).__name__},
            )
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
