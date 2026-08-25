"""Unit tests for the persisted audit-performance projection.

``app/domain/audits/performance.py`` sat at 36% line coverage. Everything below
``_performance_rows`` is pure aggregation over already-loaded rows, so it is
exercised here against unattached ORM instances — no database, no flush, no
fixtures. The one thing that genuinely needs persistence, the workspace-scoped
read, stays in the component suite.

The projection's job is to summarise WITHOUT inventing: an absent cost is
``None``, never a zero, and a coverage ratio over zero executions is not a
division error.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.audits.performance import (
    _elapsed_ms,
    _first_completed_at,
    _performance_response,
    _task_counts,
    _task_latencies,
    _total_projected_cost,
    _usage_summary,
)
from app.models.audit import Audit, AuditTask, ExecutionCostProjection

_CREATED = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)


def _audit(**overrides: object) -> Audit:
    values: dict[str, object] = {
        "id": uuid.uuid4(),
        "created_at": _CREATED,
        "started_at": None,
        "completed_at": None,
    }
    values.update(overrides)
    return Audit(**values)


def _task(
    *,
    engine: str = "gemini",
    status: str = TASK_STATUS_SUCCEEDED,
    attempt_count: int = 1,
    latency_ms: int | None = None,
    completed_at: datetime | None = None,
    search_events: list[dict[str, object]] | None = None,
) -> AuditTask:
    return AuditTask(
        id=uuid.uuid4(),
        logical_engine=engine,
        status=status,
        attempt_count=attempt_count,
        latency_ms=latency_ms,
        completed_at=completed_at,
        search_events=search_events,
    )


def _cost(
    task: AuditTask | None = None,
    *,
    projected_total_cost_microusd: int | None = None,
    uncached_input_tokens: int | None = None,
    cached_input_tokens: int | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
) -> ExecutionCostProjection:
    return ExecutionCostProjection(
        id=uuid.uuid4(),
        task_id=task.id if task is not None else uuid.uuid4(),
        projected_total_cost_microusd=projected_total_cost_microusd,
        uncached_input_tokens=uncached_input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


# --- elapsed timings ------------------------------------------------------


def test_elapsed_is_none_when_the_end_has_not_happened() -> None:
    # A run that has not completed has NO duration; zero would read as instant.
    assert _elapsed_ms(None, _CREATED) is None


def test_elapsed_is_milliseconds_between_the_two_points() -> None:
    assert _elapsed_ms(_CREATED + timedelta(seconds=1.5), _CREATED) == 1500


def test_first_completed_at_is_the_earliest_finished_task() -> None:
    tasks = [
        _task(completed_at=_CREATED + timedelta(seconds=30)),
        _task(completed_at=None),
        _task(completed_at=_CREATED + timedelta(seconds=10)),
    ]

    assert _first_completed_at(tasks) == _CREATED + timedelta(seconds=10)


def test_first_completed_at_is_none_when_nothing_has_finished() -> None:
    assert _first_completed_at([_task(completed_at=None)]) is None


# --- task counting --------------------------------------------------------


def test_task_counts_split_succeeded_failed_retries_and_searches() -> None:
    tasks = [
        _task(status=TASK_STATUS_SUCCEEDED, attempt_count=1),
        _task(status=TASK_STATUS_SUCCEEDED, attempt_count=3, search_events=[{}, {}]),
        _task(status=TASK_STATUS_FAILED, attempt_count=2),
        _task(status=TASK_STATUS_RUNNING, attempt_count=1),
    ]

    completed, failed, retries, searches = _task_counts(tasks)

    assert (completed, failed) == (2, 1)
    # Retries are attempts BEYOND the first, so a single-attempt task is zero.
    assert retries == 3
    assert searches == 2


def test_task_counts_treat_a_null_search_event_list_as_no_searches() -> None:
    assert _task_counts([_task(search_events=None)])[3] == 0


def test_latencies_skip_tasks_that_never_reported_one() -> None:
    tasks = [_task(latency_ms=100), _task(latency_ms=None), _task(latency_ms=300)]

    assert _task_latencies(tasks) == [100, 300]


# --- cost and usage -------------------------------------------------------


def test_total_projected_cost_sums_only_the_known_rows() -> None:
    costs = [
        _cost(projected_total_cost_microusd=100),
        _cost(projected_total_cost_microusd=None),
        _cost(projected_total_cost_microusd=250),
    ]

    assert _total_projected_cost(costs) == 350


def test_total_projected_cost_is_none_when_nothing_is_priced() -> None:
    # None, not 0: an unpriced run is unknown, not free.
    assert _total_projected_cost([_cost(projected_total_cost_microusd=None)]) is None
    assert _total_projected_cost([]) is None


def test_usage_summary_is_all_none_without_any_projection_rows() -> None:
    usage = _usage_summary([])

    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None


def test_usage_summary_folds_cached_and_uncached_input_together() -> None:
    costs = [
        _cost(
            uncached_input_tokens=10,
            cached_input_tokens=5,
            output_tokens=3,
            total_tokens=18,
        ),
        _cost(
            uncached_input_tokens=7,
            cached_input_tokens=None,
            output_tokens=2,
            total_tokens=9,
        ),
    ]

    usage = _usage_summary(costs)

    assert usage.input_tokens == 22
    assert usage.output_tokens == 5
    assert usage.total_tokens == 27


# --- whole response -------------------------------------------------------


def test_response_over_no_tasks_reports_zero_coverage_without_dividing() -> None:
    audit = _audit()

    response = _performance_response(audit, tasks=[], costs=[])

    assert response.execution_count == 0
    assert response.coverage == 0.0
    assert response.completed_count == 0
    assert response.time_to_first_result_ms is None
    assert response.projected_cost_microusd is None
    assert response.engines == []


def test_response_carries_queue_wait_and_total_duration() -> None:
    audit = _audit(
        started_at=_CREATED + timedelta(seconds=2),
        completed_at=_CREATED + timedelta(seconds=12),
    )
    task = _task(completed_at=_CREATED + timedelta(seconds=9))

    response = _performance_response(audit, tasks=[task], costs=[])

    assert response.audit_id == audit.id
    assert response.queue_wait_ms == 2000
    assert response.total_run_duration_ms == 12000
    assert response.time_to_first_result_ms == 9000


def test_coverage_is_the_completed_share_of_all_executions() -> None:
    tasks = [
        _task(status=TASK_STATUS_SUCCEEDED),
        _task(status=TASK_STATUS_FAILED),
        _task(status=TASK_STATUS_SUCCEEDED),
        _task(status=TASK_STATUS_RUNNING),
    ]

    response = _performance_response(_audit(), tasks=tasks, costs=[])

    assert response.execution_count == 4
    assert response.completed_count == 2
    assert response.failed_count == 1
    assert response.coverage == 0.5


def test_engine_rows_are_grouped_and_sorted_by_engine() -> None:
    tasks = [
        _task(engine="gemini"),
        _task(engine="chatgpt"),
        _task(engine="claude"),
        _task(engine="chatgpt", status=TASK_STATUS_FAILED),
    ]

    response = _performance_response(_audit(), tasks=tasks, costs=[])

    assert [row.logical_engine for row in response.engines] == [
        "chatgpt",
        "claude",
        "gemini",
    ]
    chatgpt = response.engines[0]
    assert chatgpt.execution_count == 2
    assert chatgpt.completed_count == 1
    assert chatgpt.failed_count == 1


def test_engine_latency_averages_only_the_tasks_that_reported_one() -> None:
    tasks = [
        _task(engine="gemini", latency_ms=100),
        _task(engine="gemini", latency_ms=300),
        _task(engine="gemini", latency_ms=None),
    ]

    response = _performance_response(_audit(), tasks=tasks, costs=[])

    assert response.engines[0].average_provider_latency_ms == 200.0


def test_engine_latency_is_none_when_no_task_reported_one() -> None:
    response = _performance_response(
        _audit(), tasks=[_task(engine="gemini", latency_ms=None)], costs=[]
    )

    assert response.engines[0].average_provider_latency_ms is None


def test_engine_cost_sums_only_the_projections_for_that_engine_s_tasks() -> None:
    gemini = _task(engine="gemini")
    chatgpt = _task(engine="chatgpt")
    unpriced = _task(engine="gemini")
    costs = [
        _cost(gemini, projected_total_cost_microusd=500),
        _cost(chatgpt, projected_total_cost_microusd=700),
    ]

    response = _performance_response(
        _audit(), tasks=[gemini, chatgpt, unpriced], costs=costs
    )

    by_engine = {row.logical_engine: row for row in response.engines}
    assert by_engine["gemini"].projected_cost_microusd == 500
    assert by_engine["chatgpt"].projected_cost_microusd == 700
    assert response.projected_cost_microusd == 1200


def test_engine_cost_is_none_when_that_engine_has_no_projection() -> None:
    response = _performance_response(_audit(), tasks=[_task(engine="gemini")], costs=[])

    assert response.engines[0].projected_cost_microusd is None
