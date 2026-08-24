"""Stateless support for the audit worker's one-call execution contract.

This module deliberately has no queue, session, or lifecycle ownership.  The
``AuditWorker`` keeps those boundaries and re-exports these names for existing
worker-level callers and tests.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
)
from app.connectors.answer_engines.errors import ProviderError
from app.connectors.answer_engines.normalization import normalized_usage_dict
from app.core.config import settings
from app.core.config.audits import (
    CAPACITY_OUTCOME_FAILED,
    CAPACITY_OUTCOME_RATE_LIMITED,
    CAPACITY_OUTCOME_SUCCEEDED,
    CREDENTIAL_KIND_BYOK,
    CREDENTIAL_KIND_FUNDED,
    ERROR_NO_CONNECTION,
    AuditExecutionPolicy,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ERROR_INVALID_SURFACE,
    ERROR_RATE_LIMIT,
    ERROR_TIMEOUT,
    is_active_transport,
    is_endpoint_approved,
    route_policy,
)
from app.models.audit import AuditTask, RawResponseArtifact
from app.orchestration.provider_capacity import (
    CapacityDecision,
    CapacityOutcome,
    CapacityRequest,
)

logger = logging.getLogger("app.workers.audit_worker")


def utcnow() -> datetime:
    return datetime.now(UTC)


def drain_horizon_seconds() -> float:
    """How long a one-shot drain waits for a parked row to become claimable."""
    return audit_settings.capacity_concurrency_retry_seconds + max(
        0.05, audit_settings.poll_interval_seconds
    )


# --- Request pacing (per transport, across concurrent tasks in this process) --
_provider_pacing_locks: dict[str, asyncio.Lock] = {}
_provider_last_request_started: dict[str, float] = {}


async def pace_provider_request(transport_provider: str) -> None:
    """Space provider request starts per transport to respect rate limits."""
    interval = max(0.0, audit_settings.min_request_interval_seconds)
    if interval <= 0:
        return
    lock = _provider_pacing_locks.setdefault(transport_provider, asyncio.Lock())
    async with lock:
        last_started = _provider_last_request_started.get(transport_provider)
        if last_started is not None:
            remaining = interval - (time.monotonic() - last_started)
            if remaining > 0:
                await asyncio.sleep(remaining)
        _provider_last_request_started[transport_provider] = time.monotonic()


@dataclass
class CallAttempt:
    """The outcome of ONE actual provider call (a success or a failure)."""

    response: AnswerEngineResponse | None
    error: ProviderError | None

    @property
    def succeeded(self) -> bool:
        return self.response is not None


async def call_provider_once(
    adapter,
    request: AnswerEngineRequest,
    *,
    timeout_seconds: float,
    pace_request: Callable[[str], Awaitable[None]] = pace_provider_request,
) -> CallAttempt:
    """Make ONE provider call for ONE queue attempt (the sole-call contract)."""
    try:
        await pace_request(adapter.transport_provider)
        response = await asyncio.wait_for(
            adapter.execute(request),
            timeout=timeout_seconds,
        )
        return CallAttempt(response=response, error=None)
    except TimeoutError:
        return CallAttempt(
            response=None,
            error=ProviderError(
                f"provider call exceeded timeout_seconds ({timeout_seconds}s)",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ),
        )
    except ProviderError as exc:
        return CallAttempt(response=None, error=exc)


@dataclass(frozen=True, slots=True)
class FrozenFunding:
    """The planner-frozen funded reservation one task bills against."""

    reservation_id: uuid.UUID
    billing_account_id: uuid.UUID | None


def frozen_connection_id_from(route_snapshot: dict | None) -> uuid.UUID | None:
    """Return the planner-frozen concrete connection id for a task."""
    frozen = (route_snapshot or {}).get("connection_id")
    return uuid.UUID(str(frozen)) if frozen else None


def frozen_funding_from(route_snapshot: dict | None) -> FrozenFunding | None:
    """Read the frozen funding block off a task's route snapshot."""
    funding = (route_snapshot or {}).get("funding") or {}
    reservation = funding.get("reservation_id")
    if not reservation:
        return None
    account = funding.get("funding_account_id")
    return FrozenFunding(
        reservation_id=uuid.UUID(str(reservation)),
        billing_account_id=uuid.UUID(str(account)) if account else None,
    )


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    """Everything ONE attempt needs, loaded + frozen BEFORE provider I/O."""

    task_id: uuid.UUID
    audit_id: uuid.UUID
    logical_engine: str
    transport_provider: str
    transport_model: str
    prompt_text: str
    system_instruction: str
    configuration: dict
    policy: AuditExecutionPolicy
    base_url: str
    attempt_number: int
    connection_id: uuid.UUID | None
    connection_active: bool
    api_key_encrypted: str
    funding: FrozenFunding | None


