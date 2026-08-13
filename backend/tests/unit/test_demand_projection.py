from __future__ import annotations

from app.domain.demand.projection import (
    SearchDemandInput,
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
