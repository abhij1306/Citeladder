"""Folding persisted snapshots into visibility-trend points.

The seam is a natural one: everything here is deterministic and does no I/O,
operating only on values already projected from persisted rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import overload

from app.core.config.analysis import VISIBILITY_TRENDS_STRICT_VERSION_BUCKETS
from app.domain.analysis.schemas import (
    ModelProvenance,
    VisibilityTrendPoint,
    VisibilityTrendRankingRow,
    VisibilityTrendSov,
)
from app.domain.audits.schemas import build_model_provenance


@dataclass
class _RankingAccumulator:
    """Running mention/rate sums for one entity across a bucket's snapshots."""

    name: str
    is_brand: bool
    mention_count: int = 0
    # Completion-weighted rate numerators (rate * completions) with a SEPARATE
    # denominator per rate, so a snapshot that reports one rate but not the
    # other does not dilute the missing one as though it were zero.
    mention_rate_weight: float = 0.0
    mention_rate_denom: int = 0
    citation_rate_weight: float = 0.0
    citation_rate_denom: int = 0


@dataclass
class _RateAccumulator:
    """Completion-weighted numerator/denominator for a single headline rate."""

    weighted: float = 0.0
    weight: int = 0

    def add(self, rate: float | None, completions: int) -> None:
        if rate is None or completions <= 0:
            return
        self.weighted += float(rate) * completions
        self.weight += completions

    def value(self) -> float | None:
        if self.weight <= 0:
            return None
        return round(self.weighted / self.weight, 4)


@overload
def _to_utc(value: datetime) -> datetime: ...


@overload
def _to_utc(value: None) -> None: ...


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        # Defensive: the query layer already rejects naive datetimes.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


@dataclass
class _TrendSource:
    """One dashboard-ready snapshot projected into trend-ready primitives.

    A raw point folds exactly one of these; a bucket folds many. ``metrics`` is
    the persisted per-run metrics dict, or the engine slice
    (``metrics.per_engine[engine]``) when the request is engine-filtered.
    ``(measurement_mode, transport_model, retrieval_enabled)`` is the frozen
    folding identity: sources may be folded together ONLY when all three match.
    """

    snapshot_id: uuid.UUID
    audit_id: uuid.UUID
    completed_at: datetime
    logical_engine: str | None
    measurement_mode: str
    transport_model: str | None
    retrieval_enabled: bool | None
    model_provenance: list[ModelProvenance]
    analyzer_version: str
    scoring_rule_version: str
    total_completed: int
    visibility_score: float | None
    metrics: dict


@dataclass
class _BucketAccumulators:
    """Mutable pure-fold state for one compatible trend bucket."""

    visibility: _RateAccumulator = field(default_factory=_RateAccumulator)
    brand_rate: _RateAccumulator = field(default_factory=_RateAccumulator)
    owned_rate: _RateAccumulator = field(default_factory=_RateAccumulator)
    response_sov: _RateAccumulator = field(default_factory=_RateAccumulator)
    mention_counts: dict[str, int] = field(default_factory=dict)
    rankings: dict[str, _RankingAccumulator] = field(default_factory=dict)
    brand_names: set[str] = field(default_factory=set)


def _brand_name(counts: dict, metrics: dict) -> str:
    # The SOV block keys the brand by its display name; the first non-competitor
    # entry is the brand. Fall back to a stable label.
    competitor_names = set(metrics.get("competitor_mention_rate") or {})
    for name in counts:
        if name not in competitor_names:
            return name
    return "Brand"


def _response_sov(metrics: dict) -> float | None:
    """Response-level SOV: brand presence share vs competitor presence rates.

    Deterministically derived from the persisted brand/competitor
    response-presence rates already in the snapshot — no re-read of responses.
    """
    brand_rate = metrics.get("brand_mention_rate")
    competitor_rate = metrics.get("competitor_mention_rate") or {}
    if brand_rate is None:
        return None
    total = float(brand_rate) + sum(
        float(v) for v in competitor_rate.values() if v is not None
    )
    if total <= 0:
        return 0.0
    return round(float(brand_rate) / total, 4)


