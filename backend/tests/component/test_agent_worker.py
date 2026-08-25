"""Component tests for the Growth Agent worker's claim-lease-commit path.

``app/workers/agent_worker.py`` was at 0% coverage, so the durable-queue
contract the repository invariants call load-bearing — claim with
``FOR UPDATE SKIP LOCKED``, hold a lease, commit before network I/O — had never
been executed by a test through the worker itself.

These run the real ``AgentWorker`` against a live Postgres schema with a real
task created through the public API. ``SessionLocal`` is redirected at the
per-test session factory; nothing else about the worker is stubbed. No model
provider is configured (``tests/conftest.py`` disables ``.env`` and clears
inherited credentials for the whole suite), so ``execute_claimed_task`` takes
its deterministic-narration branch.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.agent import default_agent_settings
from app.models.agent import AgentTaskRun
from app.workers import agent_worker as worker_module
from app.workers.agent_worker import AgentWorker

from .auth_helpers import register_and_login


@pytest.fixture(autouse=True)
def _no_live_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tripwire: the worker must never build a real gateway here.

    ``tests/conftest.py`` already guarantees no provider is configured (it
    disables ``.env`` and clears inherited credentials), so
    ``default_agent_settings.configured`` is false and this branch is not
    reached. That is the belt; this is the braces — if the isolation ever
    regresses, the failure is this assertion rather than a silent network call
    to a real provider.
    """
    monkeypatch.setattr(worker_module, "create_model_gateway", _no_network_gateway)


def _no_network_gateway() -> object:  # pragma: no cover - must never be reached
    raise AssertionError(
        "the worker tried to build a live model gateway inside a component test"
    )


