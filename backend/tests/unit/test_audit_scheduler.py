from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.core.config.audit_schedules import (
    CADENCE_DAILY,
    CADENCE_EVERY_N_MINUTES,
    CADENCE_HOURLY,
    CADENCE_ONE_TIME,
    CADENCE_WEEKLY,
    DEFAULT_AUDIT_SCHEDULE_TIMEZONE,
)
from app.domain.audits.schedule_schemas import AuditScheduleCreate
from app.models.audit_schedule import AuditSchedule
from app.workers.audit_scheduler import next_run_after


def _schedule(
    *, cadence: str, next_run_at: datetime, **kwargs: object
) -> AuditSchedule:
    return AuditSchedule(
        cadence=cadence,
        next_run_at=next_run_at,
        workspace_id="00000000-0000-0000-0000-000000000001",
        project_id="00000000-0000-0000-0000-000000000002",
        prompt_set_id="00000000-0000-0000-0000-000000000003",
        engines=["chatgpt"],
        timezone=kwargs.pop("timezone", DEFAULT_AUDIT_SCHEDULE_TIMEZONE),
        **kwargs,
    )


def test_one_time_schedule_has_no_successor() -> None:
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    assert (
        next_run_after(_schedule(cadence=CADENCE_ONE_TIME, next_run_at=now), after=now)
        is None
    )


def test_daily_schedule_preserves_local_wall_clock_after_dst() -> None:
    schedule = _schedule(
        cadence=CADENCE_DAILY,
        next_run_at=datetime(2026, 3, 7, 14, tzinfo=UTC),
        timezone="America/New_York",
    )
    next_run = next_run_after(schedule, after=datetime(2026, 3, 8, 13, tzinfo=UTC))
    assert next_run == datetime(2026, 3, 9, 13, tzinfo=UTC)


def test_every_n_minutes_requires_configured_interval() -> None:
    with pytest.raises(ValidationError, match="interval_minutes is required"):
        AuditScheduleCreate(
            prompt_set_id="00000000-0000-0000-0000-000000000003",
            cadence=CADENCE_EVERY_N_MINUTES,
            engines=["chatgpt"],
        )


@pytest.mark.parametrize(
    ("cadence", "kwargs", "expected"),
    [
        (
            CADENCE_EVERY_N_MINUTES,
            {"interval_minutes": 15},
            datetime(2026, 8, 4, 12, 15, tzinfo=UTC),
        ),
        (CADENCE_HOURLY, {}, datetime(2026, 8, 4, 13, tzinfo=UTC)),
        (CADENCE_WEEKLY, {}, datetime(2026, 8, 11, 12, tzinfo=UTC)),
    ],
)
def test_next_run_after_supported_cadences(cadence, kwargs, expected) -> None:
    anchor = datetime(2026, 8, 4, 12, tzinfo=UTC)
    schedule = _schedule(cadence=cadence, next_run_at=anchor, **kwargs)
    assert next_run_after(schedule, after=anchor) == expected


@pytest.mark.parametrize("interval", [None, 0])
def test_every_n_minutes_rejects_non_positive_interval(interval) -> None:
    schedule = _schedule(
        cadence=CADENCE_EVERY_N_MINUTES,
        next_run_at=datetime(2026, 8, 4, 12, tzinfo=UTC),
        interval_minutes=interval,
    )
    with pytest.raises(ValueError, match="positive interval"):
        next_run_after(schedule, after=schedule.next_run_at)
