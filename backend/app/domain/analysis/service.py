# Analysis/metrics projections (B6, invariant 7 — read persisted analysis only).
#
# Every function here reads persisted rows (``MetricSnapshot`` /
# ``ResponseAnalysis`` / ``Citation`` / ``Audit`` / ``AuditTask``) and NEVER
# calls a provider. They back the metrics/dashboard/evidence/export endpoints.
# All queries are workspace-scoped (invariant 5).
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analysis.normalization import normalize_domain
from app.core.config import commerce as commerce_config
from app.core.config.analysis import (
    VISIBILITY_EVIDENCE_DEFAULT_LIMIT,
    VISIBILITY_EVIDENCE_MAX_LIMIT,
    VISIBILITY_TREND_DEFAULT_GRANULARITY,
    VISIBILITY_TREND_GRANULARITIES,
    VISIBILITY_TREND_MAX_POINTS,
)
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
    MEASUREMENT_MODES,
)
from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.core.config.prompts import (
    ORGANIC_PROMPT_COHORTS,
    PROMPT_COHORT_CORE,
    REQUESTABLE_PROMPT_COHORTS,
)
from app.core.config.provider_catalog import LOGICAL_ENGINES
from app.domain.analysis.schemas import (
    CitationEvidence,
    EngineComparisonRow,
    ExecutionEvidenceResponse,
    MetricsResponse,
    PromptMetricItem,
    RankingRow,
    VisibilityEvidenceResponse,
    VisibilityEvidenceSearchEvent,
    VisibilityExecutionEvidence,
    VisibilityFanoutState,
    VisibilityMentionEvidence,
    VisibilityResponse,
    VisibilityTrendPoint,
)
from app.domain.analysis.trend_folding import (
    _brand_name,
    _bucket_points,
    _raw_point,
    _to_utc,
    _TrendSource,
)
from app.domain.audits.schemas import (
    ModelProvenance,
    audit_frozen_retrieval_enabled,
    execution_frozen_provenance,
    model_provenance_for,
)
from app.domain.projects.logos import get_project_logo_urls
from app.domain.projects.service import get_project
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    MetricSnapshot,
    PromptMetricSnapshot,
    ResponseAnalysis,
)
from app.models.audit import (
    Audit,
    AuditPromptSnapshot,
    AuditTask,
    RawResponseArtifact,
)
from app.models.project import Project

# A run is "completed" (dashboard-eligible) when fully or partially completed.
_DASHBOARD_STATUSES = (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)


class AnalysisNotFoundError(LookupError):
    """Raised when a requested projection has no persisted rows to serve."""


# Single source for the repeated "audit missing" detail (asserted by tests).
_AUDIT_NOT_FOUND = "Audit not found"


def _aggregate_provenance(audit: Audit) -> tuple[str, list[ModelProvenance]]:
    """Frozen mode + stable route-provenance list for an aggregate surface."""
    return (
        audit.measurement_mode or "",
        model_provenance_for(audit.engine_snapshots, audit.configuration),
    )


