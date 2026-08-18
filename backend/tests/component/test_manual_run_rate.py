"""Rolling manual-run rate admission (slice23 Task 4 Part B; real Postgres).

Pins the rolling 24h contract: ``Audit.created_at`` strictly inside the
window across EVERY workspace linked to the account, exact 24-hour-old rows
fall out, trial/scheduled rows never count and non-manual triggers are never
gated, allowance/remaining/reset metadata shape, the pre-commercial
passthrough for unprovisioned accounts, and create_audit applying (not
computing) the typed decision.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    AUDIT_TRIGGER_SCHEDULED,
    AUDIT_TRIGGER_TRIAL,
)
from app.core.config.entitlements import (
    CODE_MANUAL_RUN_RATE_EXCEEDED,
    KEY_MANUAL_RUNS_PER_DAY,
)
from app.domain.audits.creation import create_audit
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.enforcement import (
    RateAdmissionDecision,
    evaluate_manual_run_admission,
)
from app.domain.entitlements.types import GrantSpec
from app.models.audit import Audit
from app.models.billing import BillingAccount, WorkspaceBillingLink
from app.models.project import Project
from app.models.workspace import Workspace
from tests.component.audit_helpers import seed_audit_fixtures
from tests.component.occupancy_helpers import (
    seed_account_workspace,
    seed_occupancy_grants,
)

_AT = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_cache()
    yield
    clear_cache()


async def _linked_project(
    session: AsyncSession, account: BillingAccount
) -> tuple[Workspace, Project]:
    """A second workspace linked to the same account, with one project."""
    workspace = Workspace(name="Linked WS")
    session.add(workspace)
    await session.flush()
    session.add(
        WorkspaceBillingLink(workspace_id=workspace.id, billing_account_id=account.id)
    )
    project = Project(workspace_id=workspace.id, name="Linked Project")
    session.add(project)
    await session.flush()
    await session.commit()
    return workspace, project


def _audit_row(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    trigger: str,
    created_at: datetime,
) -> Audit:
    return Audit(
        workspace_id=workspace_id,
        project_id=project_id,
        status=AUDIT_STATUS_COMPLETED,
        trigger=trigger,
        created_at=created_at,
    )


async def _evaluate(
    session: AsyncSession, workspace_id: uuid.UUID, trigger: str = AUDIT_TRIGGER_MANUAL
) -> RateAdmissionDecision:
    return await evaluate_manual_run_admission(
        session, workspace_id=workspace_id, trigger=trigger, at=_AT
    )


@pytest.mark.asyncio
async def test_rolling_window_counts_across_linked_workspaces(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace_a, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_a.id,
            grants=(GrantSpec(key=KEY_MANUAL_RUNS_PER_DAY, value=3),),
        )
        project_a = Project(workspace_id=workspace_a.id, name="A")
        session.add(project_a)
        workspace_b, project_b = await _linked_project(session, account)
        session.add_all(
            [
                # 23h old in workspace A: inside the window.
                _audit_row(
                    workspace_id=workspace_a.id,
                    project_id=project_a.id,
                    trigger=AUDIT_TRIGGER_MANUAL,
                    created_at=_AT - timedelta(hours=23),
                ),
                # 1h old in workspace B: counts across linked workspaces.
                _audit_row(
                    workspace_id=workspace_b.id,
                    project_id=project_b.id,
                    trigger=AUDIT_TRIGGER_MANUAL,
                    created_at=_AT - timedelta(hours=1),
                ),
                # Exactly 24h old: the strict boundary falls out.
                _audit_row(
                    workspace_id=workspace_a.id,
                    project_id=project_a.id,
                    trigger=AUDIT_TRIGGER_MANUAL,
                    created_at=_AT - timedelta(hours=24),
                ),
                # Trial + scheduled rows never count.
                _audit_row(
                    workspace_id=workspace_a.id,
                    project_id=project_a.id,
                    trigger=AUDIT_TRIGGER_TRIAL,
                    created_at=_AT,
                ),
                _audit_row(
                    workspace_id=workspace_a.id,
                    project_id=project_a.id,
                    trigger=AUDIT_TRIGGER_SCHEDULED,
                    created_at=_AT,
                ),
            ]
        )
        await session.commit()

        decision = await _evaluate(session, workspace_a.id)
        assert isinstance(decision, RateAdmissionDecision)
        assert decision.allowed is True
        assert decision.code == ""
        assert decision.key == KEY_MANUAL_RUNS_PER_DAY
        assert decision.allowance == 3
        assert decision.used == 2
        assert decision.remaining == 1
        # Reset is when the OLDEST in-window run (23h old) ages out: +1h.
        assert decision.reset_at == _AT - timedelta(hours=23) + timedelta(hours=24)
        # The same account scope is visible from the other workspace.
        decision_b = await _evaluate(session, workspace_b.id)
        assert decision_b.used == 2


@pytest.mark.asyncio
async def test_allowance_reached_rejects_with_safe_metadata(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        account, workspace_a, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_a.id,
            grants=(GrantSpec(key=KEY_MANUAL_RUNS_PER_DAY, value=1),),
        )
        project_a = Project(workspace_id=workspace_a.id, name="A")
        session.add(project_a)
        _workspace_b, project_b = await _linked_project(session, account)
        session.add(
            _audit_row(
                workspace_id=project_b.workspace_id,
                project_id=project_b.id,
                trigger=AUDIT_TRIGGER_MANUAL,
                created_at=_AT - timedelta(hours=2),
            )
        )
        await session.commit()

        decision = await _evaluate(session, workspace_a.id)
        assert decision.allowed is False
        assert decision.code == CODE_MANUAL_RUN_RATE_EXCEEDED
        assert decision.allowance == 1
        assert decision.used == 1
        assert decision.remaining == 0
        assert decision.reset_at == _AT + timedelta(hours=22)


@pytest.mark.asyncio
async def test_unprovisioned_accounts_are_not_gated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        # No billing link at all: pre-commercial passthrough.
        workspace = Workspace(name="Unlinked WS")
        session.add(workspace)
        await session.flush()
        await session.commit()
        decision = await _evaluate(session, workspace.id)
        assert decision.allowed is True
        assert decision.allowance is None
        assert decision.remaining is None
        assert decision.reset_at is None

        # Linked account WITHOUT a manual_runs_per_day grant: unprovisioned.
        _account, workspace_b, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_b.id,
            grants=(GrantSpec(key="project_slots", value=5),),
        )
        await session.commit()
        decision_b = await _evaluate(session, workspace_b.id)
        assert decision_b.allowed is True
        assert decision_b.allowance is None


@pytest.mark.asyncio
async def test_non_manual_triggers_are_never_gated(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        _account, workspace_a, _user = await seed_account_workspace(session)
        await seed_occupancy_grants(
            session,
            workspace_id=workspace_a.id,
            grants=(GrantSpec(key=KEY_MANUAL_RUNS_PER_DAY, value=1),),
        )
        project_a = Project(workspace_id=workspace_a.id, name="A")
        session.add(project_a)
        await session.flush()
        session.add(
            _audit_row(
                workspace_id=workspace_a.id,
                project_id=project_a.id,
                trigger=AUDIT_TRIGGER_MANUAL,
                created_at=_AT,
            )
        )
        await session.commit()
        # Manual is over the allowance, but trial/scheduled evaluate clean.
        for trigger in (AUDIT_TRIGGER_TRIAL, AUDIT_TRIGGER_SCHEDULED):
            decision = await _evaluate(session, workspace_a.id, trigger=trigger)
            assert decision.allowed is True
            assert decision.allowance is None
            assert decision.used == 0


@pytest.mark.asyncio
async def test_create_audit_applies_the_decision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.domain.entitlements.enforcement import RateAdmissionDeniedError

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await seed_occupancy_grants(
            session,
            workspace_id=seed.workspace_id,
            grants=(GrantSpec(key=KEY_MANUAL_RUNS_PER_DAY, value=1),),
        )
        await session.commit()
        # First manual run consumes the single allowance.
        await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
        # Second manual run is denied by the typed decision; nothing inserts.
        with pytest.raises(RateAdmissionDeniedError) as exc_info:
            await create_audit(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                trigger=AUDIT_TRIGGER_MANUAL,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
                random_seed="2",
            )
        await session.rollback()
        assert exc_info.value.code == CODE_MANUAL_RUN_RATE_EXCEEDED
        assert exc_info.value.details["allowance"] == 1
        assert exc_info.value.details["remaining"] == 0
        assert exc_info.value.details["reset_at"] is not None
        # A non-manual caller passes its own trigger and is not rate-gated.
        trial = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_TRIAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="3",
        )
        assert trial.trigger == AUDIT_TRIGGER_TRIAL
        audits = list(
            (
                await session.scalars(
                    select(Audit).where(Audit.workspace_id == seed.workspace_id)
                )
            ).all()
        )
        assert len(audits) == 2
