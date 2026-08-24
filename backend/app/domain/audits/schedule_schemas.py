"""Request and response contracts for project audit schedules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.config.audit_schedules import (
    CADENCE_EVERY_N_MINUTES,
    DEFAULT_AUDIT_SCHEDULE_TIMEZONE,
    audit_schedule_settings,
)
from app.core.config.projects import (
    BENCHMARK_MODE_CONSUMER_LIKE,
    BENCHMARK_MODE_CONTROLLED_LOCALIZED,
    BENCHMARK_MODE_FORCED_GROUNDED,
    MAX_REPETITIONS,
    MIN_REPETITIONS,
)
from app.core.config.provider_catalog import LOGICAL_ENGINES

AuditScheduleCadence = Literal[
    "one_time", "every_n_minutes", "hourly", "daily", "weekly"
]
BenchmarkMode = Literal["consumer_like", "controlled_localized", "forced_grounded"]
assert {
    BENCHMARK_MODE_CONSUMER_LIKE,
    BENCHMARK_MODE_CONTROLLED_LOCALIZED,
    BENCHMARK_MODE_FORCED_GROUNDED,
} == set(get_args(BenchmarkMode))


class AuditScheduleCreate(BaseModel):
    prompt_set_id: uuid.UUID
    cadence: AuditScheduleCadence
    interval_minutes: int | None = None
    timezone: str = DEFAULT_AUDIT_SCHEDULE_TIMEZONE
    engines: list[str] = Field(min_length=1)
    repetitions: int | None = Field(
        default=None, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )
    benchmark_mode: BenchmarkMode | None = None
    enabled: bool = True
    next_run_at: datetime | None = None

    @field_validator("next_run_at")
    @classmethod
    def normalize_next_run_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("next_run_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("engines")
    @classmethod
    def validate_engines(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value) or any(
            engine not in LOGICAL_ENGINES for engine in value
        ):
            raise ValueError("engines must be unique supported logical engines")
        return value

    @model_validator(mode="after")
    def validate_interval(self) -> AuditScheduleCreate:
        if self.cadence == CADENCE_EVERY_N_MINUTES:
            if self.interval_minutes is None:
                raise ValueError("interval_minutes is required for every_n_minutes")
            if self.interval_minutes < audit_schedule_settings.min_interval_minutes:
                raise ValueError("interval_minutes is below the configured minimum")
        elif self.interval_minutes is not None:
            raise ValueError("interval_minutes is only valid for every_n_minutes")
        return self


class AuditScheduleUpdate(BaseModel):
    prompt_set_id: uuid.UUID | None = None
    cadence: AuditScheduleCadence | None = None
    interval_minutes: int | None = None
    timezone: str | None = None
    engines: list[str] | None = Field(default=None, min_length=1)
    repetitions: int | None = Field(
        default=None, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )
    benchmark_mode: BenchmarkMode | None = None
    enabled: bool | None = None
    next_run_at: datetime | None = None

    @field_validator("next_run_at")
    @classmethod
    def normalize_next_run_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("next_run_at must include a timezone")
        return value.astimezone(UTC)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str | None) -> str | None:
        if value is None:
            return value
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("timezone must be a valid IANA timezone") from exc
        return value

    @field_validator("engines")
    @classmethod
    def validate_engines(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        if len(set(value)) != len(value) or any(
            engine not in LOGICAL_ENGINES for engine in value
        ):
            raise ValueError("engines must be unique supported logical engines")
        return value


class AuditScheduleResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    prompt_set_id: uuid.UUID
    cadence: AuditScheduleCadence
    interval_minutes: int | None
    timezone: str
    engines: list[str]
    repetitions: int | None
    benchmark_mode: BenchmarkMode | None
    enabled: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    failure_count: int
    last_error: str
    last_failure_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