async def get_metrics(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> MetricsResponse:
    """Serve the single-run ``MetricSnapshot`` projection."""
    snapshot = await _load_snapshot(
        session, workspace_id=workspace_id, audit_id=audit_id
    )
    return MetricsResponse.model_validate(snapshot)


async def get_prompt_metrics(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
) -> list[PromptMetricItem]:
    """Return one persisted prompt projection, strongest-to-weakest."""
    if audit_id is None:
        audit_id = await _latest_dashboard_audit_id(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if audit_id is None:
            return []
    else:
        audit = await session.scalar(
            select(Audit.id).where(
                Audit.id == audit_id,
                Audit.workspace_id == workspace_id,
                Audit.project_id == project_id,
            )
        )
        if audit is None:
            raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    rows = list(
        (
            await session.scalars(
                select(PromptMetricSnapshot)
                .where(
                    PromptMetricSnapshot.workspace_id == workspace_id,
                    PromptMetricSnapshot.project_id == project_id,
                    PromptMetricSnapshot.audit_id == audit_id,
                )
                .order_by(
                    PromptMetricSnapshot.composite_score.desc(),
                    PromptMetricSnapshot.prompt_index.asc(),
                )
            )
        ).all()
    )
    return [PromptMetricItem.model_validate(row) for row in rows]


async def get_visibility(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    cohort: str = "core",
) -> VisibilityResponse:
    """Serve the selected-run dashboard projection for a project.

    Defaults to the project's latest completed/partially-completed audit when
    ``audit_id`` is omitted. Computed server-side from the persisted snapshot;
    no provider call (invariant 7).
    """
    if audit_id is None:
        audit_id = await _latest_dashboard_audit_id(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if audit_id is None:
            raise AnalysisNotFoundError("No completed audit for project")

    audit = await session.scalar(
        select(Audit)
        .options(selectinload(Audit.engine_snapshots))
        .where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
        )
    )
    if audit is None:
        raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    snapshot = await _load_snapshot(
        session, workspace_id=workspace_id, audit_id=audit_id
    )
    if cohort not in REQUESTABLE_PROMPT_COHORTS:
        raise TrendQueryError(f"Unknown prompt cohort: {cohort!r}")
    stored_metrics = snapshot.metrics or {}
    metrics = (
        stored_metrics
        if cohort == "core"
        else dict(stored_metrics.get("comparison") or {})
    )
    logo_urls, logo_identity_ids, website_urls = await _project_logo_context(
        session, workspace_id=workspace_id, project_id=project_id
    )
    provenance_mode, model_provenance = _aggregate_provenance(audit)
    return VisibilityResponse(
        project_id=project_id,
        audit_id=audit_id,
        audit_status=audit.status,
        analyzer_version=snapshot.analyzer_version,
        scoring_rule_version=snapshot.scoring_rule_version,
        cohort=cohort,
        coverage=dict(metrics.get("coverage") or {}),
        total_completed=int(metrics.get("total_completed") or 0),
        total_failed=max(
            0,
            int((metrics.get("coverage") or {}).get("requested") or 0)
            - int(metrics.get("total_completed") or 0),
        ),
        visibility_score=_selected_visibility_score(snapshot, metrics, cohort),
        measurement_mode=provenance_mode,
        model_provenance=model_provenance,
        rankings=_rankings(
            metrics,
            logo_urls=logo_urls,
            logo_identity_ids=logo_identity_ids,
            website_urls=website_urls,
        ),
        per_engine=_engine_rows(metrics),
        sentiment=metrics.get("sentiment"),
        avg_position=metrics.get("avg_position"),
        created_at=snapshot.created_at,
    )


class TrendQueryError(ValueError):
    """Raised for an invalid trend query (bad engine/granularity/range).

    The API layer maps this to HTTP 422; it is never a not-found condition.
    """


def _selected_visibility_score(
    snapshot: MetricSnapshot, metrics: dict, cohort: str
) -> float:
    if cohort == "core":
        return snapshot.visibility_score
    return round(float(metrics.get("brand_mention_rate") or 0.0) * 100, 2)


def validate_shopping_surface(surface: str) -> str:
    """Validate a requested shopping surface against the configured gate.

    Returns ``surface`` unchanged when it is the measurement identity or a
    configured ``SHOPPING_SURFACES`` key; raises ``TrendQueryError`` (HTTP
    422) otherwise. Reads the commerce gate at CALL time so tests can
    monkeypatch ``app.core.config.commerce.SHOPPING_SURFACES`` with a
    fixture surface while the shipped gate stays empty.
    """
    if (
        surface == commerce_config.SHOPPING_SURFACE_MEASUREMENT
        or surface in commerce_config.SHOPPING_SURFACES
    ):
        return surface
    raise TrendQueryError(f"Unknown shopping surface: {surface!r}")


async def get_visibility_trends(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    logical_engine: str | None = None,
    from_at: datetime | None = None,
    to_at: datetime | None = None,
    granularity: str = VISIBILITY_TREND_DEFAULT_GRANULARITY,
    measurement_mode: str | None = None,
    transport_model: str | None = None,
    retrieval_enabled: bool | None = None,
    cohort: str = "core",
) -> list[VisibilityTrendPoint]:
    """Project the workspace-scoped cross-run Visibility trend (invariant 7).

    A pure projection over the already-persisted per-run ``MetricSnapshot`` rows
    for the project's dashboard-ready audits — no provider call, no re-scoring.
    ``granularity=run`` returns one point per snapshot; ``week``/``month`` fold
    snapshots into deterministic UTC buckets. Under strict version bucketing any
    requested bucket that would cross an analyzer/scoring version boundary makes
    the whole range fall back to raw per-run points. Returns ``[]`` (never an
    error) for a valid project with no matching history.

    Folding identity is ``(measurement_mode, transport_model,
    retrieval_enabled)`` on top of the project/engine/time filters: a bucket
    may combine points ONLY inside one identity partition, and the response
    carries separate ordered points for unlike identities (a point never mixes
    pulse with benchmark, different models, or retrieval on with off). The
    explicit ``measurement_mode``/``transport_model``/``retrieval_enabled``
    slice arguments filter sources BEFORE any folding.
    """
    granularity = granularity or VISIBILITY_TREND_DEFAULT_GRANULARITY
    _validate_trend_query(
        logical_engine=logical_engine,
        from_at=from_at,
        to_at=to_at,
        granularity=granularity,
        measurement_mode=measurement_mode,
        transport_model=transport_model,
    )
    from_at = _to_utc(from_at)
    to_at = _to_utc(to_at)

    rows = await _load_trend_rows(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        from_at=from_at,
        to_at=to_at,
    )
    if cohort not in REQUESTABLE_PROMPT_COHORTS:
        raise TrendQueryError(f"Unknown prompt cohort: {cohort!r}")
    sources = [
        source
        for snapshot, audit in rows
        if (source := _trend_source(snapshot, audit, logical_engine, cohort))
        is not None
    ]
    # An explicitly requested identity slice filters BEFORE any folding.
    sources = _slice_sources(
        sources,
        measurement_mode=measurement_mode,
        transport_model=transport_model,
        retrieval_enabled=retrieval_enabled,
    )
    if not sources:
        return []

    # Cap to the newest N source snapshots but keep the response chronological.
    if len(sources) > VISIBILITY_TREND_MAX_POINTS:
        sources = sources[-VISIBILITY_TREND_MAX_POINTS:]

    if granularity == "run":
        points = [_raw_point(source) for source in sources]
    else:
        points = _bucket_points(sources, granularity)
    logo_urls, logo_identity_ids, website_urls = await _project_logo_context(
        session, workspace_id=workspace_id, project_id=project_id
    )
    for point in points:
        for ranking in point.rankings:
            ranking.logo_url = _logo_url_for_name(
                ranking.name, ranking.is_brand, logo_urls, logo_identity_ids
            )
            ranking.website_url = _website_url_for_name(
                ranking.name, ranking.is_brand, website_urls
            )
    return points


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
    _validate_engine_and_range(
        logical_engine=logical_engine, from_at=from_at, to_at=to_at
    )
    if cohort not in REQUESTABLE_PROMPT_COHORTS:
        raise TrendQueryError(f"Unknown prompt cohort: {cohort!r}")
    if limit < 1 or limit > VISIBILITY_EVIDENCE_MAX_LIMIT:
        raise TrendQueryError(
            f"'limit' must be between 1 and {VISIBILITY_EVIDENCE_MAX_LIMIT}"
        )
    from_at = _to_utc(from_at)
    to_at = _to_utc(to_at)

    # If an audit is selected, it must belong to this workspace/project (else a
    # cross-workspace/missing id must 404 — never leak that it exists).
    if audit_id is not None:
        owning = await session.scalar(
            select(Audit.id).where(
                Audit.id == audit_id,
                Audit.workspace_id == workspace_id,
                Audit.project_id == project_id,
            )
        )
        if owning is None:
            raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)

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
            # Brand evidence is MEASUREMENT-ONLY (§7.1): filter BOTH the
            # task slot and the analysis row (defense-in-depth) so probe
            # rows never surface in brand evidence.
            AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT,
            ResponseAnalysis.shopping_surface == SHOPPING_SURFACE_MEASUREMENT,
        )
    )
    if audit_id is not None:
        stmt = stmt.where(ResponseAnalysis.audit_id == audit_id)
    if prompt_id is not None:
        stmt = stmt.where(AuditPromptSnapshot.prompt_id == prompt_id)
    if logical_engine is not None:
        stmt = stmt.where(ResponseAnalysis.logical_engine == logical_engine)
    # `core` is a VIEW over every organic cohort, not a literal column match:
    # onboarding-generated portfolios store `market_visibility` /
    # `brand_relevant`, so an `== "core"` filter matched nothing and emptied
    # both evidence tabs. `app/analysis/service.py` already aggregates on the
    # same organic set — this keeps the read side in step with the write side.
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

    rows = list((await session.execute(stmt)).all())
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
    measurement_mode, retrieval_enabled = _execution_provenance(task, audit)
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
        measurement_mode=measurement_mode,
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
                # Brand exports are MEASUREMENT-ONLY (§7.1): probe rows are
                # never exported with brand executions.
                .where(AuditTask.shopping_surface == SHOPPING_SURFACE_MEASUREMENT)
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


