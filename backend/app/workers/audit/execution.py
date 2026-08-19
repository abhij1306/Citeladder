"""Provider execution, lease-guarded writes, and funded task accounting."""
# mypy: disable-error-code=attr-defined

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
)
from app.connectors.answer_engines.errors import ProviderError
from app.connectors.answer_engines.factory import build_adapter
from app.core.config.audits import (
    ATTEMPT_STATUS_FAILED,
    ATTEMPT_STATUS_SUCCEEDED,
    AUDIT_STATUS_CANCELLED,
    AUDIT_TERMINAL_STATUSES,
    CAPACITY_OUTCOME_FAILED,
    EVENT_TASK_CAPACITY_WAIT,
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
    audit_settings,
    measurement_policy_from_configuration,
)
from app.core.config.costs import (
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    RouteIdentity,
    route_pricing_for,
)
from app.core.config.provider_catalog import (
    ERROR_PARSE,
)
from app.core.security import decrypt_secret
from app.domain.audits.cost_projection import build_execution_cost_projection
from app.domain.audits.state_events import record_event
from app.domain.entitlements.ledger import (
    record_billable_attempt,
    release_terminal_funded_task,
)
from app.models.audit import (
    Audit,
    AuditEvent,
    AuditTask,
    ProviderAttempt,
    RawResponseArtifact,
)
from app.models.provider import ProviderConnection
from app.orchestration.provider_capacity import (
    CapacityDecision,
    CapacityOutcome,
    CapacityRequest,
    acquire_provider_capacity,
    release_provider_capacity,
)
from app.workers.audit_worker_support import (
    CallAttempt,
    pace_provider_request,
)
from app.workers.audit_worker_support import (
    ExecutionContext as _ExecutionContext,
)
from app.workers.audit_worker_support import (
    build_call_request as _build_call_request,
)
from app.workers.audit_worker_support import (
    call_provider_once as _call_provider_once,
)
from app.workers.audit_worker_support import (
    capacity_outcome as _capacity_outcome,
)
from app.workers.audit_worker_support import (
    capacity_request as _capacity_request,
)
from app.workers.audit_worker_support import (
    capacity_wait_payload as _capacity_wait_payload,
)
from app.workers.audit_worker_support import (
    frozen_connection_id_from as _frozen_connection_id_from,
)
from app.workers.audit_worker_support import (
    frozen_funding_from as _frozen_funding_from,
)
from app.workers.audit_worker_support import (
    terminal_rejection as _terminal_rejection,
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


class AuditExecutionMixin:
    """Concrete execution stages composed by the public worker."""

    async def _run_provider_call(self, task_id: uuid.UUID, audit_id: uuid.UUID) -> bool:
        """Orchestrate ONE queue attempt: load -> validate -> capacity -> call.

        A thin shell over the helpers below — each owns one concern (frozen
        context, terminal validation, adapter build, capacity, the single
        call, outcome persistence) so no function carries the old CC-17 lump.

        Returns True when the attempt PARKED on a capacity refusal (no
        provider call was made and the task is back in the claimable set).
        """
        context = await self._load_execution_context(task_id, audit_id)
        if context is None:
            return False
        rejection = _terminal_rejection(context)
        if rejection is not None:
            await self._fail_terminal(
                task_id=task_id,
                audit_id=audit_id,
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                transport_model=context.transport_model,
                error_code=rejection[0],
                error_detail=rejection[1],
            )
            return False
        request, request_snapshot = _build_call_request(context)
        adapter = await self._build_adapter_or_fail(context, request_snapshot)
        if adapter is None:
            return False
        # Capacity I/O happens only AFTER the claim committed (invariant 8).
        capacity = _capacity_request(context)
        decision = await acquire_provider_capacity(
            self._session_factory, request=capacity
        )
        if not decision.acquired:
            # Parked: NO provider call happens, so no attempt budget is spent
            # and no ledger unit is billed. The task re-enters the claimable
            # set once the decision's available_at passes.
            await self._park_capacity_wait(
                task_id=task_id, audit_id=audit_id, decision=decision
            )
            return True
        # Capacity is held: NOW the row is genuinely running. Losing the lease
        # here means the sweeper handed the task to another worker, so this
        # attempt must hand the slot straight back rather than call out.
        if not await self._queue.mark_running(task_id=task_id, owner=self.owner):
            await release_provider_capacity(
                self._session_factory,
                request=capacity,
                outcome=CapacityOutcome(kind=CAPACITY_OUTCOME_FAILED),
            )
            return False
        attempt = await self._execute_with_capacity(context, capacity, adapter, request)
        await self._persist_attempt_outcome(context, attempt, request_snapshot)
        return False

    async def _persist_attempt_outcome(
        self,
        context: _ExecutionContext,
        attempt: CallAttempt,
        request_snapshot: dict,
    ) -> None:
        """Route ONE finished call to the success or failure persistence path.

        Both sides take the same identity block, so the only real decision
        here is which one runs — kept out of ``_run_provider_call`` so that
        function stays the load/validate/capacity/call shell it documents.
        """
        persist = self._persist_success if attempt.succeeded else self._handle_failure
        await persist(
            task_id=context.task_id,
            audit_id=context.audit_id,
            attempts=[attempt],
            logical_engine=context.logical_engine,
            transport_provider=context.transport_provider,
            transport_model=context.transport_model,
            request_snapshot=request_snapshot,
        )

    async def _load_execution_context(
        self, task_id: uuid.UUID, audit_id: uuid.UUID
    ) -> _ExecutionContext | None:
        """Load everything the call needs in one short session, then close it.

        The session ends before any capacity/provider I/O so no transaction is
        ever held across a network call (invariant 8). The measurement policy
        comes from the FROZEN configuration, never the live settings: an env
        change must not alter an in-flight run (invariant 9).

        The credential is the FROZEN identity from the task's route snapshot
        (T11): the worker loads exactly the connection the planner froze —
        tenant BYOK or the platform row in the system workspace — by id only.
        The frozen identity IS the authorization, so the lookup deliberately
        does NOT apply tenant-workspace scoping, and the worker never
        re-resolves or falls back to another credential.
        """
        async with self._session_factory() as session:
            task = await session.get(AuditTask, task_id)
            audit = await session.get(Audit, audit_id)
            if task is None or audit is None:
                return None
            route_snapshot = task.provider_route_snapshot or {}
            connection_id = _frozen_connection_id_from(route_snapshot)
            connection: ProviderConnection | None = None
            if connection_id is not None:
                connection = await session.get(ProviderConnection, connection_id)
            configuration = dict(audit.configuration or {})
            return _ExecutionContext(
                task_id=task_id,
                audit_id=audit_id,
                logical_engine=task.logical_engine,
                transport_provider=task.transport_provider,
                transport_model=task.transport_model,
                prompt_text=task.prompt_text or "",
                system_instruction=audit.system_instruction or "",
                configuration=configuration,
                policy=measurement_policy_from_configuration(configuration),
                base_url=str(route_snapshot.get("base_url") or ""),
                attempt_number=task.attempt_count + 1,
                connection_id=connection_id,
                connection_active=(
                    bool(connection.active) if connection is not None else False
                ),
                api_key_encrypted=(
                    connection.api_key_encrypted if connection is not None else ""
                ),
                funding=_frozen_funding_from(task.provider_route_snapshot),
            )

    async def _build_adapter_or_fail(
        self, context: _ExecutionContext, request_snapshot: dict
    ):
        """Build the adapter from the execution-time decrypted BYOK key.

        The key is resolved at execution time only — never logged, persisted,
        or placed in a snapshot (invariant 6). A build failure is a terminal
        misconfiguration, not a retryable provider error.
        """
        api_key = decrypt_secret(context.api_key_encrypted)
        try:
            return build_adapter(
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                api_key=api_key,
                country_code=str(context.configuration.get("country_code", "")),
                base_url=context.base_url,
            )
        except ProviderError as exc:
            await self._fail_terminal(
                task_id=context.task_id,
                audit_id=context.audit_id,
                logical_engine=context.logical_engine,
                transport_provider=context.transport_provider,
                transport_model=context.transport_model,
                error_code=exc.error_code,
                error_detail=str(exc),
                request_snapshot=request_snapshot,
            )
            return None

    async def _execute_with_capacity(
        self,
        context: _ExecutionContext,
        capacity: CapacityRequest,
        adapter,
        request: AnswerEngineRequest,
    ) -> CallAttempt:
        """Run the single provider call under held capacity; ALWAYS release.

        The release carries the call's outcome so a provider 429 writes the
        shared pool cooldown (``rate_limited``) while any other result simply
        returns the concurrency leases. Token starts stay consumed either
        way; an abandoned call (crash/cancellation) releases as ``failed``.
        """
        attempt: CallAttempt | None = None
        try:
            attempt = await self._execute_one_attempt(context, adapter, request)
            return attempt
        finally:
            await release_provider_capacity(
                self._session_factory,
                request=capacity,
                outcome=(
                    _capacity_outcome(attempt)
                    if attempt is not None
                    else CapacityOutcome(kind=CAPACITY_OUTCOME_FAILED)
                ),
            )

    async def _execute_one_attempt(
        self, context: _ExecutionContext, adapter, request: AnswerEngineRequest
    ) -> CallAttempt:
        """Make this queue attempt's ONE provider call, heartbeating the lease.

        The per-call ceiling is the FROZEN mode timeout from the task's
        configuration — never the live settings (invariant 9).
        """
        heartbeat = asyncio.create_task(self._heartbeat_loop(context.task_id))
        try:
            return await _call_provider_once(
                adapter,
                request,
                timeout_seconds=context.policy.timeout_seconds,
                pace_request=pace_provider_request,
            )
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    async def _park_capacity_wait(
        self,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        decision: CapacityDecision,
    ) -> None:
        """Park the task on a capacity refusal; the attempt budget is untouched.

        Records ``EVENT_TASK_CAPACITY_WAIT`` (opaque ids + retry timing only —
        invariant 6) under the owner/liveness lock, then hands the row to the
        queue, which re-parks it claimable once ``available_at`` passes.

        The event is recorded AT MOST ONCE per (task, attempt, refusal code).
        A task that cannot get capacity re-parks every
        ``capacity_concurrency_retry_seconds`` for as long as the pool is
        full, and recording each one turned the event log into park churn — a
        measured 10-prompt run logged 132 ``task.capacity_wait`` events
        against 10 real task events. Since every event is an SSE frame that
        invalidates the run screen's queries, that churn cost a refetch storm
        to report a state that had not changed. One event per distinct wait
        carries the same information.
        """
        async with self._session_factory() as session:
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
            attempt_number = task.attempt_count + 1
            if await self._capacity_wait_already_recorded(
                session,
                audit_id=audit_id,
                task_id=task_id,
                attempt_number=attempt_number,
                code=decision.code,
            ):
                await session.rollback()
            else:
                record_event(
                    session,
                    audit_id=audit_id,
                    event_type=EVENT_TASK_CAPACITY_WAIT,
                    message="task waiting on provider capacity",
                    payload=_capacity_wait_payload(
                        task_id=task_id,
                        attempt_number=attempt_number,
                        decision=decision,
                    ),
                )
                await session.commit()
        await self._queue.park_capacity_wait(
            task_id=task_id,
            owner=self.owner,
            available_at=decision.available_at or _utcnow(),
        )

    async def _capacity_wait_already_recorded(
        self,
        session: AsyncSession,
        *,
        audit_id: uuid.UUID,
        task_id: uuid.UUID,
        attempt_number: int,
        code: str,
    ) -> bool:
        """True when THIS wait was already recorded for this task attempt.

        Keyed on (task, attempt, refusal code) so a task that parks, waits
        out a full pool, and then parks again for a DIFFERENT reason (a
        provider 429 rather than local concurrency) still records the new
        condition — only the identical repeat is suppressed. Runs under the
        caller's row lock on the task, so two workers cannot both decide the
        event is missing.
        """
        existing = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.audit_id == audit_id)
            .where(AuditEvent.event_type == EVENT_TASK_CAPACITY_WAIT)
            .where(
                AuditEvent.payload.contains(
                    {"task_id": str(task_id), "attempt": attempt_number, "code": code}
                )
            )
        )
        return bool(existing)

    async def _apply_funded_ledger(
        self,
        session: AsyncSession,
        *,
        task: AuditTask,
        billable: bool,
        terminal: bool,
    ) -> None:
        """The funded-ledger call sites for one task (no-op for BYOK).

        ``billable`` converts one reserved unit into a billable attempt — one
        per ACTUAL provider call, including timeouts (a timed-out call is
        billable), keyed on the just-persisted 1-based ``attempt_count`` with
        a deterministic idempotency key so a replay never double-debits.
        ``terminal`` releases the task's unused reservation exactly once at
        terminalization (idempotent on the ledger side). Caller owns the
        commit so the ledger rows land atomically with the attempt row.
        """
        funding = _frozen_funding_from(task.provider_route_snapshot)
        if funding is None:
            return
        if billable:
            await record_billable_attempt(
                session,
                reservation_id=funding.reservation_id,
                task_id=task.id,
                attempt=task.attempt_count,
                idempotency_key=f"{task.id}:{task.attempt_count}:funded-billable",
                at=_utcnow(),
            )
        if terminal:
            await release_terminal_funded_task(
                session,
                reservation_id=funding.reservation_id,
                audit_id=task.audit_id,
                task_id=task.id,
                trigger="unused",
                at=_utcnow(),
            )

    async def _heartbeat_loop(
        self, task_id: uuid.UUID
    ) -> None:  # pragma: no cover - timing loop
        interval = max(1.0, audit_settings.heartbeat_interval_seconds)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._queue.heartbeat(task_id=task_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dead heartbeat loop silently expires the lease and lets the
                # sweeper hand the task to another worker mid-call; keep beating
                # through transient failures instead.
                logger.exception(
                    "heartbeat failed; retrying", extra={"task_id": str(task_id)}
                )

    async def _lock_owned_running_task(
        self,
        session: AsyncSession,
        *,
        task_id: uuid.UUID,
        audit_id: uuid.UUID,
        allowed_statuses: frozenset[str] = frozenset({TASK_STATUS_RUNNING}),
    ) -> tuple[AuditTask, Audit] | None:
        """Lock the task FOR UPDATE and verify we still own it before writing.

        Guards invariant 3/8 (single writer / no double-claim). Between the
        provider call finishing and this write, the lease could have expired
        (sweeper -> another worker claimed it) or the audit could have been
        cancelled. Returns ``(task, audit)`` only when the task is still leased
        to THIS worker, in one of ``allowed_statuses``, and the audit is not
        cancelled or terminal; otherwise ``None`` and the stale provider
        result is discarded.

        ``allowed_statuses`` defaults to ``running`` — the post-call evidence
        writers. The pre-call writers (terminal rejection, adapter build
        failure, capacity park) pass ``TASK_PRE_CALL_STATUSES`` instead,
        because the row is deliberately still ``leased`` until capacity is
        held. Each call site declares what it expects rather than the gate
        blanket-accepting both, so a post-call write can still never land on
        a task that never started.
        """
        task = await session.get(AuditTask, task_id, with_for_update=True)
        if task is None:
            return None
        if task.lease_owner != self.owner or task.status not in allowed_statuses:
            return None
        audit = await session.get(Audit, audit_id)
        if (
            audit is None
            or audit.status == AUDIT_STATUS_CANCELLED
            or (audit.status in AUDIT_TERMINAL_STATUSES)
        ):
            return None
        return task, audit

    def _record_attempts(
        self,
        session: AsyncSession,
        *,
        task: AuditTask,
        audit_id: uuid.UUID,
        attempts: list[CallAttempt],
        logical_engine: str,
        transport_provider: str,
        transport_model: str,
        artifact_id: uuid.UUID | None,
    ) -> None:
        """Append one immutable ProviderAttempt per actual provider call.

        ProviderAttempt is append-only "one row per attempt" (invariant 3):
        one queue attempt makes one call, so each persistence pass appends
        exactly one row — a task that failed twice through queue retries and
        then succeeded ends with three rows (two failed + one succeeded), not
        a single collapsed row. Advances ``attempt_count`` by the number of
        calls made and stamps each row's ``attempt_number``.
        """
        base = task.attempt_count
        for offset, attempt in enumerate(attempts, start=1):
            attempt_number = base + offset
            response = attempt.response
            if response is not None:
                session.add(
                    ProviderAttempt(
                        task_id=task.id,
                        audit_id=audit_id,
                        attempt_number=attempt_number,
                        logical_engine=response.logical_engine,
                        transport_provider=response.transport_provider,
                        transport_model=response.transport_model,
                        status=ATTEMPT_STATUS_SUCCEEDED,
                        latency_ms=response.latency_ms,
                        artifact_id=artifact_id,
                    )
                )
            else:
                error = attempt.error
                error_code = error.error_code if error else ERROR_PARSE
                error_detail = str(error) if error else "unknown provider error"
                session.add(
                    ProviderAttempt(
                        task_id=task.id,
                        audit_id=audit_id,
                        attempt_number=attempt_number,
                        logical_engine=logical_engine,
                        transport_provider=transport_provider,
                        transport_model=transport_model,
                        status=ATTEMPT_STATUS_FAILED,
                        error_code=error_code,
                        error_detail=error_detail[:2000],
                    )
                )
        task.attempt_count = base + len(attempts)

    def _record_cost_projection(
        self,
        session: AsyncSession,
        *,
        artifact: RawResponseArtifact,
        attempt_count: int,
    ) -> None:
        """Price one persisted artifact into an append-only projection row.

        Reads the artifact's own persisted route identity for the pricing
        lookup (never the request snapshot) and stamps the persisted ACTUAL
        attempt count — ProviderAttempt rows are written before this runs.
        The row is analytics-only: a pricing-catalog miss logs a safe warning
        and SKIPS the projection — unknown pricing never blocks evidence (the
        assert this replaced rolled the whole success transaction back,
        losing the artifact, the attempts, and the funded bill+release to a
        post-call crash).
        """

        pricing = route_pricing_for(
            RouteIdentity(
                logical_engine=artifact.logical_engine,
                transport_provider=artifact.transport_provider,
                transport_model=artifact.transport_model,
            ),
            PRICING_CATALOG_VERSION,
        )
        if pricing is None:
            logger.warning(
                "execution cost projection skipped: no pricing for route",
                extra={
                    "logical_engine": artifact.logical_engine,
                    "transport_provider": artifact.transport_provider,
                    "transport_model": artifact.transport_model,
                },
            )
            return
        session.add(
            build_execution_cost_projection(
                artifact,
                pricing=pricing,
                formula_version=EXECUTION_COST_FORMULA_VERSION,
                attempt_count=attempt_count,
            )
        )
