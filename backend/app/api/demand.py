"""Workspace-safe Demand Intelligence API over persisted projections."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import WorkspaceContext, get_db, require_active_workspace
from app.core.config.demand import (
    DEMAND_LIST_DEFAULT_LIMIT,
    DEMAND_LIST_MAX_LIMIT,
)
from app.core.config.errors import CODE_CONFLICT, CODE_VALIDATION_ERROR
from app.core.config.integrations import INTEGRATION_DATASET_TEMPLATES
from app.core.errors import ApiException
from app.core.http_errors import raise_not_found
from app.domain.analytics.enqueue import enqueue_demand_snapshot_refresh
from app.domain.demand.projection import stable_hash
from app.domain.demand.schemas import (
    DemandCapabilityView,
    DemandDatasetCapability,
    DemandRecomputeRequest,
    DemandRecomputeResponse,
    DemandSignalView,
    DemandSnapshotList,
    DemandSnapshotView,
    JourneyDefinitionView,
    JourneyDefinitionWrite,
)
from app.domain.demand.service import (
    demand_source_revision,
    get_snapshot,
    list_signals,
    list_snapshots,
)
from app.domain.projects.service import ProjectNotFoundError, get_project
from app.models.demand import JourneyDefinition, JourneyDefinitionVersion
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationPropertyMapping,
)

router = APIRouter(prefix="/projects", tags=["demand"])
_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]


async def _authorize(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    try:
        await get_project(session, workspace_id=workspace_id, project_id=project_id)
    except ProjectNotFoundError as exc:
        raise_not_found("Project", cause=exc)


def _signal_view(row) -> DemandSignalView:
    return DemandSignalView.model_validate(row)


async def _snapshot_view(
    session: AsyncSession, row, *, include_signals: bool
) -> DemandSnapshotView:
    signals = (
        await list_signals(
            session,
            workspace_id=row.workspace_id,
            project_id=row.project_id,
            snapshot_id=row.id,
        )
        if include_signals
        else []
    )
    return DemandSnapshotView(
        id=row.id,
        project_id=row.project_id,
        window_start=row.window_start,
        window_end=row.window_end,
        source_hash=row.source_hash,
        site_snapshot_id=row.site_snapshot_id,
        prior_snapshot_id=row.prior_snapshot_id,
        source_artifact_ids=list(row.source_artifact_ids or []),
        source_metric_row_ids=list(row.source_metric_row_ids or []),
        source_audit_ids=list(row.source_audit_ids or []),
        journey_version_ids=list(row.journey_version_ids or []),
        coverage=dict(row.coverage or {}),
        summary=dict(row.summary or {}),
        comparison=row.comparison,
        formula_version=row.formula_version,
        analyzer_version=row.analyzer_version,
        created_at=row.created_at,
        signals=[_signal_view(signal) for signal in signals],
    )


async def _latest_artifacts(
    session: AsyncSession, *, workspace_id: uuid.UUID, connection_id: uuid.UUID
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(
                IntegrationImportArtifact.id,
                IntegrationImportArtifact.dataset,
                IntegrationImportArtifact.query_snapshot,
            )
            .where(
                IntegrationImportArtifact.workspace_id == workspace_id,
                IntegrationImportArtifact.connection_id == connection_id,
            )
            .distinct(IntegrationImportArtifact.dataset)
            .order_by(
                IntegrationImportArtifact.dataset,
                IntegrationImportArtifact.created_at.desc(),
                IntegrationImportArtifact.id.desc(),
            )
        )
    ).all()
    return {row.dataset: row for row in rows}


def _capability_items(
    mapping: IntegrationPropertyMapping,
    connection: IntegrationConnection | None,
    latest: dict[str, Any],
) -> list[DemandDatasetCapability]:
    items: list[DemandDatasetCapability] = []
    capabilities = connection.dataset_capabilities if connection else {}
    capabilities = capabilities or {}
    for template in INTEGRATION_DATASET_TEMPLATES.values():
        if template.provider != mapping.provider:
            continue
        artifact = latest.get(template.dataset)
        snapshot = artifact.query_snapshot or {} if artifact else {}
        capability = capabilities.get(template.dataset, {})
        capability = capability if isinstance(capability, dict) else {}
        provider_metadata = _provider_metadata(snapshot, capability)
        state = (
            "observed" if artifact else str(capability.get("status") or "unavailable")
        )
        items.append(
            DemandDatasetCapability(
                provider=mapping.provider,
                dataset=template.dataset,
                state=state,
                latest_artifact_id=artifact.id if artifact else None,
                coverage=dict(snapshot.get("coverage") or {}),
                provider_metadata=provider_metadata,
            )
        )
    return items


def _provider_metadata(
    snapshot: dict[str, Any], capability: dict[str, Any]
) -> dict[str, Any]:
    metadata = dict(snapshot.get("providerMetadata") or {})
    if capability:
        metadata["capability"] = capability
    return metadata


@router.get("/{project_id}/demand/snapshots")
async def snapshots(
    project_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    limit: Annotated[int, Query(ge=1, le=DEMAND_LIST_MAX_LIMIT)] = (
        DEMAND_LIST_DEFAULT_LIMIT
    ),
) -> DemandSnapshotList:
    await _authorize(session, ctx.workspace_id, project_id)
    rows = await list_snapshots(
        session, workspace_id=ctx.workspace_id, project_id=project_id, limit=limit
    )
    return DemandSnapshotList(
        items=[
            await _snapshot_view(session, row, include_signals=False) for row in rows
        ]
    )


@router.get("/{project_id}/demand/capabilities")
async def capabilities(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> DemandCapabilityView:
    """Persisted dataset availability; never probes Google from a read."""
    await _authorize(session, ctx.workspace_id, project_id)
    mappings = list(
        (
            await session.scalars(
                select(IntegrationPropertyMapping).where(
                    IntegrationPropertyMapping.workspace_id == ctx.workspace_id,
                    IntegrationPropertyMapping.project_id == project_id,
                    IntegrationPropertyMapping.status == "active",
                )
            )
        ).all()
    )
    items: list[DemandDatasetCapability] = []
    for mapping in mappings:
        connection = await session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.workspace_id == ctx.workspace_id,
                IntegrationConnection.id == mapping.connection_id,
            )
        )
        latest = await _latest_artifacts(
            session,
            workspace_id=ctx.workspace_id,
            connection_id=mapping.connection_id,
        )
        items.extend(_capability_items(mapping, connection, latest))
    items.sort(key=lambda item: (item.provider, item.dataset))
    return DemandCapabilityView(datasets=items)


@router.get("/{project_id}/demand/snapshots/{snapshot_id}")
async def snapshot_detail(
    project_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> DemandSnapshotView:
    await _authorize(session, ctx.workspace_id, project_id)
    row = await get_snapshot(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        snapshot_id=snapshot_id,
    )
    if row is None:
        raise_not_found("Demand snapshot")
    return await _snapshot_view(session, row, include_signals=True)


@router.post(
    "/{project_id}/demand/recompute",
    status_code=status.HTTP_202_ACCEPTED,
)
async def recompute(
    project_id: uuid.UUID,
    payload: DemandRecomputeRequest,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> DemandRecomputeResponse:
    await _authorize(session, ctx.workspace_id, project_id)
    revision = await demand_source_revision(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
    )
    task_id = await enqueue_demand_snapshot_refresh(
        session,
        workspace_id=ctx.workspace_id,
        project_id=project_id,
        window_start=payload.window_start,
        window_end=payload.window_end,
        source_revision=revision,
    )
    await session.commit()
    return DemandRecomputeResponse(
        task_id=task_id, status="queued" if task_id else "already_queued"
    )


async def _journey_view(
    session: AsyncSession, row: JourneyDefinition
) -> JourneyDefinitionView:
    version = await session.scalar(
        select(JourneyDefinitionVersion).where(
            JourneyDefinitionVersion.workspace_id == row.workspace_id,
            JourneyDefinitionVersion.project_id == row.project_id,
            JourneyDefinitionVersion.journey_id == row.id,
            JourneyDefinitionVersion.version == row.current_version,
        )
    )
    if version is None:
        raise RuntimeError("journey current version is missing")
    return JourneyDefinitionView(
        id=row.id,
        project_id=row.project_id,
        slug=row.slug,
        name=row.name,
        status=row.status,
        current_version=row.current_version,
        definition=version.definition,
        source_kind=version.source_kind,
        source_version=version.source_version,
        version_id=version.id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/{project_id}/demand/journeys")
async def journeys(
    project_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[JourneyDefinitionView]:
    await _authorize(session, ctx.workspace_id, project_id)
    rows = list(
        (
            await session.scalars(
                select(JourneyDefinition)
                .where(
                    JourneyDefinition.workspace_id == ctx.workspace_id,
                    JourneyDefinition.project_id == project_id,
                )
                .order_by(JourneyDefinition.slug)
            )
        ).all()
    )
    return [await _journey_view(session, row) for row in rows]


@router.put("/{project_id}/demand/journeys/{slug}")
async def put_journey(
    project_id: uuid.UUID,
    slug: str,
    payload: JourneyDefinitionWrite,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> JourneyDefinitionView:
    await _authorize(session, ctx.workspace_id, project_id)
    if slug != payload.slug:
        raise ApiException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            CODE_VALIDATION_ERROR,
            "path slug must match payload slug",
        )
    row = await session.scalar(
        select(JourneyDefinition)
        .where(
            JourneyDefinition.workspace_id == ctx.workspace_id,
            JourneyDefinition.project_id == project_id,
            JourneyDefinition.slug == slug,
        )
        .with_for_update()
    )
    created = False
    if row is None:
        candidate_id = uuid.uuid4()
        inserted_id = await session.scalar(
            pg_insert(JourneyDefinition)
            .values(
                id=candidate_id,
                workspace_id=ctx.workspace_id,
                project_id=project_id,
                slug=slug,
                name=payload.name,
                status=payload.status,
                current_version=1,
            )
            .on_conflict_do_nothing(index_elements=["project_id", "slug"])
            .returning(JourneyDefinition.id)
        )
        if inserted_id is not None:
            row = await session.get(JourneyDefinition, inserted_id)
            created = True
        else:
            row = await session.scalar(
                select(JourneyDefinition)
                .where(
                    JourneyDefinition.workspace_id == ctx.workspace_id,
                    JourneyDefinition.project_id == project_id,
                    JourneyDefinition.slug == slug,
                )
                .with_for_update()
            )
            if row is None:
                raise ApiException(
                    status.HTTP_409_CONFLICT,
                    CODE_CONFLICT,
                    "Journey creation conflicted; retry request",
                )
    if row is None:
        raise ApiException(
            status.HTTP_409_CONFLICT,
            CODE_CONFLICT,
            "Journey creation did not resolve",
        )
    if created:
        version_number = 1
    else:
        current = await session.scalar(
            select(JourneyDefinitionVersion).where(
                JourneyDefinitionVersion.journey_id == row.id,
                JourneyDefinitionVersion.version == row.current_version,
            )
        )
        content_hash = stable_hash(
            {
                "definition": payload.definition,
                "source_kind": payload.source_kind,
                "source_version": payload.source_version,
            }
        )
        current_hash = (
            stable_hash(
                {
                    "definition": current.definition,
                    "source_kind": current.source_kind,
                    "source_version": current.source_version,
                }
            )
            if current
            else ""
        )
        row.name = payload.name
        row.status = payload.status
        if content_hash == current_hash:
            await session.commit()
            return await _journey_view(session, row)
        version_number = row.current_version + 1
        row.current_version = version_number
    session.add(
        JourneyDefinitionVersion(
            workspace_id=ctx.workspace_id,
            project_id=project_id,
            journey_id=row.id,
            version=version_number,
            definition=payload.definition,
            source_kind=payload.source_kind,
            source_version=payload.source_version,
            created_by_user_id=ctx.user.id,
        )
    )
    await session.commit()
    await session.refresh(row)
    return await _journey_view(session, row)
