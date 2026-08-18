"""Cooperative audit cancellation and funded-reservation release."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import (
    AUDIT_ACTIVE_STATUSES,
    AUDIT_STATUS_CANCELLED,
    EVENT_AUDIT_CANCELLED,
    TASK_STATUS_CANCELLED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.audits.errors import AuditValidationError
from app.domain.audits.reads import get_audit
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.entitlements.ledger import release_terminal_funded_task
from app.models.audit import Audit, AuditTask


async def _release_funded_on_cancel(
    session: AsyncSession,
    *,
    audit: Audit,
    cancelled_task_ids: set[uuid.UUID],
    at: datetime,
) -> None:
    """Release every cancelled funded task's unused reservation.

    A cancelled task is never claimed, so neither worker-side release path
    ever runs for it — without this the reservation leaks (indefinitely for
    grants with no ``valid_until``). Only the tasks THIS cancel terminalized
    are released: the bulk update's RETURNING set is exactly the rows that
    were still non-terminal once its row locks settled, so a task a worker
    already terminalized (and released) is never re-released. The audit
    configuration's frozen task-reservation map (invariant 9) carries every
    funded task's reservation id; BYOK tasks are absent from it.
    """
    task_reservations = (audit.configuration or {}).get("task_reservations") or {}
    for task_id in sorted(cancelled_task_ids, key=str):
        reservation = task_reservations.get(str(task_id))
        if reservation is None:
            continue
        await release_terminal_funded_task(
            session,
            reservation_id=uuid.UUID(str(reservation)),
            audit_id=audit.id,
            task_id=task_id,
            trigger="cancel",
            at=at,
        )


async def cancel_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit_id: uuid.UUID
) -> Audit:
    """Cooperatively cancel an active audit and terminalize open tasks.

    Flips the audit to ``cancelled`` (so a live worker stops at the next
    execution boundary) and marks any non-terminal task ``cancelled`` so counts
    and the UI stay consistent. This also cleans up a zombie audit whose worker
    died mid-run. Every funded task it terminalizes has its unused reservation
    released in the same transaction — a cancelled task is never claimed, so
    no worker-side release path would ever run for it.
    """
    # Lock the audit row FIRST: a worker's boundary terminalization (run
    # deadline / cooperative cancel) holds this same lock while it releases
    # the task's reservation, so this cancel either observes that committed
    # release (its own release then no-ops on the outstanding computation) or
    # commits first (the worker's boundary check then discards the task).
    # Either way exactly one release settles per reservation.
    await session.get(Audit, audit_id, with_for_update=True)
    audit = await get_audit(session, workspace_id=workspace_id, audit_id=audit_id)
    if audit.status not in AUDIT_ACTIVE_STATUSES:
        raise AuditValidationError("Only active audits can be cancelled")
    now = datetime.now(UTC)
    audit.completed_at = now
    # Route the flip through the state machine (invariant 9): AUDIT_ACTIVE_STATUSES
    # only contains statuses the machine allows to reach CANCELLED, so this never
    # raises here, but it keeps the single enforcement path and records the event.
    apply_transition(
        session,
        audit=audit,
        target=AUDIT_STATUS_CANCELLED,
        message="audit cancelled",
    )
    cancelled_task_ids = set(
        (
            await session.execute(
                update(AuditTask)
                .where(AuditTask.audit_id == audit.id)
                .where(AuditTask.status.not_in(list(TASK_TERMINAL_STATUSES)))
                .values(
                    status=TASK_STATUS_CANCELLED,
                    lease_owner=None,
                    lease_expires_at=None,
                    completed_at=now,
                    error_code="cancelled",
                )
                .returning(AuditTask.id)
            )
        )
        .scalars()
        .all()
    )
    await _release_funded_on_cancel(
        session, audit=audit, cancelled_task_ids=cancelled_task_ids, at=now
    )
    record_event(
        session,
        audit_id=audit.id,
        event_type=EVENT_AUDIT_CANCELLED,
        message="audit cancelled",
        payload={"status": AUDIT_STATUS_CANCELLED},
    )
    await session.commit()
    # See the comment in ``create_audit``: refresh() would expire (and later
    # lazy-load) ``engine_snapshots``, which needs to stay eagerly loaded for
    # safe serialization outside the async greenlet.
    return await get_audit(session, workspace_id=workspace_id, audit_id=audit.id)
