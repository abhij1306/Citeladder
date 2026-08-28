"""A lock conflict is not a page failure.

Discovery admits child URLs while analyze finalizes a sibling, and each holds
a row the other wants; Postgres breaks the tie by rolling one back
(``40P01 deadlock_detected``). The worker used to record that as
``crawl_task_crashed`` — a TERMINAL failure — so a transient lock race
permanently lost a page, left the crawl ``partially_completed``, and kept real
product URLs out of the Commerce catalog. These tests pin the classification
and the re-queue that replaced it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.exc import DBAPIError

from app.core.config.site_health_runtime import site_health_settings
from app.workers.site_health.db_conflicts import is_transient_db_conflict
from app.workers.site_health_worker import SiteHealthWorker


class _PgError(Exception):
    def __init__(self, sqlstate: str) -> None:
        super().__init__("deadlock detected")
        self.sqlstate = sqlstate


def _dbapi_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, _PgError(sqlstate))


def test_deadlock_and_serialization_failures_are_transient() -> None:
    assert is_transient_db_conflict(_dbapi_error("40P01"))  # deadlock_detected
    assert is_transient_db_conflict(_dbapi_error("40001"))  # serialization_failure
    # `lock_timeout` raises this, and it was missing from the set: a sibling
    # holding a contended row just past the timeout killed the waiter outright,
    # with attempt_count AND conflict_count still 0 because the crash never
    # reached the retry path. Three tasks died that way in one measured crawl
    # and finalized it `partially_completed` -- a lock a second try would have
    # taken, reported to the user as pages that could not be analyzed.
    assert is_transient_db_conflict(_dbapi_error("55P03"))  # lock_not_available


def test_every_other_failure_stays_terminal() -> None:
    # A constraint violation, a bug, or a fetch error says something REAL about
    # the task; retrying it just burns the attempt budget.
    assert not is_transient_db_conflict(_dbapi_error("23505"))  # unique_violation
    assert not is_transient_db_conflict(ValueError("bad page"))


class _Queue:
    def __init__(self) -> None:
        self.retried: list[dict[str, Any]] = []
        self.failed: list[dict[str, Any]] = []

    async def retry(self, **kwargs: Any) -> bool:
        self.retried.append(kwargs)
        mutate = kwargs.get("mutate")
        if mutate is not None:
            mutate(SimpleNamespace(attempt_count=0))
        return True

    async def fail(self, **kwargs: Any) -> bool:
        self.failed.append(kwargs)
        return True


def _worker(task: object | None) -> tuple[SiteHealthWorker, _Queue]:
    class _Session:
        async def __aenter__(self) -> _Session:
            return self

        async def __aexit__(self, *_: object) -> None:
            return None

        async def get(self, _model: object, _id: uuid.UUID) -> object | None:
            return task

    worker = SiteHealthWorker(
        session_factory=cast(Any, _Session), owner="conflict-test"
    )
    queue = _Queue()
    worker._queue = cast(Any, queue)
    return worker, queue


@pytest.mark.asyncio
async def test_a_deadlocked_task_is_requeued_without_spending_an_attempt() -> None:
    worker, queue = _worker(
        SimpleNamespace(attempt_count=2, max_attempts=3, conflict_count=0)
    )

    await worker._record_crash(uuid.uuid4(), _dbapi_error("40P01"))

    assert queue.failed == []
    assert len(queue.retried) == 1
    requeued = queue.retried[0]
    assert requeued["error_code"] == "crawl_task_lock_conflict"
    assert requeued["mutate"] is not None
    assert requeued["delay_seconds"] > 0
    row = SimpleNamespace(attempt_count=2, conflict_count=0)
    requeued["mutate"](row)
    assert row.attempt_count == 2
    assert row.conflict_count == 1


@pytest.mark.asyncio
async def test_a_task_out_of_conflict_requeues_fails_terminally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(site_health_settings, "db_conflict_max_requeues", 2)
    worker, queue = _worker(
        SimpleNamespace(attempt_count=0, max_attempts=3, conflict_count=2)
    )

    await worker._record_crash(uuid.uuid4(), _dbapi_error("40P01"))

    assert queue.retried == []
    assert queue.failed[0]["error_code"] == "crawl_task_crashed"


@pytest.mark.asyncio
async def test_a_non_conflict_crash_never_reaches_the_retry_path() -> None:
    worker, queue = _worker(SimpleNamespace(attempt_count=0, max_attempts=3))

    await worker._record_crash(uuid.uuid4(), ValueError("boom"))

    assert queue.retried == []
    assert queue.failed[0]["error_code"] == "crawl_task_crashed"
