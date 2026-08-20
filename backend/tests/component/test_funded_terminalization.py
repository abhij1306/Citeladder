"""Funded-ledger conservation on every terminalization path (real Postgres).

Regression pins for the conservation invariant "every reservation is
eventually debited or released" on the four paths that used to break it:

  - ``cancel_audit`` terminalized unclaimed funded tasks with NO ledger
    release, permanently shrinking the account's usable balance;
  - the queue sweeper terminalized a crash-looped task at max attempts with
    no funded release (the queue stays billing-agnostic — the audit worker,
    its caller, owns the janitor release);
  - ``_record_crash`` terminalized without the funded-ledger release the
    cancel/deadline/fail-terminal paths all run;
  - ``assert pricing is not None`` crashed a successful task AFTER the
    provider call, rolling back artifact + attempts + funded bill/release.

Each pin asserts the settle-once contract: the provider call that DID happen
is billed exactly once, and exactly the still-reserved units are released
exactly once, however many terminalization paths race the same task.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_CANCELLED,
    AUDIT_TRIGGER_MANUAL,
    MEASUREMENT_MODE_PULSE,
    audit_settings,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_FUNDED,
    KEY_PULSE_CREDITS,
    LEDGER_ENTRY_DEBIT,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
)
from app.core.config.provider_catalog import ENGINE_CLAUDE
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import AuditValidationError
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.ledger import (
    consumable_usage,
    release_terminal_funded_task,
)
from app.domain.entitlements.types import GrantSpec
from app.models.audit import (
    AuditTask,
    ExecutionCostProjection,
    RawResponseArtifact,
)
from app.models.billing import BillingAccount, ConsumableLedger
from app.workers.audit import execution as audit_execution
from app.workers.audit_worker import AuditWorker
from tests.component.audit_helpers import (
    Seed,
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.log_capture import capture_log_messages
from tests.component.occupancy_helpers import seed_occupancy_grants
from tests.component.test_audit_worker import _StubAdapter


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _seed_funded(
    session: AsyncSession, *, prompt_count: int = 2, credits: int = 100
) -> tuple[BillingAccount, Seed]:
    """Funded-capable workspace: unprobed tenant BYOK (no precedence), the
    platform credential funded resolution binds, and a pulse-credit account."""
    seed = await seed_audit_fixtures(
        session, prompt_count=prompt_count, engines=[ENGINE_CLAUDE], probed=False
    )
    await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
    account = await seed_occupancy_grants(
        session,
        workspace_id=seed.workspace_id,
        grants=(GrantSpec(key=KEY_PULSE_CREDITS, value=credits),),
    )
    await session.commit()
    return account, seed


async def _create_funded(session: AsyncSession, seed: Seed):
    return await create_audit(
        session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        engines=[ENGINE_CLAUDE],
        trigger=AUDIT_TRIGGER_MANUAL,
        credential_mode=CREDENTIAL_MODE_FUNDED,
        prompt_set_id=seed.prompt_set_id,
        repetitions=1,
        measurement_mode=MEASUREMENT_MODE_PULSE,
        random_seed="1",
    )


async def _ledger_rows(
    session: AsyncSession, *, task_id: uuid.UUID, kind: str
) -> list[ConsumableLedger]:
    return list(
        (
            await session.scalars(
                select(ConsumableLedger).where(
                    ConsumableLedger.task_id == task_id,
                    ConsumableLedger.entry_kind == kind,
                )
            )
        ).all()
    )


async def _usage(session: AsyncSession, account_id: uuid.UUID):
    return await consumable_usage(
        session,
        account_id=account_id,
        capability_key=KEY_PULSE_CREDITS,
        at=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_cancel_releases_every_unclaimed_funded_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancel-before-claim releases ALL unclaimed funded reservations.

    Cancelled tasks are never claimed, so neither worker release path runs
    for them; the cancel itself must release each task's full reservation in
    the same transaction, keyed by the ``cancel`` trigger.
    """
    async with session_factory() as session:
        account, seed = await _seed_funded(session, prompt_count=2)
        audit = await _create_funded(session, seed)
        tasks = list(
            (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        assert len(tasks) == 2
        usage = await _usage(session, account.id)
        # The reservation is keyed to the budget the PLANNER FROZE onto each
        # task, which is the measurement mode's (pulse retries fewer times
        # than benchmark) — never the generic live ``max_attempts``.
        assert usage.reserved == sum(t.max_attempts for t in tasks)

        cancelled = await cancel_audit(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert cancelled.status == AUDIT_STATUS_CANCELLED

        tasks = list(
            (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        assert {t.status for t in tasks} == {TASK_STATUS_CANCELLED}
        for task in tasks:
            reserved = await _ledger_rows(
                session, task_id=task.id, kind=LEDGER_ENTRY_RESERVATION
            )
            released = await _ledger_rows(
                session, task_id=task.id, kind=LEDGER_ENTRY_RELEASE
            )
            debited = await _ledger_rows(
                session, task_id=task.id, kind=LEDGER_ENTRY_DEBIT
            )
            # The full reservation is released exactly once, by the cancel
            # trigger; nothing was ever called, so nothing is debited.
            assert sum(r.units for r in reserved) == task.max_attempts
            assert sum(r.units for r in released) == task.max_attempts
            assert all(
                f"{audit.id}:{task.id}:funded-release-cancel" in r.idempotency_key
                for r in released
            )
            assert debited == []
        usage = await _usage(session, account.id)
        assert usage.reserved == 0
        assert usage.debited == 0
        assert usage.available == usage.granted

    # A repeat cancel is rejected and releases nothing more.
    async with session_factory() as session:
        released_before = len((await session.scalars(select(ConsumableLedger))).all())
        with pytest.raises(AuditValidationError, match="Only active audits"):
            await cancel_audit(
                session, workspace_id=seed.workspace_id, audit_id=audit.id
            )
        await session.rollback()
        assert (
            len((await session.scalars(select(ConsumableLedger))).all())
            == released_before
        )


@pytest.mark.asyncio
async def test_cancel_racing_in_flight_worker_release_settles_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancel vs in-flight worker release settles exactly ONE release.

    Simulates the tight window: the worker's terminal release COMMITTED (the
    success evidence path) but the queue's terminal status has not landed
    yet, so the task is still non-terminal and cancel terminalizes it — and
    attempts its own release on the same reservation. The ledger's
    outstanding computation suppresses the second release: the task's
    still-reserved units are released exactly once, by the worker.
    """
    async with session_factory() as session:
        account, seed = await _seed_funded(session, prompt_count=2)
        audit = await _create_funded(session, seed)

    worker = AuditWorker(session_factory=session_factory, owner="w-race")
    claimed = await worker._queue.claim(owner=worker.owner, limit=1)
    assert len(claimed) == 1
    raced_task_id = claimed[0].id

    # The worker bills its one actual call and terminally releases — this is
    # the persist-success commit; queue.succeed has NOT landed yet.
    async with session_factory() as session:
        task = await session.get(AuditTask, raced_task_id)
        assert task is not None
        task.attempt_count = 1
        await worker._apply_funded_ledger(
            session, task=task, billable=True, terminal=True
        )
        await session.commit()

    async with session_factory() as session:
        await cancel_audit(session, workspace_id=seed.workspace_id, audit_id=audit.id)

        released = await _ledger_rows(
            session, task_id=raced_task_id, kind=LEDGER_ENTRY_RELEASE
        )
        debited = await _ledger_rows(
            session, task_id=raced_task_id, kind=LEDGER_ENTRY_DEBIT
        )
        # max_attempts reserved, 1 billed: the release rows total the full
        # reservation exactly once — the bill's own unit release plus the
        # worker's terminal release of the remaining max_attempts-1 — and
        # cancel's release wrote NOTHING (no cancel-triggered row exists).
        raced_task = await session.get(AuditTask, raced_task_id)
        assert raced_task is not None
        frozen_attempts = raced_task.max_attempts
        assert sum(r.units for r in released) == frozen_attempts
        worker_releases = [
            r for r in released if ":funded-release-unused" in r.idempotency_key
        ]
        assert sum(r.units for r in worker_releases) == frozen_attempts - 1
        assert not any(":funded-release-cancel" in r.idempotency_key for r in released)
        assert [d.attempt for d in debited] == [1]
        task = await session.get(AuditTask, raced_task_id)
        assert task is not None
        assert task.status == TASK_STATUS_CANCELLED

        # The sibling task (never claimed) was fully released by the cancel.
        other = await session.scalar(
            select(AuditTask).where(
                AuditTask.audit_id == audit.id,
                AuditTask.id != raced_task_id,
            )
        )
        assert other is not None
        other_released = await _ledger_rows(
            session, task_id=other.id, kind=LEDGER_ENTRY_RELEASE
        )
        assert sum(r.units for r in other_released) == other.max_attempts
        assert all(
            f"{audit.id}:{other.id}:funded-release-cancel" in r.idempotency_key
            for r in other_released
        )

        usage = await _usage(session, account.id)
        assert usage.debited == 1
        assert usage.reserved == 0
        assert usage.available == usage.granted - 1


@pytest.mark.asyncio
async def test_concurrent_same_trigger_release_hits_the_designed_guard(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The deterministic-key race guard: two concurrent releases with the
    SAME trigger key settle exactly one release — the loser hits the
    per-account unique idempotency key (IntegrityError), never a double row.
    """
    async with session_factory() as session:
        account, seed = await _seed_funded(session, prompt_count=1)
        audit = await _create_funded(session, seed)
        task_id = await session.scalar(
            select(AuditTask.id).where(AuditTask.audit_id == audit.id)
        )
        assert task_id is not None
        configuration = audit.configuration or {}
        reservation_id = uuid.UUID(configuration["task_reservations"][str(task_id)])
        account_id = account.id
        audit_id = audit.id

    flushed = asyncio.Event()
    outcomes: list[str] = []

    async def _winner() -> None:
        # Flush the release rows but hold the commit until the loser is
        # blocked on the same deterministic key — the true race window.
        async with session_factory() as session:
            await release_terminal_funded_task(
                session,
                reservation_id=reservation_id,
                audit_id=audit_id,
                task_id=task_id,
                trigger="cancel",
                at=datetime.now(UTC),
            )
            flushed.set()
            await asyncio.sleep(0.2)
            await session.commit()
            outcomes.append("ok")

    async def _loser() -> None:
        await flushed.wait()
        async with session_factory() as session:
            try:
                await release_terminal_funded_task(
                    session,
                    reservation_id=reservation_id,
                    audit_id=audit_id,
                    task_id=task_id,
                    trigger="cancel",
                    at=datetime.now(UTC),
                )
                await session.commit()
                outcomes.append("unexpected-second-release")
            except IntegrityError:
                await session.rollback()
                outcomes.append("guarded")

    await asyncio.gather(_winner(), _loser())
    # Exactly one winner commits; the loser hits the designed guard.
    assert sorted(outcomes) == ["guarded", "ok"]

    async with session_factory() as session:
        released = await _ledger_rows(
            session, task_id=task_id, kind=LEDGER_ENTRY_RELEASE
        )
        # One settled release covering the full reservation — never two rows.
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert sum(r.units for r in released) == task.max_attempts
        assert len(released) == 1
        usage = await _usage(session, account_id)
        assert usage.reserved == 0
        assert usage.available == usage.granted


@pytest.mark.asyncio
async def test_sweeper_terminalized_funded_task_releases_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A crash-looped funded task the sweeper fails at max attempts gets its
    unused reservation released by the worker-side janitor (the queue sweep
    itself stays billing-agnostic and only reports the terminalized ids)."""
    async with session_factory() as session:
        account, seed = await _seed_funded(session, prompt_count=1)
        audit = await _create_funded(session, seed)

    worker = AuditWorker(session_factory=session_factory, owner="w-swept")
    claimed = await worker._queue.claim(owner=worker.owner, limit=1)
    assert len(claimed) == 1
    task_id = claimed[0].id

    # The owner crash-looped: budget spent, lease expired without a finalize.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.attempt_count = task.max_attempts
        task.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    await worker._sweep_expired_leases()

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        released = await _ledger_rows(
            session, task_id=task_id, kind=LEDGER_ENTRY_RELEASE
        )
        assert sum(r.units for r in released) == task.max_attempts
        assert all(
            f"{audit.id}:{task_id}:funded-release-sweep" in r.idempotency_key
            for r in released
        )
        usage = await _usage(session, account.id)
        assert usage.reserved == 0
        assert usage.debited == 0
        assert usage.available == usage.granted

    # A repeat sweep observes nothing terminal and releases nothing more.
    await worker._sweep_queue()
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        released = await _ledger_rows(
            session, task_id=task_id, kind=LEDGER_ENTRY_RELEASE
        )
        assert sum(r.units for r in released) == task.max_attempts


@pytest.mark.asyncio
async def test_crash_after_billed_attempt_bills_once_and_releases_remainder(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """A crash terminalization bills the actual call once and releases the
    unbilled remainder: the failure path committed the attempt-1 bill
    (will_retry=True) and ``queue.retry`` then raised, so ``_record_crash``
    terminalizes — releasing only the still-reserved unit."""
    # Pin BOTH: the frozen budget comes from the mode policy, and these
    # audits are planned in the default (pulse) mode.
    monkeypatch.setattr(audit_settings, "max_attempts", 2)
    monkeypatch.setattr(audit_settings, "pulse_max_attempts", 2)
    async with session_factory() as session:
        account, seed = await _seed_funded(session, prompt_count=1)
        await _create_funded(session, seed)

    worker = AuditWorker(session_factory=session_factory, owner="w-crash")
    claimed = await worker._queue.claim(owner=worker.owner, limit=1)
    assert len(claimed) == 1
    task_id = claimed[0].id

    # The failure path's committed bill for the one actual call (attempt 1);
    # the queue.retry raise is what sends the task into _record_crash.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        task.attempt_count = 1
        await worker._apply_funded_ledger(
            session, task=task, billable=True, terminal=False
        )
        await session.commit()

    await worker._record_crash(task_id, RuntimeError("retry raise boom"))

    async with session_factory() as session:
        task = await session.get(AuditTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        debited = await _ledger_rows(session, task_id=task_id, kind=LEDGER_ENTRY_DEBIT)
        released = await _ledger_rows(
            session, task_id=task_id, kind=LEDGER_ENTRY_RELEASE
        )
        # The one actual call is billed exactly once; the release covers the
        # billed unit (from the bill itself) plus the unbilled remainder
        # (from the crash trigger) — the full 2-unit reservation, once.
        assert [d.attempt for d in debited] == [1]
        assert sum(r.units for r in released) == 2
        crash_releases = [
            r for r in released if ":funded-release-crash" in r.idempotency_key
        ]
        assert sum(r.units for r in crash_releases) == 1
        usage = await _usage(session, account.id)
        assert usage.debited == 1
        assert usage.reserved == 0
        assert usage.available == usage.granted - 1

    # Replay: the task is already terminal and lease-free, so the fail is
    # owner-guarded and no further release is attempted.
    await worker._record_crash(task_id, RuntimeError("replay boom"))
    async with session_factory() as session:
        debited = await _ledger_rows(session, task_id=task_id, kind=LEDGER_ENTRY_DEBIT)
        released = await _ledger_rows(
            session, task_id=task_id, kind=LEDGER_ENTRY_RELEASE
        )
        assert len(debited) == 1
        assert sum(r.units for r in released) == 2


@pytest.mark.asyncio
async def test_unknown_pricing_skips_projection_and_task_still_succeeds(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """A live pricing-catalog miss never crashes the success path: the
    analytics-only projection is skipped with a safe warning while the
    artifact, attempts, and task success all persist."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
    monkeypatch.setattr(audit_execution, "build_adapter", lambda **_: _StubAdapter())
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)
    # An unknown catalog version makes the live pricing lookup return None.
    monkeypatch.setattr(audit_execution, "PRICING_CATALOG_VERSION", "v0-unknown-test")

    worker = AuditWorker(session_factory=session_factory, owner="w-pricing")
    with capture_log_messages("app.workers.audit_worker") as messages:
        await worker.run_until_idle()

    assert any("no pricing for route" in message for message in messages)
    async with session_factory() as session:
        task = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED
        assert task.result_artifact_id is not None
        artifacts = await session.scalar(
            select(RawResponseArtifact.id).where(RawResponseArtifact.task_id == task.id)
        )
        assert artifacts is not None
        projections = await session.scalar(
            select(ExecutionCostProjection.id).where(
                ExecutionCostProjection.task_id == task.id
            )
        )
        assert projections is None
