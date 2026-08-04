# Audit request/response DTOs (string UUID ids; workspace-scoped, invariant 5).
#
# Mirrors the `POST /audits` contract in docs/backend-architecture.md §4. The
# request references a project + prompt source + logical engines; provider keys
# are NEVER carried here — the worker resolves the decrypted key from the
# workspace's ``ProviderConnection`` at execution time (invariant 6). Responses
# never expose secrets or the raw brand list.
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal, get_args

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.core.config.audits import (
    EVENT_AUDIT_CANCELLED,
    EVENT_AUDIT_COMPLETED,
    EVENT_AUDIT_CREATED,
    EVENT_AUDIT_QUEUED,
    EVENT_AUDIT_RUNNING,
    EVENT_AUDIT_STATUS,
    EVENT_TASK_CAPACITY_WAIT,
    EVENT_TASK_FAILED,
    EVENT_TASK_RETRY,
    EVENT_TASK_SUCCEEDED,
    MEASUREMENT_POLICY_KEY,
)

if TYPE_CHECKING:
    # Type-only: domain schemas never import a model at runtime (circular).
    from app.models.audit import AuditEvent
from app.core.config.commerce import SHOPPING_SURFACE_MEASUREMENT
from app.core.config.projects import MAX_REPETITIONS, MIN_REPETITIONS
from app.core.config.provider_catalog import LOGICAL_ENGINES

BenchmarkModeStr = str


# --- Measurement provenance (read-path projections, invariants 4/7) --------
#
# Every helper below derives provenance ONLY from frozen audit/task/artifact
# fields (``Audit.measurement_mode``/``configuration``, the frozen task
# request/route snapshots). Live config is NEVER consulted to infer retrieval
# state or a measurement mode: when the frozen fields do not record a value
# the projection reports ``None``/``""`` rather than guessing (reports are
# projections — if it is not persisted, it does not appear).


class ModelProvenance(BaseModel):
    """One measured route's provenance on an AGGREGATE surface.

    ``(logical_engine, transport_provider, transport_model, retrieval_enabled)``
    for one route the audit measured. Aggregate surfaces (audit, overview,
    trend point, exports) carry a LIST of these in stable catalog order and
    never force a singular model when the aggregate spans models.
    ``retrieval_enabled`` comes only from frozen fields; ``None`` means the
    audit predates the frozen policy block (never inferred from live config).
    """

    logical_engine: str
    transport_provider: str
    transport_model: str
    retrieval_enabled: bool | None = None


# Stable catalog order: the engine order of the approved-route catalog
# (config-owned; unknown/retired engines sort after it, deterministically).
_ENGINE_CATALOG_ORDER: dict[str, int] = {
    engine: index for index, engine in enumerate(sorted(LOGICAL_ENGINES))
}


def _provenance_sort_key(item: ModelProvenance) -> tuple[int, str, str, str, str]:
    return (
        _ENGINE_CATALOG_ORDER.get(item.logical_engine, len(_ENGINE_CATALOG_ORDER)),
        item.logical_engine,
        item.transport_provider,
        item.transport_model,
        "" if item.retrieval_enabled is None else str(item.retrieval_enabled),
    )


def build_model_provenance(
    items: Iterable[ModelProvenance],
) -> list[ModelProvenance]:
    """Dedupe exact provenance items and order them by the stable catalog."""
    unique: dict[tuple[str, str, str, bool | None], ModelProvenance] = {}
    for item in items:
        unique.setdefault(
            (
                item.logical_engine,
                item.transport_provider,
                item.transport_model,
                item.retrieval_enabled,
            ),
            item,
        )
    return sorted(unique.values(), key=_provenance_sort_key)


def frozen_retrieval_enabled(*snapshots: dict | None) -> bool | None:
    """First frozen ``retrieval_enabled`` across snapshots; None if unrecorded."""
    for snapshot in snapshots:
        if isinstance(snapshot, dict):
            retrieval_enabled = snapshot.get("retrieval_enabled")
            if retrieval_enabled is not None:
                return bool(retrieval_enabled)
    return None


