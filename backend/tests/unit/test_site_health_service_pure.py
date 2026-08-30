"""Unit tests for the pure Site Health service/normalization helpers.

Covers the logic that does not need a database:
  - typed keyset cursors: fingerprint stability, cross-scope/cross-filter
    replay rejection (``CursorScopeError``), and tamper rejection
    (``ValueError``);
  - ``display_label_for`` current labels + rule-id fallback;
  - ``presentation_status_for`` derivation, including the policy ``blocked``
    vs generic ``error`` split and the invariant that ``failed`` is never
    surfaced as page copy.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

from app.core.config.site_health_acquisition import (
    ERROR_ROBOTS_DENIED,
    ERROR_SSRF_BLOCKED,
    ERROR_URL_ADMISSION_REJECTED,
)
from app.core.config.site_health_contracts import (
    PAGE_ANALYSIS_STATUS_COMPLETED,
    PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.architecture import _indexability_outcome
from app.domain.site_health.normalization import (
    CursorScopeError,
    decode_keyset_cursor,
    encode_keyset_cursor,
    filter_fingerprint,
)
from app.domain.site_health.service import (
    _score_summary,
    display_label_for,
    presentation_status_for,
)
from app.domain.site_health.snapshot import _eligibility_state
from app.domain.site_health.web_fundamentals_projection import _area_state
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask

# --------------------------------------------------------------------------
# Keyset cursors
# --------------------------------------------------------------------------


def test_web_fundamentals_na_only_area_is_not_measured() -> None:
    state, coverage = _area_state(
        [SimpleNamespace(outcome="not_applicable")], unavailable=0
    )

    assert state == "not_measured"
    assert coverage is None


def test_fingerprint_is_stable_and_ignores_empty_values() -> None:
    a = filter_fingerprint("pages", {"status": "completed", "monitored": None})
    b = filter_fingerprint("pages", {"status": "completed"})
    c = filter_fingerprint("pages", {"status": "completed", "monitored": ""})
    assert a == b == c


def test_fingerprint_changes_on_scope_or_filter() -> None:
    base = filter_fingerprint("pages", {"status": "completed"})
    assert base != filter_fingerprint("inventory", {"status": "completed"})
    assert base != filter_fingerprint("pages", {"status": "error"})
    assert base != filter_fingerprint("pages", {"monitored": True})


def test_cursor_round_trips_within_same_scope_and_filters() -> None:
    scope, filters = "pages", {"status": "completed"}
    cursor = encode_keyset_cursor(
        scope=scope, filters=filters, sort_values=["https://x/a", "id-1"]
    )
    assert decode_keyset_cursor(cursor, scope=scope, filters=filters) == [
        "https://x/a",
        "id-1",
    ]


def test_cursor_replay_across_filters_raises_scope_error() -> None:
    cursor = encode_keyset_cursor(
        scope="pages", filters={"status": "completed"}, sort_values=["u", "i"]
    )
    with pytest.raises(CursorScopeError):
        decode_keyset_cursor(cursor, scope="pages", filters={"status": "error"})


def test_cursor_replay_across_scope_raises_scope_error() -> None:
    cursor = encode_keyset_cursor(scope="pages", filters={}, sort_values=["u", "i"])
    with pytest.raises(CursorScopeError):
        decode_keyset_cursor(cursor, scope="inventory", filters={})


def test_tampered_cursor_raises_value_error() -> None:
    with pytest.raises(ValueError):
        decode_keyset_cursor("!!!not-base64!!!", scope="pages", filters={})


# --------------------------------------------------------------------------
# Display labels
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    [
        ("technical.title_present", "Missing page title"),
        ("technical.canonical_present", "Missing canonical URL"),
        ("technical.indexable", "Page blocked from indexing"),
        ("aeo.structured_data_present", "Missing structured data"),
    ],
)
def test_display_label_for_known_rules(rule_id: str, expected: str) -> None:
    assert display_label_for(rule_id) == expected


def test_display_label_for_unknown_rule_falls_back_to_rule_id() -> None:
    assert display_label_for("does.not.exist") == "does.not.exist"


# --------------------------------------------------------------------------
# Presentation status derivation
# --------------------------------------------------------------------------


def _analysis(status: str) -> SimpleNamespace:
    return SimpleNamespace(status=status)


def _task(status: str, error_code: str = "") -> SimpleNamespace:
    return SimpleNamespace(status=status, error_code=error_code)


def test_completed_analysis_wins() -> None:
    st, code = presentation_status_for(
        analysis=cast(SitePageAnalysis, _analysis(PAGE_ANALYSIS_STATUS_COMPLETED)),
        monitored=True,
        latest_analyze_task=cast(
            SiteCrawlTask, _task(TASK_STATUS_FAILED, ERROR_SSRF_BLOCKED)
        ),
    )
    assert st == PAGE_ANALYSIS_STATUS_COMPLETED
    assert code == ""


def test_partially_completed_analysis_wins() -> None:
    st, code = presentation_status_for(
        analysis=cast(
            SitePageAnalysis, _analysis(PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED)
        ),
        monitored=False,
        latest_analyze_task=None,
    )
    assert st == PAGE_ANALYSIS_STATUS_PARTIALLY_COMPLETED
    assert code == ""


@pytest.mark.parametrize("code", [ERROR_ROBOTS_DENIED, ERROR_SSRF_BLOCKED])
def test_policy_denial_maps_to_blocked(code: str) -> None:
    st, out_code = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(TASK_STATUS_FAILED, code)),
    )
    assert st == "blocked"
    assert out_code == code


def test_other_terminal_failure_maps_to_error_not_failed() -> None:
    st, code = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(TASK_STATUS_FAILED, "timeout")),
    )
    assert st == "error"
    assert st != "failed"
    assert code == "timeout"


def test_cancelled_without_code_maps_to_cancelled() -> None:
    st, code = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(TASK_STATUS_CANCELLED, "")),
    )
    assert st == "cancelled"
    assert code == ""


def test_succeeded_task_without_analysis_is_pending() -> None:
    st, _ = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(TASK_STATUS_SUCCEEDED)),
    )
    assert st == "pending"


@pytest.mark.parametrize("status", [TASK_STATUS_RUNNING, TASK_STATUS_LEASED])
def test_in_flight_task_is_running(status: str) -> None:
    st, _ = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(status)),
    )
    assert st == "running"


def test_queued_task_is_pending() -> None:
    st, _ = presentation_status_for(
        analysis=None,
        monitored=True,
        latest_analyze_task=cast(SiteCrawlTask, _task(TASK_STATUS_QUEUED)),
    )
    assert st == "pending"


def test_monitored_with_nothing_is_pending() -> None:
    st, _ = presentation_status_for(
        analysis=None, monitored=True, latest_analyze_task=None
    )
    assert st == "pending"


def test_unmonitored_with_nothing_is_not_selected() -> None:
    st, _ = presentation_status_for(
        analysis=None, monitored=False, latest_analyze_task=None
    )
    assert st == "not_selected"


# --------------------------------------------------------------------------
# score_summary projection (v2 P1 by_page_kind breakdown)
# --------------------------------------------------------------------------


def _crawl_with_summary(summary: dict | None) -> SimpleNamespace:
    return SimpleNamespace(score_summary=summary, scoring_version="sh-scoring-4")


def test_score_summary_projects_by_page_kind() -> None:
    crawl = _crawl_with_summary(
        {
            "web_fundamentals_score": 80.0,
            "web_fundamentals_coverage": 1.0,
            "web_fundamentals_state": "measured",
            "aeo_readiness_score": 70.0,
            "aeo_measurement_coverage": 0.8,
            "aeo_measurement_state": "measured",
            "search_eligibility": "eligible",
            "selected_count": 4,
            "analyzed_count": 3,
            "issue_count": 2,
            "scoring_version": "sh-scoring-4",
            "by_page_kind": {
                "article": {
                    "analyzed_count": 2,
                    "web_fundamentals_score": 85.0,
                    "web_fundamentals_coverage": 1.0,
                    "web_fundamentals_state": "measured",
                    "aeo_readiness_score": 70.0,
                    "aeo_measurement_coverage": 0.8,
                    "aeo_measurement_state": "measured",
                },
                "product": {
                    "analyzed_count": 1,
                    "web_fundamentals_score": None,
                    "web_fundamentals_coverage": 0.5,
                    "web_fundamentals_state": "limited_evidence",
                    "aeo_readiness_score": 70.0,
                    "aeo_measurement_coverage": 0.8,
                    "aeo_measurement_state": "measured",
                },
            },
        }
    )
    projected = _score_summary(cast(SiteCrawl, crawl))
    assert projected is not None
    by_page_kind = projected["by_page_kind"]
    assert set(by_page_kind) == {"article", "product"}
    assert by_page_kind["article"] == {
        "analyzed_count": 2,
        "web_fundamentals_score": 85.0,
        "web_fundamentals_coverage": 1.0,
        "web_fundamentals_state": "measured",
        "aeo_readiness_score": 70.0,
        "aeo_measurement_coverage": 0.8,
        "aeo_measurement_state": "measured",
    }
    # A None mean is projected as None, never fabricated as zero.
    assert by_page_kind["product"]["web_fundamentals_score"] is None


def test_score_summary_without_breakdown_projects_empty_map() -> None:
    # Pre-P1 summaries carry no by_page_kind key: the strict DTO shape gets
    # an empty map rather than a missing key.
    crawl = _crawl_with_summary(
        {
            "web_fundamentals_score": 50.0,
            "web_fundamentals_coverage": 1.0,
            "web_fundamentals_state": "measured",
            "aeo_readiness_score": 50.0,
            "aeo_measurement_coverage": 0.8,
            "aeo_measurement_state": "measured",
            "selected_count": 1,
            "analyzed_count": 1,
            "issue_count": 0,
        }
    )
    projected = _score_summary(cast(SiteCrawl, crawl))
    assert projected is not None
    assert projected["by_page_kind"] == {}
    assert projected["scoring_version"] == "sh-scoring-4"


def test_score_summary_none_when_absent() -> None:
    assert _score_summary(cast(SiteCrawl, _crawl_with_summary(None))) is None


def test_admission_rejection_is_excluded_from_search_eligibility() -> None:
    task = SimpleNamespace(
        status=TASK_STATUS_FAILED,
        error_code=ERROR_URL_ADMISSION_REJECTED,
    )
    assert _eligibility_state("unknown", "unknown", "unknown", "unknown", task) == (
        "excluded",
        "excluded",
    )


def test_robots_denial_remains_an_observed_blocker() -> None:
    task = SimpleNamespace(status=TASK_STATUS_FAILED, error_code=ERROR_ROBOTS_DENIED)
    assert _eligibility_state("missing", "unknown", "unknown", "unknown", task) == (
        "blocked",
        "blocked",
    )


def test_search_eligibility_uses_only_public_representation_and_indexability() -> None:
    task = SimpleNamespace(status=TASK_STATUS_SUCCEEDED, error_code=None)
    assert _eligibility_state(
        "satisfied", "satisfied", "unknown", "not_applicable", task
    ) == ("eligible", "audited")
    assert _eligibility_state(
        "satisfied", "unknown", "satisfied", "satisfied", task
    ) == ("unknown", "pending")


def test_only_determinate_indexability_outcomes_become_booleans() -> None:
    assert _indexability_outcome("satisfied") is True
    assert _indexability_outcome("missing") is False
    assert _indexability_outcome("unknown") is None
    assert _indexability_outcome("unavailable") is None
