"""Unit tests for the worker's per-authority robots cache eviction (DB-free).

Without eviction a long-lived worker retains stale policies and locks after
crawls complete. TTL expiry used to be only *checked* by the read path and
never removed anything.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import cast

import pytest

from app.connectors.web_evidence.contracts import FetchRequest, FetchResult
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.workers.site_health.robots_cache import RobotsCache


class _UnusedFetcher:
    def __call__(self):
        raise AssertionError("eviction tests must not fetch")


def _cache() -> RobotsCache:
    factory = cast(Callable[[], SecureFetcher], _UnusedFetcher())
    return RobotsCache(new_fetcher=factory)


class _ResultFetcherFactory:
    def __init__(self, *, status: int, body: bytes = b"") -> None:
        self.calls = 0
        self.result = FetchResult(
            requested_url="https://example.com/robots.txt",
            final_url="https://example.com/robots.txt",
            status_code=status,
            redacted_headers={},
            content_type="text/plain",
            http_version="HTTP/1.1",
            body=body,
            wire_bytes=len(body),
            decoded_bytes=len(body),
            ttfb_ms=1,
            latency_ms=1,
        )

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def fetch(self, _request: FetchRequest) -> FetchResult:
        self.calls += 1
        await asyncio.sleep(0)
        return self.result


def _result_cache(factory: _ResultFetcherFactory) -> RobotsCache:
    typed = cast(Callable[[], SecureFetcher], factory)
    return RobotsCache(new_fetcher=typed)


def _seed(cache: RobotsCache, authority: str, ts: float) -> None:
    policy = RobotsPolicy.parse("", user_agent="bot")
    cache._entries[authority] = (policy, None, 200)
    cache._fetched_at[authority] = ts
    cache._locks.setdefault(authority, asyncio.Lock())


def test_expired_authorities_are_removed_from_all_three_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 100.0)
    cache = _cache()
    # Timestamps are monotonic-clock readings; a large negative offset is
    # simply "long ago" relative to time.monotonic() inside the prune.
    _seed(cache, "https://stale.example", -10_000.0)
    _seed(cache, "https://fresh.example", 10.0**12)

    cache.prune()

    assert "https://stale.example" not in cache._entries
    assert "https://stale.example" not in cache._fetched_at
    assert "https://stale.example" not in cache._locks
    # The fresh entry survives.
    assert "https://fresh.example" in cache._entries


def test_size_cap_evicts_oldest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beyond the ceiling the oldest go, so external hosts cannot grow forever."""
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 10.0**9)
    monkeypatch.setattr(site_health_settings, "robots_cache_max_authorities", 3)
    cache = _cache()
    for i in range(6):
        _seed(cache, f"https://h{i}.example", float(i))

    cache.prune()

    assert len(cache._fetched_at) == 3
    # The three newest timestamps survived; the three oldest were dropped.
    assert set(cache._fetched_at) == {
        "https://h3.example",
        "https://h4.example",
        "https://h5.example",
    }


def test_cap_of_zero_disables_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 10.0**9)
    monkeypatch.setattr(site_health_settings, "robots_cache_max_authorities", 0)
    cache = _cache()
    for i in range(5):
        _seed(cache, f"https://h{i}.example", float(i))

    cache.prune()

    assert len(cache._fetched_at) == 5


@pytest.mark.asyncio
async def test_a_held_lock_is_never_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eviction must not replace the lock an in-flight fetch is holding.

    Dropping it would let a second fetch for the same authority run
    concurrently against a fresh lock — exactly what the lock prevents.
    """
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 100.0)
    cache = _cache()
    _seed(cache, "https://busy.example", -10_000.0)
    lock = cache._locks["https://busy.example"]

    async with lock:
        cache.prune()
        # The stale ENTRY is gone, but the live lock object is retained.
        assert "https://busy.example" not in cache._entries
        assert cache._locks["https://busy.example"] is lock


@pytest.mark.asyncio
async def test_concurrent_ensure_deduplicates_fetch_and_exposes_cached_delay() -> None:
    factory = _ResultFetcherFactory(
        status=200,
        body=b"User-agent: *\nCrawl-delay: 2\n",
    )
    cache = _result_cache(factory)
    authority = "https://example.com:443"

    first, second = await asyncio.gather(
        cache.ensure(authority), cache.ensure(authority)
    )

    assert factory.calls == 1
    assert first is second
    assert cache.crawl_delay(f"{authority}/page") == 2.0


@pytest.mark.asyncio
async def test_5xx_policy_is_temporary_deny_all() -> None:
    cache = _result_cache(_ResultFetcherFactory(status=503))
    authority = "https://example.com"

    policy, body, status = await cache.ensure(authority)

    assert body is None
    assert status == 503
    assert policy.unavailable is True
    assert policy.can_fetch(f"{authority}/page") is False