def _execution_provenance(
    task: AuditTask | None, audit: Audit | None
) -> tuple[str, bool | None]:
    """Frozen ``(measurement_mode, retrieval_enabled)`` for one execution.

    Task request/route snapshots win (what the call executed under), then the
    audit's frozen mode column + policy block. Live config is never consulted
    (invariants 4/7 — read paths are projections of frozen fields only).
    """
    return execution_frozen_provenance(
        request_snapshot=task.request_snapshot if task is not None else None,
        route_snapshot=task.provider_route_snapshot if task is not None else None,
        audit_measurement_mode=audit.measurement_mode if audit is not None else None,
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
    measurement_mode, retrieval_enabled = _execution_provenance(task, audit)
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
        measurement_mode=measurement_mode,
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


async def _load_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> MetricSnapshot:
    snapshot = await session.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.audit_id == audit_id,
            MetricSnapshot.workspace_id == workspace_id,
        )
    )
    if snapshot is None:
        raise AnalysisNotFoundError("Metrics not available for audit")
    return snapshot


async def _latest_dashboard_audit_id(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(Audit.id)
        .where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
        )
        .order_by(Audit.completed_at.desc().nullslast(), Audit.created_at.desc())
        .limit(1)
    )


async def _project_logo_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[
    dict[uuid.UUID, str],
    dict[tuple[bool, str], uuid.UUID],
    dict[tuple[bool, str], str],
]:
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    logo_urls = get_project_logo_urls(project)
    identity_ids: dict[tuple[bool, str], uuid.UUID] = {}
    if project.brand is not None:
        identity_ids[(True, project.brand.name)] = project.brand.id
    for competitor in project.competitors:
        identity_ids[(False, competitor.name)] = competitor.id
    return logo_urls, identity_ids, _project_website_urls(project)


