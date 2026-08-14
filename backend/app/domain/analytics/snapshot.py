# AnalyticsSnapshot builder + ``analytics_snapshot_refresh`` executor (A8).
#
# The C5 referral chain's third link: rebuild the LLM-Analytics projection
# for one (project, window) from PERSISTED evidence only — the
# ``ReferralClassification`` + ``ReferralEvent`` rows landed by the
# ingest/classify links (each event joined to the ``IntegrationMetricRow``
# it was projected from) and the per-run ``MetricSnapshot`` / per-execution
# ``ResponseAnalysis`` rows the audit pipeline already persists. NO provider
# I/O anywhere (invariant 7) and NO LLM (invariant 9): every number below is
# a deterministic fold of persisted rows.
#
# FORMULAS (all folds share ONE session measure, documented so a reader can
# reproduce every number):
#   - Referral facts: one fact per classification whose event still resolves
#     to a metric row, keeping only the LATEST ``resync_seq`` per metric-row
#     identity ``(property_ref, provider, dataset, date, dimension_key)`` —
#     a fact backed by a superseded revision is stale evidence and never
#     folds in (its replacement enters via its own event). An event whose
#     ``source_metric_row_id`` is NULL (the row was deleted) carries no
#     session measure and is excluded.
#   - ``sessions`` per fact = the metric row's ``metrics["sessions"]`` (a
#     missing/non-numeric value counts as 0).
#   - ai_sessions(bucket)   = Σ sessions over the bucket's AI facts.
#     total_sessions(bucket) = Σ sessions over ALL the bucket's facts (AI +
#     non-AI) — numerator and denominator are drawn from the IDENTICAL
#     latest-revision row set (the C1 referral datasets), so the ratio is
#     internally consistent.
#   - referral_volume point = ai_sessions when the bucket has ANY folded
#     referral fact (a measured zero is 0), else ``None`` (no measurement —
#     a chart gap, never a coerced zero).
#   - referral_share point  = ai_sessions / total_sessions when
#     total_sessions > 0, else ``None``.
#   - sources breakdown (window-level): per ``ai_source`` Σ sessions over AI
#     facts; ``share`` = source sessions / window total_sessions (the same
#     denominator as the share series). Only sources with sessions > 0 are
#     listed, ordered sessions desc then ``ai_source`` asc. Non-AI referrals
#     (``other``) never appear — the breakdown is over AI sources only.
#   - engine_visibility: per logical engine, the per-bucket
#     completion-weighted mean of the folded ``MetricSnapshot`` per-engine
#     visibility scores (``per_engine[engine].brand_mention_rate * 100``,
#     mirroring ``visibility_score``), rounded to 2 decimals; ``None`` for a
#     bucket with no snapshot covering that engine.
#   - correlation: DAY-aligned (granularity-independent). x = the day's
#     completion-weighted mean ``visibility_score``; y = the day's AI
#     sessions. Aligned pairs = days having BOTH values, sorted by day.
#     Pearson product-moment over the aligned pairs; fewer than
#     ``CORRELATION_MIN_SAMPLE`` pairs — or a zero-variance axis, where
#     Pearson is undefined — reports ``insufficient_data`` with a NULL
#     coefficient, NEVER a fabricated number.
#   - themes (window-level): per-execution ``ResponseAnalysis`` rows joined
#     to the frozen ``AuditPromptSnapshot`` on ``(audit_id, prompt_index)``,
#     grouped by ``(theme, intent)``: ``total_completed`` = executions;
#     ``brand_mention_rate`` = brand-mentioned executions / total (rounded
#     to 4 like the run aggregate); ``visibility_score`` = rate * 100
#     (rounded to 2, mirroring the run-level formula);
#     ``share_of_voice`` = brand mentions / (brand + competitor mention
#     incidences), ``None`` when the group has no mentions at all.
#
# Visibility + theme inputs come only from audits in the dashboard statuses
# (completed / partially_completed — the ONE owner tuple in
# ``domain/analysis/service.py``) completed inside the window.
#
# Idempotent: recomputing from the same persisted rows rewrites the SAME
# snapshot rows in place via ``INSERT ... ON CONFLICT (project_id,
# window_start, window_end, granularity) DO UPDATE`` (precedent:
# ``domain/traffic/service.py``), so a re-run never duplicates. Provenance
# (invariant 4): ``source_classification_ids`` = the folded classification
# ids (AI and non-AI — both feed the share), ``source_snapshot_ids`` = the
# folded ``MetricSnapshot`` ids; analyzer/formula versions reuse the
# config/analysis.py constants (llm-analytics.md section 8, invariant 2).
# Cooperative cancel is honored at every classification batch boundary
# (invariant 9) — the write phase is a single transaction, so a cancelled
# run leaves no partial projection behind.
from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

