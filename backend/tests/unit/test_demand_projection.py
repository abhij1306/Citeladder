from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.domain.demand.projection import (
    SearchDemandInput,
    detect_question_gap_signals,
    detect_search_signals,
)


def test_search_detector_preserves_zero_and_unavailable_distinction() -> None:
    signal = detect_search_signals(
        [
            SearchDemandInput(
                source_metric_row_ids=("row",),
                source_artifact_ids=("artifact",),
                target_kind="query",
                target="school admission fees",
                impressions=100,
                clicks=0,
            )
        ]
    )[0]
    assert signal.metrics["clicks"] == 0
    assert signal.metrics["ctr"] == 0
    assert signal.coverage["search_demand"] == "observed"


def test_search_detector_ignores_low_volume_and_healthy_ctr() -> None:
    signals = detect_search_signals(
        [
            SearchDemandInput((), (), "query", "low", 9, 0),
            SearchDemandInput((), (), "query", "minimum", 10, 0),
            SearchDemandInput((), (), "query", "threshold", 100, 2),
            SearchDemandInput((), (), "query", "healthy", 100, 20),
        ]
    )
    assert [signal.topic_cluster for signal in signals] == ["minimum", "threshold"]


def test_question_gap_detector_excludes_answered_and_not_applicable() -> None:
    signals = detect_question_gap_signals(
        [
            {"question_id": "missing", "state": "missing", "label": "Missing?"},
            {"question_id": "missing", "state": "missing", "label": "Duplicate"},
            {"question_id": "answered", "state": "answered_strong"},
            {"question_id": "weak", "state": "answered_weak"},
            {"question_id": "excluded", "state": "not_applicable"},
            {"state": "missing"},
        ],
        site_snapshot_id=uuid.uuid4(),
    )
    assert [signal.evidence["question_id"] for signal in signals] == ["missing"]
    assert signals[0].coverage["search_demand"] == "unavailable"


def test_sanitized_asian_school_question_gap_fixture() -> None:
    fixture_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "demand"
        / "asian_school_question_gaps.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    signals = detect_question_gap_signals(
        fixture["questions"], site_snapshot_id=uuid.uuid4()
    )
    assert [row.evidence["question_id"] for row in signals] == fixture[
        "expected_signal_ids"
    ]
    assert signals[0].limitations == [
        "No compatible GSC demand was joined to this pack question."
    ]
