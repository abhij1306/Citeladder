from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_PARTIALLY_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    EVENT_AUDIT_CREATED,
    EVENT_AUDIT_QUEUED,
)
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_BYOK,
    CREDENTIAL_SOURCE_PLATFORM,
)
from app.core.config.task_queue import TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED
from app.domain.audits.creation import create_audit
from app.domain.audits.reads import list_tasks
from app.domain.audits.repair import AuditRepairError, create_repair_audit
from app.domain.audits.schemas import audit_event_response
from app.models.audit import AuditEvent
from tests.component.audit_helpers import seed_audit_fixtures


@pytest.mark.asyncio
async def test_repair_clones_only_failed_slots_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)
        parent = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=parent.id
        )
        tasks[0].status = TASK_STATUS_SUCCEEDED
        tasks[1].status = TASK_STATUS_FAILED
        parent.status = AUDIT_STATUS_PARTIALLY_COMPLETED
        parent_id = parent.id
        failed_task_id = tasks[1].id
        failed_prompt_text = tasks[1].prompt_text
        await session.commit()

    async with session_factory() as session:
        child, created = await create_repair_audit(
            session, workspace_id=seed.workspace_id, audit_id=parent_id
        )
        child_tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=child.id
        )
        assert child.parent_audit_id == parent_id
        assert len(child_tasks) == 1
        assert child_tasks[0].source_task_id == failed_task_id
        assert child_tasks[0].prompt_text == failed_prompt_text
        events = list(
            (
                await session.scalars(
                    select(AuditEvent).where(AuditEvent.audit_id == child.id)
                )
            ).all()
        )
        event_types = {event.event_type for event in events}
        assert EVENT_AUDIT_CREATED in event_types
        assert EVENT_AUDIT_QUEUED in event_types
        assert all(audit_event_response(event) for event in events)

        replay, replay_created = await create_repair_audit(
            session, workspace_id=seed.workspace_id, audit_id=parent_id
        )
        assert created is True
        assert replay_created is False
        assert replay.id == child.id


@pytest.mark.asyncio
async def test_repair_rejects_success_only_filter(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=["gemini", "chatgpt"]
        )
        parent = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        task = (
            await list_tasks(
                session, workspace_id=seed.workspace_id, audit_id=parent.id
            )
        )[0]
        task.status = TASK_STATUS_SUCCEEDED
        parent.status = AUDIT_STATUS_PARTIALLY_COMPLETED
        await session.commit()
        with pytest.raises(AuditRepairError, match="No failed tasks"):
            await create_repair_audit(
                session, workspace_id=seed.workspace_id, audit_id=parent.id
            )


@pytest.mark.asyncio
async def test_default_repair_selects_only_byok_failures_from_mixed_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(
            session, prompt_count=1, engines=["gemini", "chatgpt"]
        )
        parent = await create_audit(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            trigger=AUDIT_TRIGGER_MANUAL,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
        )
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=parent.id
        )
        assert len(tasks) >= 2
        for task in tasks[:2]:
            task.status = TASK_STATUS_FAILED
        tasks[0].provider_route_snapshot = {
            **(tasks[0].provider_route_snapshot or {}),
            "credential_source": CREDENTIAL_SOURCE_BYOK,
        }
        tasks[1].provider_route_snapshot = {
            **(tasks[1].provider_route_snapshot or {}),
            "credential_source": CREDENTIAL_SOURCE_PLATFORM,
        }
        parent.status = AUDIT_STATUS_PARTIALLY_COMPLETED
        await session.commit()

        child, created = await create_repair_audit(
            session, workspace_id=seed.workspace_id, audit_id=parent.id
        )
        repaired = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=child.id
        )
        assert created is True
        assert [task.source_task_id for task in repaired] == [tasks[0].id]
        with pytest.raises(AuditRepairError, match="Funded audit failures"):
            await create_repair_audit(
                session,
                workspace_id=seed.workspace_id,
                audit_id=parent.id,
                task_ids=[tasks[1].id],
            )
