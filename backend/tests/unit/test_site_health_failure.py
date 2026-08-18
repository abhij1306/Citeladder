"""Unit tests for crawl-failure humanization + the B1/B2 config tokens.

Covers the pure half of ``domain/site_health/failure`` (the async loaders are
exercised by the component tests):
  - ``humanize_crawl_failure``: one uniform human sentence per failure — a
    stable code rides alongside; HTTP failures name the terminal status, a
    retried 5xx names the attempt count, an unrecognized code still gets a
    sentence (never a bare ``http_4xx`` token — SH-5);
  - the config-owned tokens the worker, the read projections, and the UI copy
    share (invariant 1): ``EVENT_CRAWL_FAILED``, ``ROBOTS_FETCH_STATUS_*``,
    ``FETCH_ATTEMPT_OUTCOME_*``.
"""

from __future__ import annotations

from app.core.config.site_health_acquisition import (
    FETCH_ATTEMPT_OUTCOME_ERROR,
    FETCH_ATTEMPT_OUTCOME_SUCCESS,
    ROBOTS_FETCH_STATUS_FETCH_FAILED,
    ROBOTS_FETCH_STATUS_FETCHED,
    ROBOTS_FETCH_STATUS_NOT_FOUND,
)
from app.core.config.site_health_contracts import (
    EVENT_CRAWL_COMPLETED,
    EVENT_CRAWL_FAILED,
)
from app.domain.site_health.failure import humanize_crawl_failure


class TestHumanizeCrawlFailure:
    def test_dns_failure_names_dns(self) -> None:
        assert (
            humanize_crawl_failure(
                code="dns_resolution_failed", status_code=None, attempts=None
            )
            == "The domain could not be resolved (DNS)"
        )

    def test_http_404_names_the_status_for_the_start_url(self) -> None:
        assert (
            humanize_crawl_failure(code="http_4xx", status_code=404, attempts=1)
            == "The site returned HTTP 404 for the start URL"
        )

    def test_retried_http_500_names_status_and_attempts(self) -> None:
        assert (
            humanize_crawl_failure(code="http_5xx", status_code=500, attempts=4)
            == "The site returned HTTP 500 after 4 attempts"
        )

    def test_single_attempt_http_500_uses_start_url_phrasing(self) -> None:
        assert (
            humanize_crawl_failure(code="http_5xx", status_code=503, attempts=1)
            == "The site returned HTTP 503 for the start URL"
        )

    def test_http_failure_without_status_falls_back_to_generic(self) -> None:
        # A classified http_* token with no recorded status cannot name one.
        assert (
            humanize_crawl_failure(code="http_4xx", status_code=None, attempts=1)
            == "The crawl failed before it could fetch the start URL"
        )

    def test_unknown_code_still_gets_a_sentence(self) -> None:
        # e.g. ``crawl_task_crashed`` — never surface the bare code (SH-5).
        message = humanize_crawl_failure(
            code="crawl_task_crashed", status_code=None, attempts=None
        )
        assert message == "The crawl failed before it could fetch the start URL"
        assert "crawl_task_crashed" not in message

    def test_empty_code_gets_the_generic_sentence(self) -> None:
        assert (
            humanize_crawl_failure(code="", status_code=None, attempts=None)
            == "The crawl failed before it could fetch the start URL"
        )

    def test_retried_non_http_failure_carries_the_attempts_suffix(self) -> None:
        assert (
            humanize_crawl_failure(code="timeout", status_code=None, attempts=3)
            == "The site did not answer in time after 3 attempts"
        )

    def test_single_attempt_non_http_failure_has_no_suffix(self) -> None:
        assert (
            humanize_crawl_failure(code="timeout", status_code=None, attempts=1)
            == "The site did not answer in time"
        )

    def test_robots_denial_messages_are_distinct(self) -> None:
        denied = humanize_crawl_failure(
            code="robots_denied", status_code=None, attempts=1
        )
        unavailable = humanize_crawl_failure(
            code="robots_unavailable", status_code=None, attempts=1
        )
        assert denied != unavailable
        assert "robots.txt" in denied
        assert "server error" in unavailable


class TestFailureConfigTokens:
    def test_crawl_failed_event_is_distinct_from_completed(self) -> None:
        # SH-2: SSE/replay consumers must never read a failed run as completed.
        assert EVENT_CRAWL_FAILED == "crawl.failed"
        assert EVENT_CRAWL_FAILED != EVENT_CRAWL_COMPLETED

    def test_robots_fetch_status_tokens(self) -> None:
        # SH-1/B2: not_found (404 — fail-open) != fetch_failed (network/5xx).
        assert ROBOTS_FETCH_STATUS_FETCHED == "fetched"
        assert ROBOTS_FETCH_STATUS_NOT_FOUND == "not_found"
        assert ROBOTS_FETCH_STATUS_FETCH_FAILED == "fetch_failed"

    def test_fetch_attempt_outcome_tokens_match_worker_aliases(self) -> None:
        # The writer (worker) and the read projection (failure.load_root_errors)
        # share the config-owned tokens (invariant 1).
        from app.workers.site_health_worker import _OUTCOME_ERROR, _OUTCOME_SUCCESS

        assert FETCH_ATTEMPT_OUTCOME_SUCCESS == "success"
        assert FETCH_ATTEMPT_OUTCOME_ERROR == "error"
        assert _OUTCOME_SUCCESS == FETCH_ATTEMPT_OUTCOME_SUCCESS
        assert _OUTCOME_ERROR == FETCH_ATTEMPT_OUTCOME_ERROR
