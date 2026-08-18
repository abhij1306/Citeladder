"""ConsumableLedger service contract tests (slice23 Task 4 Part B; real Postgres).

Pins the exact reservation/attempt-accounting contract Slice 1's worker call
sites consume (commit 7 wires those): per-task reservations in resolver draw
order, one release+debit pair per billable attempt with idempotent
``(task_id, attempt)`` retry accounting (a timeout bills — outcome is not a
parameter), terminal release restoring availability, concurrency safety via
``FOR UPDATE`` grant locks, RESTRICT FKs preserving ``(task_id, attempt)``
identity, and the graceful ``funded_credits_exhausted`` refusal + telemetry.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import AUDIT_TRIGGER_MANUAL
from app.core.config.billing_contracts import (
    TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED,
)
from app.core.config.entitlements import (
    KEY_PULSE_CREDITS,
    LEDGER_ENTRY_DEBIT,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
)
from app.core.config.provider_catalog import ENGINE_CLAUDE
from app.domain.audits.creation import create_audit
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.ledger import (
    FundedCreditsExhaustedError,
    Reservation,
    UsageSnapshot,
    consumable_usage,
    record_billable_attempt,
    release_unused_reservation,
    reserve_funded_task,
)
from app.domain.entitlements.service import resolve_account_entitlement
from app.domain.entitlements.types import GrantSpec
from app.models.audit import Audit, AuditTask
from app.models.billing import AccountGrant, BillingAccount, ConsumableLedger
from tests.component.audit_helpers import seed_audit_fixtures
from tests.component.log_capture import capture_log_messages
from tests.component.occupancy_helpers import seed_occupancy_grants

_NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _seed(
    session: AsyncSession,
    *,
    credits: tuple[int, ...] = (10,),
) -> tuple[BillingAccount, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Workspace+project+prompt+route, an account with pulse-credit grant
    bundles (one bundle per value), and one BYOK audit + task to reserve
    against. Returns (account, workspace_id, audit_id, task_id)."""
    seed = await seed_audit_fixtures(session, prompt_count=1, engines=[ENGINE_CLAUDE])
    account = None
    for value in credits:
        account = await seed_occupancy_grants(
            session,
            workspace_id=seed.workspace_id,
            grants=(GrantSpec(key=KEY_PULSE_CREDITS, value=value),),
        )
    assert account is not None
    await session.commit()
    audit = await create_audit(
        session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        engines=seed.engines,
        trigger=AUDIT_TRIGGER_MANUAL,
        prompt_set_id=seed.prompt_set_id,
        repetitions=1,
        random_seed="1",
    )
    task_id = await session.scalar(
        select(AuditTask.id).where(AuditTask.audit_id == audit.id)
    )
    assert task_id is not None
    return account, seed.workspace_id, audit.id, task_id


async def _usage(session: AsyncSession, account_id: uuid.UUID) -> UsageSnapshot:
    return await consumable_usage(
        session, account_id=account_id, capability_key=KEY_PULSE_CREDITS, at=_NOW
    )


async def _entries(
    session: AsyncSession, *, reservation_id: uuid.UUID, kind: str
) -> list[ConsumableLedger]:
    return list(
        (
            await session.scalars(
                select(ConsumableLedger).where(
                    ConsumableLedger.reservation_id == reservation_id,
                    ConsumableLedger.entry_kind == kind,
                )
            )
        ).all()
    )


@pytest.mark.asyncio
async def test_reserve_allocates_units_and_usage_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        reservation = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=5,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        await session.commit()
        assert isinstance(reservation, Reservation)
        assert reservation.units == 5
        assert reservation.task_id == task_id
        assert len(reservation.allocations) == 1
        assert reservation.allocations[0].units == 5
        usage = await _usage(session, account.id)
        assert usage.granted == 10
        assert usage.reserved == 5
        assert usage.debited == 0
        assert usage.available == 5


