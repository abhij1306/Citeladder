"""The worker surface the phase mixins call into, declared once for typing.

A mixin's body is type-checked on its own, so every ``self._queue`` /
``self._leased(...)`` in a phase module would otherwise be an unknown
attribute. This declares that shared surface in one place — which also
documents exactly what a phase is allowed to reach for.

Signatures here are the REAL ones, not ``**kwargs: Any``. Loose stubs would be
worse than nothing: mypy checks overrides for compatibility, so a permissive
supertype both hides mistakes inside the phases and reports every concrete
implementation as an incompatible override.

Nothing here executes. ``SiteHealthWorker`` defines all of it and sits first in
the MRO, so its implementations always win; the stubs raise rather than return
``None`` so a genuine wiring mistake fails loudly.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.contracts import FetchResult
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health import FETCH_PURPOSE_DISCOVER
from app.domain.site_health.schemas import DiscoveryOutput
from app.models.site_health import SiteCrawl, SiteCrawlTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.site_health.outcomes import AnalyzeOutcome, DiscoverOutcome

if TYPE_CHECKING:
    from app.workers.site_health.lifecycle import CrawlLifecycle


class PhaseSupport:
    """Shared worker infrastructure available to every phase mixin."""

    _session_factory: async_sessionmaker[AsyncSession]
    _queue: PostgresTaskQueue[SiteCrawlTask]
    _lifecycle: CrawlLifecycle
    owner: str
    # Per-authority robots.txt cache: policy + raw body + status, the fetch
    # timestamp for TTL expiry, and a per-authority lock so concurrent tasks
    # never duplicate the fetch. Owned by the discover phase; read by the
    # worker's politeness gate and the link-check probe.
    _robots_cache: dict[str, tuple[RobotsPolicy, str | None, int | None]]
    _robots_cache_ts: dict[str, float]
    _robots_locks: dict[str, asyncio.Lock]

    def _new_fetcher(self) -> SecureFetcher:
        raise NotImplementedError

    def _leased(self, task_id: uuid.UUID) -> AbstractAsyncContextManager[None]:
        raise NotImplementedError

    async def _lock_owned_running_task(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
    ) -> tuple[SiteCrawlTask, SiteCrawl] | None:
        raise NotImplementedError

    async def _ensure_robots_policy(
        self, authority: str
    ) -> tuple[RobotsPolicy, str | None, int | None]:
        raise NotImplementedError

    # --- shared evidence writers (defined on the worker, used by phases) ---

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
        raise NotImplementedError

    def _write_attempt(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        outcome: DiscoverOutcome | AnalyzeOutcome,
        succeeded: bool,
        requested_url: str,
        artifact_id: uuid.UUID | None,
    ) -> None:
        raise NotImplementedError

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
        raise NotImplementedError

    async def _resolve_site_url_id(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        url: str,
        depth: int,
    ) -> uuid.UUID | None:
        raise NotImplementedError

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
        raise NotImplementedError