def frozen_measurement_mode(*snapshots: dict | None) -> str:
    """First non-empty frozen ``measurement_mode`` across snapshots ("" if none)."""
    for snapshot in snapshots:
        if isinstance(snapshot, dict):
            mode = snapshot.get("measurement_mode")
            if isinstance(mode, str) and mode:
                return mode
    return ""


def audit_frozen_retrieval_enabled(configuration: dict | None) -> bool | None:
    """Retrieval state from the audit's frozen measurement-policy block."""
    frozen = (configuration or {}).get(MEASUREMENT_POLICY_KEY)
    if not isinstance(frozen, dict):
        return None
    return frozen_retrieval_enabled(frozen)


def model_provenance_for(
    engine_snapshots: Iterable[Any], configuration: dict | None
) -> list[ModelProvenance]:
    """Aggregate provenance from frozen engine snapshots + the frozen policy.

    The retrieval state is audit-wide (the frozen mode policy), applied to
    every route the audit measured; items are in stable catalog order.
    """
    retrieval = audit_frozen_retrieval_enabled(configuration)
    return build_model_provenance(
        ModelProvenance(
            logical_engine=snapshot.logical_engine,
            transport_provider=snapshot.transport_provider,
            transport_model=snapshot.transport_model,
            retrieval_enabled=retrieval,
        )
        for snapshot in engine_snapshots
    )


def execution_frozen_provenance(
    *,
    request_snapshot: dict | None,
    route_snapshot: dict | None,
    audit_measurement_mode: str | None = None,
    audit_configuration: dict | None = None,
) -> tuple[str, bool | None]:
    """Frozen ``(measurement_mode, retrieval_enabled)`` for one execution.

    The frozen task request snapshot (what the call executed under) wins,
    then the planner's frozen route snapshot, then the audit's frozen mode
    column + policy block. Live config is never consulted (invariants 4/7).
    """
    mode = frozen_measurement_mode(request_snapshot, route_snapshot)
    if not mode:
        mode = audit_measurement_mode or ""
    retrieval = frozen_retrieval_enabled(request_snapshot, route_snapshot)
    if retrieval is None:
        retrieval = audit_frozen_retrieval_enabled(audit_configuration)
    return mode, retrieval


class AuditCreate(BaseModel):
    """`POST /audits` body. The workspace is resolved from the session/header."""

    project_id: uuid.UUID
    # Prompt source: a whole set, or explicit prompt ids (at least one).
    prompt_set_id: uuid.UUID | None = None
    prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    # Logical engines to measure (chatgpt|gemini|claude). Must have a workspace
    # provider route configured for each.
    engines: list[str] = Field(default_factory=list, min_length=1)
    repetitions: int | None = Field(
        default=None, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )
    benchmark_mode: BenchmarkModeStr | None = None
    # Measurement mode — an axis INDEPENDENT of ``benchmark_mode`` (prompt
    # framing): it selects the frozen route/output policy (retrieval, output
    # cap, timeout, repetitions, answer instruction). Defaults to ``benchmark``
    # so an explicit manual run keeps its full-run shape; a later PR3
    # schedule/trial caller passes its own mode explicitly.
    # The literal spellings are written out rather than interpolated from the
    # config constants: a type checker cannot see through a name inside
    # ``Literal[...]``. The constants remain the DEFAULT and the value the rest
    # of the code compares against, so a drift between the two sides shows up
    # here as a type error instead of passing silently.
    measurement_mode: Literal["pulse", "benchmark"] = "pulse"
    # Optional explicit 64-bit seed (decimal string). Generated + stored when
    # omitted so the slot shuffle is reproducible (invariant 9).
    random_seed: str | None = None


class AuditRepairRequest(BaseModel):
    provider: str | None = None
    engine: str | None = None
    prompt_id: uuid.UUID | None = None
    task_ids: list[uuid.UUID] = Field(default_factory=list)


class AuditEstimateRequest(BaseModel):
    project_id: uuid.UUID
    prompt_set_id: uuid.UUID | None = None
    prompt_ids: list[uuid.UUID] = Field(default_factory=list)
    engines: list[str] = Field(min_length=1)
    repetitions: int | None = Field(
        default=None, ge=MIN_REPETITIONS, le=MAX_REPETITIONS
    )
    measurement_mode: Literal["pulse", "benchmark"] = "pulse"


