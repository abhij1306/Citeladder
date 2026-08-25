"""Unit tests for the brand-discovery worker's poll loop and backoff.

``app/workers/brand_discovery_worker.py`` sat at 29% line coverage. The half
that persists discovery state runs against a real schema in
``tests/component/test_brand_discovery_worker.py``; this file covers the pure
control flow — idle backoff, consecutive-failure accounting, cancellation,
heartbeat cleanup, and the reaper's schedule — with no database and no real
sleeping.

The behaviour worth pinning is that a worker which keeps failing must back OFF
rather than spin: an unreachable database with a 1s poll would otherwise
produce a hot loop of failing connections and a log line per iteration.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.workers import brand_discovery_worker as worker_module


def _install_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    poll_seconds: float = 2.0,
    failure_backoff_max_seconds: float = 30.0,
    reaper_interval_seconds: float = 60.0,
) -> None:
    monkeypatch.setattr(
        worker_module,
        "brand_discovery_settings",
        SimpleNamespace(
            poll_seconds=poll_seconds,
            failure_backoff_max_seconds=failure_backoff_max_seconds,
            reaper_interval_seconds=reaper_interval_seconds,
            heartbeat_interval_seconds=0.01,
            reaper_batch_size=10,
        ),
    )


# --- idle backoff ---------------------------------------------------------


def test_a_healthy_worker_idles_at_the_poll_cadence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, poll_seconds=2.0)

    assert worker_module._idle_delay(0) == 2.0


@pytest.mark.parametrize(
    ("failures", "expected"),
    [(1, 2.0), (2, 4.0), (3, 8.0), (4, 16.0)],
)
def test_backoff_doubles_with_each_consecutive_failure(
    monkeypatch: pytest.MonkeyPatch, failures: int, expected: float
) -> None:
    _install_settings(monkeypatch, poll_seconds=2.0, failure_backoff_max_seconds=300.0)

    assert worker_module._idle_delay(failures) == expected


def test_backoff_is_capped_so_a_worker_never_sleeps_indefinitely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Uncapped doubling would put a recovered worker minutes or hours behind
    # the queue it is supposed to be draining.
    _install_settings(monkeypatch, poll_seconds=2.0, failure_backoff_max_seconds=30.0)

    assert worker_module._idle_delay(20) == 30.0


# --- failure accounting ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_successful_iteration_resets_the_failure_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        return True

    monkeypatch.setattr(worker_module, "run_once", _run_once)

    processed, failures = await worker_module._attempt_iteration(
        "w-1", asyncio.Event(), reap=False, consecutive_failures=4
    )

    assert (processed, failures) == (True, 0)


@pytest.mark.asyncio
async def test_a_failed_iteration_increments_the_failure_count(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        raise RuntimeError("queue exploded")

    monkeypatch.setattr(worker_module, "run_once", _run_once)

    with caplog.at_level(logging.ERROR, logger=worker_module.logger.name):
        processed, failures = await worker_module._attempt_iteration(
            "w-1", asyncio.Event(), reap=False, consecutive_failures=2
        )

    # The worker survives: a transient fault must not take the process down.
    assert (processed, failures) == (False, 3)
    assert "still failing" in caplog.text


@pytest.mark.asyncio
async def test_cancellation_sets_shutdown_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        raise asyncio.CancelledError

    monkeypatch.setattr(worker_module, "run_once", _run_once)
    shutdown = asyncio.Event()

    # Cancellation is a shutdown request, not an iteration failure: swallowing
    # it would leave the loop running through a terminating process.
    with pytest.raises(asyncio.CancelledError):
        await worker_module._attempt_iteration(
            "w-1", shutdown, reap=False, consecutive_failures=0
        )

    assert shutdown.is_set() is True


def test_the_first_failure_logs_a_traceback_and_later_ones_do_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger=worker_module.logger.name):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            worker_module._log_iteration_failure(1)
        worker_module._log_iteration_failure(7)

    first, later = caplog.records
    # One traceback when the problem starts; a bounded one-liner while it
    # persists, so a long outage does not fill the log with identical stacks.
    assert first.exc_info is not None
    assert later.exc_info is None
    assert later.consecutive_failures == 7


# --- heartbeat cleanup ----------------------------------------------------


@pytest.mark.asyncio
async def test_stopping_a_heartbeat_swallows_its_cancellation() -> None:
    async def _forever() -> None:
        await asyncio.sleep(3600)

    heartbeat = asyncio.create_task(_forever())

    await worker_module._stop_heartbeat(heartbeat)

    assert heartbeat.cancelled() or heartbeat.done()


@pytest.mark.asyncio
async def test_a_failing_heartbeat_is_logged_and_does_not_skip_finalize(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def _explode() -> None:
        raise RuntimeError("heartbeat lost the lease")

    heartbeat = asyncio.create_task(_explode())
    await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger=worker_module.logger.name):
        # Must not raise: the caller's `finally` still has to run `_finalize`,
        # or the task stays leased until its TTL expires.
        await worker_module._stop_heartbeat(heartbeat)

    assert "heartbeat cleanup failed" in caplog.text


# --- the loop -------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_loop_does_not_sleep_while_it_keeps_finding_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch)
    shutdown = asyncio.Event()
    remaining = [True, True, True]
    slept: list[float] = []

    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        if remaining:
            remaining.pop()
            return True
        shutdown.set()
        return False

    async def _sleep(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(worker_module, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    await worker_module._run_loop("w-1", shutdown)

    assert remaining == []
    # The final empty iteration set shutdown, so it does not sleep either.
    assert slept == []


@pytest.mark.asyncio
async def test_the_loop_sleeps_between_empty_polls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, poll_seconds=2.0)
    shutdown = asyncio.Event()
    slept: list[float] = []

    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        return False

    async def _sleep(delay: float) -> None:
        slept.append(delay)
        if len(slept) >= 3:
            shutdown.set()

    monkeypatch.setattr(worker_module, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    await worker_module._run_loop("w-1", shutdown)

    assert slept == [2.0, 2.0, 2.0]


@pytest.mark.asyncio
async def test_the_loop_backs_off_further_on_each_repeated_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, poll_seconds=1.0, failure_backoff_max_seconds=8.0)
    shutdown = asyncio.Event()
    slept: list[float] = []

    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        raise RuntimeError("database unreachable")

    async def _sleep(delay: float) -> None:
        slept.append(delay)
        if len(slept) >= 5:
            shutdown.set()

    monkeypatch.setattr(worker_module, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    await worker_module._run_loop("w-1", shutdown)

    # 1, 2, 4, then capped at 8 — never a hot loop against a dead dependency.
    assert slept == [1.0, 2.0, 4.0, 8.0, 8.0]


@pytest.mark.asyncio
async def test_the_reaper_runs_on_the_first_pass_then_on_its_own_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, poll_seconds=1.0, reaper_interval_seconds=60.0)
    shutdown = asyncio.Event()
    reaps: list[bool] = []

    async def _run_once(_worker_id: str, *, reap: bool) -> bool:
        reaps.append(reap)
        if len(reaps) >= 3:
            shutdown.set()
        return False

    async def _sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr(worker_module, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "sleep", _sleep)

    await worker_module._run_loop("w-1", shutdown)

    # Expired leases are swept immediately at startup — a worker that just
    # replaced a crashed one must not wait a full interval to free its tasks —
    # and then only once per interval.
    assert reaps == [True, False, False]


@pytest.mark.asyncio
async def test_a_worker_asked_to_stop_does_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch)
    shutdown = asyncio.Event()
    shutdown.set()
    calls: list[Any] = []

    async def _run_once(_worker_id: str, *, reap: bool) -> bool:  # pragma: no cover
        calls.append(reap)
        return False

    monkeypatch.setattr(worker_module, "run_once", _run_once)

    await worker_module._run_loop("w-1", shutdown)

    assert calls == []


# --- shutdown handlers ----------------------------------------------------


@pytest.mark.asyncio
async def test_the_loop_handler_is_preferred_when_the_platform_offers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[str] = []

    def _loop_handlers(_loop: object, _shutdown: asyncio.Event) -> None:
        installed.append("loop")

    def _fallback(_loop: object, _shutdown: asyncio.Event) -> None:  # pragma: no cover
        installed.append("fallback")

    monkeypatch.setattr(
        worker_module, "_install_loop_shutdown_handlers", _loop_handlers
    )
    monkeypatch.setattr(worker_module, "_install_fallback_shutdown_handler", _fallback)

    worker_module._install_shutdown_handler(asyncio.Event())

    assert installed == ["loop"]


@pytest.mark.asyncio
async def test_a_platform_without_loop_signal_handlers_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installed: list[str] = []

    def _loop_handlers(_loop: object, _shutdown: asyncio.Event) -> None:
        raise NotImplementedError

    def _fallback(_loop: object, _shutdown: asyncio.Event) -> None:
        installed.append("fallback")

    monkeypatch.setattr(
        worker_module, "_install_loop_shutdown_handlers", _loop_handlers
    )
    monkeypatch.setattr(worker_module, "_install_fallback_shutdown_handler", _fallback)

    # Windows raises NotImplementedError (a RuntimeError subclass) from
    # `loop.add_signal_handler`; the worker still has to be stoppable there.
    worker_module._install_shutdown_handler(asyncio.Event())

    assert installed == ["fallback"]


@pytest.mark.asyncio
async def test_a_non_main_thread_logs_rather_than_failing_to_start(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _set_fallback(*_args: object) -> None:
        raise ValueError("signal only works in main thread")

    monkeypatch.setattr(worker_module, "_set_fallback_signal", _set_fallback)

    with caplog.at_level(logging.WARNING, logger=worker_module.logger.name):
        worker_module._install_fallback_shutdown_handler(
            asyncio.get_running_loop(), asyncio.Event()
        )

    # A worker embedded in a thread still runs; it just cannot self-stop.
    assert "outside the main thread" in caplog.text
