"""Audit success/failure persistence and aggregate terminalization."""
# mypy: disable-error-code=attr-defined

from __future__ import annotations

import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.service import (
    analyze_task,
    build_scoring_config,
    finalize_audit_analysis,
)
from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    AUDIT_STATUS_ANALYZING,
    AUDIT_STATUS_FAILED,
    AUDIT_STATUS_RUNNING,
    AUDIT_TERMINAL_STATUSES,
    EVENT_TASK_FAILED,
    EVENT_TASK_RETRY,
    EVENT_TASK_SUCCEEDED,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ERROR_AUTH,
    ERROR_PARSE,
    RETRYABLE_ERRORS,
)
from app.core.config.task_queue import (
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    TASK_TERMINAL_STATUSES,
)
from app.domain.audits.state_events import apply_transition, record_event
from app.domain.commerce.shelf import analyze_commerce_task, finalize_commerce_shelf
from app.domain.opportunities.verification import enqueue_audit_opportunity_tasks
from app.domain.providers.credentials import pause_connection_after_key_failure
from app.models.audit import (
    Audit,
    AuditTask,
    ProviderAttempt,
)
from app.workers.audit_worker_support import (
    CallAttempt,
)
from app.workers.audit_worker_support import (
    apply_response_to_task as _apply_response_to_task,
)
from app.workers.audit_worker_support import (
    build_artifact as _build_artifact,
)
from app.workers.audit_worker_support import (
    frozen_connection_id_from as _frozen_connection_id_from,
)
from app.workers.audit_worker_support import (
    serialize_citations as _serialize_citations,
)
from app.workers.audit_worker_support import (
    serialize_search_events as _serialize_search_events,
)
from app.workers.audit_worker_support import (
    utcnow as _utcnow,
)

logger = logging.getLogger("app.workers.audit_worker")

# Statuses a task may hold while the PRE-CALL writers act on it. The row is
# still `leased` (not `running`) until provider capacity is held, so the
# terminal-rejection / adapter-failure / capacity-park paths must accept it;
# `running` stays accepted because a retry re-enters those paths.
TASK_PRE_CALL_STATUSES = frozenset({TASK_STATUS_LEASED, TASK_STATUS_RUNNING})


