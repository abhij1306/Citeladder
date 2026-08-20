"""Create immutable child audits containing only selected failed slots."""

from __future__ import annotations

import uuid
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import (
    AUDIT_STATUS_DRAFT,
    AUDIT_STATUS_QUEUED,
    AUDIT_STATUS_VALIDATING,
    AUDIT_TERMINAL_STATUSES,
    AUDIT_TRIGGER_REPAIR,
    EVENT_AUDIT_CREATED,
    EVENT_AUDIT_QUEUED,
)
from app.core.config.provider_catalog import CREDENTIAL_SOURCE_BYOK
from app.core.config.task_queue import TASK_STATUS_FAILED, TASK_STATUS_QUEUED
from app.domain.audits.state_events import apply_transition, record_event
from app.models.audit import (
    Audit,
    AuditEngineSnapshot,
    AuditPromptSnapshot,
    AuditTask,
)


class AuditRepairError(ValueError):
    pass


async def create_repair_audit(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    audit_id: uuid.UUID,
    provider: str | None = None,
    engine: str | None = None,
    prompt_id: uuid.UUID | None = None,
    task_ids: list[uuid.UUID] | None = None,
) -> tuple[Audit, bool]:
    parent = await session.scalar(
        select(Audit)
        .where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
        )
        .with_for_update()
    )
    if parent is None:
        raise LookupError("Audit not found")
    if parent.status not in AUDIT_TERMINAL_STATUSES:
        raise AuditRepairError("Only a terminal audit can be repaired")

    prompt_rows = list(
        (
            await session.scalars(
                select(AuditPromptSnapshot).where(
                    AuditPromptSnapshot.audit_id == parent.id
                )
            )
        ).all()
    )
    prompts_by_id = {row.id: row for row in prompt_rows}
    tasks = await _selected_failed_tasks(
        session,
        parent=parent,
        workspace_id=workspace_id,
        prompts_by_id=prompts_by_id,
        provider=provider,
        engine=engine,
        prompt_id=prompt_id,
        task_ids=task_ids,
    )
    if not tasks:
        raise AuditRepairError("No failed tasks match the repair filters")
    if any(
        (task.provider_route_snapshot or {}).get("credential_source")
        != CREDENTIAL_SOURCE_BYOK
        for task in tasks
    ):
        raise AuditRepairError(
            "Funded audit failures require a new admitted audit; repair supports "
            "BYOK tasks"
        )
    repair_key = sha256(
        "|".join(sorted(str(task.id) for task in tasks)).encode("utf-8")
    ).hexdigest()
    existing = await session.scalar(
        select(Audit).where(
            Audit.workspace_id == workspace_id,
            Audit.parent_audit_id == parent.id,
            Audit.repair_key == repair_key,
        )
    )
    if existing is not None:
        return existing, False

    child = _new_repair_audit(parent, workspace_id, repair_key, tasks)
    session.add(child)
    await session.flush()
    prompt_map = _clone_prompt_snapshots(session, child.id, tasks, prompts_by_id)
    engine_map = await _clone_engine_snapshots(session, parent.id, child.id, tasks)
    await session.flush()
    _clone_tasks(session, child, workspace_id, tasks, prompt_map, engine_map)
    _queue_repair(session, child, tasks)
    await session.commit()
    return child, True


async def _selected_failed_tasks(
    session,
    *,
    parent,
    workspace_id,
    prompts_by_id,
    provider,
    engine,
    prompt_id,
    task_ids,
):
    selected_ids = set(task_ids or [])
    rows = list(
        (
            await session.scalars(
                select(AuditTask)
                .where(
                    AuditTask.audit_id == parent.id,
                    AuditTask.workspace_id == workspace_id,
                    AuditTask.status == TASK_STATUS_FAILED,
                )
                .order_by(AuditTask.randomized_position.asc())
            )
        ).all()
    )
    matches = [
        task
        for task in rows
        if _task_matches(
            task,
            provider=provider,
            engine=engine,
            selected_ids=selected_ids,
            prompt_id=prompt_id,
            prompts_by_id=prompts_by_id,
        )
    ]
    if selected_ids and selected_ids != {task.id for task in matches}:
        raise AuditRepairError("task_ids must identify failed tasks in this audit")
    if not selected_ids:
        matches = [
            task
            for task in matches
            if (task.provider_route_snapshot or {}).get("credential_source")
            == CREDENTIAL_SOURCE_BYOK
        ]
    return matches