def _project_website_urls(project: Project) -> dict[tuple[bool, str], str]:
    website_urls: dict[tuple[bool, str], str] = {}
    if project.brand is not None:
        brand_website = _normalized_logo_website_url(
            project.website_url
            or next((item.domain for item in project.owned_domains if item.domain), "")
        )
        if brand_website:
            website_urls[(True, project.brand.name)] = brand_website
    for competitor in project.competitors:
        competitor_website = _normalized_logo_website_url(
            next(
                (str(domain) for domain in competitor.domains or [] if str(domain)),
                "",
            )
        )
        if competitor_website:
            website_urls[(False, competitor.name)] = competitor_website
    return website_urls


def _rankings(
    metrics: dict,
    *,
    logo_urls: dict[uuid.UUID, str] | None = None,
    logo_identity_ids: dict[tuple[bool, str], uuid.UUID] | None = None,
    website_urls: dict[tuple[bool, str], str] | None = None,
) -> list[RankingRow]:
    """Build the brand-vs-competitor rankings table from the aggregate.

    Visibility % (mention rate) + SOV are populated; sentiment + average
    position are present but null (decision B-2).
    """
    sov = metrics.get("share_of_voice") or {}
    share = sov.get("share") or {}
    counts = sov.get("mention_counts") or {}
    brand_name = _brand_name(counts, metrics)
    competitor_mention = metrics.get("competitor_mention_rate") or {}
    competitor_citation = metrics.get("competitor_citation_rate") or {}

    rows: list[RankingRow] = [
        RankingRow(
            name=brand_name,
            is_brand=True,
            logo_url=_logo_url_for_name(
                brand_name, True, logo_urls or {}, logo_identity_ids or {}
            ),
            website_url=_website_url_for_name(brand_name, True, website_urls),
            mention_rate=metrics.get("brand_mention_rate"),
            citation_rate=metrics.get("owned_citation_rate"),
            share_of_voice=share.get(brand_name),
            mention_count=int(counts.get(brand_name, 0) or 0),
        )
    ]
    for name in competitor_mention:
        rows.append(
            RankingRow(
                name=name,
                is_brand=False,
                logo_url=_logo_url_for_name(
                    name, False, logo_urls or {}, logo_identity_ids or {}
                ),
                website_url=_website_url_for_name(name, False, website_urls),
                mention_rate=competitor_mention.get(name),
                citation_rate=competitor_citation.get(name),
                share_of_voice=share.get(name),
                mention_count=int(counts.get(name, 0) or 0),
            )
        )
    # Deterministic order: highest SOV first, then name for stable ties.
    rows.sort(key=lambda r: (-(r.share_of_voice or 0.0), r.name))
    return rows


