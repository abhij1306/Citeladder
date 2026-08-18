# Generic Postgres task queue (invariant 8): FOR UPDATE SKIP LOCKED claim +
# leasing, parameterized over the queue-row model via ``PostgresQueueSpec``.
#
# The ``TaskQueue[T]`` implementation. Postgres is both durable state and
# the queue (no Redis yet). The claim runs in one short transaction that
# locks eligible rows with ``FOR UPDATE SKIP LOCKED`` and commits BEFORE the
# worker does any I/O, so a DB transaction is never held across a network call.
# ``SKIP LOCKED`` plus each model's unique idempotency key and slot constraint
# guarantee no double-claim. ``release_expired`` is the sweeper that reclaims
# leases from a crashed worker.
#
# One implementation serves every task type (``AuditTask`` / ``SiteCrawlTask``
# / future ones): the concrete model + lease TTL + deterministic claim order +
# max-attempts error token come from the injected ``PostgresQueueSpec``, so the
# claim/lease/heartbeat/expiry/retry semantics are identical for all of them.
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.task_queue import (
    TASK_CLAIMABLE_STATUSES,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_CAPACITY_WAIT,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    PostgresQueueSpec,
)
from app.models.abuse import QueueWorkspaceTurn

if TYPE_CHECKING:
    # Type-only: the queue is generic over the concrete queue-row models (the
    # ``PostgresQueueSpec`` constraint); nothing here imports them at runtime.
    from app.models.analytics import AnalyticsTask
    from app.models.audit import AuditTask
    from app.models.content import ContentGeneration
    from app.models.integrations import IntegrationSyncRun
    from app.models.site_health.queue import SiteCrawlTask

logger = logging.getLogger("app.orchestration.postgres_task_queue")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ExpiredLeaseSweep:
    """What one ``release_expired`` pass reclaimed.

    ``failed_parent_ids`` carries the de-duplicated owning-run ids of rows the
    sweeper terminalized at max attempts — the reclaims no worker's finalize
    will ever observe. Empty for queues whose spec sets no ``parent_id_attr``.
    """

    reclaimed: int
    failed_task_ids: tuple[uuid.UUID, ...] = ()
    failed_parent_ids: tuple[uuid.UUID, ...] = ()


