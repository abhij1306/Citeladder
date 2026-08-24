"""Funded audit admission (slice23 Task 4 Part B; real Postgres).

Pins the planner contract: every funded task reserves its own
``max_attempts`` in the planner transaction BEFORE claimability (frozen task
configuration carries the reservation id; the audit configuration carries
the task-reservation map), the UTC-month worst-case budget gate converts the
minor-USD ceiling through ``MICRO_USD_PER_USD`` and holds under concurrent
admissions, incomplete expected costs fail closed (retrieval-off leaves the
search fields not applicable), BYOK writes no funded rows, and credit/budget
exhaustion rolls back EVERYTHING (no audit/task/ledger rows, nothing
enqueued) with the allowlisted telemetry events.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_TRIGGER_MANUAL,
    audit_settings,
)
from app.core.config.billing_contracts import (
    TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED,
    TELEMETRY_ENTITLEMENT_UNRESOLVED,
    TELEMETRY_FUNDED_BUDGET_EXHAUSTED,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.config.costs import (
    _EXPECTED_COST_CATALOG,
    MICRO_USD_PER_USD,
    ROUTE_CLAUDE,
    _ExpectedCostEstimate,
)
from app.core.config.entitlements import (
    CODE_FUNDED_BUDGET_EXHAUSTED,
    CODE_FUNDED_COST_UNRESOLVED,
    CODE_FUNDED_CREDITS_EXHAUSTED,
    CREDENTIAL_MODE_BYOK,
    CREDENTIAL_MODE_FUNDED,
    KEY_AUDIT_CREDITS,
)
from app.core.config.provider_catalog import (
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    TELEMETRY_FUNDED_ADMISSION_DENIED,
)
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import FundedAdmissionError
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.types import STATUS_ENTITLEMENT_UNRESOLVED, GrantSpec
from app.models.audit import Audit, AuditTask
from app.models.billing import BillingAccount, ConsumableLedger
from app.models.provider import ProviderConnection
from tests.component.audit_helpers import (
    _mark_connection_probed,
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.log_capture import capture_log_messages
from tests.component.occupancy_helpers import seed_occupancy_grants

# The test catalog freezes Claude at 2,890 token micro-USD plus three searches
# at 10,000 micro-USD each.
_AUDIT_CLAUDE_MICROUSD = 32_890

# What one funded audit here reserves: two tasks (2 prompts x 1 engine x
# 1 repetition), each reserving the frozen audit attempt budget. DERIVED, not
# spelled: the audit attempt budget is a cost knob, and a test that hard-codes
# the product silently stops testing the ceiling the moment it moves.
_FUNDED_TASK_COUNT = 2
_AUDIT_RESERVED_MICROUSD = (
    _AUDIT_CLAUDE_MICROUSD * audit_settings.max_attempts * _FUNDED_TASK_COUNT
)
_MICROUSD_PER_MINOR = MICRO_USD_PER_USD // 100
# Budgets expressed against that reservation, so both cases keep their meaning:
# one that cannot fund a single audit, and one that funds exactly one of two.
_BUDGET_BELOW_ONE_AUDIT = (_AUDIT_RESERVED_MICROUSD - 1) // _MICROUSD_PER_MINOR
_BUDGET_FOR_ONE_AUDIT = -(-_AUDIT_RESERVED_MICROUSD // _MICROUSD_PER_MINOR)
assert _BUDGET_BELOW_ONE_AUDIT * _MICROUSD_PER_MINOR < _AUDIT_RESERVED_MICROUSD
assert (
    _AUDIT_RESERVED_MICROUSD
    <= _BUDGET_FOR_ONE_AUDIT * _MICROUSD_PER_MINOR
    < 2 * _AUDIT_RESERVED_MICROUSD
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _seed_funded(
    session: AsyncSession,
    *,
    prompt_count: int = 2,
    credits: int = 1_000,
    credit_key: str = KEY_AUDIT_CREDITS,
) -> tuple[BillingAccount, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed workspace/project/prompts plus a linked funded account with
    credits. Returns (account, workspace_id, project_id, prompt_set_id).

    The tenant BYOK connection stays UNPROBED so T11 BYOK precedence cannot
    claim funded tasks, and the platform credential in the system workspace
    is what funded credential resolution binds.
    """
    seed = await seed_audit_fixtures(
        session, prompt_count=prompt_count, engines=[ENGINE_CLAUDE], probed=False
    )
    await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
    account = await seed_occupancy_grants(
        session,
        workspace_id=seed.workspace_id,
        grants=(GrantSpec(key=credit_key, value=credits),),
    )
    await session.commit()
    return account, seed.workspace_id, seed.project_id, seed.prompt_set_id


async def _create_funded(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_set_id: uuid.UUID,
    engines: list[str] | None = None,
) -> Audit:
    return await create_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        engines=engines or [ENGINE_CLAUDE],
        trigger=AUDIT_TRIGGER_MANUAL,
        credential_mode=CREDENTIAL_MODE_FUNDED,
        prompt_set_id=prompt_set_id,
        repetitions=1,
        random_seed="1",
    )


