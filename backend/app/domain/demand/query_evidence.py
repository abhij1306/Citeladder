"""Persisted bounded query↔page↔date evidence projection and reads."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.demand import (
    PAGE_EQUIVALENCE_RESOLVER_VERSION,
    QUERY_EVIDENCE_ANALYZER_VERSION,
    QUERY_EVIDENCE_MAX_ARTIFACTS,
    QUERY_EVIDENCE_MAX_ROWS,
    QUERY_EVIDENCE_STATE_AVAILABLE,
    QUERY_EVIDENCE_STATE_OBSERVED_ZERO,
    QUERY_EVIDENCE_STATE_UNAVAILABLE,
)
from app.core.config.integrations_datasets import (
    DATASET_GSC_QUERY_PAGE_DAILY,
    unpack_dimension_key,
)
from app.domain.demand.page_equivalence import PageResolution, resolve_owned_pages
from app.domain.demand.projection import stable_hash
from app.domain.demand.query_classification import normalize_query
from app.domain.demand.query_evidence_reads import latest_query_evidence_snapshot
from app.domain.integrations.sync import integrity_constraint_name
from app.domain.traffic.projection import TrafficMetricRowInput, select_latest_rows
from app.models.demand import QueryEvidenceRow, QueryEvidenceSnapshot
from app.models.integrations import (
    IntegrationImportArtifact,
    IntegrationMetricRow,
    IntegrationPropertyMapping,
)


@dataclass(frozen=True)
class _SnapshotInputs:
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    window_start: date
    window_end: date
    source_hash: str
    prior: QueryEvidenceSnapshot | None
    source_rows: list[TrafficMetricRowInput]
    material: list[dict[str, Any]]
    selected: list[dict[str, Any]]
    artifacts: list[IntegrationImportArtifact]


def _metric_number(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _to_traffic_input(row: IntegrationMetricRow) -> TrafficMetricRowInput:
    return TrafficMetricRowInput(
        id=row.id,
        property_ref=row.property_ref,
        provider=row.provider,
        dataset=row.dataset,
        date=row.date,
        dimension_key=row.dimension_key,
        metrics=row.metrics,
        source_artifact_id=row.source_artifact_id,
        resync_seq=row.resync_seq,
        importer_version=row.importer_version,
    )


async def _source_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> list[TrafficMetricRowInput]:
    identity = (
        IntegrationMetricRow.property_ref,
        IntegrationMetricRow.provider,
        IntegrationMetricRow.dataset,
        IntegrationMetricRow.date,
        IntegrationMetricRow.dimension_key,
    )
    ranked = (
        select(
            IntegrationMetricRow.id.label("row_id"),
            func.row_number()
            .over(
                partition_by=identity,
                order_by=(
                    IntegrationMetricRow.resync_seq.desc(),
                    IntegrationMetricRow.id.desc(),
                ),
            )
            .label("revision_rank"),
        )
        .where(IntegrationMetricRow.workspace_id == workspace_id)
        .where(IntegrationMetricRow.project_id == project_id)
        .where(IntegrationMetricRow.dataset == DATASET_GSC_QUERY_PAGE_DAILY)
        .where(IntegrationMetricRow.date >= window_start)
        .where(IntegrationMetricRow.date <= window_end)
        .subquery()
    )
    rows = list(
        (
            await session.scalars(
                select(IntegrationMetricRow)
                .join(ranked, ranked.c.row_id == IntegrationMetricRow.id)
                .where(ranked.c.revision_rank == 1)
                .order_by(*identity, IntegrationMetricRow.id)
                .limit(QUERY_EVIDENCE_MAX_ROWS + 1)
            )
        ).all()
    )
    return select_latest_rows([_to_traffic_input(row) for row in rows])


def _artifact_matches_window(
    artifact: IntegrationImportArtifact, window_start: date, window_end: date
) -> bool:
    query = artifact.query_snapshot or {}
    start = str(query.get("start_date") or query.get("startDate") or "")
    end = str(query.get("end_date") or query.get("endDate") or "")
    return start == window_start.isoformat() and end == window_end.isoformat()


async def _zero_row_artifacts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> list[IntegrationImportArtifact]:
    artifacts = list(
        (
            await session.scalars(
                select(IntegrationImportArtifact)
                .join(
                    IntegrationPropertyMapping,
                    and_(
                        IntegrationPropertyMapping.workspace_id
                        == IntegrationImportArtifact.workspace_id,
                        IntegrationPropertyMapping.connection_id
                        == IntegrationImportArtifact.connection_id,
                    ),
                )
                .where(IntegrationImportArtifact.workspace_id == workspace_id)
                .where(IntegrationPropertyMapping.project_id == project_id)
                .where(
                    IntegrationImportArtifact.dataset == DATASET_GSC_QUERY_PAGE_DAILY
                )
                .where(
                    or_(
                        and_(
                            IntegrationImportArtifact.query_snapshot[
                                "start_date"
                            ].as_string()
                            == window_start.isoformat(),
                            IntegrationImportArtifact.query_snapshot[
                                "end_date"
                            ].as_string()
                            == window_end.isoformat(),
                        ),
                        and_(
                            IntegrationImportArtifact.query_snapshot[
                                "startDate"
                            ].as_string()
                            == window_start.isoformat(),
                            IntegrationImportArtifact.query_snapshot[
                                "endDate"
                            ].as_string()
                            == window_end.isoformat(),
                        ),
                    )
                )
                .order_by(
                    IntegrationImportArtifact.fetched_at.desc(),
                    IntegrationImportArtifact.id.desc(),
                )
                .limit(QUERY_EVIDENCE_MAX_ARTIFACTS)
            )
        ).all()
    )
    return [
        artifact
        for artifact in artifacts
        if _artifact_matches_window(artifact, window_start, window_end)
    ]


def _row_material(row: TrafficMetricRowInput) -> dict[str, Any] | None:
    dimensions = unpack_dimension_key(row.dataset, row.dimension_key)
    if dimensions is None or len(dimensions) != 3:
        return None
    query, page, _provider_date = dimensions
    normalized = normalize_query(query)
    metrics = dict(row.metrics or {})
    impressions = _metric_number(metrics, "impressions")
    clicks = _metric_number(metrics, "clicks")
    if not normalized or not page or impressions is None or clicks is None:
        return None
    return {
        "source": row,
        "normalized_query": normalized,
        "observed_page_url": page,
        "impressions": int(impressions),
        "clicks": int(clicks),
        "ctr": _metric_number(metrics, "ctr"),
        "position": _metric_number(metrics, "position"),
    }


def _resolved_url(resolution: PageResolution) -> str:
    if resolution.site_url_id is None:
        return ""
    return next(
        (
            item.normalized_url
            for item in resolution.candidates
            if item.site_url_id == resolution.site_url_id
        ),
        "",
    )


def _candidate_payload(resolution: PageResolution) -> list[dict[str, Any]]:
    return [
        {
            "site_url_id": str(item.site_url_id),
            "normalized_url": item.normalized_url,
            "evidence": list(item.evidence),
        }
        for item in resolution.candidates
    ]


def _source_hash(
    *,
    window_start: date,
    window_end: date,
    material: list[dict[str, Any]],
    artifacts: list[IntegrationImportArtifact],
) -> str:
    return stable_hash(
        {
            "window": [window_start.isoformat(), window_end.isoformat()],
            "rows": [
                [str(item["source"].id), item["source"].resync_seq] for item in material
            ],
            "zero_artifacts": [[str(item.id), item.payload_hash] for item in artifacts],
            "analyzer_version": QUERY_EVIDENCE_ANALYZER_VERSION,
            "resolver_version": PAGE_EQUIVALENCE_RESOLVER_VERSION,
        }
    )


async def build_query_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> QueryEvidenceSnapshot:
    source_rows = await _source_rows(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    material = [item for row in source_rows if (item := _row_material(row))]
    selected = material[:QUERY_EVIDENCE_MAX_ROWS]
    artifacts = await _zero_row_artifacts(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    source_hash = _source_hash(
        window_start=window_start,
        window_end=window_end,
        material=selected,
        artifacts=artifacts,
    )
    existing = await session.scalar(
        select(QueryEvidenceSnapshot).where(
            QueryEvidenceSnapshot.workspace_id == workspace_id,
            QueryEvidenceSnapshot.project_id == project_id,
            QueryEvidenceSnapshot.window_start == window_start,
            QueryEvidenceSnapshot.window_end == window_end,
            QueryEvidenceSnapshot.source_hash == source_hash,
            QueryEvidenceSnapshot.analyzer_version == QUERY_EVIDENCE_ANALYZER_VERSION,
        )
    )
    if existing is not None:
        return existing
    prior = await latest_query_evidence_snapshot(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    resolutions = await resolve_owned_pages(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        urls=[str(item["observed_page_url"]) for item in selected],
    )
    snapshot = _snapshot_record(
        _SnapshotInputs(
            workspace_id=workspace_id,
            project_id=project_id,
            window_start=window_start,
            window_end=window_end,
            source_hash=source_hash,
            prior=prior,
            source_rows=source_rows,
            material=material,
            selected=selected,
            artifacts=artifacts,
        )
    )
    persisted = await _insert_snapshot_or_get_existing(session, snapshot)
    if persisted is not snapshot:
        return persisted
    _add_evidence_rows(session, snapshot, selected, resolutions)
    await session.flush()
    return snapshot


async def _insert_snapshot_or_get_existing(
    session: AsyncSession, snapshot: QueryEvidenceSnapshot
) -> QueryEvidenceSnapshot:
    try:
        async with session.begin_nested():
            session.add(snapshot)
            await session.flush()
    except IntegrityError as exc:
        if integrity_constraint_name(exc) != "uq_query_evidence_snapshot_identity":
            raise
        concurrent = await session.scalar(
            select(QueryEvidenceSnapshot).where(
                QueryEvidenceSnapshot.workspace_id == snapshot.workspace_id,
                QueryEvidenceSnapshot.project_id == snapshot.project_id,
                QueryEvidenceSnapshot.window_start == snapshot.window_start,
                QueryEvidenceSnapshot.window_end == snapshot.window_end,
                QueryEvidenceSnapshot.source_hash == snapshot.source_hash,
                QueryEvidenceSnapshot.analyzer_version == snapshot.analyzer_version,
            )
        )
        if concurrent is None:
            raise
        return concurrent
    return snapshot


def _snapshot_state(
    selected: list[dict[str, Any]], artifacts: list[IntegrationImportArtifact]
) -> str:
    if selected:
        return QUERY_EVIDENCE_STATE_AVAILABLE
    if artifacts and all(item.row_count == 0 for item in artifacts):
        return QUERY_EVIDENCE_STATE_OBSERVED_ZERO
    return QUERY_EVIDENCE_STATE_UNAVAILABLE


def _projection_limitations(
    source_rows: list[TrafficMetricRowInput],
    material: list[dict[str, Any]],
    selected: list[dict[str, Any]],
) -> list[str]:
    limitations: list[str] = []
    if len(source_rows) > QUERY_EVIDENCE_MAX_ROWS or len(material) > len(selected):
        limitations.append("query_evidence_row_limit")
    if len(material) != len(source_rows):
        limitations.append("malformed_source_rows_excluded")
    return limitations


def _snapshot_record(inputs: _SnapshotInputs) -> QueryEvidenceSnapshot:
    return QueryEvidenceSnapshot(
        workspace_id=inputs.workspace_id,
        project_id=inputs.project_id,
        window_start=inputs.window_start,
        window_end=inputs.window_end,
        source_hash=inputs.source_hash,
        supersedes_snapshot_id=inputs.prior.id if inputs.prior else None,
        state=_snapshot_state(inputs.selected, inputs.artifacts),
        source_metric_row_ids=[str(item["source"].id) for item in inputs.selected],
        source_artifact_ids=sorted(
            {str(item["source"].source_artifact_id) for item in inputs.selected}
            | {str(item.id) for item in inputs.artifacts}
        ),
        coverage={
            "source_row_count": len(inputs.source_rows),
            "usable_row_count": len(inputs.material),
            "projected_row_count": len(inputs.selected),
            "row_limit": QUERY_EVIDENCE_MAX_ROWS,
            "truncated": len(inputs.source_rows) > QUERY_EVIDENCE_MAX_ROWS
            or len(inputs.material) > len(inputs.selected),
        },
        limitations=_projection_limitations(
            inputs.source_rows, inputs.material, inputs.selected
        ),
        analyzer_version=QUERY_EVIDENCE_ANALYZER_VERSION,
        resolver_version=PAGE_EQUIVALENCE_RESOLVER_VERSION,
    )


def _add_evidence_rows(
    session: AsyncSession,
    snapshot: QueryEvidenceSnapshot,
    selected: list[dict[str, Any]],
    resolutions: dict[str, PageResolution],
) -> None:
    session.add_all(
        [
            _evidence_row(snapshot, item, resolutions[str(item["observed_page_url"])])
            for item in selected
        ]
    )


async def query_evidence_source_revision(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> str:
    source_rows = await _source_rows(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    material = [item for row in source_rows if (item := _row_material(row))][
        :QUERY_EVIDENCE_MAX_ROWS
    ]
    artifacts = await _zero_row_artifacts(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
    )
    return _source_hash(
        window_start=window_start,
        window_end=window_end,
        material=material,
        artifacts=artifacts,
    )[:24]


def _evidence_row(
    snapshot: QueryEvidenceSnapshot,
    item: dict[str, Any],
    resolution: PageResolution,
) -> QueryEvidenceRow:
    source: TrafficMetricRowInput = item["source"]
    return QueryEvidenceRow(
        snapshot_id=snapshot.id,
        workspace_id=snapshot.workspace_id,
        project_id=snapshot.project_id,
        date=source.date,
        normalized_query=item["normalized_query"],
        observed_page_url=item["observed_page_url"],
        site_url_id=resolution.site_url_id,
        resolved_page_url=_resolved_url(resolution),
        resolution_outcome=resolution.outcome,
        resolution_candidates=_candidate_payload(resolution),
        property_ref=source.property_ref,
        impressions=item["impressions"],
        clicks=item["clicks"],
        ctr=item["ctr"],
        position=item["position"],
        source_metric_row_id=source.id,
        source_artifact_id=source.source_artifact_id,
        importer_version=source.importer_version,
        resolver_version=resolution.resolver_version,
    )