def terminal_rejection(context: ExecutionContext) -> tuple[str, str] | None:
    """Return the pre-I/O terminal rejection, if a frozen task has one."""
    if not is_active_transport(context.transport_provider):
        return (
            ERROR_INVALID_SURFACE,
            "transport provider is retired and not executable",
        )
    if context.connection_id is None or not context.connection_active:
        return (ERROR_NO_CONNECTION, "provider connection missing or inactive")
    if not is_endpoint_approved(context.transport_provider, context.base_url):
        return (ERROR_INVALID_SURFACE, "provider endpoint is not approved")
    return None


def build_call_request(
    context: ExecutionContext,
) -> tuple[AnswerEngineRequest, dict]:
    """Build the adapter request + provenance snapshot from frozen policy."""
    request = build_request(
        prompt_text=context.prompt_text,
        system_instruction=context.system_instruction,
        transport_model=context.transport_model,
        logical_engine=context.logical_engine,
        policy=context.policy,
    )
    snapshot = build_request_snapshot(
        logical_engine=context.logical_engine,
        transport_provider=context.transport_provider,
        transport_model=context.transport_model,
        request=request,
        configuration=context.configuration,
        answer_instruction=context.policy.answer_instruction,
    )
    return request, snapshot


def capacity_request(context: ExecutionContext) -> CapacityRequest:
    """Build this attempt's capacity demand from frozen credential identity."""
    if context.funding is not None:
        return CapacityRequest(
            task_id=context.task_id,
            attempt_number=context.attempt_number,
            logical_engine=context.logical_engine,
            transport_provider=context.transport_provider,
            credential_kind=CREDENTIAL_KIND_FUNDED,
            billing_account_id=context.funding.billing_account_id,
        )
    return CapacityRequest(
        task_id=context.task_id,
        attempt_number=context.attempt_number,
        logical_engine=context.logical_engine,
        transport_provider=context.transport_provider,
        credential_kind=CREDENTIAL_KIND_BYOK,
        connection_id=context.connection_id,
    )


def capacity_wait_payload(
    *, task_id: uuid.UUID, attempt_number: int, decision: CapacityDecision
) -> dict:
    """Build the opaque ``task.capacity_wait`` event body."""
    return {
        "task_id": str(task_id),
        "attempt": attempt_number,
        "code": decision.code,
        "pool_kind": decision.pool_kind,
        "available_at": (
            decision.available_at.isoformat()
            if decision.available_at is not None
            else ""
        ),
        "retry_after_seconds": decision.retry_after_seconds or 0.0,
    }


def capacity_outcome(attempt: CallAttempt) -> CapacityOutcome:
    """Map one finished provider call to its capacity release outcome."""
    if attempt.succeeded:
        return CapacityOutcome(kind=CAPACITY_OUTCOME_SUCCEEDED)
    error = attempt.error
    if error is not None and error.error_code == ERROR_RATE_LIMIT:
        return CapacityOutcome(
            kind=CAPACITY_OUTCOME_RATE_LIMITED,
            retry_after_seconds=error.retry_after_seconds,
        )
    return CapacityOutcome(kind=CAPACITY_OUTCOME_FAILED)


def build_request_snapshot(
    *,
    logical_engine: str,
    transport_provider: str,
    transport_model: str,
    request: AnswerEngineRequest,
    configuration: dict,
    answer_instruction: str,
) -> dict:
    """Build the request provenance snapshot without credentials or brand data."""
    return {
        "logical_engine": logical_engine,
        "transport_provider": transport_provider,
        "transport_model": transport_model,
        "model": request.model,
        "prompt": request.prompt,
        "system_instruction": request.system_instruction,
        "stateless": True,
        "benchmark_mode": configuration.get("benchmark_mode", ""),
        "country_code": configuration.get("country_code", ""),
        "language_code": configuration.get("language_code", ""),
        "retrieval_enabled": request.retrieval_enabled,
        "max_output_tokens": request.max_output_tokens,
        "timeout_seconds": request.timeout_seconds,
        "reasoning_effort": request.reasoning_effort,
        "answer_instruction": answer_instruction,
    }