def _mention_sov_of(counts: dict, names: set[str]) -> float | None:
    """Mention-level SOV summed over every brand key present in the bucket.

    Brand naming can change across snapshots in one bucket, so the numerator
    aggregates counts across all brand keys rather than a single name.
    """
    total = sum(int(v or 0) for v in counts.values())
    if total <= 0:
        return None
    brand_total = sum(int(counts.get(name, 0) or 0) for name in names)
    return round(brand_total / total, 4)


def _trend_rankings(metrics: dict) -> list[VisibilityTrendRankingRow]:
    """Brand-vs-competitor ranking rows for a raw point (persisted counts)."""
    sov = metrics.get("share_of_voice") or {}
    counts = sov.get("mention_counts") or {}
    share = sov.get("share") or {}
    brand_name = _brand_name(counts, metrics)
    competitor_mention = metrics.get("competitor_mention_rate") or {}
    competitor_citation = metrics.get("competitor_citation_rate") or {}

    rows: list[VisibilityTrendRankingRow] = [
        VisibilityTrendRankingRow(
            name=brand_name,
            is_brand=True,
            mention_rate=metrics.get("brand_mention_rate"),
            citation_rate=metrics.get("owned_citation_rate"),
            share_of_voice=share.get(brand_name),
            mention_count=int(counts.get(brand_name, 0) or 0),
        )
    ]
    for name in competitor_mention:
        rows.append(
            VisibilityTrendRankingRow(
                name=name,
                is_brand=False,
                mention_rate=competitor_mention.get(name),
                citation_rate=competitor_citation.get(name),
                share_of_voice=share.get(name),
                mention_count=int(counts.get(name, 0) or 0),
            )
        )
    rows.sort(key=lambda r: (-(r.share_of_voice or 0.0), r.name))
    return rows


def _raw_point(source: _TrendSource) -> VisibilityTrendPoint:
    metrics = source.metrics
    sov = metrics.get("share_of_voice") or {}
    counts = sov.get("mention_counts") or {}
    brand_name = _brand_name(counts, metrics)
    return VisibilityTrendPoint(
        audit_id=source.audit_id,
        completed_at=source.completed_at,
        logical_engine=source.logical_engine,
        visibility_score=source.visibility_score,
        brand_mention_rate=metrics.get("brand_mention_rate"),
        owned_citation_rate=metrics.get("owned_citation_rate"),
        sov=VisibilityTrendSov(
            response=_response_sov(metrics),
            mention=_mention_sov_of(counts, {brand_name}),
        ),
        rankings=_trend_rankings(metrics),
        sentiment=None,
        avg_position=None,
        measurement_mode=source.measurement_mode,
        transport_model=source.transport_model,
        retrieval_enabled=source.retrieval_enabled,
        model_provenance=source.model_provenance,
        source_snapshot_ids=[source.snapshot_id],
        analyzer_versions=[source.analyzer_version],
        scoring_rule_versions=[source.scoring_rule_version],
        spans_version_boundary=False,
    )


def _bucket_key(completed_at: datetime, granularity: str) -> datetime:
    """UTC bucket-start boundary for a completion timestamp."""
    at = _to_utc(completed_at)
    if granularity == "month":
        return datetime(at.year, at.month, 1, tzinfo=UTC)
    # Week: ISO Monday 00:00 UTC.
    day = datetime(at.year, at.month, at.day, tzinfo=UTC)
    return day - timedelta(days=at.weekday())


# Folding identity: ``(measurement_mode, transport_model, retrieval_enabled)``.
# Raw, weekly, and monthly folding may combine sources ONLY inside one
# identity partition (invariant 7): no point or bucket ever mixes pulse with
# benchmark, different models, or retrieval on with off.
_TrendIdentity = tuple[str, str | None, bool | None]