async def _count(session: AsyncSession, model) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar_one()
    )


@pytest.mark.asyncio
async def test_funded_run_reserves_each_task_before_claimable_and_freezes_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace_id, project_id, prompt_set_id = await _seed_funded(session)
        audit = await _create_funded(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt_set_id=prompt_set_id,
        )
        tasks = list(
            (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        assert len(tasks) == 2
        # The budget the PLANNER FROZE onto each task — the measurement
        # mode's, not the generic live ``audit_settings.max_attempts``.
        max_attempts = tasks[0].max_attempts
        expected_cost = _AUDIT_CLAUDE_MICROUSD * max_attempts * len(tasks)
        # Audit-level funded provenance persisted in the same transaction.
        assert audit.funding_account_id == account.id
        assert audit.funded_reserved_cost_microusd == expected_cost
        month_start = datetime.now(UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        assert audit.funded_budget_period_start == month_start
        # Every task is claimable AND reserved for its own max_attempts; the
        # frozen task configuration carries its reservation id, and the audit
        # configuration carries the task-reservation map.
        configuration = audit.configuration or {}
        task_reservations = configuration.get("task_reservations") or {}
        assert set(task_reservations) == {str(task.id) for task in tasks}
        ledger_rows = list(
            (
                await session.scalars(
                    select(ConsumableLedger).where(
                        ConsumableLedger.audit_id == audit.id,
                        ConsumableLedger.entry_kind == "reservation",
                    )
                )
            ).all()
        )
        assert len(ledger_rows) == len(tasks)
        for task in tasks:
            assert task.status == TASK_STATUS_QUEUED
            funding = (task.provider_route_snapshot or {}).get("funding")
            assert funding is not None
            assert funding["credential_mode"] == CREDENTIAL_MODE_FUNDED
            assert funding["capability_key"] == KEY_AUDIT_CREDITS
            assert funding["reserved_units"] == max_attempts
            assert funding["funding_account_id"] == str(account.id)
            assert funding["entitlement"]["registry_revision"]
            reservation_id = task_reservations[str(task.id)]
            assert funding["reservation_id"] == reservation_id
            row = next(r for r in ledger_rows if str(r.task_id) == str(task.id))
            assert str(row.reservation_id) == reservation_id
            assert row.units == max_attempts
        funding_block = configuration.get("funding") or {}
        assert funding_block.get("capability_key") == KEY_AUDIT_CREDITS
        assert funding_block.get("reserved_cost_microusd") == expected_cost


@pytest.mark.asyncio
async def test_budget_exhaustion_persists_nothing_and_emits_telemetry(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async with session_factory() as session:
        _account, workspace_id, project_id, prompt_set_id = await _seed_funded(session)
        # A ceiling below one audit's reservation: admission must fail closed.
        monkeypatch.setattr(
            billing_settings, "funded_monthly_budget_minor", _BUDGET_BELOW_ONE_AUDIT
        )
        with capture_log_messages("app.billing") as events:
            with pytest.raises(FundedAdmissionError) as exc_info:
                await _create_funded(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    prompt_set_id=prompt_set_id,
                )
        await session.rollback()
        assert exc_info.value.code == CODE_FUNDED_BUDGET_EXHAUSTED
        assert any(TELEMETRY_FUNDED_BUDGET_EXHAUSTED in m for m in events)
        # Every funded-admission denial also emits the outcome event once.
        denied = [m for m in events if TELEMETRY_FUNDED_ADMISSION_DENIED in m]
        assert len(denied) == 1
        assert CODE_FUNDED_BUDGET_EXHAUSTED in denied[0]
        assert await _count(session, Audit) == 0
        assert await _count(session, AuditTask) == 0
        assert await _count(session, ConsumableLedger) == 0


@pytest.mark.asyncio
async def test_concurrent_funded_admissions_never_exceed_ceiling(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    async with session_factory() as session:
        account, workspace_id, project_id, prompt_set_id = await _seed_funded(session)
        account_id = account.id
    # A ceiling that funds one audit but not two, so exactly ONE of two
    # concurrent admissions may commit.
    monkeypatch.setattr(
        billing_settings, "funded_monthly_budget_minor", _BUDGET_FOR_ONE_AUDIT
    )

    async def _admit() -> str:
        async with session_factory() as session:
            try:
                await _create_funded(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    prompt_set_id=prompt_set_id,
                )
                return "ok"
            except FundedAdmissionError as exc:
                await session.rollback()
                return exc.code

    results = await asyncio.gather(_admit(), _admit())
    assert sorted(results) == [CODE_FUNDED_BUDGET_EXHAUSTED, "ok"]
    ceiling = _BUDGET_FOR_ONE_AUDIT * _MICROUSD_PER_MINOR
    async with session_factory() as session:
        reserved = await session.scalar(
            select(
                func.coalesce(func.sum(Audit.funded_reserved_cost_microusd), 0)
            ).where(Audit.funding_account_id == account_id)
        )
        assert int(reserved or 0) <= ceiling
        assert int(reserved or 0) == _AUDIT_RESERVED_MICROUSD


@pytest.mark.asyncio
async def test_incomplete_expected_cost_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        # Claude with retrieval ON and an incomplete observed search envelope
        # -> incomplete -> funded_cost_unresolved (never coerced to zero).
        monkeypatch.setitem(
            _EXPECTED_COST_CATALOG,
            ROUTE_CLAUDE,
            _ExpectedCostEstimate(
                token_cost_microusd=2_890,
                search_fee_microusd=None,
                expected_searches=None,
            ),
        )
        _account, workspace_id, project_id, prompt_set_id = await _seed_funded(
            session, credit_key=KEY_AUDIT_CREDITS
        )
        with pytest.raises(FundedAdmissionError) as exc_info:
            await _create_funded(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                prompt_set_id=prompt_set_id,
            )
        await session.rollback()
        assert exc_info.value.code == CODE_FUNDED_COST_UNRESOLVED

        # Gemini audit: the route has NO catalog estimate at all -> token
        # estimate absent -> incomplete with citation-capable retrieval.
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=[ENGINE_GEMINI]
        )
        await seed_occupancy_grants(
            session,
            workspace_id=seed.workspace_id,
            grants=(GrantSpec(key=KEY_AUDIT_CREDITS, value=100),),
        )
        await session.commit()
        with pytest.raises(FundedAdmissionError) as exc_info:
            await _create_funded(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                prompt_set_id=seed.prompt_set_id,
                engines=[ENGINE_GEMINI],
            )
        await session.rollback()
        assert exc_info.value.code == CODE_FUNDED_COST_UNRESOLVED
        assert await _count(session, ConsumableLedger) == 0


@pytest.mark.asyncio
async def test_byok_run_writes_no_funded_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace_id, project_id, prompt_set_id = await _seed_funded(session)
        # BYOK mode needs an executable tenant credential: mark the seeded
        # tenant connection probed (``_seed_funded`` keeps it unprobed).
        tenant_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == workspace_id
            )
        )
        assert tenant_connection is not None
        _mark_connection_probed(
            session, connection=tenant_connection, engine=ENGINE_CLAUDE
        )
        await session.commit()
        audit = await create_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            engines=[ENGINE_CLAUDE],
            trigger=AUDIT_TRIGGER_MANUAL,
            credential_mode=CREDENTIAL_MODE_BYOK,
            prompt_set_id=prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
        assert audit.funding_account_id is None
        assert audit.funded_reserved_cost_microusd is None
        assert audit.funded_budget_period_start is None
        configuration = audit.configuration or {}
        assert "task_reservations" not in configuration
        assert "funding" not in configuration
        tasks = list(
            (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        assert tasks
        for task in tasks:
            assert task.status == TASK_STATUS_QUEUED
            assert "funding" not in (task.provider_route_snapshot or {})
        assert await _count(session, ConsumableLedger) == 0


@pytest.mark.asyncio
async def test_credit_exhaustion_rolls_back_everything_and_emits_telemetry(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # 3 credits < the 10 units two tasks reserve (2 x max_attempts=5).
        _account, workspace_id, project_id, prompt_set_id = await _seed_funded(
            session, credits=3
        )
        with capture_log_messages("app.billing") as events:
            with pytest.raises(FundedAdmissionError) as exc_info:
                await _create_funded(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    prompt_set_id=prompt_set_id,
                )
        await session.rollback()
        assert exc_info.value.code == CODE_FUNDED_CREDITS_EXHAUSTED
        assert any(TELEMETRY_CONSUMABLE_CREDITS_EXHAUSTED in m for m in events)
        denied = [m for m in events if TELEMETRY_FUNDED_ADMISSION_DENIED in m]
        assert len(denied) == 1
        assert CODE_FUNDED_CREDITS_EXHAUSTED in denied[0]
        assert await _count(session, Audit) == 0
        assert await _count(session, AuditTask) == 0
        assert await _count(session, ConsumableLedger) == 0


@pytest.mark.asyncio
async def test_unresolved_entitlement_fails_closed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # No billing link at all -> entitlement_unresolved; nothing persists.
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=[ENGINE_CLAUDE]
        )
        with capture_log_messages("app.billing") as events:
            with pytest.raises(FundedAdmissionError) as exc_info:
                await _create_funded(
                    session,
                    workspace_id=seed.workspace_id,
                    project_id=seed.project_id,
                    prompt_set_id=seed.prompt_set_id,
                )
        await session.rollback()
        assert exc_info.value.code == STATUS_ENTITLEMENT_UNRESOLVED
        assert any(TELEMETRY_ENTITLEMENT_UNRESOLVED in m for m in events)
        denied = [m for m in events if TELEMETRY_FUNDED_ADMISSION_DENIED in m]
        assert len(denied) == 1
        assert STATUS_ENTITLEMENT_UNRESOLVED in denied[0]
        assert await _count(session, Audit) == 0
        assert await _count(session, AuditTask) == 0
        assert await _count(session, ConsumableLedger) == 0