def build_request(
    *,
    prompt_text: str,
    system_instruction: str,
    transport_model: str,
    logical_engine: str,
    policy: AuditExecutionPolicy,
) -> AnswerEngineRequest:
    """Build an adapter request from the frozen measurement policy only."""
    return AnswerEngineRequest(
        prompt=prompt_text,
        system_instruction=system_instruction,
        model=transport_model,
        timeout_seconds=policy.timeout_seconds,
        retrieval_enabled=policy.retrieval_enabled,
        max_output_tokens=policy.max_output_tokens,
        reasoning_effort=route_policy(logical_engine).reasoning_effort,
    )


def serialize_search_events(response: AnswerEngineResponse) -> list[dict]:
    return [
        {
            "sequence": event.sequence,
            "query": event.query,
            "call_id": event.call_id,
            "call_sequence": event.call_sequence,
            "query_sequence": event.query_sequence,
        }
        for event in response.search_events
    ]


def serialize_citations(response: AnswerEngineResponse) -> list[dict]:
    """Serialize one row per distinct cited source URL."""
    seen: set = set()
    deduped: list[dict] = []
    for citation in response.citations:
        url = str(citation.url or "").strip()
        key = url or (citation.domain, citation.title)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "ordinal": len(deduped),
                "url": citation.url,
                "domain": citation.domain,
                "title": citation.title,
                "start_index": citation.start_index,
                "end_index": citation.end_index,
                "cited_text": citation.cited_text,
            }
        )
    return deduped


def raw_finish_reason(response: AnswerEngineResponse) -> str | None:
    """Return the provider's own finish token, retaining absent as null."""
    return response.raw_finish_reason or None


def build_artifact(
    *,
    audit_id: uuid.UUID,
    task_id: uuid.UUID,
    response: AnswerEngineResponse,
    search_events: list[dict],
    citations: list[dict],
) -> RawResponseArtifact:
    """Build the immutable evidence row for one provider call."""
    return RawResponseArtifact(
        audit_id=audit_id,
        task_id=task_id,
        logical_engine=response.logical_engine,
        transport_provider=response.transport_provider,
        transport_model=response.transport_model,
        answer_text=response.answer_text,
        search_used=response.search_used,
        search_events=search_events,
        citations=citations,
        provider_metadata=dict(response.provider_metadata),
        usage=normalized_usage_dict(response.normalized_usage),
        finish_reason=response.finish_reason,
        raw_finish_reason=raw_finish_reason(response),
        latency_ms=response.latency_ms,
    )


def apply_response_to_task(
    task: AuditTask,
    *,
    response: AnswerEngineResponse,
    request_snapshot: dict,
    search_events: list[dict],
    citations: list[dict],
    artifact_id: uuid.UUID,
) -> None:
    """Project a persisted artifact onto its queue row."""
    task.answer_text = response.answer_text
    task.search_used = response.search_used
    task.search_events = search_events
    task.citations = citations
    task.result_artifact_id = artifact_id
    task.request_snapshot = request_snapshot
    task.provider_metadata = dict(response.provider_metadata)
    task.finish_reason = response.finish_reason
    task.raw_finish_reason = raw_finish_reason(response)
    task.latency_ms = response.latency_ms
    task.error_code = ""
    task.error_detail = ""


def assert_worker_pool_capacity() -> None:
    """Fail fast when the engine pool cannot cover peak worker demand."""
    capacity = settings.db_pool_size + settings.db_max_overflow
    demand = (
        max(1, audit_settings.worker_max_inflight)
        * audit_settings.worker_db_sessions_per_task
        + audit_settings.operational_headroom
    )
    if capacity < demand:
        raise RuntimeError(
            "db pool undersized for audit worker: "
            f"db_pool_size + db_max_overflow = {capacity} < "
            f"worker_max_inflight ({audit_settings.worker_max_inflight}) * "
            f"worker_db_sessions_per_task "
            f"({audit_settings.worker_db_sessions_per_task}) + "
            f"operational_headroom ({audit_settings.operational_headroom}) = "
            f"{demand}; raise DB_POOL_SIZE/DB_MAX_OVERFLOW or lower the "
            "worker demand knobs"
        )


def warn_if_provider_pacing_unbounded() -> None:
    """Log when concurrent provider starts have no configured pacing."""
    concurrency = max(1, audit_settings.worker_concurrency)
    interval = max(0.0, audit_settings.min_request_interval_seconds)
    if interval > 0 or concurrency <= 1:
        return
    logger.warning(
        "provider request pacing is disabled; concurrent calls may hit provider "
        "rate limits (set AUDIT_MIN_REQUEST_INTERVAL_SECONDS to spread starts)",
        extra={
            "worker_concurrency": concurrency,
            "min_request_interval_seconds": interval,
        },
    )
