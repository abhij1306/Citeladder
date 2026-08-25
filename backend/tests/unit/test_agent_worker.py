"""Unit tests for the Growth Agent worker loop.

``AgentWorker`` was at 0% coverage: the poll/execute/backoff loop that keeps a
durable queue draining had no test at all. The claim-lease-commit half runs
against a real schema in ``tests/component/test_agent_worker.py``; this file
covers the parts that are pure control flow — owner identity, the lease budget,
gateway gating, and the loop's stop / retry / error handling — with no database
and no sleeping on the real poll interval.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app.workers import agent_worker as worker_module
from app.workers.agent_worker import AgentWorker


class _FakeSession:
    """Stands in for the async context manager ``SessionLocal()`` returns."""

    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True


def _install_session(monkeypatch: pytest.MonkeyPatch) -> _FakeSession:
    session = _FakeSession()
    monkeypatch.setattr(worker_module, "SessionLocal", lambda: session)
    return session


def _install_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    configured: bool = False,
    execution_timeout_seconds: float = 210.0,
    reconcile_poll_seconds: float = 0.01,
) -> None:
    monkeypatch.setattr(
        worker_module,
        "default_agent_settings",
        SimpleNamespace(
            configured=configured,
            execution_timeout_seconds=execution_timeout_seconds,
            reconcile_poll_seconds=reconcile_poll_seconds,
        ),
    )


def test_owner_defaults_to_a_unique_prefixed_identity() -> None:
    first = AgentWorker()
    second = AgentWorker()

    # The owner is the lease holder, so two processes must never collide on it.
    assert first._owner.startswith("agent-")
    assert second._owner.startswith("agent-")
    assert first._owner != second._owner


def test_explicit_owner_is_used_verbatim() -> None:
    assert AgentWorker(owner="agent-pinned")._owner == "agent-pinned"


@pytest.mark.asyncio
async def test_run_once_returns_zero_and_does_no_work_when_nothing_is_claimed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _install_session(monkeypatch)
    _install_settings(monkeypatch)
    executed: list[object] = []

    async def _claim(*_args: object, **_kwargs: object) -> None:
        return None

    async def _execute(*_args: object, **_kwargs: object) -> None:
        executed.append(object())

    monkeypatch.setattr(worker_module, "claim_task", _claim)
    monkeypatch.setattr(worker_module, "execute_claimed_task", _execute)

    assert await AgentWorker(owner="agent-idle").run_once() == 0
    assert executed == []
    # The session is released even on the empty path.
    assert session.closed is True


@pytest.mark.asyncio
async def test_lease_budget_is_the_execution_timeout_plus_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_session(monkeypatch)
    _install_settings(monkeypatch, execution_timeout_seconds=120.0)
    claims: list[dict[str, Any]] = []

    async def _claim(_session: object, **kwargs: Any) -> None:
        claims.append(kwargs)
        return None

    monkeypatch.setattr(worker_module, "claim_task", _claim)

    await AgentWorker(owner="agent-lease").run_once()

    # The lease has to outlive the longest permitted execution, or a task still
    # running gets stolen by a second worker mid-flight.
    assert claims == [{"owner": "agent-lease", "lease_seconds": 150.0}]


@pytest.mark.asyncio
async def test_no_gateway_is_built_when_the_default_agent_is_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_session(monkeypatch)
    _install_settings(monkeypatch, configured=False)
    run = object()
    calls: list[dict[str, Any]] = []

    async def _claim(*_args: object, **_kwargs: object) -> object:
        return run

    async def _execute(_session: object, **kwargs: Any) -> None:
        calls.append(kwargs)

    def _gateway() -> object:  # pragma: no cover - must never be reached
        raise AssertionError("gateway built without configuration")

    monkeypatch.setattr(worker_module, "claim_task", _claim)
    monkeypatch.setattr(worker_module, "execute_claimed_task", _execute)
    monkeypatch.setattr(worker_module, "create_model_gateway", _gateway)

    assert await AgentWorker(owner="agent-unconfigured").run_once() == 1
    assert calls == [{"run": run, "owner": "agent-unconfigured", "gateway": None}]


@pytest.mark.asyncio
async def test_gateway_is_built_and_passed_through_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_session(monkeypatch)
    _install_settings(monkeypatch, configured=True)
    run = object()
    gateway = object()
    calls: list[dict[str, Any]] = []

    async def _claim(*_args: object, **_kwargs: object) -> object:
        return run

    async def _execute(_session: object, **kwargs: Any) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(worker_module, "claim_task", _claim)
    monkeypatch.setattr(worker_module, "execute_claimed_task", _execute)
    monkeypatch.setattr(worker_module, "create_model_gateway", lambda: gateway)

    assert await AgentWorker(owner="agent-configured").run_once() == 1
    assert calls == [{"run": run, "owner": "agent-configured", "gateway": gateway}]


@pytest.mark.asyncio
async def test_run_forever_drains_consecutive_work_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, reconcile_poll_seconds=30.0)
    worker = AgentWorker(owner="agent-drain")
    remaining = [1, 1, 1]
    waited: list[float] = []

    async def _run_once() -> int:
        if not remaining:
            worker.stop()
            return 0
        remaining.pop()
        return 1

    async def _wait_for(awaitable: Any, timeout: float) -> None:
        waited.append(timeout)
        awaitable.close()

    monkeypatch.setattr(worker, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "wait_for", _wait_for)

    await worker.run_forever()

    # Three iterations found work and looped straight back round; only the
    # fourth, empty one reached the poll wait.
    assert remaining == []
    assert waited == [30.0]


@pytest.mark.asyncio
async def test_run_forever_waits_on_the_reconcile_interval_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch, reconcile_poll_seconds=7.5)
    worker = AgentWorker(owner="agent-idle-loop")
    waited: list[float] = []

    async def _run_once() -> int:
        return 0

    async def _wait_for(awaitable: Any, timeout: float) -> None:
        waited.append(timeout)
        awaitable.close()
        if len(waited) >= 2:
            worker.stop()

    monkeypatch.setattr(worker, "run_once", _run_once)
    monkeypatch.setattr(asyncio, "wait_for", _wait_for)

    await worker.run_forever()

    assert waited == [7.5, 7.5]


@pytest.mark.asyncio
async def test_a_failed_iteration_is_logged_and_the_loop_survives(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _install_settings(monkeypatch, reconcile_poll_seconds=0.01)
    worker = AgentWorker(owner="agent-crash")
    attempts: list[int] = []

    async def _run_once() -> int:
        attempts.append(len(attempts))
        if len(attempts) == 1:
            raise RuntimeError("claim exploded")
        worker.stop()
        return 0

    monkeypatch.setattr(worker, "run_once", _run_once)

    with caplog.at_level(logging.ERROR, logger=worker_module.logger.name):
        await worker.run_forever()

    # A transient failure must not take the worker process down: the queue
    # would stop draining with no operator signal beyond the crash.
    assert len(attempts) == 2
    assert "agent worker iteration failed" in caplog.text
    assert "claim exploded" in caplog.text


@pytest.mark.asyncio
async def test_stop_before_the_first_iteration_runs_no_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_settings(monkeypatch)
    worker = AgentWorker(owner="agent-prestopped")
    attempts: list[int] = []

    async def _run_once() -> int:  # pragma: no cover - must never be reached
        attempts.append(1)
        return 0

    monkeypatch.setattr(worker, "run_once", _run_once)
    worker.stop()

    await worker.run_forever()

    assert attempts == []


@pytest.mark.asyncio
async def test_main_stops_the_worker_and_always_disposes_the_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed: list[int] = []

    async def _dispose() -> None:
        disposed.append(1)

    async def _run_forever(self: AgentWorker) -> None:
        raise RuntimeError("loop exploded")

    monkeypatch.setattr(worker_module, "dispose_engine", _dispose)
    monkeypatch.setattr(AgentWorker, "run_forever", _run_forever)

    # The engine holds a Postgres pool; leaking it on an abnormal exit leaves
    # connections open against the durable queue.
    with pytest.raises(RuntimeError, match="loop exploded"):
        await worker_module._main()

    assert disposed == [1]
