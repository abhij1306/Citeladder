"""Component tests for brand-discovery task finalization and lease reaping.

``app/workers/brand_discovery_worker.py`` sat at 29% line coverage, and the
uncovered half was the part that decides what happens to a queue row after the
work stops: succeed, retry with backoff, or fail closed once the attempt budget
is spent. Those three outcomes are the difference between a discovery that
eventually completes, one that is retried forever, and one that strands a user
on a spinner.

``_finalize`` also has two guards that only a concurrency test can prove: it
must do nothing when the lease has moved to another worker, and nothing when
the row is already terminal. Both protect against a slow worker overwriting the
result of the worker that replaced it.

Everything here runs the real functions against a live Postgres schema.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.brand_discovery import (
    BRAND_DISCOVERY_QUEUE_SPEC,
    DISCOVERY_STATUS_COMPLETING,
    DISCOVERY_STATUS_FAILED,
    ERROR_BRAND_COMPLETION,
    ERROR_BRAND_DISCOVERY,
    TASK_KIND_BRAND_COMPLETION,
    WARNING_BRAND_COMPLETION_FAILED,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.models.discovery import BrandDiscovery, BrandDiscoveryTask
from app.models.workspace import Workspace
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers import brand_discovery_worker as worker_module

_OWNER = "worker-under-test"


async def _workspace(session: AsyncSession) -> uuid.UUID:
    workspace = Workspace(name=f"WS {uuid.uuid4().hex[:6]}")
    session.add(workspace)
    await session.flush()
    return workspace.id


async def _discovery(
    session: AsyncSession, workspace_id: uuid.UUID, *, status: str = "running"
) -> BrandDiscovery:
    row = BrandDiscovery(
        workspace_id=workspace_id,
        status=status,
        stage="research",
        input_data={"brand_name": "Acme", "website_url": "https://acme.example/"},
        domains=["acme.example"],
        idempotency_key=f"discover-{uuid.uuid4()}",
    )
    session.add(row)
    await session.flush()
    return row


async def _task(
    session: AsyncSession,
    discovery: BrandDiscovery,
    *,
    status: str = TASK_STATUS_RUNNING,
    attempt_count: int = 0,
    max_attempts: int = 3,
    lease_owner: str | None = _OWNER,
    task_kind: str = "brand_discovery",
) -> BrandDiscoveryTask:
    now = datetime.now(UTC)
    task = BrandDiscoveryTask(
        discovery_id=discovery.id,
        workspace_id=discovery.workspace_id,
        task_kind=task_kind,
        idempotency_key=f"task-{uuid.uuid4()}",
        status=status,
        attempt_count=attempt_count,
        max_attempts=max_attempts,
        lease_owner=lease_owner,
        lease_expires_at=now + timedelta(minutes=5) if lease_owner else None,
        heartbeat_at=now if lease_owner else None,
    )
    session.add(task)
    await session.flush()
    return task


@pytest.fixture(autouse=True)
def _worker_uses_the_test_database(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Point both the worker AND its queue at the per-test schema.

    ``_queue`` is built at import time from the real ``SessionLocal``, so
    redirecting only the module attribute would leave every claim, heartbeat,
    and reaper sweep talking to the developer's database.
    """
    monkeypatch.setattr(worker_module, "SessionLocal", session_factory)
    monkeypatch.setattr(
        worker_module,
        "_queue",
        PostgresTaskQueue(session_factory, BRAND_DISCOVERY_QUEUE_SPEC),
    )


# --- finalize: the three outcomes -----------------------------------------


