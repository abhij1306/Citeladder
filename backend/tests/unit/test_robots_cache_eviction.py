"""Unit tests for the worker's per-authority robots cache eviction (DB-free).

The cache is NOT bounded by the crawl's own domain: link checks resolve robots
for arbitrary EXTERNAL link targets, so without eviction a long-lived worker
retains one policy + one lock per host it ever probed. TTL expiry used to be
only *checked* by the read path and never removed anything.
"""

from __future__ import annotations

import asyncio

import pytest

from app.connectors.web_evidence.robots import RobotsPolicy
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.workers.site_health.phases.discover import DiscoverPhaseMixin


class _Pruner(DiscoverPhaseMixin):
    """Just the cache maps + the prune/forget logic under test."""

    def __init__(self) -> None:
        self._robots_cache: dict = {}
        self._robots_cache_ts: dict[str, float] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}

    def seed(self, authority: str, ts: float) -> None:
        policy = RobotsPolicy.parse("", user_agent="bot")
        self._robots_cache[authority] = (policy, None, 200)
        self._robots_cache_ts[authority] = ts
        self._robots_locks.setdefault(authority, asyncio.Lock())


def test_expired_authorities_are_removed_from_all_three_maps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 100.0)
    pruner = _Pruner()
    # Timestamps are monotonic-clock readings; a large negative offset is
    # simply "long ago" relative to time.monotonic() inside the prune.
    pruner.seed("https://stale.example", -10_000.0)
    pruner.seed("https://fresh.example", 10.0**12)

    pruner._prune_robots_cache()

    assert "https://stale.example" not in pruner._robots_cache
    assert "https://stale.example" not in pruner._robots_cache_ts
    assert "https://stale.example" not in pruner._robots_locks
    # The fresh entry survives.
    assert "https://fresh.example" in pruner._robots_cache


def test_size_cap_evicts_oldest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beyond the ceiling the oldest go, so external hosts cannot grow forever."""
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 10.0**9)
    monkeypatch.setattr(site_health_settings, "robots_cache_max_authorities", 3)
    pruner = _Pruner()
    for i in range(6):
        pruner.seed(f"https://h{i}.example", float(i))

    pruner._prune_robots_cache()

    assert len(pruner._robots_cache_ts) == 3
    # The three newest timestamps survived; the three oldest were dropped.
    assert set(pruner._robots_cache_ts) == {
        "https://h3.example",
        "https://h4.example",
        "https://h5.example",
    }


def test_cap_of_zero_disables_the_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 10.0**9)
    monkeypatch.setattr(site_health_settings, "robots_cache_max_authorities", 0)
    pruner = _Pruner()
    for i in range(5):
        pruner.seed(f"https://h{i}.example", float(i))

    pruner._prune_robots_cache()

    assert len(pruner._robots_cache_ts) == 5


@pytest.mark.asyncio
async def test_a_held_lock_is_never_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Eviction must not replace the lock an in-flight fetch is holding.

    Dropping it would let a second fetch for the same authority run
    concurrently against a fresh lock — exactly what the lock prevents.
    """
    monkeypatch.setattr(site_health_settings, "robots_cache_ttl_seconds", 100.0)
    pruner = _Pruner()
    pruner.seed("https://busy.example", -10_000.0)
    lock = pruner._robots_locks["https://busy.example"]

    async with lock:
        pruner._prune_robots_cache()
        # The stale ENTRY is gone, but the live lock object is retained.
        assert "https://busy.example" not in pruner._robots_cache
        assert pruner._robots_locks["https://busy.example"] is lock