# ``ANALYZER_VERSION`` / ``SCORING_RULE_VERSION`` are OWNED by
# config/analysis.py and reused for the snapshot provenance stamps
# (invariant 2) — never the same-named site-health constants.
from app.core.config.analytics import (
    AI_REFERRAL_ANALYZER_VERSION,
    AI_REFERRAL_FORMULA_VERSION,
    ANALYTICS_SNAPSHOT_GRANULARITIES,
)
from app.core.config.integrations import DATASET_GA4_SOURCE_MEDIUM_DAILY

# The dashboard-status audit tuple (completed | partially_completed) is
# OWNED by the analysis projections service — imported, never re-derived
# (invariant 2; the visibility/theme folds must measure the same audit
# population the Visibility dashboard serves).
from app.domain.analysis.service import _DASHBOARD_STATUSES
from app.domain.analytics.statistics import (
    correlation_summary,
)
from app.domain.analytics.statistics import (
    pearson_coefficient as pearson_coefficient,
)
from app.domain.analytics.statistics import (
    select_latest_referral_facts as select_latest_referral_facts,
)
from app.domain.analytics.statistics import (
    weighted_mean as _weighted_mean,
)
from app.domain.analytics.tasks import payload_window, raise_if_task_terminal

# Calendar bucketing (day | ISO-Monday week | 1st-of-month, first label
# clamped to the window), the persisted series-point shape, and the
# additive-measure count rule are OWNED by the Traffic projection — the
# two projections share the granularity/series vocabulary, so those have
# one owner too (invariant 2).
from app.domain.traffic.projection import (
    bucket_labels,
    bucket_start,
    metric_count,
    series_point,
)
from app.models.analysis import MetricSnapshot, ResponseAnalysis
from app.models.analytics import (
    AnalyticsSnapshot,
    AnalyticsTask,
    ReferralClassification,
    ReferralEvent,
)
from app.models.audit import Audit, AuditPromptSnapshot
from app.models.integrations import IntegrationMetricRow

# Bounded work per read batch: each batch is one cooperative-cancel boundary
# (the WRITE phase is a single transaction). Module constant (not config) —
# the same precedent as A6's ``_CLASSIFY_BATCH_SIZE``; tests monkeypatch it
# down to 1 to exercise the boundary per row.
_CLASSIFICATION_BATCH_SIZE = 1000

# Rounding conventions mirrored from the run-level aggregate
# (``analysis/scoring.py``): rates round to 4, visibility scores to 2. The
# correlation coefficient rounds to 6 so re-runs serialize identically.
_RATE_DECIMALS = 4
_SCORE_DECIMALS = 2


# --- Pure projection inputs (the executor reduces ORM rows to these) ---------


@dataclass(frozen=True)
class ReferralFactInput:
    """One canonical GA4 metric row with optional referral classification.

    ``row_identity`` always identifies the metric row revision and
    ``occurred_date`` is that row's date. ``classification_id`` and
    ``is_ai_referral`` remain NULL when the row has not been classified, so
    incomplete evidence stays unmeasured. ``sessions`` is the row's measured
    session count (0 when the metric payload lacks a numeric value).
    """

    classification_id: uuid.UUID | None
    is_ai_referral: bool | None
    ai_source: str
    occurred_date: date
    sessions: int
    row_identity: tuple[str, str, str, date, str] | None
    resync_seq: int