@pytest.mark.asyncio
async def test_reserve_spans_grants_in_resolver_draw_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(3, 7))
        entitlement = await resolve_account_entitlement(
            session, account_id=account.id, at=_NOW
        )
        capability = entitlement.capability(KEY_PULSE_CREDITS)
        assert capability is not None
        expected_order = capability.ordered_draw_grant_ids
        assert len(expected_order) == 2
        reservation = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=5,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        grants_by_id = {
            row.id: row
            for row in (
                await session.scalars(
                    select(AccountGrant).where(
                        AccountGrant.billing_account_id == account.id
                    )
                )
            ).all()
        }
        # Allocations follow the resolver draw order as a PREFIX: the first
        # grant in draw order is drained before the next is touched, no grant
        # funds past its value, and the reservation is fully covered.
        alloc_ids = [a.grant_id for a in reservation.allocations]
        assert alloc_ids == list(expected_order[: len(alloc_ids)])
        assert sum(a.units for a in reservation.allocations) == 5
        for allocation in reservation.allocations:
            assert allocation.units <= grants_by_id[allocation.grant_id].value
        if len(alloc_ids) > 1:
            first = reservation.allocations[0]
            assert first.units == grants_by_id[first.grant_id].value


@pytest.mark.asyncio
async def test_reserve_idempotent_replay_returns_same_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        key = f"reserve:{uuid.uuid4().hex[:12]}"
        first = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=4,
            idempotency_key=key,
            at=_NOW,
        )
        await session.commit()
        second = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=4,
            idempotency_key=key,
            at=_NOW,
        )
        assert second.reservation_id == first.reservation_id
        count = await session.scalar(
            select(func.count())
            .select_from(ConsumableLedger)
            .where(ConsumableLedger.reservation_id == first.reservation_id)
        )
        assert count == 1  # no duplicate rows written by the replay


@pytest.mark.asyncio
async def test_billable_attempt_rows_idempotency_and_timeout_billing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        reservation = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=3,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        await session.commit()

        for attempt in (1, 2):
            await record_billable_attempt(
                session,
                reservation_id=reservation.reservation_id,
                task_id=task_id,
                attempt=attempt,
                idempotency_key=f"bill:{task_id}:{attempt}",
                at=_NOW,
            )
        await session.commit()
        releases = await _entries(
            session,
            reservation_id=reservation.reservation_id,
            kind=LEDGER_ENTRY_RELEASE,
        )
        debits = await _entries(
            session, reservation_id=reservation.reservation_id, kind=LEDGER_ENTRY_DEBIT
        )
        # One release + one debit per billable attempt, against the same grant.
        assert sorted(r.units for r in releases) == [1, 1]
        assert sorted(d.attempt for d in debits if d.attempt is not None) == [1, 2]
        for release, debit in zip(releases, debits, strict=True):
            assert release.grant_id == debit.grant_id

        # Duplicate (task_id, attempt) is idempotent — a timeout-style retry
        # of the SAME attempt bills exactly once; a NEW attempt bills again.
        await record_billable_attempt(
            session,
            reservation_id=reservation.reservation_id,
            task_id=task_id,
            attempt=2,
            idempotency_key=f"bill:{task_id}:2:retry",
            at=_NOW,
        )
        # A timed-out provider call is billable: outcome is not a parameter.
        await record_billable_attempt(
            session,
            reservation_id=reservation.reservation_id,
            task_id=task_id,
            attempt=3,
            idempotency_key=f"bill:{task_id}:3",
            at=_NOW,
        )
        await session.commit()
        debits = await _entries(
            session, reservation_id=reservation.reservation_id, kind=LEDGER_ENTRY_DEBIT
        )
        assert sorted(d.attempt for d in debits if d.attempt is not None) == [1, 2, 3]
        usage = await _usage(session, account.id)
        assert usage.debited == 3
        assert usage.reserved == 0
        assert usage.available == 7