async def _project(client: httpx.AsyncClient, name: str) -> str:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "brand_name": name,
            "website_url": f"https://{name.casefold().replace(' ', '-')}.example",
            "industry": "Education",
            "country_code": "IN",
            "language_code": "en-IN",
            "benchmark_mode": "consumer_like",
            "default_repetitions": 1,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _queue_task(
    client: httpx.AsyncClient, project_id: str, *, idempotency_key: str
) -> str:
    response = await client.post(
        "/api/v1/agent/tasks",
        json={
            "project_id": project_id,
            "task_type": "explain",
            "objective": "Explain the saved evidence",
        },
        headers={"Idempotency-Key": idempotency_key},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "queued"
    return response.json()["id"]


def _use_test_sessions(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)


@pytest.mark.asyncio
async def test_run_once_claims_executes_and_terminalizes_a_queued_task(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-claim@example.com")
    project_id = await _project(client, "Agent Worker Claim")
    task_id = await _queue_task(client, project_id, idempotency_key="claim-1")
    _use_test_sessions(monkeypatch, session_factory)

    assert await AgentWorker(owner="agent-worker-1").run_once() == 1

    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
    assert run is not None
    assert run.status == "completed"
    assert run.attempt_count == 1
    assert run.completed_at is not None
    # The lease is released on a terminal outcome, so no later worker can
    # re-claim a finished task as an expired one.
    assert run.lease_owner in (None, "")
    assert run.lease_expires_at is None
    # Provenance: the run stays scoped to the workspace that owns the project.
    assert str(run.project_id) == project_id
    assert run.workspace_id is not None
    # No provider is configured in the test environment, so the deterministic
    # branch runs and says so rather than inventing narration.
    assert run.result is not None
    assert "Narration provider is not configured." in run.result["limitations"]


@pytest.mark.asyncio
async def test_run_once_is_a_no_op_when_the_queue_is_empty(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-empty@example.com")
    await _project(client, "Agent Worker Empty")
    _use_test_sessions(monkeypatch, session_factory)

    assert await AgentWorker(owner="agent-worker-empty").run_once() == 0

    async with session_factory() as session:
        rows = (await session.scalars(select(AgentTaskRun))).all()
    assert rows == []


@pytest.mark.asyncio
async def test_two_workers_on_one_task_execute_it_exactly_once(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-once@example.com")
    project_id = await _project(client, "Agent Worker Once")
    task_id = await _queue_task(client, project_id, idempotency_key="once-1")
    _use_test_sessions(monkeypatch, session_factory)

    first = await AgentWorker(owner="agent-worker-a").run_once()
    # The second worker arrives after the first committed a terminal status, so
    # the row is no longer claimable and the attempt count does not move.
    second = await AgentWorker(owner="agent-worker-b").run_once()

    assert (first, second) == (1, 0)
    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
    assert run is not None
    assert run.attempt_count == 1


@pytest.mark.asyncio
async def test_a_live_lease_held_by_another_owner_is_not_stolen(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-lease@example.com")
    project_id = await _project(client, "Agent Worker Lease")
    task_id = await _queue_task(client, project_id, idempotency_key="lease-1")
    now = datetime.now(UTC)
    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
        assert run is not None
        run.status = "running"
        run.lease_owner = "agent-worker-holder"
        run.heartbeat_at = now
        run.lease_expires_at = now + timedelta(minutes=5)
        await session.commit()
    _use_test_sessions(monkeypatch, session_factory)

    assert await AgentWorker(owner="agent-worker-thief").run_once() == 0

    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
    assert run is not None
    assert run.lease_owner == "agent-worker-holder"
    assert run.status == "running"


@pytest.mark.asyncio
async def test_an_expired_lease_is_reclaimed_and_the_attempt_is_counted(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-expired@example.com")
    project_id = await _project(client, "Agent Worker Expired")
    task_id = await _queue_task(client, project_id, idempotency_key="expired-1")
    now = datetime.now(UTC)
    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
        assert run is not None
        run.status = "running"
        run.attempt_count = 1
        run.lease_owner = "agent-worker-dead"
        run.heartbeat_at = now - timedelta(minutes=30)
        run.lease_expires_at = now - timedelta(minutes=5)
        await session.commit()
    _use_test_sessions(monkeypatch, session_factory)

    # A worker that died mid-task must not strand the row: the next worker
    # takes it over once the lease it was holding has run out.
    assert await AgentWorker(owner="agent-worker-successor").run_once() == 1

    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
    assert run is not None
    assert run.status == "completed"
    assert run.attempt_count == 2


@pytest.mark.asyncio
async def test_a_task_past_its_attempt_budget_fails_closed_without_executing(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-budget@example.com")
    project_id = await _project(client, "Agent Worker Budget")
    task_id = await _queue_task(client, project_id, idempotency_key="budget-1")
    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
        assert run is not None
        run.attempt_count = run.max_attempts
        await session.commit()
    _use_test_sessions(monkeypatch, session_factory)

    # Nothing is claimed, so the worker reports no work — but the row is
    # terminalized rather than left to be polled forever.
    assert await AgentWorker(owner="agent-worker-budget").run_once() == 0

    async with session_factory() as session:
        run = await session.get(AgentTaskRun, task_id)
    assert run is not None
    assert run.status == "failed"
    assert run.error_code == "attempts_exhausted"
    assert run.completed_at is not None


@pytest.mark.asyncio
async def test_the_persisted_lease_window_matches_the_configured_budget(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register_and_login(client, "agent-worker-window@example.com")
    project_id = await _project(client, "Agent Worker Window")
    task_id = await _queue_task(client, project_id, idempotency_key="window-1")
    _use_test_sessions(monkeypatch, session_factory)
    observed: list[timedelta] = []

    async def _capture(session: AsyncSession, **kwargs: object) -> None:
        run = await session.get(AgentTaskRun, task_id)
        assert run is not None
        assert run.lease_expires_at is not None
        assert run.heartbeat_at is not None
        observed.append(run.lease_expires_at - run.heartbeat_at)

    monkeypatch.setattr(worker_module, "execute_claimed_task", _capture)

    assert await AgentWorker(owner="agent-worker-window").run_once() == 1

    expected = timedelta(seconds=default_agent_settings.execution_timeout_seconds + 30)
    assert observed == [expected]
