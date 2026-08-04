"""Configuration and closed vocabulary for the audit scheduler."""

from __future__ import annotations

from typing import Final

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

CADENCE_ONE_TIME: Final = "one_time"
CADENCE_EVERY_N_MINUTES: Final = "every_n_minutes"
CADENCE_HOURLY: Final = "hourly"
CADENCE_DAILY: Final = "daily"
CADENCE_WEEKLY: Final = "weekly"
AUDIT_SCHEDULE_CADENCES: Final[frozenset[str]] = frozenset(
    {
        CADENCE_ONE_TIME,
        CADENCE_EVERY_N_MINUTES,
        CADENCE_HOURLY,
        CADENCE_DAILY,
        CADENCE_WEEKLY,
    }
)
DEFAULT_AUDIT_SCHEDULE_TIMEZONE: Final = "UTC"
MINUTES_PER_HOUR: Final = 60
HOURS_PER_DAY: Final = 24
DAYS_PER_WEEK: Final = 7


class AuditScheduleSettings(BaseSettings):
    """Runtime limits for the separate, lightweight scheduler process."""

    model_config = SettingsConfigDict(env_prefix="AUDIT_SCHEDULE_", extra="ignore")

    poll_interval_seconds: float = Field(default=30.0, gt=0)
    lease_ttl_seconds: float = Field(default=120.0, gt=0)
    claim_batch_size: int = Field(default=20, gt=0)
    min_interval_minutes: int = Field(default=5, gt=0)
    failure_retry_seconds: int = Field(default=300, gt=0)
    max_consecutive_failures: int = Field(default=5, gt=0)
    health_stale_seconds: int = Field(default=180, gt=0)
    heartbeat_path: str = Field(default="/tmp/citeladder-audit-scheduler-heartbeat")


audit_schedule_settings = AuditScheduleSettings()