def _logo_url_for_name(
    name: str,
    is_brand: bool,
    logo_urls: dict[uuid.UUID, str],
    identity_ids: dict[tuple[bool, str], uuid.UUID],
) -> str | None:
    identity_id = identity_ids.get((is_brand, name))
    return logo_urls.get(identity_id) if identity_id is not None else None


def _website_url_for_name(
    name: str,
    is_brand: bool,
    website_urls: dict[tuple[bool, str], str] | None,
) -> str | None:
    return website_urls.get((is_brand, name)) if website_urls is not None else None


def _normalized_logo_website_url(value: object) -> str | None:
    domain = normalize_domain(value)
    return f"https://{domain}" if domain else None


def _engine_rows(metrics: dict) -> list[EngineComparisonRow]:
    per_engine = metrics.get("per_engine") or {}
    rows: list[EngineComparisonRow] = []
    for engine, agg in sorted(per_engine.items()):
        rate = agg.get("brand_mention_rate")
        rows.append(
            EngineComparisonRow(
                logical_engine=engine,
                total_completed=int(agg.get("total_completed", 0) or 0),
                brand_mention_rate=rate,
                owned_citation_rate=agg.get("owned_citation_rate"),
                search_use_rate=agg.get("search_use_rate"),
                visibility_score=round(float(rate) * 100, 2)
                if rate is not None
                else None,
            )
        )
    return rows


# --- Cross-run Visibility trend projection helpers (pure, invariant 7) -----
#
# Every helper below reads only the already-persisted ``MetricSnapshot.metrics``
# dict (the same shape the single-run dashboard reads) and the owning ``Audit``
# timestamp/status. None of them re-score, re-extract, or call a provider.


