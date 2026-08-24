"""Persisted execution, citation, and export evidence readers."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.analysis import (
    VISIBILITY_EVIDENCE_DEFAULT_LIMIT,
    VISIBILITY_EVIDENCE_MAX_LIMIT,
)
from app.core.config.prompts import (
    ORGANIC_PROMPT_COHORTS,
    PROMPT_COHORT_CORE,
    REQUESTABLE_PROMPT_COHORTS,
)
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.analysis.projection_common import _AUDIT_NOT_FOUND, _DASHBOARD_STATUSES
from app.domain.analysis.schemas import (
    CitationEvidence,
    ExecutionEvidenceResponse,
    VisibilityEvidenceResponse,
    VisibilityEvidenceSearchEvent,
    VisibilityExecutionEvidence,
    VisibilityFanoutState,
    VisibilityMentionEvidence,
)
from app.domain.analysis.trend_folding import _to_utc
from app.domain.analysis.trends import validate_engine_and_range
from app.domain.audits.schemas import execution_frozen_provenance
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    ResponseAnalysis,
)
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask, RawResponseArtifact

type EvidenceRow = tuple[
    ResponseAnalysis,
    AuditTask,
    AuditPromptSnapshot,
    Audit,
    RawResponseArtifact | None,
]


async def get_visibility_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    prompt_id: uuid.UUID | None = None,
    logical_engine: str | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    limit: int = VISIBILITY_EVIDENCE_DEFAULT_LIMIT,
    cohort: str = "core",
) -> VisibilityEvidenceResponse:
    """Project the workspace-scoped execution evidence dataset (invariant 7).

    A pure READ-ONLY projection over already-persisted per-execution rows for
    the project's dashboard-ready audits — never a provider call and never a
    mutation/backfill. Feeds the Mentions & Citations and Query Fanout tabs.

    Optional filters (``audit_id`` / ``prompt_id`` / ``logical_engine`` /
    inclusive UTC ``from``/``to`` completion window) INTERSECT: when both
    ``audit_id`` and a date window are supplied the selected audit must also
    fall inside the window. Returns at most ``limit`` items in deterministic
    newest-first order with ``truncated`` set when more matches exist. A valid
    project with no matching evidence returns an empty list, ``truncated=False``.
    """
    from_at, to_at = _validated_evidence_request(
        logical_engine=logical_engine,
        from_at=from_at,
        to_at=to_at,
        limit=limit,
        cohort=cohort,
    )
    await _assert_selected_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit_id=audit_id,
    )
    rows = list(
        (
            await session.execute(
                _evidence_statement(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    audit_id=audit_id,
                    prompt_id=prompt_id,
                    logical_engine=logical_engine,
                    from_at=from_at,
                    to_at=to_at,
                    limit=limit,
                    cohort=cohort,
                )
            )
        ).all()
    )
    if not rows:
        return VisibilityEvidenceResponse(items=[], truncated=False)
    return await _evidence_response(
        session, rows=cast(list[EvidenceRow], rows), limit=limit
    )


def _validated_evidence_request(
    *,
    logical_engine: str | None,
    from_at: datetime | None,
    to_at: datetime | None,
    limit: int,
    cohort: str,
) -> tuple[datetime | None, datetime | None]:
    validate_engine_and_range(
        logical_engine=logical_engine, from_at=from_at, to_at=to_at
    )
    if cohort not in REQUESTABLE_PROMPT_COHORTS:
        raise TrendQueryError(f"Unknown prompt cohort: {cohort!r}")
    if limit < 1 or limit > VISIBILITY_EVIDENCE_MAX_LIMIT:
        raise TrendQueryError(
            f"'limit' must be between 1 and {VISIBILITY_EVIDENCE_MAX_LIMIT}"
        )
    return _to_utc(from_at), _to_utc(to_at)


async def _assert_selected_audit(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
) -> None:
    if audit_id is None:
        return
    owning = await session.scalar(
        select(Audit.id).where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
        )
    )
    if owning is None:
        raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)


def _evidence_statement(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
    prompt_id: uuid.UUID | None,
    logical_engine: str | None,
    from_at: datetime | None,
    to_at: datetime | None,
    limit: int,
    cohort: str,
):
    stmt = (
        select(
            ResponseAnalysis,
            AuditTask,
            AuditPromptSnapshot,
            Audit,
            RawResponseArtifact,
        )
        .join(AuditTask, AuditTask.id == ResponseAnalysis.task_id)
        .join(Audit, Audit.id == ResponseAnalysis.audit_id)
        .join(
            AuditPromptSnapshot,
            AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
        )
        .outerjoin(
            RawResponseArtifact,
            RawResponseArtifact.id == ResponseAnalysis.artifact_id,
        )
        .where(
            ResponseAnalysis.workspace_id == workspace_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
        )
    )
    if audit_id is not None:
        stmt = stmt.where(ResponseAnalysis.audit_id == audit_id)
    if prompt_id is not None:
        stmt = stmt.where(AuditPromptSnapshot.prompt_id == prompt_id)
    if logical_engine is not None:
        stmt = stmt.where(ResponseAnalysis.logical_engine == logical_engine)
    stmt = stmt.where(
        ResponseAnalysis.cohort.in_(
            tuple(ORGANIC_PROMPT_COHORTS) if cohort == PROMPT_COHORT_CORE else (cohort,)
        )
    )
    if from_at is not None:
        stmt = stmt.where(Audit.completed_at >= from_at)
    if to_at is not None:
        stmt = stmt.where(Audit.completed_at <= to_at)
    # Newest-first: audit completion desc, then prompt index / engine /
    # repetition asc for a deterministic order (created_at + analysis id break
    # any remaining ties so the truncation window is stable).
    stmt = stmt.order_by(
        Audit.completed_at.desc().nullslast(),
        Audit.created_at.desc(),
        ResponseAnalysis.prompt_index.asc(),
        ResponseAnalysis.logical_engine.asc(),
        ResponseAnalysis.repetition.asc(),
        ResponseAnalysis.id.asc(),
    ).limit(limit + 1)

    return stmt


async def _evidence_response(
    session: AsyncSession,
    *,
    rows: list[EvidenceRow],
    limit: int,
) -> VisibilityEvidenceResponse:
    truncated = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return VisibilityEvidenceResponse(items=[], truncated=False)

    analysis_ids = [analysis.id for analysis, *_ in rows]
    brand_by_analysis = await _mentions_by_analysis(
        session, model=BrandMention, analysis_ids=analysis_ids, kind="brand"
    )
    competitor_by_analysis = await _mentions_by_analysis(
        session,
        model=CompetitorMention,
        analysis_ids=analysis_ids,
        kind="competitor",
    )
    citations_by_analysis = await _citations_by_analysis(
        session, analysis_ids=analysis_ids
    )

    items = [
        _evidence_item(
            analysis=analysis,
            task=task,
            snapshot=snapshot,
            audit=audit,
            artifact=artifact,
            mentions=(
                brand_by_analysis.get(analysis.id, [])
                + competitor_by_analysis.get(analysis.id, [])
            ),
            citations=citations_by_analysis.get(analysis.id, []),
        )
        for analysis, task, snapshot, audit, artifact in rows
    ]
    return VisibilityEvidenceResponse(items=items, truncated=truncated)


async def get_execution_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    task_id: uuid.UUID,
) -> ExecutionEvidenceResponse:
    """Serve one execution's persisted analysis + citation evidence.

    Keyed on the *execution* (``AuditTask``) id — the id clients receive from
    ``GET /audits/{id}/executions`` — not the internal ``ResponseAnalysis`` id.
    The analysis' own id is still surfaced as ``analysis_id``.
    """
    analysis = await session.scalar(
        select(ResponseAnalysis).where(
            ResponseAnalysis.task_id == task_id,
            ResponseAnalysis.workspace_id == workspace_id,
        )
    )
    if analysis is None:
        raise AnalysisNotFoundError("Execution analysis not found")
    citations = list(
        (
            await session.scalars(
                select(Citation)
                .where(Citation.analysis_id == analysis.id)
                .order_by(Citation.ordinal.asc())
            )
        ).all()
    )
    # Frozen measurement provenance comes from the task/audit parents — never
    # from live config (invariants 4/7).
    task = await session.scalar(select(AuditTask).where(AuditTask.id == task_id))
    audit = await session.scalar(select(Audit).where(Audit.id == analysis.audit_id))
    retrieval_enabled = _execution_provenance(task, audit)
    score = analysis.score or {}
    return ExecutionEvidenceResponse(
        id=analysis.task_id,
        analysis_id=analysis.id,
        audit_id=analysis.audit_id,
        task_id=analysis.task_id,
        artifact_id=analysis.artifact_id,
        analyzer_version=analysis.analyzer_version,
        scoring_rule_version=analysis.scoring_rule_version,
        logical_engine=analysis.logical_engine,
        transport_provider=analysis.transport_provider,
        transport_model=analysis.transport_model,
        retrieval_enabled=retrieval_enabled,
        prompt_index=analysis.prompt_index,
        repetition=analysis.repetition,
        prompt_class=analysis.prompt_class,
        cohort=analysis.cohort,
        brand_mentioned=analysis.brand_mentioned,
        brand_first_offset=analysis.brand_first_offset,
        owned_domain_cited=analysis.owned_domain_cited,
        owned_citation_count=analysis.owned_citation_count,
        unintended_domain_cited=analysis.unintended_domain_cited,
        citation_count=analysis.citation_count,
        search_used=analysis.search_used,
        search_query_count=analysis.search_query_count,
        sentiment=analysis.sentiment,
        avg_position=analysis.avg_position,
        score=analysis.score,
        citations=[CitationEvidence.model_validate(c) for c in citations],
        competitors_mentioned=list(score.get("competitors_mentioned") or []),
        created_at=analysis.created_at,
    )


async def load_export_bundle(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> tuple[Audit, list[AuditTask]]:
    """Load the audit + its execution rows for CSV/MD export (invariant 7)."""
    audit = await session.scalar(
        select(Audit)
        .options(selectinload(Audit.engine_snapshots))
        .where(Audit.id == audit_id, Audit.workspace_id == workspace_id)
    )
    if audit is None:
        raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    tasks = list(
        (
            await session.scalars(
                select(AuditTask)
                .where(AuditTask.audit_id == audit_id)
                .where(AuditTask.workspace_id == workspace_id)
                .order_by(AuditTask.prompt_index.asc(), AuditTask.repetition.asc())
            )
        ).all()
    )
    return audit, tasks


# --- Execution-evidence projection helpers (pure, read-only, invariant 7) --
#
# Every helper below reads only already-persisted rows and normalizes stored
# JSON tolerantly: malformed event entries are ignored, empty query strings are
# preserved, and query text / call ids / counts are never invented.


async def _mentions_by_analysis[M: (BrandMention, CompetitorMention)](
    session: AsyncSession,
    *,
    model: type[M],
    analysis_ids: list[uuid.UUID],
    kind: str,
) -> dict[uuid.UUID, list[VisibilityMentionEvidence]]:
    """Batch-load persisted mention rows grouped by analysis id."""
    if not analysis_ids:
        return {}
    name_field = "brand_name" if kind == "brand" else "competitor_name"
    rows: list[M] = list(
        (
            await session.scalars(
                select(model)
                .where(model.analysis_id.in_(analysis_ids))
                .order_by(model.created_at.asc(), model.id.asc())
            )
        ).all()
    )
    grouped: dict[uuid.UUID, list[VisibilityMentionEvidence]] = {}
    for row in rows:
        grouped.setdefault(row.analysis_id, []).append(
            VisibilityMentionEvidence(
                kind=kind,
                name=getattr(row, name_field) or "",
                first_offset=getattr(row, "first_offset", None),
                artifact_id=row.artifact_id,
                analyzer_version=row.analyzer_version or "",
            )
        )
    return grouped


async def _citations_by_analysis(
    session: AsyncSession, *, analysis_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[CitationEvidence]]:
    """Batch-load persisted classified citation rows grouped by analysis id."""
    if not analysis_ids:
        return {}
    rows = list(
        (
            await session.scalars(
                select(Citation)
                .where(Citation.analysis_id.in_(analysis_ids))
                .order_by(Citation.analysis_id.asc(), Citation.ordinal.asc())
            )
        ).all()
    )
    grouped: dict[uuid.UUID, list[CitationEvidence]] = {}
    for row in rows:
        grouped.setdefault(row.analysis_id, []).append(
            CitationEvidence.model_validate(row)
        )
    return grouped


def _normalize_events(raw: object) -> list[VisibilityEvidenceSearchEvent]:
    """Tolerantly normalize a stored search-event list.

    Ignores non-list payloads and malformed entries; preserves empty query
    strings; never invents query text/call ids. An entry must be a mapping to
    contribute an event.
    """
    if not isinstance(raw, list):
        return []
    known_keys = {
        "sequence",
        "query",
        "call_id",
        "call_sequence",
        "query_sequence",
    }
    events: list[VisibilityEvidenceSearchEvent] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        # A well-formed event carries at least one recognized field; entries
        # with none (e.g. ``{}`` or ``{"foo": "bar"}``) are malformed and would
        # otherwise surface as phantom all-zero placeholder events.
        if not known_keys.intersection(entry):
            continue
        events.append(
            VisibilityEvidenceSearchEvent(
                sequence=_as_int(entry.get("sequence")),
                query=_as_str(entry.get("query")),
                call_id=_as_str(entry.get("call_id")),
                call_sequence=_as_int(entry.get("call_sequence")),
                query_sequence=_as_int(entry.get("query_sequence")),
            )
        )
    return events


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _select_events(
    artifact: RawResponseArtifact | None, task: AuditTask
) -> tuple[list[VisibilityEvidenceSearchEvent], str]:
    """Prefer non-empty artifact events; fall back to the task copy.

    Never merges the two copies. Returns ``(events, event_source)`` where
    ``event_source`` is ``raw_artifact`` / ``audit_task`` / ``none``.
    """
    if artifact is not None:
        artifact_events = _normalize_events(artifact.search_events)
        if artifact_events:
            return artifact_events, "raw_artifact"
    task_events = _normalize_events(task.search_events)
    if task_events:
        return task_events, "audit_task"
    return [], "none"


def _fanout_state(
    *,
    events: list[VisibilityEvidenceSearchEvent],
    search_used: bool,
    search_query_count: int,
) -> tuple[bool, VisibilityFanoutState]:
    """Derive ``(query_text_available, state)`` from the persisted signals."""
    query_text_available = any(ev.query.strip() for ev in events)
    if query_text_available:
        return True, VisibilityFanoutState.QUERIES_AVAILABLE
    if search_used or search_query_count > 0:
        return False, VisibilityFanoutState.COUNT_ONLY
    return False, VisibilityFanoutState.NO_SEARCH


def _execution_provenance(task: AuditTask | None, audit: Audit | None) -> bool | None:
    """Frozen retrieval state for one execution.

    Task request/route snapshots win (what the call executed under), then the
    audit's frozen policy block. Live config is never consulted
    (invariants 4/7 — read paths are projections of frozen fields only).
    """
    return execution_frozen_provenance(
        request_snapshot=task.request_snapshot if task is not None else None,
        route_snapshot=task.provider_route_snapshot if task is not None else None,
        audit_configuration=audit.configuration if audit is not None else None,
    )


def _evidence_item(
    *,
    analysis: ResponseAnalysis,
    task: AuditTask,
    snapshot: AuditPromptSnapshot,
    audit: Audit,
    artifact: RawResponseArtifact | None,
    mentions: list[VisibilityMentionEvidence],
    citations: list[CitationEvidence],
) -> VisibilityExecutionEvidence:
    events, event_source = _select_events(artifact, task)
    query_text_available, state = _fanout_state(
        events=events,
        search_used=bool(analysis.search_used),
        search_query_count=int(analysis.search_query_count or 0),
    )
    retrieval_enabled = _execution_provenance(task, audit)
    return VisibilityExecutionEvidence(
        audit_id=analysis.audit_id,
        task_id=analysis.task_id,
        analysis_id=analysis.id,
        artifact_id=analysis.artifact_id,
        prompt_snapshot_id=snapshot.id,
        prompt_id=snapshot.prompt_id,
        prompt_index=analysis.prompt_index,
        prompt_text=snapshot.text or "",
        repetition=analysis.repetition,
        completed_at=_to_utc(audit.completed_at),
        logical_engine=analysis.logical_engine,
        transport_provider=analysis.transport_provider,
        transport_model=analysis.transport_model,
        retrieval_enabled=retrieval_enabled,
        search_used=bool(analysis.search_used),
        search_query_count=int(analysis.search_query_count or 0),
        query_text_available=query_text_available,
        state=state,
        search_events=events,
        event_source=event_source,
        mentions=mentions,
        citations=citations,
    )