class AuditEngineEstimate(BaseModel):
    logical_engine: str
    transport_provider: str
    transport_model: str
    retrieval_enabled: bool
    prompt_count: int
    repetition_count: int
    execution_count: int
    maximum_attempt_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_search_calls: int | None
    estimated_token_cost_microusd: int | None
    estimated_search_cost_microusd: int | None
    estimated_total_cost_microusd: int | None
    cost_status: Literal["complete", "partial", "unknown"]
    pricing_version: str


class AuditEstimateResponse(BaseModel):
    measurement_mode: Literal["pulse", "benchmark"]
    retrieval_enabled: bool
    prompt_count: int
    engine_count: int
    repetition_count: int
    execution_count: int
    maximum_attempt_count: int
    maximum_wall_clock_seconds: int
    cost_status: Literal["complete", "partial", "unknown"]
    estimated_total_cost_microusd: int | None
    engines: list[AuditEngineEstimate]


class AuditEnginePerformance(BaseModel):
    logical_engine: str
    execution_count: int
    completed_count: int
    failed_count: int
    retry_count: int
    search_calls: int
    average_provider_latency_ms: float | None
    projected_cost_microusd: int | None


class AuditUsageSummary(BaseModel):
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class AuditPerformanceResponse(BaseModel):
    audit_id: uuid.UUID
    queue_wait_ms: int | None
    total_run_duration_ms: int | None
    time_to_first_result_ms: int | None
    execution_count: int
    completed_count: int
    failed_count: int
    coverage: float
    retry_count: int
    usage: AuditUsageSummary
    search_calls: int
    projected_cost_microusd: int | None
    engines: list[AuditEnginePerformance]


class AuditTaskResponse(BaseModel):
    """A single execution/queue row projection (never contains secrets).

    Execution-level surface: the provenance triple is singular (one execution
    = one exact model). ``measurement_mode``/``retrieval_enabled`` project the
    frozen task request/route snapshots only — never live config (inv. 4/7).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_id: uuid.UUID
    prompt_index: int
    repetition: int
    randomized_position: int
    logical_engine: str
    transport_provider: str
    transport_model: str
    shopping_surface: str = SHOPPING_SURFACE_MEASUREMENT
    measurement_mode: str = ""
    retrieval_enabled: bool | None = None
    status: str
    attempt_count: int
    max_attempts: int
    prompt_text: str = ""
    answer_text: str = ""
    search_used: bool = False
    error_code: str = ""
    error_detail: str = ""
    latency_ms: int | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _inject_frozen_provenance(cls, data: Any) -> Any:
        """Project frozen per-execution provenance from the task snapshots."""
        if isinstance(data, dict):
            return data
        values = {
            name: getattr(data, name)
            for name in cls.model_fields
            if hasattr(data, name)
        }
        values["measurement_mode"], values["retrieval_enabled"] = (
            execution_frozen_provenance(
                request_snapshot=getattr(data, "request_snapshot", None),
                route_snapshot=getattr(data, "provider_route_snapshot", None),
                audit_measurement_mode=getattr(data, "audit_measurement_mode", None),
                audit_configuration=getattr(data, "audit_configuration", None),
            )
        )
        return values


class AuditEngineSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    logical_engine: str
    transport_provider: str
    transport_model: str


class AuditShoppingSurfaceSnapshotResponse(BaseModel):
    """Frozen shopping-surface identity (empty list while the gate is off)."""

    model_config = ConfigDict(from_attributes=True)

    shopping_surface: str
    logical_engine: str
    transport_provider: str
    transport_model: str


class AuditResponse(BaseModel):
    """Audit projection. Includes engine provenance but never the key.

    Aggregate surface: ``measurement_mode`` is the frozen column and
    ``model_provenance`` is the stable catalog-ordered list of every measured
    route (never a forced singular model when the audit spans models).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    parent_audit_id: uuid.UUID | None = None
    status: str
    benchmark_mode: str = ""
    measurement_mode: str = ""
    repetitions: int
    random_seed: str = ""
    requested_count: int
    completed_count: int
    failed_count: int
    error_message: str = ""
    engine_snapshots: list[AuditEngineSnapshotResponse] = Field(default_factory=list)
    shopping_surface_snapshots: list[AuditShoppingSurfaceSnapshotResponse] = Field(
        default_factory=list
    )
    model_provenance: list[ModelProvenance] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _inject_aggregate_provenance(cls, data: Any) -> Any:
        """Project aggregate provenance from frozen snapshots + policy only."""
        if isinstance(data, dict):
            return data
        values = {
            name: getattr(data, name)
            for name in cls.model_fields
            if hasattr(data, name)
        }
        values["model_provenance"] = model_provenance_for(
            getattr(data, "engine_snapshots", None) or [],
            getattr(data, "configuration", None),
        )
        return values


