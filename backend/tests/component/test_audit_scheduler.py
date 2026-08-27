from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config.audit_schedules import (
    CADENCE_HOURLY,
    CADENCE_ONE_TIME,
    audit_schedule_settings,
)
from app.core.config.audits import AUDIT_TRIGGER_SCHEDULED
from app.models.audit_schedule import AuditSchedule
from app.models.project import Project
from app.models.prompt import PromptSet
from app.models.workspace import Workspace
from app.workers.audit_scheduler import AuditScheduler


@pytest.mark.asyncio
async def test_due_schedule_delegates_to_audit_planner_once(
    db_session, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(name="Scheduler test")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme")
    db_session.add(project)
    await db_session.flush()
    prompt_set = PromptSet(project_id=project.id, name="Default")
    db_session.add(prompt_set)
    await db_session.flush()
    due_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    schedule = AuditSchedule(
        workspace_id=workspace.id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        audit_scope="commerce",
        cadence=CADENCE_ONE_TIME,
        engines=["chatgpt"],
        next_run_at=due_at,
    )
    db_session.add(schedule)
    await db_session.commit()

    calls: list[dict[str, object]] = []

    async def fake_create_audit(_session, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr("app.workers.audit_scheduler.create_audit", fake_create_audit)
    scheduler = AuditScheduler(session_factory=session_factory, owner="scheduler-test")

    assert await scheduler.run_once(now=due_at) == 1
    assert len(calls) == 1
    assert calls[0]["trigger"] == AUDIT_TRIGGER_SCHEDULED
    assert calls[0]["schedule_id"] == schedule.id
    assert calls[0]["scheduled_for"] == due_at
    assert calls[0]["audit_scope"] == "commerce"

    await db_session.refresh(schedule)
    assert schedule.enabled is False
    assert schedule.next_run_at is None
    assert schedule.lease_owner is None
    assert await scheduler.run_once(now=due_at) == 0


@pytest.mark.asyncio
async def test_recurring_schedule_advances_and_failure_retries(
    db_session, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(name="Recurring scheduler test")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme")
    db_session.add(project)
    await db_session.flush()
    prompt_set = PromptSet(project_id=project.id, name="Default")
    db_session.add(prompt_set)
    await db_session.flush()
    due_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    schedule = AuditSchedule(
        workspace_id=workspace.id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        cadence=CADENCE_HOURLY,
        engines=["chatgpt"],
        next_run_at=due_at,
    )
    db_session.add(schedule)
    await db_session.commit()
    scheduler = AuditScheduler(session_factory=session_factory, owner="recurring-test")

    async def succeeds(*_args, **_kwargs):
        return object()

    monkeypatch.setattr("app.workers.audit_scheduler.create_audit", succeeds)
    assert await scheduler.run_once(now=due_at) == 1
    await db_session.refresh(schedule)
    assert schedule.enabled is True
    assert schedule.next_run_at == datetime(2026, 8, 4, 13, tzinfo=UTC)

    async def fails(*_args, **_kwargs):
        raise RuntimeError("planner unavailable")

    monkeypatch.setattr("app.workers.audit_scheduler.create_audit", fails)
    failed_at = schedule.next_run_at
    assert await scheduler.run_once(now=failed_at) == 0
    await db_session.refresh(schedule)
    assert schedule.lease_owner is None
    assert schedule.failure_count == 1
    assert schedule.last_error == "audit_planning_failed"
    assert schedule.next_run_at == failed_at + timedelta(
        seconds=audit_schedule_settings.failure_retry_seconds
    )


@pytest.mark.asyncio
async def test_disabled_schedule_is_not_planned_after_claim(
    db_session, session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = Workspace(name="Disabled scheduler test")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme")
    db_session.add(project)
    await db_session.flush()
    prompt_set = PromptSet(project_id=project.id, name="Default")
    db_session.add(prompt_set)
    await db_session.flush()
    due_at = datetime(2026, 8, 4, 12, tzinfo=UTC)
    schedule = AuditSchedule(
        workspace_id=workspace.id,
        project_id=project.id,
        prompt_set_id=prompt_set.id,
        cadence=CADENCE_HOURLY,
        engines=["chatgpt"],
        next_run_at=due_at,
    )
    db_session.add(schedule)
    await db_session.commit()
    scheduler = AuditScheduler(session_factory=session_factory, owner="disable-test")
    claims = await scheduler._claim_due(due_at)
    assert claims == [(schedule.id, due_at)]

    schedule.enabled = False
    await db_session.commit()

    async def unexpected_plan(*_args, **_kwargs):
        pytest.fail("disabled schedule must not create an audit")

    monkeypatch.setattr("app.workers.audit_scheduler.create_audit", unexpected_plan)
    assert await scheduler._plan_claim(schedule.id, due_at, due_at) is False
    await db_session.refresh(schedule)
    assert schedule.lease_owner is None
    assert schedule.failure_count == 0
