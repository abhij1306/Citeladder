"""Component tests for workspace-scoped audit-schedule persistence.

``app/domain/audits/schedule_service.py`` sat at 31% line coverage. It is the
only writer for ``audit_schedules``, and every one of its reads is supposed to
be workspace-authorized — a claim nothing was checking. These run the real
service against a live Postgres schema, seeded through the shared audit helper.

Each mutating test asserts isolation explicitly: a second workspace must not be
able to read, update, or delete the first workspace's schedule, and must never
be able to bind a schedule to another workspace's prompt set.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audit_schedules import (
    CADENCE_EVERY_N_MINUTES,
    audit_schedule_settings,
)
from app.domain.audits.schedule_schemas import AuditScheduleCreate, AuditScheduleUpdate
from app.domain.audits.schedule_service import (
    AuditScheduleNotFoundError,
    AuditScheduleValidationError,
    create_schedule,
    delete_schedule,
    get_schedule,
    list_schedules,
    update_schedule,
)

from .audit_helpers import Seed, seed_audit_fixtures


def _create_payload(seed: Seed, **overrides: object) -> AuditScheduleCreate:
    values: dict[str, object] = {
        "prompt_set_id": seed.prompt_set_id,
        "cadence": "daily",
        "engines": list(seed.engines),
    }
    values.update(overrides)
    return AuditScheduleCreate(**values)  # type: ignore[arg-type]


async def _seed_schedule(session: AsyncSession, seed: Seed, **overrides: object):
    return await create_schedule(
        session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        payload=_create_payload(seed, **overrides),
    )


@pytest.mark.asyncio
async def test_create_persists_the_schedule_scoped_to_its_workspace(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)

    schedule = await _seed_schedule(db_session, seed)

    assert schedule.workspace_id == seed.workspace_id
    assert schedule.project_id == seed.project_id
    assert schedule.prompt_set_id == seed.prompt_set_id
    assert schedule.cadence == "daily"
    assert schedule.enabled is True
    # An enabled schedule is immediately due unless the caller pinned a time,
    # so the scheduler has something to claim rather than a null next run.
    assert schedule.next_run_at is not None


@pytest.mark.asyncio
async def test_create_honours_an_explicit_next_run_at(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    pinned = datetime.now(UTC) + timedelta(hours=6)

    schedule = await _seed_schedule(db_session, seed, next_run_at=pinned)

    assert schedule.next_run_at is not None
    stored = schedule.next_run_at
    if stored.tzinfo is None:
        stored = stored.replace(tzinfo=UTC)
    assert abs((stored - pinned).total_seconds()) < 1


@pytest.mark.asyncio
async def test_create_rejects_a_prompt_set_from_another_project(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-a@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-b@example.com")

    # Workspace isolation: an ID from another workspace must not be usable just
    # because the caller happens to know it.
    with pytest.raises(AuditScheduleValidationError, match="Prompt set not found"):
        await create_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            payload=_create_payload(seed, prompt_set_id=other.prompt_set_id),
        )


@pytest.mark.asyncio
async def test_create_rejects_a_project_outside_the_active_workspace(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-c@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-d@example.com")

    with pytest.raises(AuditScheduleValidationError, match="Project not found"):
        await create_schedule(
            db_session,
            workspace_id=other.workspace_id,
            project_id=seed.project_id,
            payload=_create_payload(seed),
        )


@pytest.mark.asyncio
async def test_every_n_minutes_requires_at_least_the_configured_minimum(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    minimum = audit_schedule_settings.min_interval_minutes
    schedule = await _seed_schedule(
        db_session,
        seed,
        cadence=CADENCE_EVERY_N_MINUTES,
        interval_minutes=minimum,
    )

    with pytest.raises(AuditScheduleValidationError, match="configured-minimum"):
        await update_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            schedule_id=schedule.id,
            payload=AuditScheduleUpdate(interval_minutes=minimum - 1),
        )


@pytest.mark.asyncio
async def test_an_interval_is_rejected_for_a_non_interval_cadence(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    schedule = await _seed_schedule(db_session, seed, cadence="daily")

    with pytest.raises(
        AuditScheduleValidationError, match="only valid for every_n_minutes"
    ):
        await update_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            schedule_id=schedule.id,
            payload=AuditScheduleUpdate(interval_minutes=90),
        )


@pytest.mark.asyncio
async def test_switching_to_an_interval_cadence_without_an_interval_is_rejected(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    schedule = await _seed_schedule(db_session, seed, cadence="daily")

    # The merged view is what gets validated: a cadence change alone must not
    # leave the row in a state the scheduler cannot interpret.
    with pytest.raises(AuditScheduleValidationError, match="configured-minimum"):
        await update_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            schedule_id=schedule.id,
            payload=AuditScheduleUpdate(cadence=CADENCE_EVERY_N_MINUTES),
        )


@pytest.mark.asyncio
async def test_list_returns_only_the_active_workspace_and_project(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-e@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-f@example.com")
    mine = await _seed_schedule(db_session, seed)
    await _seed_schedule(db_session, other)

    rows = await list_schedules(
        db_session, workspace_id=seed.workspace_id, project_id=seed.project_id
    )

    assert [row.id for row in rows] == [mine.id]


@pytest.mark.asyncio
async def test_list_is_ordered_by_creation(db_session: AsyncSession) -> None:
    seed = await seed_audit_fixtures(db_session)
    first = await _seed_schedule(db_session, seed)
    second = await _seed_schedule(db_session, seed, cadence="hourly")
    first.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    second.created_at = first.created_at + timedelta(seconds=1)
    await db_session.commit()

    rows = await list_schedules(
        db_session, workspace_id=seed.workspace_id, project_id=seed.project_id
    )

    assert [row.id for row in rows] == [first.id, second.id]


@pytest.mark.asyncio
async def test_get_from_another_workspace_is_not_found(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-g@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-h@example.com")
    schedule = await _seed_schedule(db_session, seed)

    # Not "forbidden": a caller outside the workspace learns nothing about
    # whether the ID exists.
    with pytest.raises(AuditScheduleNotFoundError):
        await get_schedule(
            db_session,
            workspace_id=other.workspace_id,
            project_id=other.project_id,
            schedule_id=schedule.id,
        )


@pytest.mark.asyncio
async def test_get_with_an_unknown_id_is_not_found(db_session: AsyncSession) -> None:
    seed = await seed_audit_fixtures(db_session)

    with pytest.raises(AuditScheduleNotFoundError):
        await get_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            schedule_id=uuid.uuid4(),
        )


@pytest.mark.asyncio
async def test_update_applies_only_the_supplied_fields(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    schedule = await _seed_schedule(db_session, seed, cadence="daily")
    original_prompt_set = schedule.prompt_set_id

    updated = await update_schedule(
        db_session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        schedule_id=schedule.id,
        payload=AuditScheduleUpdate(cadence="weekly"),
    )

    assert updated.cadence == "weekly"
    assert updated.prompt_set_id == original_prompt_set


@pytest.mark.asyncio
async def test_re_enabling_a_schedule_gives_it_a_due_time(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session)
    schedule = await _seed_schedule(db_session, seed, enabled=False)
    schedule.next_run_at = None
    await db_session.commit()

    updated = await update_schedule(
        db_session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        schedule_id=schedule.id,
        payload=AuditScheduleUpdate(enabled=True),
    )

    # Without this the row would be enabled but permanently unclaimable.
    assert updated.enabled is True
    assert updated.next_run_at is not None


@pytest.mark.asyncio
async def test_update_rejects_a_prompt_set_from_another_workspace(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-i@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-j@example.com")
    schedule = await _seed_schedule(db_session, seed)

    with pytest.raises(AuditScheduleValidationError, match="Prompt set not found"):
        await update_schedule(
            db_session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            schedule_id=schedule.id,
            payload=AuditScheduleUpdate(prompt_set_id=other.prompt_set_id),
        )


@pytest.mark.asyncio
async def test_update_from_another_workspace_is_not_found(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-k@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-l@example.com")
    schedule = await _seed_schedule(db_session, seed, cadence="daily")

    with pytest.raises(AuditScheduleNotFoundError):
        await update_schedule(
            db_session,
            workspace_id=other.workspace_id,
            project_id=other.project_id,
            schedule_id=schedule.id,
            payload=AuditScheduleUpdate(cadence="weekly"),
        )

    unchanged = await get_schedule(
        db_session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        schedule_id=schedule.id,
    )
    assert unchanged.cadence == "daily"


@pytest.mark.asyncio
async def test_delete_removes_the_schedule(db_session: AsyncSession) -> None:
    seed = await seed_audit_fixtures(db_session)
    schedule = await _seed_schedule(db_session, seed)

    await delete_schedule(
        db_session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        schedule_id=schedule.id,
    )

    assert (
        await list_schedules(
            db_session, workspace_id=seed.workspace_id, project_id=seed.project_id
        )
        == []
    )


@pytest.mark.asyncio
async def test_delete_from_another_workspace_leaves_the_row_intact(
    db_session: AsyncSession,
) -> None:
    seed = await seed_audit_fixtures(db_session, email="owner-m@example.com")
    other = await seed_audit_fixtures(db_session, email="owner-n@example.com")
    schedule = await _seed_schedule(db_session, seed)

    with pytest.raises(AuditScheduleNotFoundError):
        await delete_schedule(
            db_session,
            workspace_id=other.workspace_id,
            project_id=other.project_id,
            schedule_id=schedule.id,
        )

    survivor = await get_schedule(
        db_session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        schedule_id=schedule.id,
    )
    assert survivor.id == schedule.id
