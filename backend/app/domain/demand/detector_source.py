"""Bounded database input assembly for pure Demand query detectors."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.demand.projection import QueryEvidenceInput, SearchDemandInput
from app.domain.demand.query_classification import classify_project_queries
from app.models.demand import QueryEvidenceRow, QueryEvidenceSnapshot


async def load_query_detector_inputs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    snapshot: QueryEvidenceSnapshot,
) -> list[QueryEvidenceInput]:
    rows = list(
        (
            await session.scalars(
                select(QueryEvidenceRow)
                .where(
                    QueryEvidenceRow.workspace_id == workspace_id,
                    QueryEvidenceRow.project_id == project_id,
                    QueryEvidenceRow.snapshot_id == snapshot.id,
                )
                .order_by(QueryEvidenceRow.date, QueryEvidenceRow.id)
            )
        ).all()
    )
    classifications = await classify_project_queries(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        queries=[row.normalized_query for row in rows],
    )
    inputs: list[QueryEvidenceInput] = []
    for row in rows:
        classification = classifications.get(row.normalized_query)
        if classification is None:
            continue
        inputs.append(
            QueryEvidenceInput(
                observed_date=row.date,
                property_ref=row.property_ref,
                normalized_query=row.normalized_query,
                resolved_page_url=row.resolved_page_url,
                resolution_outcome=row.resolution_outcome,
                classification=classification.classification,
                classifier_version=classification.classifier_version,
                classification_override_id=(
                    str(classification.override_id)
                    if classification.override_id
                    else None
                ),
                impressions=row.impressions,
                clicks=row.clicks,
                position=row.position,
                source_metric_row_id=str(row.source_metric_row_id),
                source_artifact_id=str(row.source_artifact_id),
            )
        )
    return inputs


async def classification_revision_material(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    search_inputs: list[SearchDemandInput],
) -> list[dict[str, Any]]:
    classifications = await classify_project_queries(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        queries=[row.target for row in search_inputs if row.target_kind == "query"],
    )
    return [
        {
            "query": key,
            "classification": value.classification,
            "classifier_version": value.classifier_version,
            "override_id": str(value.override_id) if value.override_id else None,
        }
        for key, value in sorted(classifications.items())
    ]