@dataclass(frozen=True)
class VisibilityFactInput:
    """One folded ``MetricSnapshot`` reduced for the visibility series.

    ``engine_scores`` carries the snapshot's per-engine visibility scores
    (0-100) as sorted ``(logical_engine, score)`` pairs; ``visibility_score``
    is the project-level 0-100 score used by the correlation fold.
    """

    snapshot_id: uuid.UUID
    completed_date: date
    visibility_score: float
    total_completed: int
    engine_scores: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class ThemeFactInput:
    """One per-execution analysis reduced for the theme rollup.

    ``competitors_mentioned`` is the count of DISTINCT competitors credited
    with a mention in this execution (each competitor contributes at most
    one mention incidence per execution — the run-level SOV definition).
    """

    theme: str
    intent: str
    brand_mentioned: bool
    competitors_mentioned: int


@dataclass(frozen=True)
class AnalyticsProjection:
    """The full projection for one (window, granularity), ready to persist.

    ``metrics`` carries the exact DTO fragments the read API serves
    (series / sources / engine visibility / correlation / themes); the
    top-level provenance lists are the folded evidence ids (sorted string
    UUIDs, so re-runs serialize identically).
    """

    granularity: str
    metrics: dict[str, Any]
    source_classification_ids: list[str]
    source_snapshot_ids: list[str]


# --- Pure math ---------------------------------------------------------------


def _source_sort_key(source: Mapping[str, Any]) -> tuple[int, str]:
    """Stable descending-session source ordering."""
    return (-int(source["sessions"]), str(source["ai_source"]))


def _referral_aggregates(
    latest: Sequence[ReferralFactInput],
    *,
    window_start: date,
    window_end: date,
    granularity: str,
) -> tuple[
    dict[date, int],
    dict[date, int],
    set[date],
    set[date],
    dict[str, int],
    int,
    bool,
]:
    bucket_ai: dict[date, int] = {}
    bucket_total: dict[date, int] = {}
    bucket_measured: set[date] = set()
    bucket_unclassified: set[date] = set()
    source_sessions: dict[str, int] = {}
    window_total = 0
    window_has_unclassified = False
    for referral_fact in latest:
        if not window_start <= referral_fact.occurred_date <= window_end:
            continue
        bucket = bucket_start(referral_fact.occurred_date, granularity)
        bucket_measured.add(bucket)
        bucket_total[bucket] = bucket_total.get(bucket, 0) + referral_fact.sessions
        window_total += referral_fact.sessions
        if referral_fact.is_ai_referral is None:
            bucket_unclassified.add(bucket)
            window_has_unclassified = True
            continue
        if referral_fact.is_ai_referral:
            bucket_ai[bucket] = bucket_ai.get(bucket, 0) + referral_fact.sessions
            source_sessions[referral_fact.ai_source] = (
                source_sessions.get(referral_fact.ai_source, 0) + referral_fact.sessions
            )
    return (
        bucket_ai,
        bucket_total,
        bucket_measured,
        bucket_unclassified,
        source_sessions,
        window_total,
        window_has_unclassified,
    )


