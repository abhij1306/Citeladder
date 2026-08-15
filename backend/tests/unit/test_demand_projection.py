from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain.demand.projection import (
    QueryEvidenceInput,
    SearchDemandInput,
    detect_search_signals,
    detect_striking_distance,
)
from app.domain.demand.query_detectors import (
    detect_cannibalization,
    detect_property_relative_ctr_gap,
    detect_query_trends,
)
from app.domain.demand.query_evidence import _insert_snapshot_or_get_existing
from app.models.demand import QueryEvidenceSnapshot


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


def _query_row(
    query: str,
    *,
    classification: str = "non_branded",
    impressions: int = 50,
    position: float | None = 4.0,
    outcome: str = "exact",
    page_url: str | None = None,
    clicks: int = 2,
    observed_date: date = date(2026, 7, 1),
    property_ref: str = "sc-domain:example.com",
) -> QueryEvidenceInput:
    return QueryEvidenceInput(
        observed_date=observed_date,
        property_ref=property_ref,
        normalized_query=query,
        resolved_page_url=page_url or f"https://example.com/{query.replace(' ', '-')}",
        resolution_outcome=outcome,
        classification=classification,
        classifier_version="branded-query-1",
        classification_override_id=None,
        impressions=impressions,
        clicks=clicks,
        position=position,
        source_metric_row_id=f"row-{query}",
        source_artifact_id="artifact",
    )


def test_striking_distance_includes_exact_thresholds_and_branded_cohort() -> None:
    evaluation = detect_striking_distance(
        [
            _query_row("lower bound"),
            _query_row("upper bound", position=15.0),
            _query_row("brand", classification="branded", position=1.0),
        ]
    )

    assert evaluation.state == "available"
    assert [item.signal_type for item in evaluation.candidates] == [
        "branded_query_performance",
        "striking_distance",
        "striking_distance",
    ]
    assert evaluation.counts_by_classification == {
        "branded": 1,
        "non_branded": 2,
        "ambiguous": 0,
    }
    assert evaluation.candidates[0].evidence["classifier_versions"] == [
        "branded-query-1"
    ]


def test_striking_distance_abstains_for_boundaries_without_evidence() -> None:
    evaluation = detect_striking_distance(
        [
            _query_row("low volume", impressions=49),
            _query_row("too high", position=15.01),
            _query_row("ambiguous", classification="ambiguous"),
            _query_row("unresolved", outcome="unresolved"),
            _query_row("no position", position=None),
        ]
    )

    assert evaluation.candidates == ()
    assert evaluation.state == "partial"
    assert evaluation.limitations


def test_striking_distance_reports_unavailable_without_rows() -> None:
    evaluation = detect_striking_distance([])
    assert evaluation.state == "unavailable"
    assert evaluation.candidates == ()


def test_cannibalization_requires_two_resolved_pages_at_both_thresholds() -> None:
    positive = detect_cannibalization(
        [
            _query_row(
                "shared query", impressions=180, page_url="https://example.com/a"
            ),
            _query_row(
                "shared query", impressions=20, page_url="https://example.com/b"
            ),
        ]
    )
    assert [item.signal_type for item in positive.candidates] == [
        "query_cannibalization"
    ]
    assert positive.candidates[0].metrics["qualifying_page_count"] == 2
    assert positive.candidates[0].evidence["classifier_versions"] == ["branded-query-1"]

    boundary = detect_cannibalization(
        [
            _query_row(
                "shared query", impressions=181, page_url="https://example.com/a"
            ),
            _query_row(
                "shared query", impressions=19, page_url="https://example.com/b"
            ),
        ]
    )
    unresolved = detect_cannibalization([_query_row("unknown", outcome="unresolved")])
    assert boundary.candidates == ()
    assert unresolved.state == "partial"


def test_property_relative_ctr_gap_uses_only_qualified_property_cohort() -> None:
    rows = [
        _query_row(f"cohort {index}", impressions=30, clicks=3, position=5.4)
        for index in range(19)
    ]
    rows.append(_query_row("gap", impressions=100, clicks=5, position=5.8))
    evaluation = detect_property_relative_ctr_gap(rows)
    assert evaluation.state == "available"
    assert [item.signal_type for item in evaluation.candidates] == [
        "property_relative_ctr_gap"
    ]
    assert evaluation.candidates[0].metrics["cohort_row_count"] == 20

    thin = detect_property_relative_ctr_gap(rows[:19])
    assert thin.state == "unavailable"
    assert thin.candidates == ()

    zero_impression = detect_property_relative_ctr_gap(
        [_query_row("zero", impressions=0, clicks=0, position=5.0)]
    )
    assert zero_impression.state == "unavailable"
    assert zero_impression.candidates == ()


def test_query_trends_prove_both_classes_and_reject_26_day_history() -> None:
    end = date(2026, 7, 28)
    rows: list[QueryEvidenceInput] = []
    for offset in range(28):
        observed = date(2026, 7, 1) + timedelta(days=offset)
        recent = offset >= 14
        rows.extend(
            [
                _query_row(
                    "emerging",
                    impressions=4 if recent else 2,
                    observed_date=observed,
                ),
                _query_row(
                    "declining",
                    impressions=2 if recent else 4,
                    observed_date=observed,
                ),
            ]
        )
    evaluation = detect_query_trends(rows, window_end=end)
    assert evaluation.state == "available"
    assert {item.signal_type for item in evaluation.candidates} == {
        "emerging_query",
        "declining_query",
    }

    thin = detect_query_trends(rows[4:], window_end=end)
    assert thin.state == "insufficient_history"
    assert thin.candidates == ()

    sparse = detect_query_trends(
        [
            _query_row("sparse", impressions=30, observed_date=date(2026, 7, 1)),
            _query_row("sparse", impressions=60, observed_date=end),
        ],
        window_end=end,
    )
    assert sparse.state == "insufficient_history"
    assert sparse.candidates == ()


@pytest.mark.asyncio
async def test_equal_concurrent_query_snapshot_insert_reuses_winner() -> None:
    snapshot = QueryEvidenceSnapshot(
        workspace_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        window_start=date(2026, 7, 1),
        window_end=date(2026, 7, 28),
        source_hash="a" * 64,
        state="available",
        source_metric_row_ids=[],
        source_artifact_ids=[],
        coverage={},
        limitations=[],
        analyzer_version="query-evidence-3",
        resolver_version="owned-page-resolver-2",
    )
    winner = QueryEvidenceSnapshot(
        workspace_id=snapshot.workspace_id,
        project_id=snapshot.project_id,
        window_start=snapshot.window_start,
        window_end=snapshot.window_end,
        source_hash=snapshot.source_hash,
        state="available",
        source_metric_row_ids=[],
        source_artifact_ids=[],
        coverage={},
        limitations=[],
        analyzer_version=snapshot.analyzer_version,
        resolver_version=snapshot.resolver_version,
    )

    class _UniqueViolation(Exception):
        constraint_name = "uq_query_evidence_snapshot_identity"

    class _Nested:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    class _Session:
        def begin_nested(self):
            return _Nested()

        def add(self, _row):
            return None

        async def flush(self):
            raise IntegrityError("insert", {}, _UniqueViolation())

        async def scalar(self, _statement):
            return winner

    result = await _insert_snapshot_or_get_existing(  # type: ignore[arg-type]
        _Session(), snapshot
    )
    assert result is winner
