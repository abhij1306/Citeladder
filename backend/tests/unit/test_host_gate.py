"""Unit tests for the per-host politeness gate (DB-free).

The gate's whole job is a pair of invariants that are easy to break silently:
a start is never closer to the previous one than the applicable delay, and
per-host state is never evicted while that delay window is still open. The
second is the subtle one — a robots-declared ``crawl-delay`` widens the window
well past the config floor, so eviction that measures against the floor drops
``_last_started`` early and the NEXT task starts immediately.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.config.site_health import site_health_settings
from app.workers.site_health.host_gate import HostGate


@pytest.mark.asyncio
async def test_delay_callback_receives_the_full_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``delay_for`` is a URL lookup — robots policy is scheme+host scoped."""
    monkeypatch.setattr(
        site_health_settings, "per_host_delay_seconds", 0.0, raising=False
    )
    seen: list[str] = []

    def _delay_for(url: str) -> float:
        seen.append(url)
        return 0.0

    gate = HostGate(delay_for=_delay_for)
    async with gate.slot("example.com", "https://example.com/a/b?c=1"):
        pass

    assert seen == ["https://example.com/a/b?c=1"]


@pytest.mark.asyncio
async def test_release_keeps_state_for_a_robots_widened_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crawl-delay far above the floor must survive its last holder leaving."""
    monkeypatch.setattr(
        site_health_settings, "per_host_delay_seconds", 0.0, raising=False
    )
    gate = HostGate(delay_for=lambda _url: 30.0)

    async with gate.slot("example.com", "https://example.com/"):
        pass

    # Refcount is back to zero, but the 30s window is still open: dropping the
    # maps here is what let the next task start with no delay at all.
    assert gate.tracked_hosts() == {"example.com"}
    gate.evict_idle()
    assert gate.tracked_hosts() == {"example.com"}


@pytest.mark.asyncio
async def test_idle_host_is_evicted_once_its_window_elapses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the window passed and no holders, the per-host maps are swept."""
    monkeypatch.setattr(
        site_health_settings, "per_host_delay_seconds", 0.0, raising=False
    )
    gate = HostGate(delay_for=lambda _url: 0.0)

    async with gate.slot("example.com", "https://example.com/"):
        pass

    assert gate.tracked_hosts() == set()  # released at a zero window


@pytest.mark.asyncio
async def test_successive_starts_are_spaced_by_the_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two starts against one host are paced, not fired together."""
    monkeypatch.setattr(
        site_health_settings, "per_host_delay_seconds", 0.0, raising=False
    )
    monkeypatch.setattr(site_health_settings, "per_host_concurrency", 2, raising=False)
    gate = HostGate(delay_for=lambda _url: 0.1)
    starts: list[float] = []

    async def _one() -> None:
        async with gate.slot("example.com", "https://example.com/"):
            starts.append(asyncio.get_running_loop().time())

    await asyncio.gather(_one(), _one())

    assert len(starts) == 2
    # Tolerance for timer granularity (a Windows tick is ~15ms): the assertion
    # is "clearly paced", not "paced to the millisecond".
    assert abs(starts[1] - starts[0]) >= 0.08