def _validate_engine_and_range(
    *,
    logical_engine: str | None,
    from_at: datetime | None,
    to_at: datetime | None,
) -> None:
    """Shared engine + inclusive-UTC-range validation (trends + evidence).

    Raises ``TrendQueryError`` (mapped to HTTP 422) for an unknown logical
    engine, a naive timestamp, or a reversed range. Kept identical to the
    original trend validation so the trend contract is unchanged.
    """
    if logical_engine is not None and logical_engine not in LOGICAL_ENGINES:
        raise TrendQueryError(f"Unknown logical engine: {logical_engine!r}")
    _require_aware("from", from_at)
    _require_aware("to", to_at)
    if from_at is not None and to_at is not None:
        if _to_utc(from_at) > _to_utc(to_at):
            raise TrendQueryError("'from' must not be after 'to'")


def _validate_identity_slice(
    *, measurement_mode: str | None, transport_model: str | None
) -> None:
    """Validate an explicitly requested identity slice (HTTP 422 on misuse)."""
    if measurement_mode is not None and measurement_mode not in MEASUREMENT_MODES:
        raise TrendQueryError(f"Unsupported measurement_mode: {measurement_mode!r}")
    if transport_model is not None and not transport_model.strip():
        raise TrendQueryError("'transport_model' must be a non-empty model id")


def _validate_trend_query(
    *,
    logical_engine: str | None,
    from_at: datetime | None,
    to_at: datetime | None,
    granularity: str,
    measurement_mode: str | None,
    transport_model: str | None,
) -> None:
    if granularity not in VISIBILITY_TREND_GRANULARITIES:
        raise TrendQueryError(f"Unsupported granularity: {granularity!r}")
    _validate_identity_slice(
        measurement_mode=measurement_mode, transport_model=transport_model
    )
    _validate_engine_and_range(
        logical_engine=logical_engine, from_at=from_at, to_at=to_at
    )


def _require_aware(label: str, value: datetime | None) -> None:
    if value is not None and value.tzinfo is None:
        raise TrendQueryError(f"'{label}' must be a timezone-aware timestamp")


async def _load_trend_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    from_at: datetime | None,
    to_at: datetime | None,
) -> list[tuple[MetricSnapshot, Audit]]:
    """Load (snapshot, audit) pairs for the project's dashboard-ready audits.

    Workspace/project scoped (invariant 5), restricted to dashboard-ready
    statuses with a non-null ``completed_at`` and the requested inclusive UTC
    window, ordered chronologically.
    """
    stmt = (
        select(MetricSnapshot, Audit)
        .join(Audit, Audit.id == MetricSnapshot.audit_id)
        .options(selectinload(Audit.engine_snapshots))
        .where(
            MetricSnapshot.workspace_id == workspace_id,
            MetricSnapshot.project_id == project_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
            Audit.completed_at.is_not(None),
        )
    )
    if from_at is not None:
        stmt = stmt.where(Audit.completed_at >= from_at)
    if to_at is not None:
        stmt = stmt.where(Audit.completed_at <= to_at)
    stmt = stmt.order_by(Audit.completed_at.asc(), Audit.created_at.asc())
    result = await session.execute(stmt)
    return list(result.tuples().all())


