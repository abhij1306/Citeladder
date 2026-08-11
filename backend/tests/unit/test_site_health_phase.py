"""Server-side Site Health screen phase resolution.

Replaces the 367-line `resolveSiteHealthPhase` block in
`frontend/lib/site-health/status.test.ts` — the phase is resolved once, here.
"""

from __future__ import annotations

import pytest

from app.domain.site_health.phase import resolve_phase
from app.models.site_health import SiteCrawl


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


def _resolve(crawl, *, summary=None, selection_mode=True, monitored=False):
    return resolve_phase(
        crawl,
        score_summary=summary,
        selection_mode=selection_mode,
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
    shell = {"overall_score": None, "analyzed_count": 0}
    assert _resolve(_crawl(status="failed"), summary=shell) == "terminal"


def test_failed_crawl_that_scored_something_keeps_its_dashboard() -> None:
    assert (
        _resolve(_crawl(status="failed"), summary={"overall_score": 71}) == "dashboard"
    )


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_parked_crawl_with_inventory_returns_to_selection(status: str) -> None:
    assert _resolve(_crawl(status=status)) == "selection"


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_parked_crawl_with_nothing_discovered_is_terminal(status: str) -> None:
    assert _resolve(_crawl(status=status, admitted_url_count=0)) == "terminal"


@pytest.mark.parametrize("status", ["cancelled", "paused"])
def test_parked_crawl_dead_ends_without_a_monitored_allowance(status: str) -> None:
    assert _resolve(_crawl(status=status), selection_mode=False) == "terminal"


def test_parked_crawl_with_partial_scores_prefers_the_dashboard() -> None:
    assert (
        _resolve(_crawl(status="cancelled"), summary={"overall_score": 71})
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


def test_stopped_analysis_is_not_treated_as_live() -> None:
    # The monitored set survives Stop; it is not evidence analysis is running.
    crawl = _crawl(discovery_status="completed", analysis_status="stopped")
    assert _resolve(crawl, monitored=True) == "selection"


def test_finished_discovery_waits_for_selection() -> None:
    assert _resolve(_crawl(discovery_status="completed")) == "selection"


def test_finished_discovery_auto_analyzes_for_a_sample_account() -> None:
    assert (
        _resolve(_crawl(discovery_status="completed"), selection_mode=False)
        == "analyzing"
    )


def test_running_analysis_after_discovery_is_analyzing() -> None:
    crawl = _crawl(discovery_status="completed", analysis_status="running")
    assert _resolve(crawl) == "analyzing"
