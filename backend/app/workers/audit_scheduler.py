"""Periodic planner for workspace audit schedules.

This process only turns due schedules into normal ``Audit`` rows.  The audit
planner remains the sole owner of frozen snapshots and queue-task creation.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audit_schedules import (
    CADENCE_DAILY,
    CADENCE_EVERY_N_MINUTES,
    CADENCE_HOURLY,
    CADENCE_ONE_TIME,
    CADENCE_WEEKLY,
    DAYS_PER_WEEK,
    HOURS_PER_DAY,
    MINUTES_PER_HOUR,
    audit_schedule_settings,
)
from app.core.config.audits import AUDIT_TRIGGER_SCHEDULED
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging
from app.domain.audits.creation import create_audit
from app.models.audit import Audit
from app.models.audit_schedule import AuditSchedule

logger = logging.getLogger("app.workers.audit_scheduler")
HEARTBEAT_PATH = Path(audit_schedule_settings.heartbeat_path)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def next_run_after(schedule: AuditSchedule, *, after: datetime) -> datetime | None:
    """Return the first cadence slot strictly after ``after`` in its timezone."""
    if schedule.cadence == CADENCE_ONE_TIME:
        return None
    anchor = schedule.next_run_at or after
    zone = ZoneInfo(schedule.timezone)
    local = anchor.astimezone(zone)
    if schedule.cadence == CADENCE_EVERY_N_MINUTES:
        if schedule.interval_minutes is None or schedule.interval_minutes <= 0:
            raise ValueError("every_n_minutes requires a positive interval")
        delta = timedelta(minutes=schedule.interval_minutes)
        elapsed = max(0.0, (after - anchor).total_seconds())
        steps = int(elapsed // delta.total_seconds()) + 1
        return (anchor + steps * delta).astimezone(UTC)
    elif schedule.cadence == CADENCE_HOURLY:
        delta = timedelta(minutes=MINUTES_PER_HOUR)
    elif schedule.cadence == CADENCE_DAILY:
        delta = timedelta(hours=HOURS_PER_DAY)
    elif schedule.cadence == CADENCE_WEEKLY:
        delta = timedelta(days=DAYS_PER_WEEK)
    else:
        raise ValueError(f"Unsupported audit schedule cadence: {schedule.cadence}")
    candidate = local.astimezone(UTC)
    while candidate <= after:
        local += delta
        candidate = local.astimezone(UTC)
    return candidate


class AuditScheduler:
    """Leases due schedule rows and invokes the existing audit planner."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self.owner = owner or f"audit-scheduler-{uuid.uuid4().hex[:12]}"

    async def run_once(self, *, now: datetime | None = None) -> int:
        """Plan each currently due schedule once; return successful audit count."""
        tick_at = now or _utcnow()
        claims = await self._claim_due(tick_at)
        created = 0
        for schedule_id, scheduled_for in claims:
            if not await self._renew_claim(schedule_id, tick_at):
                continue
            if await self._plan_claim(schedule_id, scheduled_for, tick_at):
                created += 1
        _write_heartbeat(tick_at)
        return created

    async def _renew_claim(self, schedule_id: uuid.UUID, now: datetime) -> bool:
        async with self._session_factory() as session:
            schedule = await session.get(
                AuditSchedule, schedule_id, with_for_update=True
            )
            if schedule is None or schedule.lease_owner != self.owner:
                return False
            schedule.lease_expires_at = now + timedelta(
                seconds=audit_schedule_settings.lease_ttl_seconds
            )
            await session.commit()
            return True

    async def run_forever(self) -> None:  # pragma: no cover - process entrypoint
        logger.info("audit scheduler started", extra={"owner": self.owner})
        while True:
            try:
                await self.run_once()
            except Exception:  # noqa: BLE001 - one bad row cannot stop scheduling
                logger.exception("audit scheduler tick failed")
            await asyncio.sleep(audit_schedule_settings.poll_interval_seconds)

    async def _claim_due(self, now: datetime) -> list[tuple[uuid.UUID, datetime]]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(AuditSchedule)
                    .where(
                        AuditSchedule.enabled.is_(True),
                        AuditSchedule.next_run_at.is_not(None),
                        AuditSchedule.next_run_at <= now,
                        or_(
                            AuditSchedule.lease_expires_at.is_(None),
                            AuditSchedule.lease_expires_at <= now,
                        ),
                    )
                    .order_by(AuditSchedule.next_run_at.asc(), AuditSchedule.id.asc())
                    .limit(audit_schedule_settings.claim_batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).all()
            expires_at = now + timedelta(
                seconds=audit_schedule_settings.lease_ttl_seconds
            )
            claims: list[tuple[uuid.UUID, datetime]] = []
            for schedule in rows:
                if schedule.next_run_at is None:
                    continue
                schedule.lease_owner = self.owner
                schedule.lease_expires_at = expires_at
                claims.append((schedule.id, schedule.next_run_at))
            await session.commit()
            return claims

    async def _plan_claim(
        self, schedule_id: uuid.UUID, scheduled_for: datetime, now: datetime
    ) -> bool:
        async with self._session_factory() as session:
            schedule = await _current_claim(
                session,
                schedule_id=schedule_id,
                owner=self.owner,
                scheduled_for=scheduled_for,
            )
            if schedule is None:
                return False
            try:
                await create_audit(
                    session,
                    workspace_id=schedule.workspace_id,
                    project_id=schedule.project_id,
                    engines=list(schedule.engines),
                    trigger=AUDIT_TRIGGER_SCHEDULED,
                    prompt_set_id=schedule.prompt_set_id,
                    repetitions=schedule.repetitions,
                    benchmark_mode=schedule.benchmark_mode,
                    measurement_mode=schedule.measurement_mode,
                    schedule_id=schedule.id,
                    scheduled_for=scheduled_for,
                )
                created = True
            except IntegrityError:
                # A prior process committed the immutable audit before it could
                # advance the schedule row.  The unique slot makes this retry a
                # harmless completion, never a duplicate planned audit.
                await session.rollback()
                created = (
                    await session.scalar(
                        select(Audit.id).where(
                            Audit.schedule_id == schedule_id,
                            Audit.scheduled_for == scheduled_for,
                        )
                    )
                ) is not None
            except Exception:  # noqa: BLE001 - scheduler must survive bad schedules
                logger.exception(
                    "scheduled audit planning failed",
                    extra={"schedule_id": str(schedule_id)},
                )
                await session.rollback()
                created = False

        await self._finalize_claim(
            schedule_id=schedule_id,
            now=now,
            succeeded=created,
        )
        return created

    async def _finalize_claim(
        self,
        *,
        schedule_id: uuid.UUID,
        now: datetime,
        succeeded: bool,
    ) -> None:
        async with self._session_factory() as session:
            schedule = await session.get(
                AuditSchedule, schedule_id, with_for_update=True
            )
            if schedule is None or schedule.lease_owner != self.owner:
                await session.commit()
                return
            if succeeded:
                schedule.last_run_at = now
                schedule.failure_count = 0
                schedule.last_error = ""
                schedule.last_failure_at = None
                schedule.next_run_at = next_run_after(schedule, after=now)
                if schedule.next_run_at is None:
                    schedule.enabled = False
            else:
                schedule.failure_count += 1
                schedule.last_error = "audit_planning_failed"
                schedule.last_failure_at = now
                schedule.next_run_at = now + timedelta(
                    seconds=audit_schedule_settings.failure_retry_seconds
                )
                if (
                    schedule.failure_count
                    >= audit_schedule_settings.max_consecutive_failures
                ):
                    schedule.enabled = False
            schedule.lease_owner = None
            schedule.lease_expires_at = None
            await session.commit()


def _write_heartbeat(now: datetime) -> None:
    HEARTBEAT_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    HEARTBEAT_PATH.write_text(now.isoformat(), encoding="utf-8")


async def _current_claim(
    session: AsyncSession,
    *,
    schedule_id: uuid.UUID,
    owner: str,
    scheduled_for: datetime,
) -> AuditSchedule | None:
    schedule = await session.get(AuditSchedule, schedule_id)
    if schedule is None or schedule.lease_owner != owner:
        return None
    if schedule.enabled and schedule.next_run_at == scheduled_for:
        return schedule
    schedule.lease_owner = None
    schedule.lease_expires_at = None
    await session.commit()
    return None


def healthcheck() -> int:
    try:
        age = _utcnow().timestamp() - HEARTBEAT_PATH.stat().st_mtime
    except OSError:
        return 1
    return 0 if age <= audit_schedule_settings.health_stale_seconds else 1


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    if "--healthcheck" in sys.argv:
        raise SystemExit(healthcheck())
    asyncio.run(AuditScheduler().run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