def _referral_metrics(
    latest: Sequence[ReferralFactInput],
    *,
    window_start: date,
    window_end: date,
    granularity: str,
    labels: Sequence[date],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build the referral series and source breakdown from latest facts."""
    (
        bucket_ai,
        bucket_total,
        bucket_measured,
        bucket_unclassified,
        source_sessions,
        window_total,
        window_has_unclassified,
    ) = _referral_aggregates(
        latest,
        window_start=window_start,
        window_end=window_end,
        granularity=granularity,
    )

    referral_volume: list[dict[str, Any]] = []
    referral_share: list[dict[str, Any]] = []
    for label in labels:
        bucket = bucket_start(label, granularity)
        if bucket not in bucket_measured or bucket in bucket_unclassified:
            referral_volume.append(series_point(label, None))
            referral_share.append(series_point(label, None))
            continue
        ai_sessions = bucket_ai.get(bucket, 0)
        total_sessions = bucket_total.get(bucket, 0)
        referral_volume.append(series_point(label, ai_sessions))
        referral_share.append(
            series_point(
                label,
                ai_sessions / total_sessions if total_sessions > 0 else None,
            )
        )

    sources: list[dict[str, Any]] = (
        [
            {
                "ai_source": ai_source,
                "sessions": sessions,
                "share": sessions / window_total if window_total > 0 else None,
            }
            for ai_source, sessions in source_sessions.items()
            if sessions > 0
        ]
        if not window_has_unclassified
        else []
    )
    sources.sort(key=_source_sort_key)
    return referral_volume, referral_share, sources


def _correlation_metric(
    latest: Sequence[ReferralFactInput],
    facts: Sequence[VisibilityFactInput],
    *,
    window_start: date,
    window_end: date,
) -> dict[str, Any]:
    """Build the always-day-aligned visibility/referral correlation."""
    day_visibility: dict[date, list[tuple[float, int]]] = {}
    for visibility_fact in facts:
        if window_start <= visibility_fact.completed_date <= window_end:
            day_visibility.setdefault(visibility_fact.completed_date, []).append(
                (visibility_fact.visibility_score, visibility_fact.total_completed)
            )
    day_ai: dict[date, int] = {}
    for referral_fact in latest:
        if (
            referral_fact.is_ai_referral
            and window_start <= referral_fact.occurred_date <= window_end
        ):
            day_ai[referral_fact.occurred_date] = (
                day_ai.get(referral_fact.occurred_date, 0) + referral_fact.sessions
            )
    aligned = [
        (mean, float(day_ai[day]))
        for day in sorted(day_visibility)
        if (mean := _weighted_mean(day_visibility[day])) is not None and day in day_ai
    ]
    return correlation_summary(aligned)


def _theme_metrics(facts: Sequence[ThemeFactInput]) -> list[dict[str, Any]]:
    """Build the window-level theme rollup in deterministic key order."""
    theme_groups: dict[tuple[str, str], list[ThemeFactInput]] = {}
    for theme_fact in facts:
        theme_groups.setdefault((theme_fact.theme, theme_fact.intent), []).append(
            theme_fact
        )
    themes: list[dict[str, Any]] = []
    for (theme, intent), group in sorted(theme_groups.items()):
        total_completed = len(group)
        brand_mentions = sum(1 for theme_fact in group if theme_fact.brand_mentioned)
        competitor_incidences = sum(
            theme_fact.competitors_mentioned for theme_fact in group
        )
        mention_volume = brand_mentions + competitor_incidences
        brand_mention_rate = (
            round(brand_mentions / total_completed, _RATE_DECIMALS)
            if total_completed > 0
            else None
        )
        themes.append(
            {
                "theme": theme,
                "intent": intent,
                "total_completed": total_completed,
                "brand_mention_rate": brand_mention_rate,
                "visibility_score": (
                    round(brand_mention_rate * 100, _SCORE_DECIMALS)
                    if brand_mention_rate is not None
                    else None
                ),
                "share_of_voice": (
                    round(brand_mentions / mention_volume, _RATE_DECIMALS)
                    if mention_volume > 0
                    else None
                ),
            }
        )
    return themes


def build_analytics_projection(
    *,
    referral_facts: Sequence[ReferralFactInput],
    visibility_facts: Sequence[VisibilityFactInput],
    theme_facts: Sequence[ThemeFactInput],
    window_start: date,
    window_end: date,
    granularity: str,
) -> AnalyticsProjection:
    """Fold the reduced inputs into one snapshot's metrics + provenance.

    PURE: no DB, no network, no clock — the same inputs always yield
    byte-identical metrics and provenance (invariants 7 + 9).
    Latest-``resync_seq`` selection is applied INSIDE so a stale revision
    can never leak in, and the module docstring documents every formula.
    """
    if granularity not in ANALYTICS_SNAPSHOT_GRANULARITIES:
        raise ValueError(f"unknown analytics granularity: {granularity!r}")
    if window_end < window_start:
        raise ValueError("analytics window_end before window_start")

    latest = select_latest_referral_facts(referral_facts)
    labels = bucket_labels(window_start, window_end, granularity)

    referral_volume, referral_share, sources = _referral_metrics(
        latest,
        window_start=window_start,
        window_end=window_end,
        granularity=granularity,
        labels=labels,
    )
    return AnalyticsProjection(
        granularity=granularity,
        metrics={
            "referral_volume": referral_volume,
            "referral_share": referral_share,
            "sources": sources,
        },
        source_classification_ids=sorted(
            str(fact.classification_id)
            for fact in latest
            if fact.classification_id is not None
        ),
        source_snapshot_ids=[],
    )


# --- Executor ----------------------------------------------------------------


async def _raise_if_task_terminal(
    session_factory: async_sessionmaker[AsyncSession], task_id: uuid.UUID | None
) -> None:
    """Cooperative-cancel boundary check (invariant 9).

    Thin label adapter over the single owner (``domain/analytics/tasks.py``)
    so this executor's message names its own batch boundary and tests keep
    a module-local patch point. The refresh writes nothing before its
    single write transaction, so stopping here leaves no partial
    projection behind.
    """
    await raise_if_task_terminal(
        session_factory, task_id, boundary="classification batch"
    )


def _window_bounds(window_start: date, window_end: date) -> tuple[datetime, datetime]:
    """The inclusive-window UTC datetimes [start 00:00, end+1day 00:00)."""
    start_dt = datetime.combine(window_start, time.min, tzinfo=UTC)
    end_dt = datetime.combine(window_end + timedelta(days=1), time.min, tzinfo=UTC)
    return start_dt, end_dt


async def _classification_batch(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    after_id: uuid.UUID | None,
    limit: int,
) -> list[
    tuple[IntegrationMetricRow, ReferralEvent | None, ReferralClassification | None]
]:
    """One keyset batch anchored on canonical source/medium metric rows.

    Workspace + project scoped (invariant 5); the metric-row keyset order
    keeps the scan stable across batches. Event and classification are OUTER
    joins so missing classification remains unknown; latest-
    ``resync_seq`` selection is applied by the pure projection (one owner
    of the rule), not here.
    """
    stmt = (
        select(IntegrationMetricRow, ReferralEvent, ReferralClassification)
        .outerjoin(
            ReferralEvent,
            and_(
                ReferralEvent.source_metric_row_id == IntegrationMetricRow.id,
                ReferralEvent.workspace_id == workspace_id,
                ReferralEvent.project_id == project_id,
            ),
        )
        .outerjoin(
            ReferralClassification,
            and_(
                ReferralClassification.referral_event_id == ReferralEvent.id,
                ReferralClassification.workspace_id == workspace_id,
                ReferralClassification.project_id == project_id,
            ),
        )
        .where(IntegrationMetricRow.workspace_id == workspace_id)
        .where(IntegrationMetricRow.project_id == project_id)
        .where(IntegrationMetricRow.date >= window_start)
        .where(IntegrationMetricRow.date <= window_end)
        .where(IntegrationMetricRow.dataset == DATASET_GA4_SOURCE_MEDIUM_DAILY)
        .order_by(IntegrationMetricRow.id.asc())
        .limit(limit)
    )
    if after_id is not None:
        stmt = stmt.where(IntegrationMetricRow.id > after_id)
    return list((await session.execute(stmt)).tuples().all())


def _to_referral_input(
    row: IntegrationMetricRow,
    _event: ReferralEvent | None,
    classification: ReferralClassification | None,
) -> ReferralFactInput:
    return ReferralFactInput(
        classification_id=classification.id if classification is not None else None,
        is_ai_referral=(
            bool(classification.is_ai_referral) if classification is not None else None
        ),
        ai_source=classification.ai_source if classification is not None else "",
        occurred_date=row.date,
        sessions=metric_count(row.metrics, "sessions"),
        row_identity=(
            row.property_ref,
            row.provider,
            row.dataset,
            row.date,
            row.dimension_key,
        ),
        resync_seq=row.resync_seq,
    )


def _engine_scores(metrics: dict | None) -> tuple[tuple[str, float], ...]:
    """The snapshot's per-engine visibility scores (0-100), sorted.

    Mirrors the run-level headline (``visibility_score`` =
    ``brand_mention_rate * 100``) per engine; an engine with no numeric
    rate in this snapshot's ``per_engine`` block contributes nothing.
    """
    per_engine = (metrics or {}).get("per_engine") or {}
    scores: list[tuple[str, float]] = []
    for engine, aggregate in per_engine.items():
        rate = (aggregate or {}).get("brand_mention_rate")
        if isinstance(rate, (int, float)):
            scores.append((str(engine), float(rate) * 100.0))
    return tuple(sorted(scores))


async def _visibility_facts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> list[VisibilityFactInput]:
    """The window's folded ``MetricSnapshot`` rows (dashboard audits only).

    Mirrors the trends query pattern (``domain/analysis/service.py``):
    workspace/project scoped, dashboard statuses, non-null completion,
    inclusive UTC window — a pure read of persisted rows (invariant 7).
    """
    start_dt, end_dt = _window_bounds(window_start, window_end)
    stmt = (
        select(MetricSnapshot, Audit.completed_at)
        .join(Audit, Audit.id == MetricSnapshot.audit_id)
        .where(MetricSnapshot.workspace_id == workspace_id)
        .where(MetricSnapshot.project_id == project_id)
        .where(Audit.workspace_id == workspace_id)
        .where(Audit.project_id == project_id)
        .where(Audit.status.in_(_DASHBOARD_STATUSES))
        .where(Audit.completed_at.is_not(None))
        .where(Audit.completed_at >= start_dt)
        .where(Audit.completed_at < end_dt)
        .order_by(Audit.completed_at.asc(), MetricSnapshot.id.asc())
    )
    facts: list[VisibilityFactInput] = []
    for snapshot, completed_at in (await session.execute(stmt)).tuples().all():
        if completed_at is None:
            continue  # defensive: the query already filters completed_at NOT NULL
        facts.append(
            VisibilityFactInput(
                snapshot_id=snapshot.id,
                # Bucket by the AUDIT's completion day (the run's measured
                # instant), never the snapshot row's write time.
                completed_date=completed_at.date(),
                visibility_score=float(snapshot.visibility_score or 0.0),
                total_completed=int(snapshot.total_completed or 0),
                engine_scores=_engine_scores(snapshot.metrics),
            )
        )
    return facts


async def _theme_facts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
) -> list[ThemeFactInput]:
    """The window's per-execution rows joined to their frozen prompt axes.

    ``ResponseAnalysis`` carries ``(audit_id, prompt_index)``; the frozen
    ``AuditPromptSnapshot`` (unique per the same tuple) supplies the
    theme/intent axes the rollup groups by — a later edit to the source
    prompt never rewrites what the audit measured (invariant 3).
    """
    start_dt, end_dt = _window_bounds(window_start, window_end)
    stmt = (
        select(ResponseAnalysis, AuditPromptSnapshot)
        .join(Audit, Audit.id == ResponseAnalysis.audit_id)
        .join(
            AuditPromptSnapshot,
            and_(
                AuditPromptSnapshot.audit_id == ResponseAnalysis.audit_id,
                AuditPromptSnapshot.prompt_index == ResponseAnalysis.prompt_index,
            ),
        )
        .where(ResponseAnalysis.workspace_id == workspace_id)
        .where(Audit.workspace_id == workspace_id)
        .where(Audit.project_id == project_id)
        .where(Audit.status.in_(_DASHBOARD_STATUSES))
        .where(Audit.completed_at.is_not(None))
        .where(Audit.completed_at >= start_dt)
        .where(Audit.completed_at < end_dt)
        .order_by(ResponseAnalysis.id.asc())
    )
    facts: list[ThemeFactInput] = []
    for analysis, prompt_snapshot in (await session.execute(stmt)).tuples().all():
        score = analysis.score or {}
        competitors = score.get("competitors_mentioned") or []
        facts.append(
            ThemeFactInput(
                theme=prompt_snapshot.theme or "",
                intent=prompt_snapshot.intent or "",
                brand_mentioned=bool(analysis.brand_mentioned),
                competitors_mentioned=len(set(competitors)),
            )
        )
    return facts


async def _upsert_snapshot(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    window_start: date,
    window_end: date,
    granularity: str,
    projection: AnalyticsProjection,
) -> None:
    """The transactional upsert of the one current snapshot row.

    ``INSERT ... ON CONFLICT (project_id, window_start, window_end,
    granularity) DO UPDATE`` — concurrent refreshes serialize on the unique
    row and can never create a duplicate "current" snapshot (precedent:
    ``domain/traffic/service.py``). The conflict target's workspace cannot
    drift (one project lives in one workspace), so only the projection
    payload + provenance + version stamps are updated.
    """
    stmt = (
        pg_insert(AnalyticsSnapshot)
        .values(
            workspace_id=task.workspace_id,
            project_id=task.project_id,
            window_start=window_start,
            window_end=window_end,
            granularity=granularity,
            metrics=projection.metrics,
            source_classification_ids=projection.source_classification_ids,
            source_snapshot_ids=projection.source_snapshot_ids,
            analyzer_version=AI_REFERRAL_ANALYZER_VERSION,
            formula_version=AI_REFERRAL_FORMULA_VERSION,
        )
        .on_conflict_do_update(
            index_elements=[
                "project_id",
                "window_start",
                "window_end",
                "granularity",
            ],
            set_={
                "metrics": projection.metrics,
                "source_classification_ids": projection.source_classification_ids,
                "source_snapshot_ids": projection.source_snapshot_ids,
                "analyzer_version": AI_REFERRAL_ANALYZER_VERSION,
                "formula_version": AI_REFERRAL_FORMULA_VERSION,
            },
        )
    )
    await session.execute(stmt)


async def refresh_analytics_snapshot(
    session_factory: async_sessionmaker[AsyncSession], task: AnalyticsTask
) -> None:
    """``analytics_snapshot_refresh`` executor: rebuild one window's snapshots.

    Read phase: every canonical GA4 source/medium metric row in the window,
    left-linked to its optional referral event and classification, in bounded
    keyset batches (cooperative cancel at every batch boundary). Write phase:
    for each configured granularity
    (``ANALYTICS_SNAPSHOT_GRANULARITIES``) the pure projection is upserted —
    ALL of it in ONE transaction (one commit), so a refresh never leaves a
    half-written snapshot family. NO provider I/O (invariant 7).
    """
    if task.project_id is None:
        raise ValueError("analytics_snapshot_refresh task missing project_id")
    window_start, window_end = payload_window(task, kind="analytics_snapshot_refresh")
    async with session_factory() as session:
        referral_facts: list[ReferralFactInput] = []
        after_id: uuid.UUID | None = None
        while True:
            await _raise_if_task_terminal(session_factory, task.id)
            batch = await _classification_batch(
                session,
                workspace_id=task.workspace_id,
                project_id=task.project_id,
                window_start=window_start,
                window_end=window_end,
                after_id=after_id,
                limit=_CLASSIFICATION_BATCH_SIZE,
            )
            if not batch:
                break
            referral_facts.extend(
                _to_referral_input(row, event, classification)
                for row, event, classification in batch
            )
            after_id = batch[-1][0].id
            if len(batch) < _CLASSIFICATION_BATCH_SIZE:
                break

        for granularity in sorted(ANALYTICS_SNAPSHOT_GRANULARITIES):
            projection = build_analytics_projection(
                referral_facts=referral_facts,
                visibility_facts=(),
                theme_facts=(),
                window_start=window_start,
                window_end=window_end,
                granularity=granularity,
            )
            await _upsert_snapshot(
                session,
                task=task,
                window_start=window_start,
                window_end=window_end,
                granularity=granularity,
                projection=projection,
            )
        await session.commit()