@pytest.mark.asyncio
async def test_terminal_release_restores_unused_availability(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        reservation = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=5,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        await record_billable_attempt(
            session,
            reservation_id=reservation.reservation_id,
            task_id=task_id,
            attempt=1,
            idempotency_key=f"bill:{task_id}:1",
            at=_NOW,
        )
        await session.commit()
        await release_unused_reservation(
            session,
            reservation_id=reservation.reservation_id,
            idempotency_key=f"release:{reservation.reservation_id}",
            at=_NOW,
        )
        await session.commit()
        usage = await _usage(session, account.id)
        # 5 reserved - 1 billed - 4 released: availability restored but the
        # billed unit stays consumed.
        assert usage.reserved == 0
        assert usage.debited == 1
        assert usage.available == 9
        # Terminal release is idempotent.
        await release_unused_reservation(
            session,
            reservation_id=reservation.reservation_id,
            idempotency_key=f"release:{reservation.reservation_id}",
            at=_NOW,
        )
        await session.commit()
        usage = await _usage(session, account.id)
        assert usage.available == 9


@pytest.mark.asyncio
async def test_concurrent_reserves_never_overallocate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(5,))
        account_id = account.id

    async def _reserve(marker: str) -> str:
        async with session_factory() as session:
            try:
                await reserve_funded_task(
                    session,
                    account_id=account_id,
                    capability_key=KEY_PULSE_CREDITS,
                    audit_id=audit_id,
                    task_id=task_id,
                    units=4,
                    idempotency_key=f"reserve:{marker}",
                    at=_NOW,
                )
                await session.commit()
                return "ok"
            except FundedCreditsExhaustedError:
                await session.rollback()
                return "denied"

    # FOR UPDATE grant locks serialize the two reservations; the loser
    # recomputes balances AFTER the winner commits and is denied.
    results = await asyncio.gather(_reserve("a"), _reserve("b"))
    assert sorted(results) == ["denied", "ok"]
    async with session_factory() as session:
        usage = await _usage(session, account_id)
        assert usage.reserved == 4
        assert usage.available == 1
        assert usage.available >= 0


@pytest.mark.asyncio
async def test_ledger_fks_restrict_audit_and_task_deletion(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=2,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        await session.commit()

        task = await session.get(AuditTask, task_id)
        assert task is not None
        await session.delete(task)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

        audit = await session.get(Audit, audit_id)
        assert audit is not None
        await session.delete(audit)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

        # (task_id, attempt) accounting identity survives the failed deletes.
        still_there = await session.scalar(
            select(func.count())
            .select_from(ConsumableLedger)
            .where(ConsumableLedger.task_id == task_id)
        )
        assert int(still_there or 0) == 1


@pytest.mark.asyncio
async def test_insufficient_balance_is_graceful_and_emits_telemetry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(2,))
        with capture_log_messages("app.billing") as events:
            with pytest.raises(FundedCreditsExhaustedError) as exc_info:
                await reserve_funded_task(
                    session,
                    account_id=account.id,
                    capability_key=KEY_PULSE_CREDITS,
                    audit_id=audit_id,
                    task_id=task_id,
                    units=5,
                    idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
                    at=_NOW,
                )
        await session.rollback()
        assert exc_info.value.code == "funded_credits_exhausted"
        assert any(
            TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED in message for message in events
        )
        rows = await session.scalar(select(func.count()).select_from(ConsumableLedger))
        assert int(rows or 0) == 0


@pytest.mark.asyncio
async def test_reservation_vocabulary_entries_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Every written row uses the config-owned entry-kind vocabulary."""
    async with session_factory() as session:
        account, _ws, audit_id, task_id = await _seed(session, credits=(10,))
        reservation = await reserve_funded_task(
            session,
            account_id=account.id,
            capability_key=KEY_PULSE_CREDITS,
            audit_id=audit_id,
            task_id=task_id,
            units=2,
            idempotency_key=f"reserve:{uuid.uuid4().hex[:12]}",
            at=_NOW,
        )
        await record_billable_attempt(
            session,
            reservation_id=reservation.reservation_id,
            task_id=task_id,
            attempt=1,
            idempotency_key=f"bill:{task_id}:1",
            at=_NOW,
        )
        await release_unused_reservation(
            session,
            reservation_id=reservation.reservation_id,
            idempotency_key=f"release:{reservation.reservation_id}",
            at=_NOW,
        )
        await session.commit()
        kinds = (
            await session.scalars(select(ConsumableLedger.entry_kind).distinct())
        ).all()
        assert set(kinds) == {
            LEDGER_ENTRY_RESERVATION,
            LEDGER_ENTRY_DEBIT,
            LEDGER_ENTRY_RELEASE,
        }
