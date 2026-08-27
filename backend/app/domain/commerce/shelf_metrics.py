"""Persist and read target-bound Commerce AI Shelf metric projections."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import (
    COMMERCE_RECOMMENDATION_MATCHER_VERSION,
    COMMERCE_RECOMMENDATION_PARSER_VERSION,
    COMMERCE_SHELF_FORMULA_VERSION,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.commerce.schemas import (
    CommerceTarget,
    RecommendationObservationResponse,
    ShelfMetricResponse,
    ShelfResponse,
)
from app.domain.commerce.service import require_project
from app.domain.commerce.shelf import _frozen_target_ids
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.commerce import (
    CommercePromptTarget,
    CommerceRecommendationObservation,
    CommerceShelfSnapshot,
)


async def finalize_commerce_shelf(session: AsyncSession, *, audit: Audit) -> None:
    if audit.audit_scope != "commerce":
        return
    frozen = dict((audit.configuration or {}).get("commerce_measurement") or {})
    target_ids = _frozen_target_ids(frozen)
    if not target_ids:
        return
    targets = list(
        (
            await session.scalars(
                select(CommercePromptTarget).where(
                    CommercePromptTarget.workspace_id == audit.workspace_id,
                    CommercePromptTarget.project_id == audit.project_id,
                    CommercePromptTarget.id.in_(target_ids),
                )
            )
        ).all()
    )
    for target in targets:
        if await _snapshot_exists(session, audit=audit, target=target):
            continue
        tasks = await _target_tasks(session, audit=audit, target=target)
        observations = await _target_observations(session, audit=audit, target=target)
        session.add(
            _build_shelf_snapshot(
                audit=audit,
                target=target,
                tasks=tasks,
                observations=observations,
            )
        )


async def _snapshot_exists(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> bool:
    return (
        await session.scalar(
            select(CommerceShelfSnapshot.id).where(
                CommerceShelfSnapshot.workspace_id == audit.workspace_id,
                CommerceShelfSnapshot.project_id == audit.project_id,
                CommerceShelfSnapshot.audit_id == audit.id,
                CommerceShelfSnapshot.target_kind == target.target_kind,
                CommerceShelfSnapshot.target_id == target.target_id,
                CommerceShelfSnapshot.formula_version == COMMERCE_SHELF_FORMULA_VERSION,
            )
        )
        is not None
    )


async def _target_tasks(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> list[AuditTask]:
    return list(
        (
            await session.scalars(
                select(AuditTask)
                .join(
                    AuditPromptSnapshot,
                    AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
                )
                .join(
                    CommercePromptTarget,
                    CommercePromptTarget.prompt_id == AuditPromptSnapshot.prompt_id,
                )
                .where(
                    AuditTask.audit_id == audit.id,
                    AuditTask.status == TASK_STATUS_SUCCEEDED,
                    CommercePromptTarget.target_kind == target.target_kind,
                    CommercePromptTarget.target_id == target.target_id,
                    CommercePromptTarget.workspace_id == audit.workspace_id,
                    CommercePromptTarget.project_id == audit.project_id,
                )
                .distinct()
            )
        ).all()
    )


async def _target_observations(
    session: AsyncSession, *, audit: Audit, target: CommercePromptTarget
) -> list[CommerceRecommendationObservation]:
    return list(
        (
            await session.scalars(
                select(CommerceRecommendationObservation).where(
                    CommerceRecommendationObservation.workspace_id
                    == audit.workspace_id,
                    CommerceRecommendationObservation.project_id == audit.project_id,
                    CommerceRecommendationObservation.audit_id == audit.id,
                    CommerceRecommendationObservation.target_kind == target.target_kind,
                    CommerceRecommendationObservation.target_id == target.target_id,
                )
            )
        ).all()
    )


def _build_shelf_snapshot(
    *,
    audit: Audit,
    target: CommercePromptTarget,
    tasks: list[AuditTask],
    observations: list[CommerceRecommendationObservation],
) -> CommerceShelfSnapshot:
    by_task: dict[uuid.UUID, list[CommerceRecommendationObservation]] = defaultdict(
        list
    )
    for observation in observations:
        by_task[observation.task_id].append(observation)
    recognized = [row for row in observations if row.classification != "unresolved"]
    owned = [row for row in recognized if row.classification == "owned"]
    ranked_owned = _ranked(owned)
    eligible_ranked = [_ranked(by_task[task.id]) for task in tasks]
    eligible_ranked = [rows for rows in eligible_ranked if rows]
    owned_tasks = _owned_task_count(tasks, by_task)
    return CommerceShelfSnapshot(
        workspace_id=audit.workspace_id,
        project_id=audit.project_id,
        audit_id=audit.id,
        target_kind=target.target_kind,
        target_id=target.target_id,
        product_visibility=owned_tasks / len(tasks) if tasks else 0.0,
        share_of_shelf=len(owned) / len(recognized) if recognized else None,
        average_shelf_position=_mean_rank(ranked_owned),
        first_position_win_rate=_first_position_rate(eligible_ranked),
        successful_execution_count=len(tasks),
        recognized_slot_count=len(recognized),
        ranked_execution_count=len(eligible_ranked),
        source_observation_ids=[str(row.id) for row in observations],
        context_snapshot={
            "target": {"kind": target.target_kind, "id": str(target.target_id)},
            "parser_version": COMMERCE_RECOMMENDATION_PARSER_VERSION,
            "matcher_version": COMMERCE_RECOMMENDATION_MATCHER_VERSION,
        },
    )


def _ranked(
    rows: list[CommerceRecommendationObservation],
) -> list[CommerceRecommendationObservation]:
    return sorted(
        (row for row in rows if row.order_observable and row.rank is not None),
        key=lambda row: row.rank or 0,
    )


def _owned_task_count(
    tasks: list[AuditTask],
    by_task: dict[uuid.UUID, list[CommerceRecommendationObservation]],
) -> int:
    return sum(
        any(row.classification == "owned" for row in by_task[task.id]) for task in tasks
    )


def _mean_rank(rows: list[CommerceRecommendationObservation]) -> float | None:
    return sum(row.rank or 0 for row in rows) / len(rows) if rows else None


def _first_position_rate(
    rows_by_task: list[list[CommerceRecommendationObservation]],
) -> float | None:
    if not rows_by_task:
        return None
    wins = sum(
        rows[0].rank == 1 and rows[0].classification == "owned" for rows in rows_by_task
    )
    return wins / len(rows_by_task)


async def get_shelf(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> ShelfResponse:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    if target_kind not in {"category", "product"}:
        return ShelfResponse()
    selected_audit_id = audit_id or await _latest_audit_id(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=target_kind,
        target_id=target_id,
    )
    target = CommerceTarget(kind=target_kind, id=target_id)
    if selected_audit_id is None:
        return ShelfResponse(target=target)
    snapshots = _scoped_snapshots(
        await _shelf_snapshots(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            target_kind=target_kind,
            target_id=target_id,
        ),
        audit_id=selected_audit_id,
        explicit=audit_id is not None,
    )
    observations = await _shelf_observations(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        target_kind=target_kind,
        target_id=target_id,
        audit_id=selected_audit_id,
    )
    return ShelfResponse(
        target=target,
        selected_audit_id=selected_audit_id,
        snapshots=[ShelfMetricResponse.model_validate(row) for row in snapshots],
        observations=[
            RecommendationObservationResponse.model_validate(row)
            for row in observations
        ],
    )


def _scoped_snapshots(
    snapshots: list[CommerceShelfSnapshot],
    *,
    audit_id: uuid.UUID,
    explicit: bool,
) -> list[CommerceShelfSnapshot]:
    """The snapshots this read may answer with, headline metrics first.

    Observations are filtered to ``selected_audit_id``, so the snapshot list
    must not contradict them: the reader takes its headline metrics from the
    first snapshot, and returning the target's newest one beside another
    audit's evidence reports two audits as one.

    An EXPLICIT ``audit_id`` asks about that audit alone, so only its snapshot
    answers -- and if it has none (a missing or not-yet-finalized audit) the
    metrics are honestly unavailable rather than borrowed from unrelated
    history. The default latest-audit read keeps the full history, because
    there the newest snapshot IS the selected audit and the history table is a
    real product surface.
    """
    if explicit:
        return [row for row in snapshots if row.audit_id == audit_id]
    return sorted(snapshots, key=lambda row: row.audit_id != audit_id)


async def _latest_audit_id(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
) -> uuid.UUID | None:
    return await session.scalar(
        select(CommerceShelfSnapshot.audit_id)
        .where(
            CommerceShelfSnapshot.workspace_id == workspace_id,
            CommerceShelfSnapshot.project_id == project_id,
            CommerceShelfSnapshot.target_kind == target_kind,
            CommerceShelfSnapshot.target_id == target_id,
        )
        .order_by(CommerceShelfSnapshot.created_at.desc())
        .limit(1)
    )


async def _shelf_snapshots(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
) -> list[CommerceShelfSnapshot]:
    rows = await session.scalars(
        select(CommerceShelfSnapshot)
        .where(
            CommerceShelfSnapshot.workspace_id == workspace_id,
            CommerceShelfSnapshot.project_id == project_id,
            CommerceShelfSnapshot.target_kind == target_kind,
            CommerceShelfSnapshot.target_id == target_id,
        )
        .order_by(CommerceShelfSnapshot.created_at.desc())
    )
    return list(rows)


async def _shelf_observations(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target_kind: str,
    target_id: uuid.UUID,
    audit_id: uuid.UUID,
) -> list[CommerceRecommendationObservation]:
    rows = await session.scalars(
        select(CommerceRecommendationObservation)
        .where(
            CommerceRecommendationObservation.workspace_id == workspace_id,
            CommerceRecommendationObservation.project_id == project_id,
            CommerceRecommendationObservation.target_kind == target_kind,
            CommerceRecommendationObservation.target_id == target_id,
            CommerceRecommendationObservation.audit_id == audit_id,
        )
        .order_by(CommerceRecommendationObservation.created_at.desc())
    )
    return list(rows)
