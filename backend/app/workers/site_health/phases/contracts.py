"""Typed capabilities shared by Site Health phase entrypoints.

The Site Health worker owns claiming, leases, host pacing, and lifecycle
reconciliation. Phase modules receive only this frozen capability value; they
never receive or inherit the worker itself. This is intentionally a Site
Health seam and does not define a repository-wide worker abstraction.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.web_evidence.contracts import FetchCallTrace, FetchResult
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.core.config.site_health_acquisition import FETCH_PURPOSE_DISCOVER
from app.domain.site_health.schemas import DiscoveryOutput
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health.robots_cache import RobotsCache


@dataclass(slots=True)
class DiscoverOutcome:
    """Bounded in-memory result of one discover acquisition."""

    result: FetchResult | None = None
    output: DiscoveryOutput | None = None
    facts: dict | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    attempts: tuple[FetchCallTrace, ...] = ()
    site_facts: dict | None = None
    sitemap_urls: tuple[str, ...] = ()
    sitemap_files: tuple[str, ...] = ()


@dataclass(slots=True)
class AnalyzeOutcome:
    """Bounded in-memory result of one analyze acquisition."""

    result: FetchResult | None = None
    facts: dict | None = None
    error_code: str = ""
    error_detail: str = ""
    retryable: bool = False
    latency_ms: int | None = None
    status_code: int | None = None
    retry_after_seconds: float | None = None
    attempts: tuple[FetchCallTrace, ...] = ()
    reused_artifact_id: uuid.UUID | None = None


PhaseOutcome = DiscoverOutcome | AnalyzeOutcome
FetcherFactory = Callable[[], SecureFetcher]
LeaseFactory = Callable[[uuid.UUID], AbstractAsyncContextManager[None]]
HostSlotFactory = Callable[[str], AbstractAsyncContextManager[None]]


class PhaseQueue(Protocol):
    """The queue operations phase modules may perform directly."""

    async def mark_running(self, *, task_id: uuid.UUID, owner: str) -> bool: ...

    async def succeed(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        result_artifact_id: uuid.UUID | None = None,
    ) -> bool: ...

    async def cancel(self, *, task_id: uuid.UUID) -> bool: ...

    async def defer(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        delay_seconds: float = 0.0,
    ) -> bool: ...


class LockOwnedTask(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        crawl_id: uuid.UUID,
    ) -> tuple[SiteCrawlTask, SiteCrawl] | None: ...


class WriteArtifact(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        result: FetchResult,
        fetch_purpose: str = FETCH_PURPOSE_DISCOVER,
        normalized_facts: dict | None = None,
    ) -> uuid.UUID: ...


class WriteAttempt(Protocol):
    def __call__(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        outcome: PhaseOutcome,
        succeeded: bool,
        requested_url: str,
        artifact_id: uuid.UUID | None,
    ) -> None: ...


class WriteObservation(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        task: SiteCrawlTask,
        output: DiscoveryOutput,
        depth: int,
        artifact_id: uuid.UUID | None,
    ) -> None: ...


class ResolveSiteUrlId(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        url: str,
        depth: int,
    ) -> uuid.UUID | None: ...


class FinalizeQueueRow(Protocol):
    async def __call__(
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
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PhaseContext:
    """Explicit worker capabilities available to every Site Health phase."""

    session_factory: async_sessionmaker[AsyncSession]
    queue: PhaseQueue
    owner: str
    new_fetcher: FetcherFactory
    leased: LeaseFactory
    host_slot: HostSlotFactory
    robots: RobotsCache
    lock_owned_running_task: LockOwnedTask
    write_artifact: WriteArtifact
    write_attempt: WriteAttempt
    write_observation: WriteObservation
    resolve_site_url_id: ResolveSiteUrlId
    finalize_queue_row: FinalizeQueueRow