class AuditTerminalizationMixin:
    """Concrete terminal stages composed by the public worker."""

    async def _persist_success(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        request_snapshot: dict,
    ) -> None:
        response = attempts[-1].response
        if response is None:
            raise RuntimeError("successful audit persistence requires a response")
        search_events = _serialize_search_events(response)
        citations = _serialize_citations(response)
        artifact_id: uuid.UUID | None = None
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock BEFORE writing any evidence
            # (invariant 3/8). If the lease was lost or the audit cancelled, the
            # provider response is discarded — no artifact/attempt/analysis.
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, audit_id=audit_id
            )
            if locked is None:
                await session.rollback()
                return
            task, audit = locked
            # Immutable raw artifact (invariant 3): written once, never mutated.
            artifact = _build_artifact(
                audit_id=audit_id,
                task_id=task_id,
                response=response,
                search_events=search_events,
                citations=citations,
            )
            session.add(artifact)
            await session.flush()
            artifact_id = artifact.id
            _apply_response_to_task(
                task,
                response=response,
                request_snapshot=request_snapshot,
                search_events=search_events,
                citations=citations,
                artifact_id=artifact_id,
            )

            # Score on persist (invariants 4/9): the deterministic analyzer runs
            # against the just-persisted answer + citations (no provider call)
            # and writes the derived ResponseAnalysis + mention/citation rows,
            # each stamped with the raw-artifact provenance + analyzer_version.
            config = build_scoring_config(audit.configuration)
            analysis = await analyze_task(session, task=task, config=config)
            if analysis is not None:
                task.score = analysis.score

            await analyze_commerce_task(session, task=task)

            # One ProviderAttempt per actual call (retries + final success).
            self._record_attempts(
                session,
                task=task,
                audit_id=audit_id,
                attempts=attempts,
                logical_engine=logical_engine,
                transport_provider=transport_provider,
                transport_model=transport_model,
                artifact_id=artifact_id,
            )
            # Funded ledger (no-op BYOK): bill the just-persisted call and
            # release the task's unused reservation at this terminalization.
            await self._apply_funded_ledger(
                session, task=task, billable=True, terminal=True
            )
            # Append-only cost projection (invariant 3): built AFTER the
            # ProviderAttempt rows so attempt_count is the persisted actual
            # call count. Unknown usage/rates stay null — never zero, and an
            # unknown pricing catalog skips the row instead of blocking the
            # success path.
            self._record_cost_projection(
                session, artifact=artifact, attempt_count=task.attempt_count
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_SUCCEEDED,
                message="task succeeded",
                payload={"task_id": str(task_id)},
            )
            await session.commit()

        await self._queue.succeed(
            task_id=task_id, owner=self.owner, result_artifact_id=artifact_id
        )

    async def _pause_frozen_credential_on_auth_failure(
        self, session: AsyncSession, *, task: AuditTask, error_code: str
    ) -> None:
        """Pause the task's FROZEN credential after an auth-classified failure.

        Tenant BYOK row or platform row alike — the pause writer keys the
        telemetry event off the row's own ``credential_source``. Runs inside
        the failure-path's owner-locked transaction so the pause lands
        atomically with the attempt evidence (invariant 3/8). A missing
        frozen id (or a row deleted mid-run) is a no-op: the task's failure
        handling must never crash on credential bookkeeping.
        """
        if error_code != ERROR_AUTH:
            return
        connection_id = _frozen_connection_id_from(task.provider_route_snapshot)
        if connection_id is None:
            return
        await pause_connection_after_key_failure(session, connection_id, _utcnow())

    async def _handle_failure(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        request_snapshot: dict,
    ) -> None:
        error = attempts[-1].error
        error_code = error.error_code if error else ERROR_PARSE
        error_detail = str(error) if error else "unknown provider error"
        retryable = bool(error and error.retryable and error_code in RETRYABLE_ERRORS)
        retry_after = getattr(error, "retry_after_seconds", None)

        will_retry = False
        attempt_number = 0
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock before writing evidence
            # (invariant 3/8): a stale/cancelled worker must not touch the task.
            locked = await self._lock_owned_running_task(
                session, task_id=task_id, audit_id=audit_id
            )
            if locked is None:
                await session.rollback()
                return
            task, _audit = locked
            task.request_snapshot = request_snapshot
            # One ProviderAttempt per actual call (all failed on this path).
            self._record_attempts(
                session,
                task=task,
                audit_id=audit_id,
                attempts=attempts,
                logical_engine=logical_engine,
                transport_provider=transport_provider,
                transport_model=transport_model,
                artifact_id=None,
            )
            attempt_number = task.attempt_count
            exhausted = task.attempt_count >= task.max_attempts
            will_retry = retryable and not exhausted
            # Funded ledger (no-op BYOK): bill this actual call — a timed-out
            # call bills too — and release the unused reservation only when
            # the task terminalizes (a queue retry keeps it for the next call).
            await self._apply_funded_ledger(
                session, task=task, billable=True, terminal=not will_retry
            )
            # T11 auth pause (details on the helper): pauses the FROZEN
            # credential so no NEW task resolves it until the grace deadline;
            # this task still fails through current finalization below and
            # there is NO silent platform fallback.
            await self._pause_frozen_credential_on_auth_failure(
                session, task=task, error_code=error_code
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_RETRY if will_retry else EVENT_TASK_FAILED,
                message="task retry" if will_retry else "task failed",
                payload={"task_id": str(task_id), "error_code": error_code},
            )
            await session.commit()

        if will_retry:
            await self._queue.retry(
                task_id=task_id,
                owner=self.owner,
                delay_seconds=audit_settings.retry_delay(attempt_number, retry_after),
                error_code=error_code,
                error_detail=error_detail,
            )
        else:
            await self._queue.fail(
                task_id=task_id,
                owner=self.owner,
                error_code=error_code,
                error_detail=error_detail,
            )

    async def _fail_terminal(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        error_code: str,
        error_detail: str,
        request_snapshot: dict | None = None,
    ) -> None:
        """Terminally fail a task (non-retryable misconfiguration)."""
        async with self._session_factory() as session:
            # Owner + liveness check under a row lock before writing evidence
            # (invariant 3/8): even a terminal fail must not touch a task this
            # worker no longer owns or an audit that was cancelled meanwhile.
            # Pre-call path: both rejection sites (retired transport / missing
            # connection, and an adapter build failure) run before capacity is
            # held, so the row is still `leased`.
            locked = await self._lock_owned_running_task(
                session,
                task_id=task_id,
                audit_id=audit_id,
                allowed_statuses=TASK_PRE_CALL_STATUSES,
            )
            if locked is None:
                await session.rollback()
                return
            task, _audit = locked
            task.attempt_count += 1
            if request_snapshot is not None:
                task.request_snapshot = request_snapshot
            session.add(
                ProviderAttempt(
                    task_id=task_id,
                    audit_id=audit_id,
                    attempt_number=task.attempt_count,
                    logical_engine=logical_engine,
                    transport_provider=transport_provider,
                    transport_model=transport_model,
                    status=ATTEMPT_STATUS_FAILED,
                    error_code=error_code,
                    error_detail=error_detail[:2000],
                )
            )
            # No provider call happened (terminal misconfiguration): nothing
            # to bill, but the task's unused funded reservation is released
            # (BYOK no-op) so a rejected funded task never strands credits.
            await self._apply_funded_ledger(
                session, task=task, billable=False, terminal=True
            )
            record_event(
                session,
                audit_id=audit_id,
                event_type=EVENT_TASK_FAILED,
                message="task failed",
                payload={"task_id": str(task_id), "error_code": error_code},
            )
            await session.commit()
        await self._queue.fail(
            task_id=task_id,
            owner=self.owner,
            error_code=error_code,
            error_detail=error_detail,
        )

    async def _record_crash(self, task_id: uuid.UUID, exc: Exception) -> None:
        detail = f"{type(exc).__name__}: {exc}"
        failed = await self._queue.fail(
            task_id=task_id,
            owner=self.owner,
            error_code=ERROR_PARSE,
            error_detail=detail,
        )
        await self._release_crashed_funded_task(task_id, terminalized=failed)

    async def _release_crashed_funded_task(
        self, task_id: uuid.UUID, *, terminalized: bool
    ) -> None:
        """Release a crashed task's unused funded reservation (best-effort).

        A crash escaping ``_run_provider_call`` ran none of the evidence
        paths, so unlike cancel/deadline/fail-terminal it had no
        funded-ledger terminalization: the reservation — or its unbilled
        remainder — leaked. ``queue.fail`` owns the terminalization and is
        owner-guarded, so a lost lease (the sweeper handed the task to
        another worker, which will bill against the reservation) skips the
        release entirely. A provider call that DID happen was billed by the
        success/failure path before the crash — the ledger releases only
        still-reserved units, so the call stays billed exactly once and the
        remainder is released exactly once.
        """
        if not terminalized:
            return
        await self._release_terminalized_funded_task(task_id, trigger="crash")

    async def _progress_counts(
        self, session: AsyncSession, audit_id: uuid.UUID
    ) -> tuple[int, int, int]:
        """``(succeeded, failed, remaining)`` over an audit's task rows.

        ``failed`` is terminal-but-not-succeeded rather than ``total -
        succeeded``: mid-run the difference matters, because a still-queued or
        in-flight task is not a failure and must never be published as one.
        The two definitions converge once ``remaining`` is 0, so the counts
        this publishes DURING a run land on exactly the terminal figures.
        """
        counted = (
            select(func.count())
            .select_from(AuditTask)
            .where(AuditTask.audit_id == audit_id)
        )
        total = int(await session.scalar(counted) or 0)
        succeeded = int(
            await session.scalar(
                counted.where(AuditTask.status == TASK_STATUS_SUCCEEDED)
            )
            or 0
        )
        terminal = int(
            await session.scalar(
                counted.where(AuditTask.status.in_(list(TASK_TERMINAL_STATUSES)))
            )
            or 0
        )
        return succeeded, terminal - succeeded, total - terminal

    async def _finalize_audit(self, audit_id: uuid.UUID) -> None:
        """Publish live progress, and terminalize once execution is done.

        Runs after EVERY task boundary, and does two things:

        1. Publishes the audit's running ``completed_count`` /
           ``failed_count``. This happens on every pass, not just the last
           one, because those counters ARE the run screen's progress
           indicator: gating them on "no task remains" pinned them at 0 for
           the whole run and then flipped them to the final figures, which
           reads as a hung run rather than a working one.
        2. When no non-terminal task remains, transitions RUNNING ->
           ANALYZING (>=1 success) or RUNNING -> FAILED (0 successes). On
           ANALYZING it hands straight to the analysis stage (aggregate +
           terminal).

        A cancelled audit keeps its status. Guarded with ``FOR UPDATE`` so
        concurrent workers don't double-finalize or interleave counts.
        """
        reached_analyzing = False
        async with self._session_factory() as session:
            audit = await session.get(Audit, audit_id, with_for_update=True)
            if audit is None or audit.status in AUDIT_TERMINAL_STATUSES:
                if audit is not None:
                    await session.rollback()
                return
            succeeded, failed, remaining = await self._progress_counts(
                session, audit_id
            )
            # Only dirty the row when a count actually moved: this method runs
            # at every task boundary INCLUDING capacity parks, and an
            # unconditional write would churn `updated_at` on passes that
            # observed no progress at all.
            if audit.completed_count != succeeded or audit.failed_count != failed:
                audit.completed_count = succeeded
                audit.failed_count = failed
            if remaining > 0:
                # Execution still in flight: the counts above are this pass's
                # only contribution; the transition waits for the last task.
                await session.commit()
                return
            if audit.status == AUDIT_STATUS_RUNNING:
                if succeeded == 0:
                    audit.completed_at = _utcnow()
                    apply_transition(
                        session,
                        audit=audit,
                        target=AUDIT_STATUS_FAILED,
                        message="audit failed: no successful executions",
                    )
                    audit.error_message = "no successful executions"
                else:
                    # Execution done; hand to the deterministic analysis stage.
                    apply_transition(
                        session,
                        audit=audit,
                        target=AUDIT_STATUS_ANALYZING,
                        message="execution complete; ready for analysis",
                        payload={"completed": succeeded, "failed": failed},
                    )
                    reached_analyzing = True
            await session.commit()

        if reached_analyzing:
            await self._finalize_analysis(audit_id)

    async def _finalize_analysis(self, audit_id: uuid.UUID) -> None:
        """Aggregate the MetricSnapshot + resolve the terminal status (B6).

        Runs once an audit reaches ANALYZING. Aggregates from persisted analyses
        only (invariant 7 — no provider call) and drives ANALYZING -> REPORTING
        -> COMPLETED / PARTIALLY_COMPLETED. Guarded with ``FOR UPDATE`` so
        concurrent workers don't double-finalize. After the terminal commit it
        best-effort queues the project's Opportunities refresh — this is the
        ONLY audit-side hook: ``_finalize_audit`` never fires it (execution
        boundary, no snapshots yet) and failed audits never reach ANALYZING.
        """
        async with self._session_factory() as session:
            audit = await session.get(Audit, audit_id, with_for_update=True)
            if audit is None or audit.status != AUDIT_STATUS_ANALYZING:
                if audit is not None:
                    await session.rollback()
                return
            try:
                async with session.begin_nested():
                    await finalize_commerce_shelf(session, audit=audit)
            except Exception:
                logger.exception(
                    "Commerce shelf finalization failed; terminalizing audit %s",
                    audit_id,
                )
            await finalize_audit_analysis(session, audit=audit)
            workspace_id = audit.workspace_id
            project_id = audit.project_id
            await session.commit()

        await self._enqueue_opportunity_refresh(
            audit_id=audit_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )

    async def _enqueue_opportunity_refresh(
        self,
        *,
        audit_id: uuid.UUID,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
    ) -> None:
        """Queue downstream work without reopening the terminal audit write."""

        # Queue work only after the source audit is durably terminal. A queue
        # outage must never roll back the evidence and snapshot above.
        try:
            async with self._session_factory() as session:
                await enqueue_audit_opportunity_tasks(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    audit_id=audit_id,
                )
                await session.commit()
        except Exception:
            logger.exception(
                "opportunity refresh enqueue failed",
                extra={"audit_id": str(audit_id)},
            )