class PostgresTaskQueue[
    T: (
        "AuditTask",
        "SiteCrawlTask",
        "ContentGeneration",
        "IntegrationSyncRun",
        "AnalyticsTask",
    )
]:
    """``TaskQueue[T]`` backed by Postgres ``FOR UPDATE SKIP LOCKED``.

    Constructed with a session factory (``async_sessionmaker``) and a
    ``PostgresQueueSpec[T]`` supplying the concrete model, lease TTL, claim
    order, and max-attempts token. Each queue operation runs in its own
    short-lived transaction — never one held open across a network call.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        spec: PostgresQueueSpec[T],
    ) -> None:
        self._session_factory = session_factory
        self._spec: PostgresQueueSpec[T] = spec

    @property
    def _model(self) -> type[T]:
        return self._spec.model

    def _lease_expiry(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self._spec.lease_ttl())

    def _claim_statement(
        self,
        *,
        model: type[T],
        now: datetime,
        limit: int,
        kinds: Sequence[str] | None,
        queue_name: str,
    ) -> Select[tuple[T]]:
        """The locking SELECT one claim runs.

        Lock eligible rows and skip any another worker already holds. The
        ORDER BY (spec-supplied) makes claim order deterministic. No queue-wide
        advisory lock is needed: task-row locks make claims disjoint, while the
        caller's cursor upsert is conflict-safe and monotonic across concurrent
        claim transactions.

        ``eligible_filter`` is applied TWICE on purpose — once inside the ranked
        subquery (to number each workspace's backlog) and once on the locked
        relation itself. Under READ COMMITTED, a statement that meets a row
        another transaction updated and COMMITTED re-evaluates only the quals
        attached to the locked relation against the new row version. With the
        predicate living solely in the subquery there is nothing left to
        re-check, so two workers whose claim statements overlap return the SAME
        rows: ``SKIP LOCKED`` covers the window while the first claim holds its
        lock, not the window after it commits. Dropping the outer copy silently
        reintroduces double-claiming under load — see
        ``test_claim_rechecks_eligibility_on_the_locked_relation``.

        Split out of ``claim`` so that shape is assertable without a race.
        """
        base_order = tuple(self._spec.claim_order(model))
        eligible_filter = (
            # queued / retry_wait / capacity_wait (config-owned claimable
            # vocabulary): a capacity-parked task becomes claimable again
            # exactly like a retry — once its ``available_at`` passes.
            model.status.in_(sorted(TASK_CLAIMABLE_STATUSES)),
            model.available_at <= now,
        )
        eligible = select(
            model.id.label("task_id"),
            func.row_number()
            .over(
                partition_by=model.workspace_id,
                order_by=base_order,
            )
            .label("workspace_position"),
        ).where(*eligible_filter)
        if kinds is not None:
            # Only queue-row models with a ``task_kind`` column (SiteCrawlTask)
            # accept a kind filter; audit rows have no such column, and the
            # audit worker never passes ``kinds``. ``task_kind`` is immutable
            # after insert, so unlike status/available_at it needs no re-check
            # copy on the locked relation.
            task_kind = getattr(model, "task_kind", None)
            if task_kind is not None:
                eligible = eligible.where(task_kind.in_(list(kinds)))

        ranked = eligible.subquery("fair_queue_candidates")
        return (
            select(model)
            .where(*eligible_filter)
            .join(ranked, ranked.c.task_id == model.id)
            .outerjoin(
                QueueWorkspaceTurn,
                (QueueWorkspaceTurn.queue_name == queue_name)
                & (QueueWorkspaceTurn.workspace_id == model.workspace_id),
            )
            # One task per workspace before any workspace receives its second,
            # then third, and so on. This keeps large tenant backlogs from
            # filling a worker's whole claim batch.
            .order_by(
                ranked.c.workspace_position.asc(),
                QueueWorkspaceTurn.last_claimed_at.asc().nulls_first(),
                *base_order,
            )
            .limit(limit)
            .with_for_update(of=model, skip_locked=True)
        )

    async def claim(
        self,
        *,
        owner: str,
        limit: int = 1,
        kinds: Sequence[str] | None = None,
    ) -> list[T]:
        """Claim up to ``limit`` eligible rows for ``owner``.

        ``kinds`` optionally restricts the claim to specific ``task_kind``
        values (e.g. a discover-only worker leaves reserved ``analyze`` rows
        untouched in the queue rather than force-failing them). ``None`` (the
        default) claims every kind, so callers without a ``task_kind`` column
        (e.g. the audit queue) are unaffected.
        """
        model = self._model
        now = _utcnow()
        lease_expires = self._lease_expiry(now)
        async with self._session_factory() as session:
            queue_name = model.__tablename__
            stmt = self._claim_statement(
                model=model,
                now=now,
                limit=limit,
                kinds=kinds,
                queue_name=queue_name,
            )
            tasks = list((await session.scalars(stmt)).all())
            for task in tasks:
                task.status = TASK_STATUS_LEASED
                task.lease_owner = owner
                task.lease_expires_at = lease_expires
                task.heartbeat_at = now
            claimed_workspaces = {task.workspace_id for task in tasks}
            if claimed_workspaces:
                turn_rows = [
                    {
                        "id": uuid.uuid4(),
                        "queue_name": queue_name,
                        "workspace_id": workspace_id,
                        "last_claimed_at": now,
                    }
                    for workspace_id in sorted(claimed_workspaces, key=str)
                ]
                await session.execute(
                    insert(QueueWorkspaceTurn)
                    .values(turn_rows)
                    .on_conflict_do_update(
                        constraint="uq_queue_workspace_turn",
                        set_={
                            "last_claimed_at": func.greatest(
                                QueueWorkspaceTurn.last_claimed_at, now
                            )
                        },
                    )
                )
            # COMMIT the claim before returning — the caller does network I/O
            # only after this returns (invariant 8).
            await session.commit()
            # Detach loaded snapshots so the caller can read fields after the
            # session closes.
            for task in tasks:
                session.expunge(task)
            return tasks

    async def _owned_task(
        self, session: AsyncSession, task_id: uuid.UUID, owner: str | None
    ) -> T | None:
        task = await session.get(self._model, task_id, with_for_update=True)
        if task is None:
            return None
        if owner is not None and task.lease_owner != owner:
            # Lease was reclaimed by the sweeper or stolen; do not act.
            return None
        return task

    async def heartbeat(self, *, task_id: uuid.UUID, owner: str) -> bool:
        now = _utcnow()
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None or task.status not in (
                TASK_STATUS_LEASED,
                TASK_STATUS_RUNNING,
            ):
                await session.commit()
                return False
            task.heartbeat_at = now
            task.lease_expires_at = self._lease_expiry(now)
            await session.commit()
            return True

    async def mark_running(self, *, task_id: uuid.UUID, owner: str) -> bool:
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None or task.status != TASK_STATUS_LEASED:
                await session.commit()
                return False
            task.status = TASK_STATUS_RUNNING
            task.heartbeat_at = _utcnow()
            await session.commit()
            return True

    async def succeed(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        result_artifact_id: uuid.UUID | None = None,
    ) -> bool:
        return await self._finalize(
            task_id=task_id,
            owner=owner,
            status=TASK_STATUS_SUCCEEDED,
            mutate=lambda task: setattr(task, "result_artifact_id", result_artifact_id),
        )

    async def fail(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        error_code: str = "",
        error_detail: str = "",
    ) -> bool:
        def _set(task: T) -> None:
            task.error_code = error_code
            task.error_detail = error_detail[:2000]

        return await self._finalize(
            task_id=task_id, owner=owner, status=TASK_STATUS_FAILED, mutate=_set
        )

    async def _finalize(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        status: str,
        mutate: Callable[[T], None] | None = None,
    ) -> bool:
        now = _utcnow()
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None:
                await session.commit()
                return False
            task.status = status
            task.lease_owner = None
            task.lease_expires_at = None
            task.completed_at = now
            if mutate is not None:
                mutate(task)
            await session.commit()
            return True

    async def retry(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        delay_seconds: float,
        error_code: str = "",
        error_detail: str = "",
    ) -> bool:
        now = _utcnow()
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None:
                await session.commit()
                return False
            task.status = TASK_STATUS_RETRY_WAIT
            task.lease_owner = None
            task.lease_expires_at = None
            task.available_at = now + timedelta(seconds=max(0.0, delay_seconds))
            task.error_code = error_code
            task.error_detail = error_detail[:2000]
            await session.commit()
            return True

    async def defer(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        delay_seconds: float = 0.0,
    ) -> bool:
        """Release a task whose durable prerequisite is still in flight."""
        now = _utcnow()
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None:
                await session.commit()
                return False
            task.status = TASK_STATUS_QUEUED
            task.lease_owner = None
            task.lease_expires_at = None
            task.available_at = now + timedelta(seconds=max(0.0, delay_seconds))
            task.error_code = ""
            task.error_detail = ""
            await session.commit()
            return True

    async def park_capacity_wait(
        self,
        *,
        task_id: uuid.UUID,
        owner: str,
        available_at: datetime,
    ) -> bool:
        """Park an owned task in ``capacity_wait`` until ``available_at``.

        Releases the lease without touching ``attempt_count`` — no provider
        call happened, so no attempt budget is spent. The row re-enters the
        claimable set once ``available_at`` passes, exactly like a retry.
        """
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner)
            if task is None:
                await session.commit()
                return False
            task.status = TASK_STATUS_CAPACITY_WAIT
            task.lease_owner = None
            task.lease_expires_at = None
            task.available_at = available_at
            await session.commit()
            return True

    async def cancel(self, *, task_id: uuid.UUID) -> bool:
        now = _utcnow()
        async with self._session_factory() as session:
            task = await self._owned_task(session, task_id, owner=None)
            if task is None or task.status in (
                TASK_STATUS_SUCCEEDED,
                TASK_STATUS_FAILED,
                TASK_STATUS_CANCELLED,
            ):
                await session.commit()
                return False
            task.status = TASK_STATUS_CANCELLED
            task.lease_owner = None
            task.lease_expires_at = None
            task.completed_at = now
            if not task.error_code:
                task.error_code = "cancelled"
            await session.commit()
            return True

    async def release_expired(self, *, batch_size: int = 500) -> int:
        """Reclaim leases whose ``lease_expires_at`` has passed.

        Expired leased/running tasks with attempts remaining return to
        ``retry_wait`` (available immediately); those that have exhausted
        ``max_attempts`` are marked ``failed``. Uses ``SKIP LOCKED`` so it never
        contends with a live worker still holding its row.

        Bounded to ``batch_size`` rows per transaction, in a deterministic
        order (oldest-expired-first, then id), so a mass expiry across a
        large frontier never holds one long-running transaction or stalls
        live claims; a caller polling this repeatedly drains the remainder
        across subsequent calls.

        Returns the number of rows reclaimed. Callers that must react to a
        TERMINAL reclaim (the sweeper failing a task at max attempts drains
        the owning run's queue without any worker running its finalize) should
        use ``release_expired_detailed`` instead, which reports those rows.
        """
        outcome = await self.release_expired_detailed(batch_size=batch_size)
        return outcome.reclaimed

    async def release_expired_detailed(
        self, *, batch_size: int = 500
    ) -> ExpiredLeaseSweep:
        """``release_expired`` that also reports which rows went TERMINAL.

        The terminal set matters because nothing else observes it: a task the
        sweeper fails at max attempts never runs a worker's ``finally``, so a
        run whose LAST outstanding task is terminalized here would otherwise
        sit non-terminal forever. Callers reconcile the reported parents.
        """
        model = self._model
        now = _utcnow()
        reclaimed = 0
        failed_task_ids: list[uuid.UUID] = []
        failed_parent_ids: list[uuid.UUID] = []
        parent_attr = self._spec.parent_id_attr
        async with self._session_factory() as session:
            stmt = (
                select(model)
                .where(model.status.in_([TASK_STATUS_LEASED, TASK_STATUS_RUNNING]))
                .where(model.lease_expires_at.is_not(None))
                .where(model.lease_expires_at < now)
                .order_by(model.lease_expires_at.asc(), model.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
            tasks = list((await session.scalars(stmt)).all())
            for task in tasks:
                task.lease_owner = None
                task.lease_expires_at = None
                if task.attempt_count >= task.max_attempts:
                    task.status = TASK_STATUS_FAILED
                    task.completed_at = now
                    if not task.error_code:
                        task.error_code = self._spec.max_attempts_error
                        task.error_detail = "lease expired after max attempts exhausted"
                    failed_task_ids.append(task.id)
                    if parent_attr is not None:
                        parent_id = getattr(task, parent_attr, None)
                        if parent_id is not None:
                            failed_parent_ids.append(parent_id)
                    # Attributable per-row record: this is the only trace that a
                    # task died without a worker finalize, so an aggregate count
                    # alone leaves a stalled run un-diagnosable.
                    logger.warning(
                        "sweeper failed task at max attempts",
                        extra={
                            "task_id": str(task.id),
                            "queue": model.__tablename__,
                            "attempt_count": task.attempt_count,
                            "parent_id": str(getattr(task, parent_attr, ""))
                            if parent_attr
                            else None,
                        },
                    )
                else:
                    task.status = TASK_STATUS_RETRY_WAIT
                    task.available_at = now
                reclaimed += 1
            await session.commit()
            if reclaimed:
                logger.info(
                    "sweeper reclaimed expired leases",
                    extra={"reclaimed": reclaimed, "failed": len(failed_task_ids)},
                )
            # De-duplicate parents (one run commonly loses several leases in the
            # same sweep) while keeping first-seen order deterministic.
            return ExpiredLeaseSweep(
                reclaimed=reclaimed,
                failed_task_ids=tuple(failed_task_ids),
                failed_parent_ids=tuple(dict.fromkeys(failed_parent_ids)),
            )
