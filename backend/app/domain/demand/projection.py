"""Pure deterministic Demand signal detection and prioritization."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

from app.core.config.demand import (
    DEMAND_FORMULA_VERSION,
    DEMAND_LOW_CTR_THRESHOLD,
    DEMAND_MIN_IMPRESSIONS,
    DEMAND_RULE_VERSION,
    DEMAND_SEARCH_GAP_WEIGHT,
    DEMAND_SIGNAL_BRANDED_QUERY,
    DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
    DEMAND_SIGNAL_STATE_ACTIVE,
    DEMAND_SIGNAL_STRIKING_DISTANCE,
    DEMAND_STRIKING_DISTANCE_GAP_WEIGHT,
    DEMAND_STRIKING_DISTANCE_MAX_POSITION,
    DEMAND_STRIKING_DISTANCE_MIN_IMPRESSIONS,
    DEMAND_STRIKING_DISTANCE_MIN_POSITION,
)


@dataclass(frozen=True)
class SearchDemandInput:
    source_metric_row_ids: tuple[str, ...]
    source_artifact_ids: tuple[str, ...]
    target_kind: str
    target: str
    impressions: int
    clicks: int


@dataclass(frozen=True)
class DemandSignalCandidate:
    identity_hash: str
    signal_type: str
    state: str
    topic_cluster: str
    page_url: str
    evidence: dict[str, Any]
    metrics: dict[str, Any]
    coverage: dict[str, Any]
    limitations: list[str]
    priority_score: float
    priority_inputs: dict[str, Any]


@dataclass(frozen=True)
class QueryEvidenceInput:
    observed_date: date
    property_ref: str
    normalized_query: str
    resolved_page_url: str
    resolution_outcome: str
    classification: str
    classifier_version: str
    classification_override_id: str | None
    impressions: int
    clicks: int
    position: float | None
    source_metric_row_id: str
    source_artifact_id: str


@dataclass(frozen=True)
class DetectorEvaluation:
    state: str
    candidates: tuple[DemandSignalCandidate, ...]
    counts_by_classification: dict[str, int]
    limitations: tuple[str, ...]


def stable_hash(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _priority(*, impressions: int, ctr: float | None, gap: float) -> tuple[float, dict]:
    demand = min(1.0, math.log1p(max(impressions, 0)) / math.log1p(10_000))
    weakness = 1.0 if ctr is None else max(0.0, 1.0 - ctr)
    score = round(100.0 * demand * weakness * gap, 2)
    return score, {
        "demand": round(demand, 6),
        "weakness": round(weakness, 6),
        "gap": gap,
        "formula_version": DEMAND_FORMULA_VERSION,
    }


def detect_search_signals(
    rows: list[SearchDemandInput],
) -> list[DemandSignalCandidate]:
    """Detect high-impression, low-click demand without inventing coverage."""
    candidates: list[DemandSignalCandidate] = []
    for row in sorted(rows, key=lambda item: (item.target_kind, item.target)):
        if row.impressions < DEMAND_MIN_IMPRESSIONS:
            continue
        ctr = row.clicks / row.impressions if row.impressions else None
        if ctr is not None and ctr > DEMAND_LOW_CTR_THRESHOLD:
            continue
        priority, inputs = _priority(
            impressions=row.impressions, ctr=ctr, gap=DEMAND_SEARCH_GAP_WEIGHT
        )
        identity = {
            "type": DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
            "target_kind": row.target_kind,
            "target": row.target,
            "rule_version": DEMAND_RULE_VERSION,
        }
        candidates.append(
            DemandSignalCandidate(
                identity_hash=stable_hash(identity),
                signal_type=DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
                state=DEMAND_SIGNAL_STATE_ACTIVE,
                topic_cluster=row.target if row.target_kind == "query" else "",
                page_url=row.target if row.target_kind == "page" else "",
                evidence={
                    "target_kind": row.target_kind,
                    "target": row.target,
                    "source_metric_row_ids": list(row.source_metric_row_ids),
                    "source_artifact_ids": list(row.source_artifact_ids),
                },
                metrics={
                    "impressions": row.impressions,
                    "clicks": row.clicks,
                    "ctr": ctr,
                },
                coverage={"search_demand": "observed"},
                limitations=["GSC detail rows may omit privacy-filtered queries."],
                priority_score=priority,
                priority_inputs=inputs,
            )
        )
    return candidates


def detect_striking_distance(rows: list[QueryEvidenceInput]) -> DetectorEvaluation:
    """Separate branded demand and detect only resolved non-branded candidates."""
    grouped: dict[tuple[str, str, str], list[QueryEvidenceInput]] = {}
    counts = {"branded": 0, "non_branded": 0, "ambiguous": 0}
    for row in rows:
        counts[row.classification] = counts.get(row.classification, 0) + 1
        if row.resolution_outcome not in {"exact", "resolved"} or row.position is None:
            continue
        grouped.setdefault(
            (row.classification, row.normalized_query, row.resolved_page_url), []
        ).append(row)

    candidates: list[DemandSignalCandidate] = []
    for key in sorted(grouped):
        classification, query, page_url = key
        aggregate = _aggregate_query_rows(grouped[key])
        if classification == "branded":
            candidates.append(
                _query_candidate(
                    signal_type=DEMAND_SIGNAL_BRANDED_QUERY,
                    query=query,
                    page_url=page_url,
                    aggregate=aggregate,
                    gap_weight=0.0,
                )
            )
        elif classification == "non_branded" and _is_striking_distance(aggregate):
            candidates.append(
                _query_candidate(
                    signal_type=DEMAND_SIGNAL_STRIKING_DISTANCE,
                    query=query,
                    page_url=page_url,
                    aggregate=aggregate,
                    gap_weight=DEMAND_STRIKING_DISTANCE_GAP_WEIGHT,
                )
            )
    state = "available" if rows else "unavailable"
    limitations = (
        "Ambiguous branded classifications and unresolved page identities abstain.",
    )
    return DetectorEvaluation(state, tuple(candidates), counts, limitations)


def _aggregate_query_rows(rows: list[QueryEvidenceInput]) -> dict[str, Any]:
    impressions = 0
    clicks = 0
    weighted_total = 0.0
    has_position = False
    metric_ids: set[str] = set()
    artifact_ids: set[str] = set()
    override_ids: set[str] = set()
    for row in rows:
        impressions += row.impressions
        clicks += row.clicks
        metric_ids.add(row.source_metric_row_id)
        artifact_ids.add(row.source_artifact_id)
        if row.position is not None and row.impressions > 0:
            has_position = True
            weighted_total += row.position * row.impressions
        if row.classification_override_id:
            override_ids.add(row.classification_override_id)
    weighted_position = (
        weighted_total / impressions if has_position and impressions else None
    )
    return {
        "impressions": impressions,
        "clicks": clicks,
        "ctr": clicks / impressions if impressions else None,
        "position": weighted_position,
        "source_metric_row_ids": sorted(metric_ids),
        "source_artifact_ids": sorted(artifact_ids),
        "classifier_version": rows[0].classifier_version,
        "classification_override_ids": sorted(override_ids),
    }


def _is_striking_distance(aggregate: dict[str, Any]) -> bool:
    position = aggregate["position"]
    return (
        aggregate["impressions"] >= DEMAND_STRIKING_DISTANCE_MIN_IMPRESSIONS
        and isinstance(position, float)
        and DEMAND_STRIKING_DISTANCE_MIN_POSITION
        <= position
        <= DEMAND_STRIKING_DISTANCE_MAX_POSITION
    )


def _query_candidate(
    *,
    signal_type: str,
    query: str,
    page_url: str,
    aggregate: dict[str, Any],
    gap_weight: float,
) -> DemandSignalCandidate:
    priority, inputs = _priority(
        impressions=aggregate["impressions"],
        ctr=aggregate["ctr"],
        gap=gap_weight,
    )
    evidence = {
        "target_kind": "query",
        "target": query,
        "resolved_page_url": page_url,
        "source_metric_row_ids": aggregate["source_metric_row_ids"],
        "source_artifact_ids": aggregate["source_artifact_ids"],
        "classifier_version": aggregate["classifier_version"],
        "classification_override_ids": aggregate["classification_override_ids"],
    }
    return DemandSignalCandidate(
        identity_hash=stable_hash(
            {
                "type": signal_type,
                "query": query,
                "page_url": page_url,
                "rule_version": DEMAND_RULE_VERSION,
            }
        ),
        signal_type=signal_type,
        state=DEMAND_SIGNAL_STATE_ACTIVE,
        topic_cluster=query,
        page_url=page_url,
        evidence=evidence,
        metrics={
            key: aggregate[key] for key in ("impressions", "clicks", "ctr", "position")
        },
        coverage={"query_evidence": "observed"},
        limitations=["GSC detail rows may omit privacy-filtered queries."],
        priority_score=priority,
        priority_inputs=inputs,
    )
