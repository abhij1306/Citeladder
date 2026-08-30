"""Server-side Site Health screen phase resolution.

Replaces the 367-line `resolveSiteHealthPhase` block in
`frontend/lib/site-health/status.test.ts` — the phase is resolved once, here.
"""

from __future__ import annotations

import pytest

from app.domain.site_health.phase import resolve_phase
from app.models.site_health.crawl import SiteCrawl


def _crawl(
    *,
    status: str = "running",
    discovery_status: str = "running",
    analysis_status: str = "pending",
    admitted_url_count: int = 3,
) -> SiteCrawl:
    return SiteCrawl(
        status=status,
        discovery_status=discovery_status,
        analysis_status=analysis_status,
        admitted_url_count=admitted_url_count,
        root_url="https://acme.com/",
        random_seed="1",
    )


def _resolve(crawl, *, summary=None, monitored=False):
    return resolve_phase(
        crawl,
        score_summary=summary,
        has_monitored_selection=monitored,
    )


def test_no_crawl_is_empty() -> None:
    assert _resolve(None) == "empty"


@pytest.mark.parametrize("status", ["completed", "partially_completed"])
def test_finished_crawl_is_the_dashboard(status: str) -> None:
    assert _resolve(_crawl(status=status)) == "dashboard"


def test_failed_crawl_with_no_scores_is_terminal() -> None:
    assert _resolve(_crawl(status="failed", discovery_status="failed")) == "terminal"


def test_failed_crawl_with_an_empty_summary_shell_is_still_terminal() -> None:
    # The production shape behind SH-2: a fully-failed crawl persists a
    # PRESENT-but-null-score summary (persist_empty=True). Treating "summary is
    # not None" as dashboard-worthy is what hid every failed crawl behind an
    # empty dashboard.
    shell = {
        "web_fundamentals_state": "not_measured",
        "aeo_measurement_state": "not_measured",
        "analyzed_count": 0,
    }
    assert _resolve(_crawl(status="failed"), summary=shell) == "terminal"


def test_failed_crawl_with_missing_measurement_states_is_still_terminal() -> None:
    assert _resolve(_crawl(status="failed"), summary={"analyzed_count": 0}) == (
        "terminal"
    )


def test_failed_crawl_that_scored_something_keeps_its_dashboard() -> None:
    assert (
        _resolve(
            _crawl(status="failed"),
            summary={"web_fundamentals_state": "measured"},
        )
        == "dashboard"
    )


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_parked_crawl_with_inventory_is_terminal(status: str) -> None:
    assert _resolve(_crawl(status=status)) == "terminal"


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_parked_crawl_with_nothing_discovered_is_terminal(status: str) -> None:
    assert _resolve(_crawl(status=status, admitted_url_count=0)) == "terminal"


def test_parked_crawl_with_partial_scores_prefers_the_dashboard() -> None:
    assert (
        _resolve(
            _crawl(status="cancelled"),
            summary={"aeo_measurement_state": "limited_evidence"},
        )
        == "dashboard"
    )


def test_active_crawl_with_a_committed_set_is_analyzing_while_discovery_runs() -> None:
    # The regression this clause exists for: the planner seeds analyze tasks at
    # crawl creation, so `analysis_status` lags at 'pending' while discovery
    # re-scans. Reading that as 'discovering' bounced the screen back to the URL
    # list right after "Start analysis" / "Re-crawl".
    assert _resolve(_crawl(), monitored=True) == "analyzing"


def test_active_crawl_without_a_committed_set_is_discovering() -> None:
    assert _resolve(_crawl()) == "discovering"


def test_active_crawl_never_falls_back_to_a_selection_step() -> None:
    crawl = _crawl(discovery_status="completed", analysis_status="stopped")
    assert _resolve(crawl, monitored=True) == "analyzing"


def test_finished_discovery_continues_on_the_live_results_surface() -> None:
    assert _resolve(_crawl(discovery_status="completed")) == "analyzing"


def test_completed_analysis_does_not_replace_results_with_selection_ui() -> None:
    crawl = _crawl(discovery_status="completed", analysis_status="completed")
    assert _resolve(crawl, monitored=True) == "analyzing"


def test_running_analysis_after_discovery_is_analyzing() -> None:
    crawl = _crawl(discovery_status="completed", analysis_status="running")
    assert _resolve(crawl) == "analyzing"
