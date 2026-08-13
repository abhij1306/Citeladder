"""Workspace-scoped discovery, candidate review, and catalog comparisons."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import (
    COMMERCE_ACQUISITION_STATE_QUEUE_READY,
    COMMERCE_CANDIDATE_KIND_COMPETITOR,
    COMMERCE_CANDIDATE_KIND_OWN,
    COMMERCE_DISCOVERY_INPUT_UPLOAD,
    COMMERCE_DISCOVERY_RUN_STATUS_COMPLETED,
    COMMERCE_DISCOVERY_RUN_STATUS_FAILED,
    COMMERCE_DISCOVERY_RUN_STATUS_PARTIALLY_COMPLETED,
    COMMERCE_DISCOVERY_RUN_STATUS_RUNNING,
    COMMERCE_DISCOVERY_VERSION,
    COMMERCE_EVIDENCE_KIND_UPLOAD,
    COMMERCE_MATCHER_VERSION,
    commerce_intelligence_settings,
)
from app.core.config.task_queue import (
    ERROR_MAX_ATTEMPTS,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.commerce.intelligence_schemas import (
    CommerceCandidateInput,
    CommerceCandidateResponse,
    CommerceDiscoveryCreateRequest,
    CommerceDiscoveryPreviewRequest,
    CommerceDiscoveryPreviewResponse,
    CommerceDiscoveryRunResponse,
    CommerceMatchDecision,
    CommercePreviewRowError,
)
from app.domain.commerce.matching import match_candidate
from app.models.commerce import (
    CommerceDiscoveryArtifact,
    CommerceDiscoveryCandidate,
    CommerceDiscoveryRun,
    CommerceDiscoveryTask,
)
from app.models.product import CompetitorProduct, Product
from app.models.project import Project


class CommerceDiscoveryNotFoundError(LookupError):
    pass


class CommerceReviewRequiredError(ValueError):
    pass


class CommerceConflictError(ValueError):
    pass


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _candidate_identity(row: CommerceCandidateInput) -> dict[str, Any]:
    return row.model_dump(mode="json")


def _csv_candidate(raw: dict[str | None, str | None]) -> CommerceCandidateInput:
    """Parse the two structured CSV columns without accepting arbitrary JSON."""
    values: dict[str, Any] = {
        str(key): value for key, value in raw.items() if key is not None
    }
    for key, fallback in (("aliases", []), ("variants", []), ("attributes", {})):
        value = values.get(key)
        if value not in (None, ""):
            try:
                values[key] = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{key} must contain JSON") from exc
        else:
            values[key] = fallback
    return CommerceCandidateInput.model_validate(values)


def _safe_source_key(value: str) -> str:
    return _digest({"source": value})


async def reconcile_discovery_run(
    session: AsyncSession, *, run_id: uuid.UUID
) -> CommerceDiscoveryRun | None:
    """Project one discovery run's terminal state from its persisted tasks.

    The worker calls this after every terminal acknowledgement and after a
    lease sweep.  It deliberately reads queue rows only: no acquisition or
    matching is repeated while presenting a run's status.
    """
    run = await session.get(CommerceDiscoveryRun, run_id, with_for_update=True)
    if run is None:
        return None
    statuses = list(
        (
            await session.scalars(
                select(CommerceDiscoveryTask.status).where(
                    CommerceDiscoveryTask.run_id == run.id
                )
            )
        ).all()
    )
    if any(status not in TASK_TERMINAL_STATUSES for status in statuses):
        run.status = COMMERCE_DISCOVERY_RUN_STATUS_RUNNING
        return run

    succeeded = sum(status == TASK_STATUS_SUCCEEDED for status in statuses)
    failed = sum(
        status in {TASK_STATUS_FAILED, TASK_STATUS_CANCELLED} for status in statuses
    )
    if succeeded and not failed:
        run.status = COMMERCE_DISCOVERY_RUN_STATUS_COMPLETED
    elif succeeded:
        run.status = COMMERCE_DISCOVERY_RUN_STATUS_PARTIALLY_COMPLETED
    else:
        run.status = COMMERCE_DISCOVERY_RUN_STATUS_FAILED
    if run.completed_at is None:
        run.completed_at = _utcnow()
    return run


async def mark_discovery_run_running(
    session: AsyncSession, *, run_id: uuid.UUID
) -> bool:
    """Move a queued run to running before its worker performs I/O."""
    run = await session.get(CommerceDiscoveryRun, run_id, with_for_update=True)
    if run is None or run.completed_at is not None:
        return False
    run.status = COMMERCE_DISCOVERY_RUN_STATUS_RUNNING
    return True


async def finalize_discovery_success(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    owner: str,
    evidence_kind: str,
    source_url: str,
    content_hash: str,
    extracted: dict[str, Any],
    acquisition: dict[str, Any],
    identity: dict[str, Any],
    extraction_confidence: float,
    candidate_kind: str = COMMERCE_CANDIDATE_KIND_OWN,
    competitor_id: uuid.UUID | None = None,
) -> uuid.UUID | None:
    """Atomically write acquired evidence, its candidate, and queue success.

    This is the sole URL-acquisition writer.  The ownership/state re-check
    makes a result from an expired or cancelled lease disposable, while the
    unique artifact/candidate constraints make a durable retry idempotent.
    """
    task = await session.get(
        CommerceDiscoveryTask, task_id, with_for_update=True, populate_existing=True
    )
    if task is None or task.lease_owner != owner or task.status != TASK_STATUS_RUNNING:
        return None
    run = await session.get(
        CommerceDiscoveryRun, task.run_id, with_for_update=True, populate_existing=True
    )
    if (
        run is None
        or run.workspace_id != task.workspace_id
        or run.project_id != task.project_id
    ):
        return None
    existing = await session.scalar(
        select(CommerceDiscoveryArtifact).where(
            CommerceDiscoveryArtifact.task_id == task.id
        )
    )
    if existing is not None:
        # Upload evidence was written before enqueueing.  A URL task with one
        # is a legacy placeholder and must not be mutated into fetched data.
        return existing.id if task.result_artifact_id == existing.id else None

    artifact = CommerceDiscoveryArtifact(
        task_id=task.id,
        run_id=task.run_id,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        evidence_kind=evidence_kind,
        source_url=source_url,
        content_hash=content_hash,
        extracted=extracted,
        acquisition=acquisition,
        discovery_version=run.discovery_version,
    )
    session.add(artifact)
    await session.flush()

    candidate_count = await session.scalar(
        select(func.count())
        .select_from(CommerceDiscoveryCandidate)
        .where(CommerceDiscoveryCandidate.run_id == task.run_id)
    )
    if int(candidate_count or 0) < int(
        (run.configuration or {}).get(
            "max_candidates",
            commerce_intelligence_settings.discovery_max_candidates_per_run,
        )
    ):
        candidate_hash = _digest(identity)
        await session.execute(
            pg_insert(CommerceDiscoveryCandidate)
            .values(
                id=uuid.uuid4(),
                run_id=task.run_id,
                task_id=task.id,
                artifact_id=artifact.id,
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                candidate_kind=candidate_kind,
                competitor_id=competitor_id,
                candidate_hash=candidate_hash,
                identity=identity,
                extraction_confidence=extraction_confidence,
            )
            .on_conflict_do_nothing(constraint="uq_commerce_candidate_run_hash")
        )
    task.attempt_count += 1
    task.result_artifact_id = artifact.id
    task.status = TASK_STATUS_SUCCEEDED
    task.lease_owner = None
    task.lease_expires_at = None
    task.completed_at = _utcnow()
    task.error_code = ""
    task.error_detail = ""
    await reconcile_discovery_run(session, run_id=task.run_id)
    return artifact.id


async def finalize_discovery_failure(
    session: AsyncSession,
    *,
    task_id: uuid.UUID,
    owner: str,
    error_code: str,
    error_detail: str,
    retryable: bool,
    retry_after_seconds: float | None = None,
    consumed_network_attempt: bool,
) -> bool:
    """Atomically account for a failed discovery attempt and reconcile its run."""
    task = await session.get(
        CommerceDiscoveryTask, task_id, with_for_update=True, populate_existing=True
    )
    if task is None or task.lease_owner != owner or task.status != TASK_STATUS_RUNNING:
        return False
    if consumed_network_attempt:
        task.attempt_count += 1
    exhausted = task.attempt_count >= task.max_attempts
    task.error_code = error_code
    task.error_detail = error_detail[:2000]
    task.lease_owner = None
    task.lease_expires_at = None
    if retryable and not exhausted:
        task.status = TASK_STATUS_RETRY_WAIT
        task.available_at = _utcnow() + timedelta(
            seconds=commerce_intelligence_settings.retry_delay(
                task.attempt_count, retry_after_seconds
            )
        )
    else:
        task.status = TASK_STATUS_FAILED
        task.completed_at = _utcnow()
        if exhausted and retryable:
            task.error_code = ERROR_MAX_ATTEMPTS
    await reconcile_discovery_run(session, run_id=task.run_id)
    return True


async def _project(
    session: AsyncSession, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    project = await session.scalar(
        select(Project).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if project is None:
        raise CommerceDiscoveryNotFoundError("Project not found")
    return project


def preview_discovery(
    request: CommerceDiscoveryPreviewRequest,
) -> CommerceDiscoveryPreviewResponse:
    """Bound and normalize client rows before any persistence or transport."""
    errors: list[CommercePreviewRowError] = []
    rows = list(request.rows or [])
    if request.csv_text is not None:
        reader = csv.DictReader(io.StringIO(request.csv_text))
        if not reader.fieldnames:
            return CommerceDiscoveryPreviewResponse(
                errors=[
                    CommercePreviewRowError(
                        row=1, field="csv", message="CSV headers are required"
                    )
                ]
            )
        for index, raw in enumerate(reader, start=1):
            try:
                rows.append(_csv_candidate(raw))
            except ValueError as exc:
                errors.append(
                    CommercePreviewRowError(row=index, field="row", message=str(exc))
                )
    accepted: list[CommerceCandidateInput] = []
    duplicates: list[int] = []
    seen: set[str] = set()
    max_rows = commerce_intelligence_settings.discovery_preview_max_rows
    truncated = len(rows) > max_rows
    for index, row in enumerate(rows[:max_rows], start=1):
        if (
            row.candidate_kind == COMMERCE_CANDIDATE_KIND_COMPETITOR
            and row.competitor_id is None
        ):
            errors.append(
                CommercePreviewRowError(
                    row=index,
                    field="competitor_id",
                    message="competitor candidates require competitor_id",
                )
            )
            continue
        fingerprint = _digest(_candidate_identity(row))
        if fingerprint in seen:
            duplicates.append(index)
            continue
        seen.add(fingerprint)
        accepted.append(row)
    return CommerceDiscoveryPreviewResponse(
        accepted=accepted, duplicates=duplicates, errors=errors, truncated=truncated
    )


def _product_entry(product: Product) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "sku": product.sku,
        "aliases": list(product.aliases or []),
        "variants": list(product.variants or []),
        "price": float(product.price) if product.price is not None else None,
        "currency": product.currency,
        "url": product.url,
        "attributes": dict(product.attributes or {}),
        "availability": str((product.attributes or {}).get("availability", "")),
    }


def _competitor_entry(product: CompetitorProduct) -> dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "aliases": list(product.aliases or []),
        "variants": list(product.variants or []),
        "price": float(product.price) if product.price is not None else None,
        "currency": product.currency,
        "url": product.url,
        "attributes": dict(product.attributes or {}),
        "availability": product.availability,
    }


async def _candidate_matches(
    session: AsyncSession, candidate: CommerceDiscoveryCandidate
) -> list[CommerceMatchDecision]:
    if candidate.candidate_kind == COMMERCE_CANDIDATE_KIND_COMPETITOR:
        competitor_targets = list(
            (
                await session.scalars(
                    select(CompetitorProduct)
                    .join(Project, CompetitorProduct.project_id == Project.id)
                    .where(
                        CompetitorProduct.project_id == candidate.project_id,
                        Project.workspace_id == candidate.workspace_id,
                    )
                )
            ).all()
        )
        target_kind = "competitor_product"
        entries = [_competitor_entry(item) for item in competitor_targets]
    else:
        product_targets = list(
            (
                await session.scalars(
                    select(Product)
                    .join(Project, Product.project_id == Project.id)
                    .where(
                        Product.project_id == candidate.project_id,
                        Project.workspace_id == candidate.workspace_id,
                    )
                )
            ).all()
        )
        target_kind = "product"
        entries = [_product_entry(item) for item in product_targets]
    return [
        CommerceMatchDecision(
            target_id=result.target_id,
            target_kind=target_kind,
            confidence=result.confidence,
            reasons=list(result.reasons),
            review_required=result.review_required,
        )
        for result in match_candidate(candidate.identity, entries)
    ]


async def _candidate_response(
    session: AsyncSession, candidate: CommerceDiscoveryCandidate
) -> CommerceCandidateResponse:
    return CommerceCandidateResponse(
        id=candidate.id,
        run_id=candidate.run_id,
        task_id=candidate.task_id,
        artifact_id=candidate.artifact_id,
        candidate_kind=candidate.candidate_kind,
        competitor_id=candidate.competitor_id,
        identity=dict(candidate.identity or {}),
        extraction_confidence=candidate.extraction_confidence,
        created_at=candidate.created_at,
        matches=await _candidate_matches(session, candidate),
    )


async def create_discovery_run(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    request: CommerceDiscoveryCreateRequest,
) -> CommerceDiscoveryRunResponse:
    await _project(session, workspace_id, project_id)
    preview = preview_discovery(CommerceDiscoveryPreviewRequest(rows=request.rows))
    if preview.errors:
        raise ValueError("discovery rows contain validation errors")
    if any(
        len(_canonical(_candidate_identity(row)))
        > commerce_intelligence_settings.discovery_max_artifact_payload_chars
        for row in preview.accepted
    ):
        raise ValueError("discovery candidate evidence exceeds the configured bound")
    run = CommerceDiscoveryRun(
        workspace_id=workspace_id,
        project_id=project_id,
        input_kind=request.input_kind,
        configuration=_discovery_configuration(),
    )
    session.add(run)
    await session.flush()
    candidates: list[CommerceDiscoveryCandidate] = []
    for position, (source_url, row) in enumerate(
        _discovery_sources(preview.accepted, request.source_urls)
    ):
        candidate = await _add_discovery_source(
            session,
            run=run,
            workspace_id=workspace_id,
            project_id=project_id,
            input_kind=request.input_kind,
            source_url=source_url,
            row=row,
            position=position,
        )
        if candidate is not None:
            candidates.append(candidate)
    await session.commit()
    for candidate in candidates:
        await session.refresh(candidate)
    await session.refresh(run)
    return CommerceDiscoveryRunResponse(
        id=run.id,
        project_id=run.project_id,
        input_kind=run.input_kind,
        status=run.status,
        configuration=dict(run.configuration or {}),
        discovery_version=run.discovery_version,
        created_at=run.created_at,
        completed_at=run.completed_at,
        candidates=[
            await _candidate_response(session, candidate) for candidate in candidates
        ],
    )


def _discovery_configuration() -> dict[str, Any]:
    return {
        "discovery_version": COMMERCE_DISCOVERY_VERSION,
        "matcher_version": COMMERCE_MATCHER_VERSION,
        "similarity_threshold": (
            commerce_intelligence_settings.title_attribute_similarity_threshold
        ),
        "ambiguity_margin": commerce_intelligence_settings.match_ambiguity_margin,
        "max_candidates": (
            commerce_intelligence_settings.discovery_max_candidates_per_run
        ),
    }


def _discovery_sources(
    rows: list[CommerceCandidateInput], source_urls: list[str]
) -> list[tuple[str, CommerceCandidateInput | None]]:
    sources: list[tuple[str, CommerceCandidateInput | None]] = [
        (row.url, row) for row in rows
    ]
    sources.extend((source_url, None) for source_url in source_urls)
    return sources


async def _add_discovery_source(
    session: AsyncSession,
    *,
    run: CommerceDiscoveryRun,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    input_kind: str,
    source_url: str,
    row: CommerceCandidateInput | None,
    position: int,
) -> CommerceDiscoveryCandidate | None:
    source_identity = source_url or (
        _canonical(_candidate_identity(row)) if row else ""
    )
    source_key = _safe_source_key(source_identity)
    task = CommerceDiscoveryTask(
        run_id=run.id,
        workspace_id=workspace_id,
        project_id=project_id,
        source_url=source_url,
        source_key=source_key,
        idempotency_key=f"commerce-discovery:{run.id}:{source_key}",
        randomized_position=position,
    )
    session.add(task)
    await session.flush()
    if input_kind != COMMERCE_DISCOVERY_INPUT_UPLOAD:
        return None
    extracted = _candidate_identity(row) if row is not None else {}
    artifact = CommerceDiscoveryArtifact(
        task_id=task.id,
        run_id=run.id,
        workspace_id=workspace_id,
        project_id=project_id,
        evidence_kind=COMMERCE_EVIDENCE_KIND_UPLOAD,
        source_url=source_url,
        content_hash=_digest(extracted or {"source_url": source_url}),
        extracted=extracted,
        acquisition={"state": COMMERCE_ACQUISITION_STATE_QUEUE_READY},
    )
    session.add(artifact)
    await session.flush()
    task.result_artifact_id = artifact.id
    if row is None:
        return None
    candidate = CommerceDiscoveryCandidate(
        run_id=run.id,
        task_id=task.id,
        artifact_id=artifact.id,
        workspace_id=workspace_id,
        project_id=project_id,
        candidate_kind=row.candidate_kind,
        competitor_id=row.competitor_id,
        candidate_hash=_digest(extracted),
        identity=extracted,
        extraction_confidence=row.extraction_confidence,
    )
    session.add(candidate)
    return candidate


async def list_discovery_candidates(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    run_id: uuid.UUID | None = None,
) -> list[CommerceCandidateResponse]:
    await _project(session, workspace_id, project_id)
    statement = (
        select(CommerceDiscoveryCandidate)
        .where(
            CommerceDiscoveryCandidate.workspace_id == workspace_id,
            CommerceDiscoveryCandidate.project_id == project_id,
        )
        .order_by(
            CommerceDiscoveryCandidate.created_at.asc(),
            CommerceDiscoveryCandidate.id.asc(),
        )
    )
    if run_id is not None:
        statement = statement.where(CommerceDiscoveryCandidate.run_id == run_id)
    candidates = list((await session.scalars(statement)).all())
    return [await _candidate_response(session, candidate) for candidate in candidates]


async def list_discovery_runs(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[CommerceDiscoveryRunResponse]:
    await _project(session, workspace_id, project_id)
    runs = list(
        (
            await session.scalars(
                select(CommerceDiscoveryRun)
                .where(
                    CommerceDiscoveryRun.workspace_id == workspace_id,
                    CommerceDiscoveryRun.project_id == project_id,
                )
                .order_by(
                    CommerceDiscoveryRun.created_at.desc(),
                    CommerceDiscoveryRun.id.desc(),
                )
            )
        ).all()
    )
    responses: list[CommerceDiscoveryRunResponse] = []
    for run in runs:
        candidates = list(
            (
                await session.scalars(
                    select(CommerceDiscoveryCandidate)
                    .where(CommerceDiscoveryCandidate.run_id == run.id)
                    .order_by(
                        CommerceDiscoveryCandidate.created_at.asc(),
                        CommerceDiscoveryCandidate.id.asc(),
                    )
                )
            ).all()
        )
        responses.append(
            CommerceDiscoveryRunResponse(
                id=run.id,
                project_id=run.project_id,
                input_kind=run.input_kind,
                status=run.status,
                configuration=dict(run.configuration or {}),
                discovery_version=run.discovery_version,
                created_at=run.created_at,
                completed_at=run.completed_at,
                candidates=[
                    await _candidate_response(session, candidate)
                    for candidate in candidates
                ],
            )
        )
    return responses


async def _candidate_in_workspace(
    session: AsyncSession, workspace_id: uuid.UUID, candidate_id: uuid.UUID
) -> CommerceDiscoveryCandidate:
    candidate = await session.scalar(
        select(CommerceDiscoveryCandidate).where(
            CommerceDiscoveryCandidate.id == candidate_id,
            CommerceDiscoveryCandidate.workspace_id == workspace_id,
        )
    )
    if candidate is None:
        raise CommerceDiscoveryNotFoundError("Commerce discovery candidate not found")
    return candidate


from app.domain.commerce.review import (  # noqa: E402
    accept_candidate,
    create_comparison_snapshot,
    list_comparison_snapshots,
)

__all__ = [
    "accept_candidate",
    "create_comparison_snapshot",
    "list_comparison_snapshots",
]
