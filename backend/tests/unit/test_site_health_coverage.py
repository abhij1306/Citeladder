"""Conservative coverage-state decision tests."""

from __future__ import annotations

from app.core.config.site_health_contracts import (
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_FAILED,
)
from app.core.config.site_health_link_metrics import (
    COVERAGE_STATE_COMPLETE,
    COVERAGE_STATE_PARTIAL,
    COVERAGE_STATE_UNKNOWN,
)
from app.domain.site_health.coverage import CoverageSignals, assess_coverage


def _signals(**overrides: object) -> CoverageSignals:
    values: dict[str, object] = {
        "sample_mode": False,
        "input_mode": "auto",
        "manual_phase_lifecycle": False,
        "cancelled": False,
        "discovery_status": DISCOVERY_STATUS_COMPLETED,
        "requested_page_limit": 500,
        "frontier_limit": 50_000,
        "admitted_url_count": 12,
        "observation_count": 12,
        "pending_frontier_count": 0,
        "discovery_task_count": 12,
        "failed_discovery_task_count": 0,
    }
    values.update(overrides)
    return CoverageSignals(**values)  # type: ignore[arg-type]


def test_exhausted_frontier_below_limits_is_complete() -> None:
    result = assess_coverage(_signals())

    assert result.state == COVERAGE_STATE_COMPLETE
    assert result.evidence["reasons"] == ["frontier_exhausted"]


def test_budget_or_pending_frontier_is_partial() -> None:
    budget = assess_coverage(_signals(admitted_url_count=500))
    pending = assess_coverage(_signals(pending_frontier_count=3))

    assert budget.state == COVERAGE_STATE_PARTIAL
    assert "requested_page_limit_reached" in budget.evidence["reasons"]
    assert pending.state == COVERAGE_STATE_PARTIAL
    assert "frontier_not_exhausted" in pending.evidence["reasons"]


def test_bounded_rerun_and_cancel_are_partial() -> None:
    rerun = assess_coverage(_signals(discovery_task_count=0))
    cancelled = assess_coverage(_signals(cancelled=True))

    assert rerun.state == COVERAGE_STATE_PARTIAL
    assert cancelled.state == COVERAGE_STATE_PARTIAL


def test_failed_discovery_without_a_limit_is_unknown() -> None:
    result = assess_coverage(
        _signals(
            discovery_status=DISCOVERY_STATUS_FAILED,
            failed_discovery_task_count=1,
        )
    )

    assert result.state == COVERAGE_STATE_UNKNOWN
    assert "discovery_failed" in result.evidence["reasons"]
