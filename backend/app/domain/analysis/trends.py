"""Persisted cross-run visibility trend projections."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import commerce as commerce_config
from app.core.config.analysis import (
    VISIBILITY_TREND_DEFAULT_GRANULARITY,
    VISIBILITY_TREND_GRANULARITIES,
    VISIBILITY_TREND_MAX_POINTS,
)
from app.core.config.audits import MEASUREMENT_MODES
from app.core.config.prompts import REQUESTABLE_PROMPT_COHORTS
from app.core.config.provider_catalog import LOGICAL_ENGINES
from app.domain.analysis.errors import TrendQueryError
from app.domain.analysis.projection_common import _DASHBOARD_STATUSES
from app.domain.analysis.schemas import VisibilityTrendPoint
from app.domain.analysis.trend_folding import (
    _bucket_points,
    _raw_point,
    _to_utc,
    _TrendSource,
)
from app.domain.analysis.visibility import (
    _logo_url_for_name,
    _project_logo_context,
    _website_url_for_name,
)
from app.domain.audits.schemas import (
    ModelProvenance,
    audit_frozen_retrieval_enabled,
    model_provenance_for,
)
from app.models.analysis import MetricSnapshot
from app.models.audit import Audit


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


def validate_engine_and_range(
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
    validate_engine_and_range(
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