def _trend_source(
    snapshot: MetricSnapshot,
    audit: Audit,
    logical_engine: str | None,
    cohort: str = "core",
) -> _TrendSource | None:
    """Project one snapshot into a trend source, or ``None`` to skip it.

    An engine-filtered request reads the same snapshot's
    ``metrics.per_engine[engine]``; a snapshot that did not measure that engine
    emits no point (invariant 10). The folding identity derives ONLY from
    frozen audit fields: the mode column, the frozen policy block (retrieval),
    and the frozen engine snapshots (models) — never from live config.
    """
    stored_metrics = snapshot.metrics or {}
    metrics = (
        stored_metrics
        if cohort == "core"
        else dict(stored_metrics.get("comparison") or {})
    )
    completed_at = audit.completed_at
    if completed_at is None:
        # Unreachable via the loader (it filters completed_at IS NOT NULL);
        # defensive skip so a malformed row never emits a point.
        return None
    engine_metrics: dict | None
    visibility_score: float | None
    if logical_engine is None:
        engine_metrics = metrics
        rate = metrics.get("brand_mention_rate")
        visibility_score = round(float(rate) * 100, 2) if rate is not None else None
    else:
        per_engine = metrics.get("per_engine") or {}
        engine_metrics = per_engine.get(logical_engine)
        if not engine_metrics:
            return None
        rate = engine_metrics.get("brand_mention_rate")
        visibility_score = round(float(rate) * 100, 2) if rate is not None else None
    mode, transport_model, retrieval, provenance = _source_identity(
        audit, logical_engine
    )
    return _TrendSource(
        snapshot_id=snapshot.id,
        audit_id=snapshot.audit_id,
        completed_at=_to_utc(completed_at),
        logical_engine=logical_engine,
        measurement_mode=mode,
        transport_model=transport_model,
        retrieval_enabled=retrieval,
        model_provenance=provenance,
        analyzer_version=snapshot.analyzer_version,
        scoring_rule_version=snapshot.scoring_rule_version,
        total_completed=int(engine_metrics.get("total_completed", 0) or 0),
        visibility_score=visibility_score,
        metrics=engine_metrics,
    )


def _source_identity(
    audit: Audit, logical_engine: str | None
) -> tuple[str, str | None, bool | None, list[ModelProvenance]]:
    """Frozen folding identity + provenance list for one trend source.

    Derives ONLY from frozen audit fields: the mode column, the frozen policy
    block (retrieval), and the frozen engine snapshots (models) — never from
    live config (invariants 4/7).
    """
    provenance = model_provenance_for(audit.engine_snapshots, audit.configuration)
    return (
        audit.measurement_mode or "",
        _source_transport_model(provenance, logical_engine),
        audit_frozen_retrieval_enabled(audit.configuration),
        provenance,
    )


def _source_transport_model(
    provenance: list[ModelProvenance], logical_engine: str | None
) -> str | None:
    """The singular frozen model for a trend source, or None when it spans models.

    Engine-filtered: the frozen model for exactly that engine (None when the
    audit has no frozen route for it). Aggregate: singular only when the audit
    measured exactly one model — a multi-model aggregate never forces one (its
    ``model_provenance`` list is the surface).
    """
    if logical_engine is not None:
        return next(
            (
                item.transport_model
                for item in provenance
                if item.logical_engine == logical_engine
            ),
            None,
        )
    models = {item.transport_model for item in provenance}
    return next(iter(models)) if len(models) == 1 else None


def _identity_slice_match(
    source: _TrendSource,
    *,
    measurement_mode: str | None,
    transport_model: str | None,
    retrieval_enabled: bool | None,
) -> bool:
    """True when the source belongs to an explicitly requested identity slice.

    Slices match the exact frozen identity: a requested model/retrieval state
    excludes aggregates whose identity does not equal it (never a fuzzy
    contains-match that would let a multi-model point into a model slice).
    """
    if measurement_mode is not None and source.measurement_mode != measurement_mode:
        return False
    if transport_model is not None and source.transport_model != transport_model:
        return False
    return retrieval_enabled is None or source.retrieval_enabled == retrieval_enabled


def _slice_sources(
    sources: list[_TrendSource],
    *,
    measurement_mode: str | None,
    transport_model: str | None,
    retrieval_enabled: bool | None,
) -> list[_TrendSource]:
    """Keep only sources belonging to an explicitly requested identity slice."""
    return [
        source
        for source in sources
        if _identity_slice_match(
            source,
            measurement_mode=measurement_mode,
            transport_model=transport_model,
            retrieval_enabled=retrieval_enabled,
        )
    ]
