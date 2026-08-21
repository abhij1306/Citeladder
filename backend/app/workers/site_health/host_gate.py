"""Per-host crawler politeness: concurrency cap + start-delay pacing.

Extracted from ``SiteHealthWorker`` so the politeness rules are one small,
DB-free unit rather than four methods and four parallel dicts threaded through
a 3,100-line class. The invariants it exists to protect:

  - At most ``per_host_concurrency`` in-flight requests to one host, while
    unrelated hosts still use the full in-process concurrency budget.
  - Successive starts against one host are spaced by at least the polite delay
    (the config default, or a longer robots-declared ``crawl-delay``).
  - The per-host maps are evicted only when a host has BOTH no waiters/holders
    and has left its delay window, so cleanup can never race active crawling
    and a task claimed inside the window still honors the delay.

The delay is applied while holding a per-host start lock, so concurrent tasks
for the same host queue their starts instead of all sleeping against the same
stale ``last_started`` and then firing together.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager

from app.core.config.site_health_runtime import (
    site_health_settings,
)


class HostGate:
    """Per-host semaphores, start locks, and last-start timestamps.

    ``delay_for`` is injected rather than read here so the caller can widen the
    wait to a robots-declared crawl-delay from its own cache; the gate itself
    never fetches anything. It is called with the FULL URL of the next request
    (not a bare host), because a robots policy is scheme+host scoped and the
    caller's cache is keyed that way.
    """

    def __init__(self, *, delay_for: Callable[[str], float] | None = None) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._start_locks: dict[str, asyncio.Lock] = {}
        self._last_started: dict[str, float] = {}
        # The delay actually applied to each host's last start. Eviction must
        # compare against THIS, not the config floor: a robots crawl-delay of
        # 30s over a 1s floor would otherwise let the maps be dropped one
        # second in, discarding `_last_started` and letting the next task for
        # that host start immediately — silently ignoring the declared delay.
        self._applied_delays: dict[str, float] = {}
        # Waiters + holders per host: the maps above are only evicted once this
        # drops to zero AND the polite start-delay window has elapsed, so
        # cleanup can never race active crawling of the host.
        self._refcounts: dict[str, int] = {}
        # Monotonic deadline before which no new start may be made to a host
        # that answered 429. Distinct from the polite spacing above: that
        # paces a HEALTHY host, this backs off one that has told us to stop.
        self._cooldown_until: dict[str, float] = {}
        self._delay_for = delay_for or (lambda _url: 0.0)

    def note_rate_limited(self, host: str, retry_after_seconds: float | None) -> None:
        """Pause new starts for a host that answered 429.

        Without this, a rate-limited host is a stampede: every queued task for
        it retries independently up to ``max_attempts``, and those retries are
        exactly what keeps the host rate-limiting. One measured 150-page crawl
        of a 429-ing host spent 1176 attempts (294 tasks x 4) to acquire 3
        pages. The cooldown is per HOST, so one 429 slows every task bound for
        it rather than each task discovering the limit for itself.
        """
        wait = (
            retry_after_seconds
            if retry_after_seconds and retry_after_seconds > 0
            else site_health_settings.rate_limit_cooldown_seconds
        )
        wait = min(float(wait), site_health_settings.max_crawl_delay_seconds)
        self._cooldown_until[host] = max(
            self._cooldown_until.get(host, 0.0), time.monotonic() + wait
        )

    def _base_delay(self) -> float:
        return max(0.0, site_health_settings.per_host_delay_seconds)

    def _delay(self, url: str) -> float:
        """The polite gap before the next start: config floor, robots ceiling."""
        return max(self._base_delay(), self._delay_for(url))

    def _window(self, host: str) -> float:
        """The delay window the host's last start committed to.

        Falls back to the config floor for a host that is tracked but has not
        started anything yet (it has no robots-widened window to protect).
        """
        return self._applied_delays.get(host, self._base_delay())

    @contextlib.asynccontextmanager
    async def slot(
        self,
        host: str,
        url: str,
        *,
        on_wait: Callable[[], AbstractAsyncContextManager[None]] | None = None,
    ) -> AsyncIterator[None]:
        """Hold a polite slot for ``host`` across the body.

        Refcounts the host up front (so eviction cannot race a waiter), waits
        for the semaphore, then paces the start under the per-host lock. The
        optional ``on_wait`` context manager wraps ONLY the waiting — callers
        use it to heartbeat a lease while queued behind the gate, and it is
        exited before the body runs so the body owns its own heartbeat and the
        two never overlap.
        """
        self._refcounts[host] = self._refcounts.get(host, 0) + 1
        semaphore = self._semaphores.setdefault(
            host, asyncio.Semaphore(site_health_settings.per_host_concurrency)
        )
        start_lock = self._start_locks.setdefault(host, asyncio.Lock())
        try:
            # The stack scopes `on_wait` to the wait; `aclose()` below ends it
            # exactly when the slot is secured, and the `async with` guarantees
            # it is still released if the wait itself raises.
            async with contextlib.AsyncExitStack() as waiting:
                if on_wait is not None:
                    await waiting.enter_async_context(on_wait())
                async with semaphore:
                    async with start_lock:
                        # Serve the rate-limit backoff first: it is a stop
                        # signal from the host, not a politeness preference.
                        cooldown = self._cooldown_until.get(host, 0.0)
                        remaining = cooldown - time.monotonic()
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                        delay = self._delay(url)
                        # Remember the window this start commits to, so neither
                        # `release` nor `evict_idle` can drop the host's state
                        # before a robots-widened delay has elapsed.
                        self._applied_delays[host] = delay
                        elapsed = time.monotonic() - self._last_started.get(host, 0.0)
                        if elapsed < delay:
                            await asyncio.sleep(delay - elapsed)
                        self._last_started[host] = time.monotonic()
                    await waiting.aclose()
                    yield
        finally:
            self.release(host)

    def release(self, host: str) -> None:
        """Drop one waiter/holder reference; evict idle per-host state at zero.

        Eviction requires BOTH a zero refcount and the politeness window having
        elapsed. A host still inside its window at refcount zero is swept by
        ``evict_idle`` on a later loop iteration instead.
        """
        remaining = self._refcounts.get(host, 1) - 1
        if remaining > 0:
            self._refcounts[host] = remaining
            return
        self._refcounts.pop(host, None)
        now = time.monotonic()
        if now < self._cooldown_until.get(host, 0.0):
            return
        if now - self._last_started.get(host, 0.0) < self._window(host):
            return
        self._evict(host)

    def evict_idle(self) -> None:
        """Sweep per-host state whose refcount is zero and delay window passed."""
        now = time.monotonic()
        # `|` on dict keys already materializes a new set, so mutating the
        # underlying dicts in `_evict` below cannot disturb this iteration.
        hosts = (
            self._semaphores.keys()
            | self._start_locks.keys()
            | self._last_started.keys()
        )
        for host in hosts:
            if self._refcounts.get(host, 0) != 0:
                continue
            if now < self._cooldown_until.get(host, 0.0):
                continue
            if now - self._last_started.get(host, 0.0) >= self._window(host):
                self._evict(host)

    def _evict(self, host: str) -> None:
        self._semaphores.pop(host, None)
        self._start_locks.pop(host, None)
        self._last_started.pop(host, None)
        # Dropped with `_last_started`: keeping a stale window for a host with
        # no start timestamp would make the next `release` hold state forever.
        self._applied_delays.pop(host, None)
        self._cooldown_until.pop(host, None)

    def tracked_hosts(self) -> set[str]:
        """Hosts with live per-host state (diagnostics + tests)."""
        return set(self._semaphores) | set(self._start_locks) | set(self._last_started)