@pytest.mark.asyncio
async def test_a_successful_run_succeeds_the_task_and_releases_the_lease(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(db_session, discovery)
    await db_session.commit()

    await worker_module._finalize(task.id, worker_id=_OWNER, error=None)

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_SUCCEEDED
    assert row.attempt_count == 1
    assert row.completed_at is not None
    assert row.error_code == ""
    assert row.error_detail == ""
    # Released, so no reaper can later mistake it for an abandoned lease.
    assert row.lease_owner is None
    assert row.lease_expires_at is None


@pytest.mark.asyncio
async def test_a_failure_inside_the_budget_is_scheduled_for_retry(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(db_session, discovery, attempt_count=0, max_attempts=3)
    await db_session.commit()
    before = datetime.now(UTC)

    await worker_module._finalize(
        task.id, worker_id=_OWNER, error=RuntimeError("research provider timed out")
    )

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_RETRY_WAIT
    assert row.attempt_count == 1
    assert row.error_code == ERROR_BRAND_DISCOVERY
    assert "research provider timed out" in row.error_detail
    # Deferred, not immediately claimable: retrying instantly would hammer the
    # dependency that just failed.
    available_at = row.available_at
    if available_at.tzinfo is None:
        available_at = available_at.replace(tzinfo=UTC)
    assert available_at > before
    assert row.lease_owner is None


@pytest.mark.asyncio
async def test_the_final_failure_fails_closed_with_the_budget_error(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    # One attempt short of the budget; this finalize spends the last one.
    task = await _task(db_session, discovery, attempt_count=2, max_attempts=3)
    await db_session.commit()

    await worker_module._finalize(
        task.id, worker_id=_OWNER, error=RuntimeError("still failing")
    )

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_FAILED
    assert row.attempt_count == 3
    assert row.completed_at is not None
    # The exhausted-budget code, not the per-attempt one: a reader must be able
    # to tell "gave up" from "one attempt failed".
    assert row.error_code == BRAND_DISCOVERY_QUEUE_SPEC.max_attempts_error
    assert "still failing" in row.error_detail


@pytest.mark.asyncio
async def test_a_long_error_is_truncated_before_it_is_persisted(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(db_session, discovery)
    await db_session.commit()

    await worker_module._finalize(
        task.id, worker_id=_OWNER, error=RuntimeError("x" * 5_000)
    )

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert len(row.error_detail) == 2_000


# --- finalize: the two guards ---------------------------------------------


@pytest.mark.asyncio
async def test_a_worker_that_lost_its_lease_writes_nothing(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(db_session, discovery, lease_owner="a-different-worker")
    await db_session.commit()

    await worker_module._finalize(task.id, worker_id=_OWNER, error=None)

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    # A slow worker finishing after its lease moved on must not overwrite the
    # successor's state.
    assert row.status == TASK_STATUS_RUNNING
    assert row.attempt_count == 0
    assert row.lease_owner == "a-different-worker"


@pytest.mark.asyncio
async def test_an_already_terminal_task_is_not_reopened(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(db_session, discovery, status=TASK_STATUS_SUCCEEDED)
    await db_session.commit()

    await worker_module._finalize(
        task.id, worker_id=_OWNER, error=RuntimeError("late failure")
    )

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_SUCCEEDED
    assert row.error_code == ""


@pytest.mark.asyncio
async def test_finalizing_a_missing_task_is_a_no_op(
    db_session: AsyncSession,
) -> None:
    # A deleted discovery cascades its task away; finalize must not raise into
    # the worker loop over it.
    await worker_module._finalize(uuid.uuid4(), worker_id=_OWNER, error=None)


# --- run_once -------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_once_reports_no_work_on_an_empty_queue(
    db_session: AsyncSession,
) -> None:
    await db_session.commit()

    assert await worker_module.run_once(_OWNER) is False


@pytest.mark.asyncio
async def test_run_once_claims_and_terminalizes_a_queued_task(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(
        db_session, discovery, status=TASK_STATUS_QUEUED, lease_owner=None
    )
    await db_session.commit()
    processed: list[uuid.UUID] = []

    async def _process(session: AsyncSession, row: BrandDiscovery) -> None:
        processed.append(row.id)

    # The research pass itself calls a provider; this test is about the queue
    # contract around it.
    monkeypatch.setattr(worker_module, "process_discovery", _process)

    assert await worker_module.run_once(_OWNER) is True

    assert processed == [discovery.id]
    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_SUCCEEDED
    assert row.lease_owner is None


@pytest.mark.asyncio
async def test_a_discovery_that_is_already_complete_is_not_reprocessed(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id, status="ready")
    task = await _task(
        db_session, discovery, status=TASK_STATUS_QUEUED, lease_owner=None
    )
    await db_session.commit()
    processed: list[uuid.UUID] = []

    async def _process(session: AsyncSession, row: BrandDiscovery) -> None:
        processed.append(row.id)

    monkeypatch.setattr(worker_module, "process_discovery", _process)

    assert await worker_module.run_once(_OWNER) is True

    # A duplicate delivery must not re-run research the user already reviewed;
    # the task still succeeds so it leaves the queue.
    assert processed == []
    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
        parent = await session.get(BrandDiscovery, discovery.id)
    assert row is not None and row.status == TASK_STATUS_SUCCEEDED
    assert parent is not None and parent.status == "ready"


@pytest.mark.asyncio
async def test_a_failing_discovery_leaves_the_task_retryable(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    task = await _task(
        db_session, discovery, status=TASK_STATUS_QUEUED, lease_owner=None
    )
    await db_session.commit()

    async def _process(session: AsyncSession, row: BrandDiscovery) -> None:
        raise RuntimeError("site unreachable")

    monkeypatch.setattr(worker_module, "process_discovery", _process)

    # `run_once` returns True — it DID process a task. "Processed" and
    # "succeeded" are different facts, and the loop only needs the former to
    # decide whether to poll again immediately.
    assert await worker_module.run_once(_OWNER) is True

    async with session_factory() as session:
        row = await session.get(BrandDiscoveryTask, task.id)
    assert row is not None
    assert row.status == TASK_STATUS_RETRY_WAIT
    assert row.error_code == ERROR_BRAND_DISCOVERY


@pytest.mark.asyncio
async def test_an_exhausted_completion_failure_terminalizes_the_discovery(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(
        db_session, workspace_id, status=DISCOVERY_STATUS_COMPLETING
    )
    task = await _task(
        db_session,
        discovery,
        status=TASK_STATUS_QUEUED,
        attempt_count=2,
        max_attempts=3,
        lease_owner=None,
        task_kind=TASK_KIND_BRAND_COMPLETION,
    )
    await db_session.commit()

    async def _fail_completion(*_: object, **__: object) -> None:
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(worker_module, "run_completion", _fail_completion)

    assert await worker_module.run_once(_OWNER) is True

    async with session_factory() as session:
        task_row = await session.get(BrandDiscoveryTask, task.id)
        parent = await session.get(BrandDiscovery, discovery.id)
    assert task_row is not None and task_row.status == TASK_STATUS_FAILED
    assert parent is not None and parent.status == DISCOVERY_STATUS_FAILED
    assert parent.error_code == ERROR_BRAND_COMPLETION
    assert WARNING_BRAND_COMPLETION_FAILED in parent.warnings


# --- reaping expired leases -----------------------------------------------


@pytest.mark.asyncio
async def test_reaping_marks_a_budget_exhausted_discovery_failed(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    expired = datetime.now(UTC) - timedelta(hours=1)
    task = await _task(db_session, discovery, attempt_count=3, max_attempts=3)
    task.lease_expires_at = expired
    task.heartbeat_at = expired
    await db_session.commit()

    await worker_module._reap_expired()

    async with session_factory() as session:
        parent = await session.get(BrandDiscovery, discovery.id)
    assert parent is not None
    # A worker that died holding the last attempt must not leave the user on a
    # spinner forever: the parent record has to say it failed, and why.
    assert parent.status == DISCOVERY_STATUS_FAILED
    assert parent.stage == "failed"
    assert parent.error_code == ERROR_BRAND_DISCOVERY
    assert "research_degraded" in parent.warnings


@pytest.mark.asyncio
async def test_reaping_does_not_duplicate_an_existing_warning(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    discovery.warnings = ["research_degraded"]
    expired = datetime.now(UTC) - timedelta(hours=1)
    task = await _task(db_session, discovery, attempt_count=3, max_attempts=3)
    task.lease_expires_at = expired
    task.heartbeat_at = expired
    await db_session.commit()

    await worker_module._reap_expired()

    async with session_factory() as session:
        parent = await session.get(BrandDiscovery, discovery.id)
    assert parent is not None
    assert parent.warnings == ["research_degraded"]


@pytest.mark.asyncio
async def test_reaping_a_live_lease_changes_nothing(
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id = await _workspace(db_session)
    discovery = await _discovery(db_session, workspace_id)
    await _task(db_session, discovery, attempt_count=3, max_attempts=3)
    await db_session.commit()

    await worker_module._reap_expired()

    async with session_factory() as session:
        parent = await session.get(BrandDiscovery, discovery.id)
    assert parent is not None
    # The lease has not expired, so the worker holding it is presumed alive.
    assert parent.status == "running"