def _task_matches(
    task, *, provider, engine, selected_ids, prompt_id, prompts_by_id
) -> bool:
    return (
        (provider is None or task.transport_provider == provider)
        and (engine is None or task.logical_engine == engine)
        and (not selected_ids or task.id in selected_ids)
        and (
            prompt_id is None
            or prompts_by_id[task.prompt_snapshot_id].prompt_id == prompt_id
        )
    )


def _new_repair_audit(parent, workspace_id, repair_key, tasks):
    return Audit(
        workspace_id=workspace_id,
        project_id=parent.project_id,
        parent_audit_id=parent.id,
        repair_key=repair_key,
        status=AUDIT_STATUS_DRAFT,
        trigger=AUDIT_TRIGGER_REPAIR,
        benchmark_mode=parent.benchmark_mode,
        measurement_mode=parent.measurement_mode,
        system_instruction=parent.system_instruction,
        repetitions=parent.repetitions,
        random_seed=str(uuid.uuid4().int & ((1 << 64) - 1)),
        configuration={
            **(parent.configuration or {}),
            "repair_parent_audit_id": str(parent.id),
            "repair_source_task_ids": [str(task.id) for task in tasks],
        },
        requested_count=len(tasks),
    )


def _clone_prompt_snapshots(session, child_id, tasks, prompts_by_id):
    selected = {
        task.prompt_snapshot_id: prompts_by_id[task.prompt_snapshot_id]
        for task in tasks
    }
    clones = {}
    for source in sorted(selected.values(), key=lambda row: row.prompt_index):
        clone = AuditPromptSnapshot(
            audit_id=child_id,
            prompt_id=source.prompt_id,
            prompt_index=source.prompt_index,
            text=source.text,
            theme=source.theme,
            intent=source.intent,
            cohort=source.cohort,
            generation_evidence=source.generation_evidence,
        )
        session.add(clone)
        clones[source.id] = clone
    return clones


async def _clone_engine_snapshots(session, parent_id, child_id, tasks):
    sources = list(
        (
            await session.scalars(
                select(AuditEngineSnapshot).where(
                    AuditEngineSnapshot.audit_id == parent_id
                )
            )
        ).all()
    )
    used_ids = {task.engine_snapshot_id for task in tasks}
    clones = {}
    for source in sources:
        if source.id in used_ids:
            clone = AuditEngineSnapshot(
                audit_id=child_id,
                logical_engine=source.logical_engine,
                transport_provider=source.transport_provider,
                transport_model=source.transport_model,
                connection_id=source.connection_id,
                base_url=source.base_url,
            )
            session.add(clone)
            clones[source.id] = clone
    return clones


def _clone_tasks(session, child, workspace_id, tasks, prompt_map, engine_map):
    for position, source in enumerate(tasks):
        session.add(
            AuditTask(
                audit_id=child.id,
                workspace_id=workspace_id,
                source_task_id=source.id,
                prompt_snapshot_id=prompt_map[source.prompt_snapshot_id].id,
                engine_snapshot_id=engine_map[source.engine_snapshot_id].id,
                prompt_index=source.prompt_index,
                repetition=source.repetition,
                randomized_position=position,
                logical_engine=source.logical_engine,
                transport_provider=source.transport_provider,
                transport_model=source.transport_model,
                prompt_text=source.prompt_text,
                provider_route_snapshot=source.provider_route_snapshot,
                idempotency_key=(
                    f"{child.id}:{source.prompt_index}:{source.repetition}:"
                    f"{source.logical_engine}"
                ),
                max_attempts=source.max_attempts,
                status=TASK_STATUS_QUEUED,
            )
        )


def _queue_repair(session, child, tasks):
    task_count = len(tasks)
    apply_transition(
        session,
        audit=child,
        target=AUDIT_STATUS_VALIDATING,
        message="repair audit validating",
    )
    apply_transition(
        session,
        audit=child,
        target=AUDIT_STATUS_QUEUED,
        message="repair audit queued",
    )
    record_event(
        session,
        audit_id=child.id,
        event_type=EVENT_AUDIT_CREATED,
        message="repair audit created",
        payload={
            "requested_count": task_count,
            "engines": sorted({task.logical_engine for task in tasks}),
        },
    )
    record_event(
        session,
        audit_id=child.id,
        event_type=EVENT_AUDIT_QUEUED,
        message="repair audit queued",
        payload={"task_count": task_count},
    )