# --- Audit lifecycle events (the discriminated list/SSE contract) -----------
#
# ``GET /audits/{id}/events`` — the JSON list AND the SSE stream — serializes
# every persisted ``AuditEvent`` through ONE discriminated envelope: common
# ``id`` / ``audit_id`` / ``event_type`` / ``occurred_at`` plus a ``payload``
# that is a tagged union keyed on ``event_type``. On the wire, SSE ``event:``
# IS the JSON ``event_type`` and SSE ``id:`` IS the event UUID — the
# ``Last-Event-ID`` resume cursor. Every payload schema is closed
# (``extra="forbid"``) and carries no secret-bearing content (invariant 6):
# opaque ids, statuses, counts, and retry timing only.
#
# ADDING A NEW EVENT TYPE is a contract change, in three places:
#   1. the ``EVENT_*`` token in ``app/core/config/audits.py``;
#   2. a strict payload schema + envelope variant in the union below (the
#      serializer index derives from the union, so the union is the only
#      list to extend here);
#   3. contract tests in ``tests/component/test_audit_events_sse.py``.
# Serializing an event whose type has no variant RAISES — the list endpoint
# and the stream never emit an untyped payload.


class _StrictEventPayload(BaseModel):
    """Base for every audit-event payload: closed and secret-free."""

    model_config = ConfigDict(extra="forbid")


class AuditCreatedPayload(_StrictEventPayload):
    """``audit.created`` — the planner's frozen run shape."""

    requested_count: int
    engines: list[str]


class AuditQueuedPayload(_StrictEventPayload):
    """``audit.queued`` — the planned task count."""

    task_count: int


class AuditStatusPayload(_StrictEventPayload):
    """``audit.status`` / ``audit.cancelled`` — a guarded state-machine move.

    The counts ride along only on the analysis stage's terminal transition;
    every other transition is status-only.
    """

    status: str
    completed: int | None = None
    failed: int | None = None


class TaskSucceededPayload(_StrictEventPayload):
    """``task.succeeded`` — opaque task reference only."""

    task_id: uuid.UUID


class TaskFailedPayload(_StrictEventPayload):
    """``task.failed`` — task reference + the safe error token (never a body)."""

    task_id: uuid.UUID
    error_code: str


class TaskRetryPayload(_StrictEventPayload):
    """``task.retry`` — task reference + the safe error token."""

    task_id: uuid.UUID
    error_code: str


class TaskCapacityWaitPayload(_StrictEventPayload):
    """``task.capacity_wait`` — a provider-capacity park decision (T4).

    Opaque ids + retry timing only — never credentials, prompts, or provider
    bodies (invariant 6). ``available_at`` is the persisted ISO timestamp
    ("" when the decision carried no guidance).
    """

    task_id: uuid.UUID
    code: str
    pool_kind: str
    available_at: str = ""
    retry_after_seconds: float = 0.0


class AuditCompletedPayload(_StrictEventPayload):
    """``audit.completed`` — terminal completion with the measured counts."""

    status: str
    completed: int
    failed: int
    visibility_score: float