def _identity_of(source: _TrendSource) -> _TrendIdentity:
    return (
        source.measurement_mode,
        source.transport_model,
        source.retrieval_enabled,
    )


def _identity_sort_key(identity: _TrendIdentity) -> tuple[str, str, str]:
    """Deterministic order for partitions sharing one bucket boundary."""
    mode, model, retrieval = identity
    return (mode, model or "", "" if retrieval is None else str(retrieval))


def _bucket_points(
    sources: list[_TrendSource], granularity: str
) -> list[VisibilityTrendPoint]:
    """Fold sources into deterministic UTC week/month identity partitions.

    Sources are grouped by ``(bucket boundary, folding identity)`` so a bucket
    never blends unlike identities; unlike identities in the same week/month
    emit separate ordered points. Under strict version bucketing, if any
    partition in the selected range would mix analyzer/scoring versions the
    whole range falls back to raw points so no bucket ever blends incompatible
    formulas.
    """
    grouped: dict[tuple[datetime, _TrendIdentity], list[_TrendSource]] = {}
    for source in sources:
        key = (_bucket_key(source.completed_at, granularity), _identity_of(source))
        grouped.setdefault(key, []).append(source)

    if VISIBILITY_TRENDS_STRICT_VERSION_BUCKETS and any(
        _is_mixed_version(bucket) for bucket in grouped.values()
    ):
        return [_raw_point(source) for source in sources]

    return [
        _fold_bucket(key[0], bucket)
        for key, bucket in sorted(
            grouped.items(),
            key=lambda entry: (entry[0][0], _identity_sort_key(entry[0][1])),
        )
    ]


def _is_mixed_version(bucket: list[_TrendSource]) -> bool:
    analyzers = {s.analyzer_version for s in bucket}
    scorings = {s.scoring_rule_version for s in bucket}
    return len(analyzers) > 1 or len(scorings) > 1


def _bucket_provenance(bucket: list[_TrendSource]) -> list[ModelProvenance]:
    """The deduped, stable-ordered union of a partition's route provenance."""
    return build_model_provenance(
        item for source in bucket for item in source.model_provenance
    )


def _stored_mention_count(counts: dict, name: str) -> int:
    return int(counts.get(name, 0) or 0)


def _accumulate_bucket_ranking(
    accumulators: _BucketAccumulators,
    *,
    name: str,
    is_brand: bool,
    mention_count: int,
    mention_rate: float | None,
    citation_rate: float | None,
    completions: int,
) -> None:
    _accumulate_entity(
        accumulators.rankings,
        name=name,
        is_brand=is_brand,
        mention_count=mention_count,
        mention_rate=mention_rate,
        citation_rate=citation_rate,
        completions=completions,
    )
    accumulators.mention_counts[name] = (
        accumulators.mention_counts.get(name, 0) + mention_count
    )


def _accumulate_bucket_source(
    accumulators: _BucketAccumulators, source: _TrendSource
) -> None:
    """Add one persisted source without substituting for unknown rates."""
    metrics = source.metrics
    completions = source.total_completed
    accumulators.visibility.add(source.visibility_score, completions)
    accumulators.brand_rate.add(metrics.get("brand_mention_rate"), completions)
    accumulators.owned_rate.add(metrics.get("owned_citation_rate"), completions)
    accumulators.response_sov.add(_response_sov(metrics), completions)

    sov = metrics.get("share_of_voice") or {}
    counts = sov.get("mention_counts") or {}
    brand_name = _brand_name(counts, metrics)
    accumulators.brand_names.add(brand_name)
    _accumulate_bucket_ranking(
        accumulators,
        name=brand_name,
        is_brand=True,
        mention_count=_stored_mention_count(counts, brand_name),
        mention_rate=metrics.get("brand_mention_rate"),
        citation_rate=metrics.get("owned_citation_rate"),
        completions=completions,
    )

    competitor_mention = metrics.get("competitor_mention_rate") or {}
    competitor_citation = metrics.get("competitor_citation_rate") or {}
    for name in competitor_mention:
        _accumulate_bucket_ranking(
            accumulators,
            name=name,
            is_brand=False,
            mention_count=_stored_mention_count(counts, name),
            mention_rate=competitor_mention.get(name),
            citation_rate=competitor_citation.get(name),
            completions=completions,
        )


