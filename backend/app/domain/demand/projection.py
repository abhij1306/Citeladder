"""Pure deterministic Demand signal detection and prioritization."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config.demand import (
    DEMAND_FORMULA_VERSION,
    DEMAND_LOW_CTR_THRESHOLD,
    DEMAND_MIN_IMPRESSIONS,
    DEMAND_QUESTION_GAP_WEIGHT,
    DEMAND_RULE_VERSION,
    DEMAND_SEARCH_GAP_WEIGHT,
    DEMAND_SIGNAL_HIGH_IMPRESSION_LOW_CTR,
    DEMAND_SIGNAL_STATE_ACTIVE,
    DEMAND_SIGNAL_UNANSWERED_QUESTION,
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


def detect_question_gap_signals(
    questions: list[dict[str, Any]], *, site_snapshot_id: uuid.UUID
) -> list[DemandSignalCandidate]:
    candidates: list[DemandSignalCandidate] = []
    seen_question_ids: set[str] = set()
    for question in sorted(
        questions, key=lambda item: str(item.get("question_id") or "")
    ):
        state = str(question.get("state") or "")
        if state in {"answered_strong", "answered_weak", "not_applicable"}:
            continue
        question_id = str(question.get("question_id") or "")
        if not question_id or question_id in seen_question_ids:
            continue
        seen_question_ids.add(question_id)
        priority, inputs = _priority(
            impressions=0, ctr=None, gap=DEMAND_QUESTION_GAP_WEIGHT
        )
        candidates.append(
            DemandSignalCandidate(
                identity_hash=stable_hash(
                    {
                        "type": DEMAND_SIGNAL_UNANSWERED_QUESTION,
                        "question_id": question_id,
                        "rule_version": DEMAND_RULE_VERSION,
                    }
                ),
                signal_type=DEMAND_SIGNAL_UNANSWERED_QUESTION,
                state=DEMAND_SIGNAL_STATE_ACTIVE,
                topic_cluster=str(question.get("label") or question_id),
                page_url="",
                evidence={
                    "site_snapshot_id": str(site_snapshot_id),
                    "question_id": question_id,
                    "question_state": state,
                    "reason": str(question.get("reason") or ""),
                },
                metrics={},
                coverage={"site_question": "observed", "search_demand": "unavailable"},
                limitations=[
                    "No compatible GSC demand was joined to this pack question."
                ],
                priority_score=priority,
                priority_inputs=inputs,
            )
        )
    return candidates