class _AuditEventEnvelope(BaseModel):
    """Common envelope fields shared by every audit-event variant.

    ``occurred_at`` projects the persisted ``created_at`` column; both names
    are accepted on input, only ``occurred_at`` is emitted.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    audit_id: uuid.UUID
    occurred_at: datetime = Field(
        validation_alias=AliasChoices("created_at", "occurred_at")
    )


class AuditCreatedEvent(_AuditEventEnvelope):
    event_type: Literal["audit.created"] = EVENT_AUDIT_CREATED
    payload: AuditCreatedPayload


class AuditQueuedEvent(_AuditEventEnvelope):
    event_type: Literal["audit.queued"] = EVENT_AUDIT_QUEUED
    payload: AuditQueuedPayload


class AuditRunningEvent(_AuditEventEnvelope):
    event_type: Literal["audit.running"] = EVENT_AUDIT_RUNNING
    payload: None = None


class AuditStatusEvent(_AuditEventEnvelope):
    event_type: Literal["audit.status"] = EVENT_AUDIT_STATUS
    payload: AuditStatusPayload


class AuditCancelledEvent(_AuditEventEnvelope):
    event_type: Literal["audit.cancelled"] = EVENT_AUDIT_CANCELLED
    payload: AuditStatusPayload


class AuditCompletedEvent(_AuditEventEnvelope):
    event_type: Literal["audit.completed"] = EVENT_AUDIT_COMPLETED
    payload: AuditCompletedPayload


class TaskSucceededEvent(_AuditEventEnvelope):
    event_type: Literal["task.succeeded"] = EVENT_TASK_SUCCEEDED
    payload: TaskSucceededPayload


class TaskFailedEvent(_AuditEventEnvelope):
    event_type: Literal["task.failed"] = EVENT_TASK_FAILED
    payload: TaskFailedPayload


class TaskRetryEvent(_AuditEventEnvelope):
    event_type: Literal["task.retry"] = EVENT_TASK_RETRY
    payload: TaskRetryPayload


class TaskCapacityWaitEvent(_AuditEventEnvelope):
    event_type: Literal["task.capacity_wait"] = EVENT_TASK_CAPACITY_WAIT
    payload: TaskCapacityWaitPayload


_AuditEventVariant = (
    AuditCreatedEvent
    | AuditQueuedEvent
    | AuditRunningEvent
    | AuditStatusEvent
    | AuditCancelledEvent
    | AuditCompletedEvent
    | TaskSucceededEvent
    | TaskFailedEvent
    | TaskRetryEvent
    | TaskCapacityWaitEvent
)
"""The bare variant union, named so the lookup below can be typed as it.

Kept separate from the annotated alias only because ``EVENT_SCHEMA_BY_TYPE``
needs the union WITHOUT the discriminator metadata: typing that mapping as the
shared base returned an envelope too wide for the response contract.
"""

AuditEventResponse = Annotated[
    _AuditEventVariant,
    Field(discriminator="event_type"),
]
"""The discriminated audit-event contract (tagged on ``event_type``).

One envelope per persisted event type; the JSON list and the SSE stream share
these DTOs (invariant 2). Extend the union — and only the union — when adding
an event type; ``EVENT_SCHEMA_BY_TYPE`` derives from it.
"""

EVENT_SCHEMA_BY_TYPE: Final[dict[str, type[_AuditEventVariant]]] = {
    variant.model_fields["event_type"].default: variant
    for variant in get_args(get_args(AuditEventResponse)[0])
}
"""``event_type`` -> envelope variant, derived from the union above."""


def audit_event_response(event: AuditEvent) -> AuditEventResponse:
    """Serialize one persisted event through its discriminated variant.

    Shared by the JSON list and the SSE stream so both surfaces emit the same
    strict shape. Raises on an unmapped ``event_type`` — a new event type that
    missed its discriminator schema (see the section header) — rather than
    emitting an untyped payload.
    """
    schema = EVENT_SCHEMA_BY_TYPE.get(event.event_type)
    if schema is None:
        raise ValueError(
            f"no audit-event schema for event_type {event.event_type!r}; "
            "add its discriminator variant to AuditEventResponse"
        )
    return schema.model_validate(event)
