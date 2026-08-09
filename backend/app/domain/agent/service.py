"""Bounded Growth Agent planning, execution, decisions, and projections."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.agent.gateway import ModelGateway
from app.core.config.agent import (
    AGENT_INSTRUCTION_VERSION,
    AGENT_PLANNER_VERSION,
    AGENT_POLICY_VERSION,
    AGENT_RESULT_VALIDATOR_VERSION,
    AGENT_TASK_POLICIES,
    TOOL_KIND_AUTOMATIC,
    default_agent_settings,
)
from app.domain.agent.context import build_agent_context
from app.domain.agent.schemas import AgentTaskSubmit
from app.domain.agent.tools import (
    TOOL_DEFINITIONS,
    AgentToolDefinition,
    ToolExecutionContext,
    execute_tool,
)
from app.domain.content.service import cancel_generation
from app.domain.site_health import service as site_service
from app.models.agent import (
    AgentConversation,
    AgentMessage,
    AgentTaskRun,
    AgentTaskStep,
    AgentToolAttempt,
)
from app.models.content import ContentGeneration, TaskContextPackage
from app.models.project import Project

logger = logging.getLogger(__name__)
_INVALID_CORRECTION_TARGET = "correction proposal target is invalid"


class AgentNotFoundError(LookupError):
    pass


class AgentValidationError(ValueError):
    pass


class AgentConflictError(RuntimeError):
    pass


async def create_conversation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    title: str,
) -> AgentConversation:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    row = AgentConversation(
        workspace_id=workspace_id,
        project_id=project_id,
        created_by_user_id=user_id,
        title=title.strip(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def list_conversations(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, limit: int
) -> list[AgentConversation]:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return list(
        (
            await session.scalars(
                select(AgentConversation)
                .where(
                    AgentConversation.workspace_id == workspace_id,
                    AgentConversation.project_id == project_id,
                )
                .order_by(
                    AgentConversation.updated_at.desc(), AgentConversation.id.desc()
                )
                .limit(limit)
            )
        ).all()
    )


async def get_conversation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> tuple[AgentConversation, list[AgentMessage]]:
    row = await session.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.workspace_id == workspace_id,
            AgentConversation.project_id == project_id,
        )
    )
    if row is None:
        raise AgentNotFoundError("conversation not found")
    messages = list(
        (
            await session.scalars(
                select(AgentMessage)
                .where(
                    AgentMessage.workspace_id == workspace_id,
                    AgentMessage.project_id == project_id,
                    AgentMessage.conversation_id == conversation_id,
                )
                .order_by(AgentMessage.created_at.asc(), AgentMessage.id.asc())
            )
        ).all()
    )
    return row, messages


async def submit_task(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: AgentTaskSubmit,
    idempotency_key: str,
    gateway: ModelGateway | None = None,
) -> tuple[AgentTaskRun, bool]:
    policy = _policy(payload)
    project = await _project(
        session, workspace_id=workspace_id, project_id=payload.project_id
    )
    conversation = await _conversation(
        session,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        conversation_id=payload.conversation_id,
    )
    await _parent_run(
        session,
        workspace_id=workspace_id,
        project_id=payload.project_id,
        parent_run_id=payload.parent_run_id,
    )
    normalized_key = idempotency_key.strip()
    if not normalized_key:
        raise AgentValidationError("Idempotency-Key is required")
    fingerprint = _fingerprint(payload)
    existing = await _idempotent_run(
        session,
        workspace_id=workspace_id,
        idempotency_key=normalized_key,
        fingerprint=fingerprint,
    )
    if existing is not None:
        return existing, False
    capability_snapshot = gateway.capabilities().as_dict() if gateway else {}
    run = AgentTaskRun(
        workspace_id=workspace_id,
        project_id=project.id,
        user_id=user_id,
        conversation_id=conversation.id if conversation else None,
        parent_run_id=payload.parent_run_id,
        idempotency_key=normalized_key,
        request_fingerprint=fingerprint,
        task_type=payload.task_type,
        objective=payload.objective.strip(),
        requested_outputs=payload.requested_outputs or list(policy.requested_outputs),
        task_policy_version=AGENT_POLICY_VERSION,
        allowed_tools=list(policy.allowed_tools),
        resource_scope=payload.resource_scope,
        industry_pack_id=project.industry_pack_id,
        status="validating",
        provider_adapter=gateway.adapter_name if gateway else "deterministic",
        endpoint_host=gateway.base_url_host if gateway else "",
        model=gateway.model if gateway else "bounded-projection-v1",
        capability_snapshot=capability_snapshot,
        instruction_version=AGENT_INSTRUCTION_VERSION,
        skill_version=AGENT_PLANNER_VERSION,
    )
    session.add(run)
    replay = await _flush_or_replay(
        session,
        workspace_id=workspace_id,
        idempotency_key=normalized_key,
        fingerprint=fingerprint,
    )
    if replay is not None:
        return replay, False
    context = await build_agent_context(
        session,
        workspace_id=workspace_id,
        project_id=project.id,
        task_type=payload.task_type,
        resource_scope=payload.resource_scope,
    )
    run.context_package_id = context.id
    pack = context.manifest.get("industry_pack") or {}
    run.industry_pack_id = _industry_pack_id(pack, project)
    run.industry_pack_version = str(pack.get("version") or "")
    plan = _build_plan(payload.task_type, payload.resource_scope)
    run.plan = plan
    run.status = "planning"
    steps = _persist_steps(run, plan)
    session.add_all(steps)
    if conversation:
        session.add(
            AgentMessage(
                workspace_id=workspace_id,
                project_id=project.id,
                conversation_id=conversation.id,
                task_run_id=run.id,
                role="user",
                content=run.objective,
                created_by_user_id=user_id,
            )
        )
        conversation.updated_at = _utcnow()
    await session.commit()
    await _execute_with_timeout(session, run=run, user_id=user_id, gateway=gateway)
    return await get_task_run(
        session, workspace_id=workspace_id, project_id=project.id, run_id=run.id
    ), True


async def confirm_decision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    decision: str,
    confirmed: bool,
    gateway: ModelGateway | None = None,
) -> AgentTaskRun:
    run = await _locked_run(
        session, workspace_id=workspace_id, project_id=project_id, run_id=run_id
    )
    if run.status != "awaiting_user":
        raise AgentConflictError("task is not awaiting a user decision")
    step = await session.scalar(
        select(AgentTaskStep)
        .where(
            AgentTaskStep.task_run_id == run.id,
            AgentTaskStep.workspace_id == workspace_id,
            AgentTaskStep.status == "awaiting_user",
        )
        .order_by(AgentTaskStep.ordinal.asc())
        .with_for_update()
        .limit(1)
    )
    if step is None or step.tool_kind != decision:
        raise AgentValidationError("decision does not match the pending step")
    run.decisions = [
        *list(run.decisions or []),
        {
            "kind": decision,
            "confirmed": confirmed,
            "user_id": str(user_id),
            "decided_at": _utcnow().isoformat(),
            "step_id": str(step.id),
        },
    ]
    if not confirmed:
        step.status = "skipped"
        step.completed_at = _utcnow()
        run.status = "partially_completed"
        run.result = _result_from_steps(
            await _steps(session, run.id),
            conclusion=(
                "The requested action was not run because you declined the decision."
            ),
        )
        run.validation = _validate_result(
            run.result, context_ids=await _context_ids(session, run)
        )
        run.completed_at = _utcnow()
        await session.commit()
        return run
    step.status = "pending"
    run.status = "running"
    await session.commit()
    await _execute_with_timeout(session, run=run, user_id=user_id, gateway=gateway)
    return await get_task_run(
        session, workspace_id=workspace_id, project_id=project_id, run_id=run_id
    )


async def accept_correction_proposal(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    reason: str,
):
    """Turn one agent proposal into the existing inline Correction artifact."""
    run = await _locked_run(
        session, workspace_id=workspace_id, project_id=project_id, run_id=run_id
    )
    step = await session.scalar(
        select(AgentTaskStep).where(
            AgentTaskStep.task_run_id == run.id,
            AgentTaskStep.tool_name == "knowledge.propose_correction",
            AgentTaskStep.status == "completed",
        )
    )
    proposal = step.output if step is not None else None
    if not isinstance(proposal, dict) or proposal.get("state") != "proposed":
        raise AgentValidationError("task has no correction proposal to accept")
    assert step is not None
    if proposal.get("accepted_correction_id"):
        raise AgentConflictError("correction proposal was already accepted")
    target_ref = proposal.get("target_ref")
    if not isinstance(target_ref, dict):
        raise AgentValidationError(_INVALID_CORRECTION_TARGET)
    target_kind, target_id = _correction_target(target_ref)
    correction = await _create_site_correction(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        user_id=user_id,
        target_kind=target_kind,
        target_id=target_id,
        proposal=proposal,
        reason=reason,
    )
    step.output = {
        **proposal,
        "state": "accepted",
        "accepted_correction_id": str(correction.id),
    }
    await session.commit()
    return correction


async def cancel_task(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AgentTaskRun:
    run = await _locked_run(
        session, workspace_id=workspace_id, project_id=project_id, run_id=run_id
    )
    if run.status in {"completed", "partially_completed", "failed", "cancelled"}:
        return run
    steps = await _steps(session, run.id)
    for step in steps:
        await _cancel_child_best_effort(session, workspace_id=workspace_id, step=step)
    run = await _locked_run(
        session, workspace_id=workspace_id, project_id=project_id, run_id=run_id
    )
    steps = await _steps(session, run.id)
    for step in steps:
        if step.status not in {"completed", "failed", "skipped"}:
            step.status = "cancelled"
            step.completed_at = _utcnow()
    run.status = "cancelled"
    run.cancelled_at = _utcnow()
    await session.commit()
    return run


async def _cancel_child_best_effort(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    step: AgentTaskStep,
) -> None:
    if step.child_task_kind != "content_generation" or step.child_task_id is None:
        return
    try:
        await cancel_generation(
            session,
            workspace_id=workspace_id,
            generation_id=step.child_task_id,
        )
    except Exception:
        logger.exception(
            "agent child cancellation failed",
            extra={"child_task_id": str(step.child_task_id)},
        )
        await session.rollback()


async def reconcile_awaiting_tasks(session: AsyncSession, *, limit: int = 50) -> int:
    runs = await _awaiting_runs(session, limit)
    steps_by_run = await _steps_by_run(session, runs)
    waiting = _waiting_steps(steps_by_run)
    children_by_id = await _children_by_id(session, runs, waiting)
    changed = 0
    continuations: list[AgentTaskRun] = []
    for run in runs:
        reconciled, should_continue = await _reconcile_run(
            session,
            run=run,
            steps=steps_by_run[run.id],
            waiting_step=waiting[run.id],
            children_by_id=children_by_id,
        )
        changed += int(reconciled)
        if should_continue:
            continuations.append(run)
    if changed:
        await session.commit()
    else:
        await session.rollback()
    await _continue_reconciled_runs(session, continuations, steps_by_run)
    return changed


async def _awaiting_runs(session: AsyncSession, limit: int) -> list[AgentTaskRun]:
    return list(
        (
            await session.scalars(
                select(AgentTaskRun)
                .where(AgentTaskRun.status == "awaiting_task")
                .order_by(AgentTaskRun.updated_at.asc(), AgentTaskRun.id.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
    )


async def _steps_by_run(
    session: AsyncSession, runs: list[AgentTaskRun]
) -> dict[uuid.UUID, list[AgentTaskStep]]:
    run_ids = [run.id for run in runs]
    result: dict[uuid.UUID, list[AgentTaskStep]] = {run_id: [] for run_id in run_ids}
    if not run_ids:
        return result
    steps = list(
        (
            await session.scalars(
                select(AgentTaskStep)
                .where(AgentTaskStep.task_run_id.in_(run_ids))
                .order_by(AgentTaskStep.task_run_id, AgentTaskStep.ordinal.asc())
            )
        ).all()
    )
    for step in steps:
        result[step.task_run_id].append(step)
    return result


def _waiting_steps(
    steps_by_run: dict[uuid.UUID, list[AgentTaskStep]],
) -> dict[uuid.UUID, AgentTaskStep | None]:
    return {
        run_id: next(
            (
                step
                for step in steps
                if step.status == "awaiting_task"
                and step.child_task_kind == "content_generation"
                and step.child_task_id is not None
            ),
            None,
        )
        for run_id, steps in steps_by_run.items()
    }


async def _children_by_id(
    session: AsyncSession,
    runs: list[AgentTaskRun],
    waiting: dict[uuid.UUID, AgentTaskStep | None],
) -> dict[uuid.UUID, ContentGeneration]:
    child_ids = [step.child_task_id for step in waiting.values() if step is not None]
    if not child_ids:
        return {}
    children = list(
        (
            await session.scalars(
                select(ContentGeneration).where(
                    ContentGeneration.id.in_(child_ids),
                    ContentGeneration.workspace_id.in_(
                        {run.workspace_id for run in runs}
                    ),
                    ContentGeneration.project_id.in_({run.project_id for run in runs}),
                )
            )
        ).all()
    )
    return {child.id: child for child in children}


async def _reconcile_run(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    steps: list[AgentTaskStep],
    waiting_step: AgentTaskStep | None,
    children_by_id: dict[uuid.UUID, ContentGeneration],
) -> tuple[bool, bool]:
    child = _waiting_child(waiting_step, children_by_id)
    if not _terminal_child_for_run(run, child):
        return False, False
    assert waiting_step is not None and child is not None
    _apply_child_outcome(run, waiting_step, child)
    if child.status == "succeeded" and _has_step_status(steps, "pending"):
        run.status = "running"
        return True, True
    if child.status == "succeeded" and _has_step_status(steps, "awaiting_task"):
        run.status = "awaiting_task"
        return True, False
    run.result = _result_from_steps(steps)
    run.validation = _validate_result(
        run.result, context_ids=await _context_ids(session, run)
    )
    run.completed_at = _utcnow()
    return True, False


def _waiting_child(
    waiting_step: AgentTaskStep | None,
    children_by_id: dict[uuid.UUID, ContentGeneration],
) -> ContentGeneration | None:
    if waiting_step is None or waiting_step.child_task_id is None:
        return None
    return children_by_id.get(waiting_step.child_task_id)


def _has_step_status(steps: list[AgentTaskStep], status: str) -> bool:
    return any(step.status == status for step in steps)


async def _continue_reconciled_runs(
    session: AsyncSession,
    runs: list[AgentTaskRun],
    steps_by_run: dict[uuid.UUID, list[AgentTaskStep]],
) -> None:
    for run in runs:
        if run.user_id is None:
            step = next(
                item for item in steps_by_run[run.id] if item.status == "pending"
            )
            await _fail_run(
                session,
                run,
                step,
                "task_owner_unavailable",
                "The task owner is no longer available.",
            )
            continue
        await _execute_available_steps(
            session, run=run, user_id=run.user_id, gateway=None
        )


def _terminal_child_for_run(run: AgentTaskRun, child: ContentGeneration | None) -> bool:
    return bool(
        child is not None
        and child.workspace_id == run.workspace_id
        and child.project_id == run.project_id
        and child.status in {"succeeded", "failed", "cancelled"}
    )


def _apply_child_outcome(
    run: AgentTaskRun, step: AgentTaskStep, child: ContentGeneration
) -> None:
    step.output = {
        **(step.output or {}),
        "state": child.status,
        "generation_id": str(child.id),
        "validation": child.validator_snapshot,
    }
    step.completed_at = _utcnow()
    if child.status == "succeeded":
        step.status = "completed"
        run.status = "completed"
        return
    step.error_code = child.error_code or f"content_{child.status}"
    step.error_detail = (child.error_detail or "Content child task did not succeed.")[
        :1_000
    ]
    run.error_code = step.error_code
    run.error_detail = step.error_detail
    if child.status == "cancelled":
        step.status = "cancelled"
        run.status = "cancelled"
        run.cancelled_at = _utcnow()
    else:
        step.status = "failed"
        run.status = "failed"


async def list_task_runs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID, limit: int
) -> list[AgentTaskRun]:
    await _project(session, workspace_id=workspace_id, project_id=project_id)
    return list(
        (
            await session.scalars(
                select(AgentTaskRun)
                .where(
                    AgentTaskRun.workspace_id == workspace_id,
                    AgentTaskRun.project_id == project_id,
                )
                .order_by(AgentTaskRun.created_at.desc(), AgentTaskRun.id.desc())
                .limit(limit)
            )
        ).all()
    )


async def get_task_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AgentTaskRun:
    row = await session.scalar(
        select(AgentTaskRun).where(
            AgentTaskRun.id == run_id,
            AgentTaskRun.workspace_id == workspace_id,
            AgentTaskRun.project_id == project_id,
        )
    )
    if row is None:
        raise AgentNotFoundError("task run not found")
    return row


async def task_run_projection(
    session: AsyncSession, run: AgentTaskRun
) -> dict[str, Any]:
    context = (
        await session.get(TaskContextPackage, run.context_package_id)
        if run.context_package_id
        else None
    )
    steps = await _steps(session, run.id)
    return {
        **_run_values(run),
        "steps": [_step_values(step) for step in steps],
        "context": _context_values(context) if context else None,
    }


async def task_runs_projection(
    session: AsyncSession, runs: list[AgentTaskRun]
) -> list[dict[str, Any]]:
    """Project runs without issuing per-run step or context queries."""
    if not runs:
        return []
    run_ids = [run.id for run in runs]
    steps = list(
        (
            await session.scalars(
                select(AgentTaskStep)
                .where(AgentTaskStep.task_run_id.in_(run_ids))
                .order_by(AgentTaskStep.task_run_id, AgentTaskStep.ordinal.asc())
            )
        ).all()
    )
    steps_by_run: dict[uuid.UUID, list[AgentTaskStep]] = {
        run_id: [] for run_id in run_ids
    }
    for step in steps:
        steps_by_run[step.task_run_id].append(step)
    context_ids = [run.context_package_id for run in runs if run.context_package_id]
    contexts = (
        list(
            (
                await session.scalars(
                    select(TaskContextPackage).where(
                        TaskContextPackage.id.in_(context_ids)
                    )
                )
            ).all()
        )
        if context_ids
        else []
    )
    contexts_by_id = {context.id: context for context in contexts}
    return [
        {
            **_run_values(run),
            "steps": [_step_values(step) for step in steps_by_run[run.id]],
            "context": (
                _context_values(contexts_by_id[run.context_package_id])
                if run.context_package_id in contexts_by_id
                else None
            ),
        }
        for run in runs
    ]


async def _execute_with_timeout(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    user_id: uuid.UUID,
    gateway: ModelGateway | None,
) -> None:
    try:
        async with asyncio.timeout(default_agent_settings.execution_timeout_seconds):
            await _execute_available_steps(
                session, run=run, user_id=user_id, gateway=gateway
            )
    except TimeoutError:
        await session.rollback()
        step = await session.scalar(
            select(AgentTaskStep)
            .where(
                AgentTaskStep.task_run_id == run.id,
                AgentTaskStep.status.in_({"pending", "running"}),
            )
            .order_by(AgentTaskStep.ordinal.asc())
            .limit(1)
        )
        if step is not None:
            await _fail_run(
                session,
                run,
                step,
                "execution_timeout",
                "The bounded task exceeded its execution time limit.",
            )


async def _execute_available_steps(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    user_id: uuid.UUID,
    gateway: ModelGateway | None,
) -> None:
    run.status = "running"
    await session.commit()
    steps = await _steps(session, run.id)
    for step in steps:
        if step.status != "pending":
            continue
        definition = await _authorized_tool_definition(session, run, step)
        if definition is None:
            return
        if definition.kind != TOOL_KIND_AUTOMATIC and not _decision_confirmed(
            run, step
        ):
            step.status = "awaiting_user"
            run.status = "awaiting_user"
            await session.commit()
            return
        await _execute_step(
            session, run=run, step=step, user_id=user_id, gateway=gateway
        )
        if await _execution_should_stop(session, run=run, gateway=gateway):
            return
    steps = await _steps(session, run.id)
    await _complete_run(session, run=run, steps=steps, gateway=gateway)


async def _authorized_tool_definition(
    session: AsyncSession, run: AgentTaskRun, step: AgentTaskStep
) -> AgentToolDefinition | None:
    if step.tool_name not in run.allowed_tools:
        await _fail_run(
            session,
            run,
            step,
            "tool_not_authorized",
            "tool is not allowed by task policy",
        )
        return None
    definition = TOOL_DEFINITIONS.get(step.tool_name)
    if definition is None:
        await _fail_run(
            session,
            run,
            step,
            "unknown_tool",
            "The persisted task references an unavailable tool.",
        )
    return definition


async def _execution_should_stop(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    gateway: ModelGateway | None,
) -> bool:
    if run.status == "failed":
        return True
    if run.status != "awaiting_task":
        return False
    await _complete_run(
        session,
        run=run,
        steps=await _steps(session, run.id),
        gateway=gateway,
    )
    return True


async def _execute_step(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    step: AgentTaskStep,
    user_id: uuid.UUID,
    gateway: ModelGateway | None,
) -> None:
    step.status = "running"
    step.started_at = _utcnow()
    await session.commit()
    started = time.monotonic()
    try:
        output = await execute_tool(
            step.tool_name,
            ToolExecutionContext(
                session=session,
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                user_id=user_id,
                idempotency_key=f"agent:{run.id}:{step.ordinal}",
                gateway=gateway,
            ),
            dict(step.input or {}),
        )
    except Exception:
        logger.exception(
            "agent tool execution failed",
            extra={"run_id": str(run.id), "tool_name": step.tool_name},
        )
        await _record_attempt(
            session,
            run=run,
            step=step,
            output=None,
            error_code="tool_failed",
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        await _fail_run(
            session,
            run,
            step,
            "tool_failed",
            "The typed tool failed. Review the safe error code and retry.",
        )
        return
    await _record_attempt(
        session,
        run=run,
        step=step,
        output=output,
        error_code="",
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    step.output = output
    child = output.get("child_task")
    if isinstance(child, dict) and child.get("id"):
        step.child_task_kind = str(child.get("kind") or "")
        step.child_task_id = uuid.UUID(str(child["id"]))
        step.status = "awaiting_task"
        run.status = "awaiting_task"
    else:
        step.status = "completed"
        step.completed_at = _utcnow()
    await session.commit()


async def _complete_run(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    steps: list[AgentTaskStep],
    gateway: ModelGateway | None,
) -> None:
    if any(step.status == "awaiting_task" for step in steps):
        run.status = "awaiting_task"
        run.result = _result_from_steps(steps, conclusion="A child task is running.")
        await session.commit()
        return
    result = _result_from_steps(steps)
    context_ids = await _context_ids(session, run)
    if gateway and run.task_type in {
        "explain",
        "build_roadmap",
        "demand_analysis",
        "next_measurement",
    }:
        try:
            result = await _narrate(
                gateway, run=run, result=result, allowed_citations=context_ids
            )
        except Exception as exc:
            result["limitations"] = [
                *list(result.get("limitations") or []),
                f"Narrative model unavailable: {type(exc).__name__}",
            ]
        else:
            run.provider_adapter = str(
                result.pop("_provider_adapter", run.provider_adapter)
            )
            run.endpoint_host = str(result.pop("_endpoint_host", run.endpoint_host))
            run.model = str(result.pop("_model", run.model))
            run.usage = result.pop("_usage", None)
            run.latency_ms = result.pop("_latency_ms", None)
    validation = _validate_result(result, context_ids=context_ids)
    run.result = result
    run.validation = validation
    run.status = (
        "completed" if validation["status"] == "passed" else "partially_completed"
    )
    run.completed_at = _utcnow()
    if run.conversation_id:
        session.add(
            AgentMessage(
                workspace_id=run.workspace_id,
                project_id=run.project_id,
                conversation_id=run.conversation_id,
                task_run_id=run.id,
                role="assistant",
                content=str(result.get("conclusion") or "Task completed."),
                citations=list(result.get("citations") or []),
            )
        )
    await session.commit()


async def _narrate(
    gateway: ModelGateway,
    *,
    run: AgentTaskRun,
    result: dict[str, Any],
    allowed_citations: set[str],
) -> dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["conclusion", "limitations", "next_step", "citations"],
        "properties": {
            "conclusion": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "next_step": {"type": "string"},
            "citations": {"type": "array", "items": {"type": "string"}},
        },
    }
    response = await gateway.complete_structured(
        system=(
            "You are CiteLadder's bounded Growth Agent. Explain only the supplied "
            "persisted tool results. Do not change ranks, infer causality, or cite "
            "an ID outside the allowlist."
        ),
        user=json.dumps(
            {
                "objective": run.objective,
                "tool_results": result["tool_results"],
                "allowed_citation_ids": sorted(allowed_citations),
            },
            sort_keys=True,
            ensure_ascii=False,
        ),
        schema_name="growth_agent_result",
        schema=schema,
    )
    try:
        narrative = json.loads(response.content)
    except (TypeError, ValueError):
        narrative = {}
    if not isinstance(narrative, dict):
        narrative = {}
    citations = [
        str(value)
        for value in narrative.get("citations") or []
        if str(value) in allowed_citations
    ]
    return {
        **result,
        "conclusion": result["conclusion"],
        "limitations": result["limitations"],
        "next_step": result["next_step"],
        "citations": citations or result["citations"],
        "_provider_adapter": response.provider_adapter,
        "_endpoint_host": response.endpoint_host,
        "_model": response.returned_model,
        "_usage": response.usage,
        "_latency_ms": response.latency_ms,
    }


def _result_from_steps(
    steps: list[AgentTaskStep], *, conclusion: str = "The bounded task completed."
) -> dict[str, Any]:
    tool_results: list[dict[str, Any]] = [
        {"tool": step.tool_name, "status": step.status, "output": step.output}
        for step in steps
        if step.output is not None
    ]
    citations, artifacts, unavailable = _result_evidence(tool_results)
    roadmap = _result_roadmap(tool_results)
    return {
        "conclusion": conclusion,
        "tool_results": tool_results,
        "roadmap": roadmap,
        "limitations": [f"{name} is unavailable" for name in unavailable],
        "artifacts_created": artifacts,
        "decisions_remaining": [
            step.tool_kind for step in steps if step.status == "awaiting_user"
        ],
        "next_step": (
            "Inspect the cited evidence and continue with the highest-ranked action."
        ),
        "citations": citations,
    }


def _result_evidence(
    tool_results: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]], list[str]]:
    citations: list[str] = []
    artifacts: list[dict[str, Any]] = []
    unavailable: list[str] = []
    for item in tool_results:
        output = item["output"]
        if not isinstance(output, dict):
            continue
        refs = [
            ref for ref in output.get("artifact_refs") or [] if isinstance(ref, dict)
        ]
        artifacts.extend(refs)
        if output.get("state") == "available":
            citations.extend(str(ref["id"]) for ref in refs if ref.get("id"))
        if output.get("state") == "unavailable":
            unavailable.append(str(item["tool"]))
    return sorted(set(citations)), artifacts, unavailable


def _result_roadmap(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
    value = next(
        (
            item["output"]
            for item in tool_results
            if item["tool"] == "opportunities.read_ranked"
        ),
        None,
    )
    return _roadmap_view(value) if isinstance(value, dict) else None


def _validate_result(
    result: dict[str, Any], *, context_ids: set[str]
) -> dict[str, Any]:
    citations = {str(value) for value in result.get("citations") or []}
    invalid = sorted(citations - context_ids)
    unsupported = bool(invalid)
    return {
        "status": "blocked" if unsupported else "passed",
        "validator_version": AGENT_RESULT_VALIDATOR_VERSION,
        "unsupported_output": unsupported,
        "invalid_citation_ids": invalid,
        "citation_count": len(citations),
    }


def _roadmap_view(roadmap: dict[str, Any]) -> dict[str, Any]:
    items = list(roadmap.get("items") or [])
    groups: list[dict[str, Any]] = []
    group_indexes: dict[str, int] = {}
    for item in items:
        group_name = str(item.get("type") or "other")
        index = group_indexes.get(group_name)
        if index is None:
            index = len(groups)
            group_indexes[group_name] = index
            groups.append(
                {
                    "name": group_name,
                    "rationale": (
                        "Grouped by the existing opportunity action family; "
                        "deterministic rank is unchanged."
                    ),
                    "items": [],
                }
            )
        groups[index]["items"].append(item)
    return {
        **roadmap,
        "groups": groups,
        "ordering_owner": "deterministic_priority_formula",
        "agent_reordered": False,
    }


def _decision_confirmed(run: AgentTaskRun, step: AgentTaskStep) -> bool:
    return any(
        decision.get("step_id") == str(step.id)
        and decision.get("kind") == step.tool_kind
        and decision.get("confirmed") is True
        for decision in run.decisions or []
        if isinstance(decision, dict)
    )


async def _context_ids(session: AsyncSession, run: AgentTaskRun) -> set[str]:
    if not run.context_package_id:
        return set()
    context = await session.get(TaskContextPackage, run.context_package_id)
    if context is None:
        return set()
    selected = context.manifest.get("selected") or {}
    return {str(value) for values in selected.values() for value in values}


def _policy(payload: AgentTaskSubmit):
    policy = AGENT_TASK_POLICIES.get(payload.task_type)
    if policy is None:
        raise AgentValidationError("unsupported task type")
    missing = [
        key
        for key in policy.required_scope
        if payload.resource_scope.get(key) in (None, "")
    ]
    if missing:
        raise AgentValidationError(f"resource_scope is missing: {', '.join(missing)}")
    return policy


def _build_plan(task_type: str, resource_scope: dict[str, Any]) -> list[dict[str, Any]]:
    policy = AGENT_TASK_POLICIES[task_type]
    tools = policy.allowed_tools
    if len(tools) > policy.max_tool_calls:
        raise AgentValidationError("task plan exceeds configured tool-call limit")
    return [
        {
            "ordinal": ordinal,
            "name": TOOL_DEFINITIONS[name].description,
            "tool_name": name,
            "tool_version": TOOL_DEFINITIONS[name].version,
            "tool_kind": TOOL_DEFINITIONS[name].kind,
            "input": dict(resource_scope),
            "depends_on": [ordinal - 1] if ordinal > 1 else [],
            "terminal": ordinal == len(tools),
        }
        for ordinal, name in enumerate(tools, start=1)
    ]


def _persist_steps(
    run: AgentTaskRun, plan: list[dict[str, Any]]
) -> list[AgentTaskStep]:
    return [
        AgentTaskStep(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            task_run_id=run.id,
            ordinal=item["ordinal"],
            name=item["name"],
            tool_name=item["tool_name"],
            tool_version=item["tool_version"],
            tool_kind=item["tool_kind"],
            input=item["input"],
        )
        for item in plan
    ]


async def _record_attempt(
    session: AsyncSession,
    *,
    run: AgentTaskRun,
    step: AgentTaskStep,
    output: dict[str, Any] | None,
    error_code: str,
    latency_ms: int,
) -> None:
    count = (
        await session.execute(
            select(func.count()).where(AgentToolAttempt.step_id == step.id)
        )
    ).scalar_one()
    session.add(
        AgentToolAttempt(
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            task_run_id=run.id,
            step_id=step.id,
            attempt_number=count + 1,
            tool_name=step.tool_name,
            tool_version=step.tool_version,
            input=step.input,
            output=output,
            error_code=error_code,
            retryable=False,
            latency_ms=latency_ms,
        )
    )


async def _fail_run(
    session: AsyncSession,
    run: AgentTaskRun,
    step: AgentTaskStep,
    code: str,
    detail: str,
) -> None:
    step.status = "failed"
    step.error_code = code
    step.error_detail = detail[:1_000]
    step.completed_at = _utcnow()
    run.status = "failed"
    run.error_code = code
    run.error_detail = detail[:1_000]
    run.completed_at = _utcnow()
    await session.commit()


async def _steps(session: AsyncSession, run_id: uuid.UUID) -> list[AgentTaskStep]:
    return list(
        (
            await session.scalars(
                select(AgentTaskStep)
                .where(AgentTaskStep.task_run_id == run_id)
                .order_by(AgentTaskStep.ordinal.asc())
            )
        ).all()
    )


async def _project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    row = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if row is None:
        raise AgentNotFoundError("project not found")
    return row


async def _conversation(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
) -> AgentConversation | None:
    if conversation_id is None:
        return None
    row = await session.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.workspace_id == workspace_id,
            AgentConversation.project_id == project_id,
        )
    )
    if row is None:
        raise AgentNotFoundError("conversation not found")
    return row


async def _parent_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    parent_run_id: uuid.UUID | None,
) -> None:
    if parent_run_id is None:
        return
    row = await session.scalar(
        select(AgentTaskRun.id).where(
            AgentTaskRun.id == parent_run_id,
            AgentTaskRun.workspace_id == workspace_id,
            AgentTaskRun.project_id == project_id,
        )
    )
    if row is None:
        raise AgentNotFoundError("parent task run not found")


async def _locked_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID,
) -> AgentTaskRun:
    row = await session.scalar(
        select(AgentTaskRun)
        .where(
            AgentTaskRun.id == run_id,
            AgentTaskRun.workspace_id == workspace_id,
            AgentTaskRun.project_id == project_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AgentNotFoundError("task run not found")
    return row


def _fingerprint(payload: AgentTaskSubmit) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _industry_pack_id(pack: dict[str, Any], project: Project) -> str:
    value = pack.get("id") or project.industry_pack_id
    return str(value or "")


async def _idempotent_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    idempotency_key: str,
    fingerprint: str,
) -> AgentTaskRun | None:
    row = await session.scalar(
        select(AgentTaskRun).where(
            AgentTaskRun.workspace_id == workspace_id,
            AgentTaskRun.idempotency_key == idempotency_key,
        )
    )
    if row is not None and row.request_fingerprint != fingerprint:
        raise AgentConflictError("idempotency key was already used for another task")
    return row


async def _flush_or_replay(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    idempotency_key: str,
    fingerprint: str,
) -> AgentTaskRun | None:
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        replay = await _idempotent_run(
            session,
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
        )
        if replay is None:
            raise AgentConflictError("idempotency conflict") from exc
        return replay
    return None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _optional_uuid_value(value: object) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    return _parse_correction_uuid(value, "correction scope identifier is invalid")


def _correction_target(target_ref: dict[str, Any]) -> tuple[str, uuid.UUID]:
    target_kind = str(target_ref.get("kind") or target_ref.get("target_kind") or "")
    target_id = target_ref.get("id") or target_ref.get("target_id")
    if target_kind not in {"entity", "assertion", "relation"} or target_id is None:
        raise AgentValidationError(_INVALID_CORRECTION_TARGET)
    return target_kind, _parse_correction_uuid(target_id, _INVALID_CORRECTION_TARGET)


def _parse_correction_uuid(value: object, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError as exc:
        raise AgentValidationError(message) from exc


async def _create_site_correction(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
    proposal: dict[str, Any],
    reason: str,
):
    try:
        return await site_service.create_correction(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            actor_user_id=user_id,
            target_kind=target_kind,
            target_id=target_id,
            value=proposal.get("corrected_value"),
            effective_scope=str(proposal.get("effective_scope") or "project"),
            effective_scope_id=_optional_uuid_value(proposal.get("effective_scope_id")),
            effective_from=None,
            effective_to=None,
            value_metadata={},
            reason=reason,
        )
    except site_service.CorrectionNotFoundError as exc:
        raise AgentNotFoundError(str(exc)) from exc
    except site_service.CorrectionValidationError as exc:
        raise AgentValidationError(str(exc)) from exc
    except site_service.CorrectionConflictError as exc:
        raise AgentConflictError(str(exc)) from exc


def _run_values(run: AgentTaskRun) -> dict[str, Any]:
    return {
        name: getattr(run, name)
        for name in (
            "id",
            "project_id",
            "conversation_id",
            "parent_run_id",
            "context_package_id",
            "task_type",
            "objective",
            "requested_outputs",
            "task_policy_version",
            "allowed_tools",
            "resource_scope",
            "industry_pack_id",
            "industry_pack_version",
            "status",
            "plan",
            "result",
            "validation",
            "decisions",
            "provider_adapter",
            "endpoint_host",
            "model",
            "capability_snapshot",
            "instruction_version",
            "skill_version",
            "usage",
            "latency_ms",
            "error_code",
            "error_detail",
            "completed_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        )
    }


def _step_values(step: AgentTaskStep) -> dict[str, Any]:
    return {
        name: getattr(step, name)
        for name in (
            "id",
            "ordinal",
            "name",
            "tool_name",
            "tool_version",
            "tool_kind",
            "status",
            "input",
            "output",
            "child_task_kind",
            "child_task_id",
            "retry_count",
            "error_code",
            "error_detail",
            "started_at",
            "completed_at",
        )
    }


def _context_values(context: TaskContextPackage) -> dict[str, Any]:
    return {
        name: getattr(context, name)
        for name in (
            "id",
            "project_id",
            "brief_id",
            "task_type",
            "manifest",
            "rendered_context",
            "omissions",
            "selection_policy_version",
            "manifest_hash",
            "char_count",
            "created_at",
        )
    }