def _fold_bucket(key: datetime, bucket: list[_TrendSource]) -> VisibilityTrendPoint:
    logical_engine = bucket[0].logical_engine
    accumulators = _BucketAccumulators()
    for source in bucket:
        _accumulate_bucket_source(accumulators, source)

    total_mentions = sum(accumulators.mention_counts.values())
    ranking_rows = _fold_ranking_rows(
        accumulators.rankings, accumulators.mention_counts, total_mentions
    )
    # Aggregate every brand key seen in the bucket for mention-level SOV so a
    # brand rename across snapshots does not undercount brand share.
    brand_keys = accumulators.brand_names or {"Brand"}

    # Every source in the bucket shares one folding identity by construction.
    measurement_mode, transport_model, retrieval_enabled = _identity_of(bucket[0])
    return VisibilityTrendPoint(
        audit_id=None,
        completed_at=key,
        logical_engine=logical_engine,
        visibility_score=accumulators.visibility.value(),
        brand_mention_rate=accumulators.brand_rate.value(),
        owned_citation_rate=accumulators.owned_rate.value(),
        sov=VisibilityTrendSov(
            response=accumulators.response_sov.value(),
            mention=_mention_sov_of(accumulators.mention_counts, brand_keys),
        ),
        rankings=ranking_rows,
        sentiment=None,
        avg_position=None,
        measurement_mode=measurement_mode,
        transport_model=transport_model,
        retrieval_enabled=retrieval_enabled,
        model_provenance=_bucket_provenance(bucket),
        source_snapshot_ids=[source.snapshot_id for source in bucket],
        analyzer_versions=sorted({s.analyzer_version for s in bucket}),
        scoring_rule_versions=sorted({s.scoring_rule_version for s in bucket}),
        spans_version_boundary=_is_mixed_version(bucket),
    )


def _accumulate_entity(
    rankings: dict[str, _RankingAccumulator],
    *,
    name: str,
    is_brand: bool,
    mention_count: int,
    mention_rate: float | None,
    citation_rate: float | None,
    completions: int,
) -> None:
    acc = rankings.get(name)
    if acc is None:
        acc = _RankingAccumulator(name=name, is_brand=is_brand)
        rankings[name] = acc
    acc.is_brand = acc.is_brand or is_brand
    acc.mention_count += mention_count
    if completions > 0:
        if mention_rate is not None:
            acc.mention_rate_weight += float(mention_rate) * completions
            acc.mention_rate_denom += completions
        if citation_rate is not None:
            acc.citation_rate_weight += float(citation_rate) * completions
            acc.citation_rate_denom += completions


def _fold_ranking_rows(
    rankings: dict[str, _RankingAccumulator],
    mention_counts: dict[str, int],
    total_mentions: int,
) -> list[VisibilityTrendRankingRow]:
    rows: list[VisibilityTrendRankingRow] = []
    for name, acc in rankings.items():
        share = (
            round(mention_counts.get(name, 0) / total_mentions, 4)
            if total_mentions > 0
            else None
        )
        rows.append(
            VisibilityTrendRankingRow(
                name=name,
                is_brand=acc.is_brand,
                mention_rate=(
                    round(acc.mention_rate_weight / acc.mention_rate_denom, 4)
                    if acc.mention_rate_denom > 0
                    else None
                ),
                citation_rate=(
                    round(acc.citation_rate_weight / acc.citation_rate_denom, 4)
                    if acc.citation_rate_denom > 0
                    else None
                ),
                share_of_voice=share,
                mention_count=acc.mention_count,
            )
        )
    rows.sort(key=lambda r: (-(r.share_of_voice or 0.0), r.name))
    return rows
