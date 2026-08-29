"""Bounded per-authority robots policy cache for the Site Health worker."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from app.connectors.web_evidence.contracts import FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health_acquisition import (
    FETCH_PURPOSE_ROBOTS,
    ROBOTS_TXT_PATH,
    SITE_HEALTH_USER_AGENT,
)
from app.core.config.site_health_runtime import site_health_settings
from app.workers.site_health.urls import authority_key

RobotsEntry = tuple[RobotsPolicy, str | None, int | None]


class RobotsCache:
    """Fetch, cache, and evict robots policies for one worker process."""

    def __init__(self, *, new_fetcher: Callable[[], SecureFetcher]) -> None:
        self._new_fetcher = new_fetcher
        self._entries: dict[str, RobotsEntry] = {}
        self._fetched_at: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def crawl_delay(self, url: str) -> float:
        """Return a cached crawl delay without performing network I/O."""
        cached = self._entries.get(authority_key(url))
        return cached[0].crawl_delay() if cached is not None else 0.0

    def _cached(self, authority: str) -> RobotsEntry | None:
        cached = self._entries.get(authority)
        if cached is None:
            return None
        fetched_at = self._fetched_at.get(authority, 0.0)
        if (
            time.monotonic() - fetched_at
            >= site_health_settings.robots_cache_ttl_seconds
        ):
            return None
        return cached

    async def ensure(self, authority: str) -> RobotsEntry:
        """Return the current policy, fetching robots.txt once when needed."""
        cached = self._cached(authority)
        if cached is not None:
            return cached
        lock = self._locks.setdefault(authority, asyncio.Lock())
        async with lock:
            cached = self._cached(authority)
            if cached is not None:
                return cached
            body, status = await self._fetch(authority)
            if status is not None and 500 <= status < 600:
                policy = RobotsPolicy.deny_all(user_agent=SITE_HEALTH_USER_AGENT)
            else:
                policy = RobotsPolicy.parse(
                    body or "", user_agent=SITE_HEALTH_USER_AGENT
                )
            entry = (policy, body, status)
            self._entries[authority] = entry
            self._fetched_at[authority] = time.monotonic()
            self.prune()
            return entry

    async def _fetch(self, authority: str) -> tuple[str | None, int | None]:
        request = FetchRequest(
            url=f"{authority}{ROBOTS_TXT_PATH}",
            purpose=FETCH_PURPOSE_ROBOTS,
            max_wire_bytes=site_health_settings.robots_max_decoded_bytes,
            max_decoded_bytes=site_health_settings.robots_max_decoded_bytes,
        )
        try:
            async with self._new_fetcher() as fetcher:
                result = await fetcher.fetch(request)
        except Exception:  # noqa: BLE001 - cancellation remains a BaseException
            return None, None
        body = None
        if 200 <= result.status_code < 300:
            body = (result.body or b"").decode("utf-8", errors="replace")
        return body, result.status_code

    def forget(self, authority: str) -> None:
        """Remove one cached authority without replacing an active lock."""
        self._entries.pop(authority, None)
        self._fetched_at.pop(authority, None)
        lock = self._locks.get(authority)
        if lock is not None and not lock.locked():
            self._locks.pop(authority, None)

    def prune(self) -> None:
        """Evict expired entries, then enforce the configured size ceiling."""
        now = time.monotonic()
        ttl = site_health_settings.robots_cache_ttl_seconds
        for authority in [
            key for key, timestamp in self._fetched_at.items() if now - timestamp >= ttl
        ]:
            self.forget(authority)
        cap = site_health_settings.robots_cache_max_authorities
        if cap <= 0 or len(self._fetched_at) <= cap:
            return
        oldest = sorted(self._fetched_at.items(), key=lambda item: item[1])
        for authority, _timestamp in oldest[: len(self._fetched_at) - cap]:
            self.forget(authority)
