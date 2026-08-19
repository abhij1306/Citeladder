"""Provider-neutral contracts for answer-engine adapters.

Every field is transport-agnostic so the Gemini (``google``), Anthropic
(``anthropic``) adapters produce the same shape. The response
records the resolved provenance triple — ``logical_engine`` (what was asked
for), ``transport_provider`` (how it was reached), and ``transport_model`` (the
concrete model) — so downstream persistence carries identity per invariant 10.

Ported from the reference ``ai_visibility/contracts.py`` and extended with the
logical/transport provenance fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class FinishReason(StrEnum):
    """Canonical, provider-neutral reason a generation stopped.

    Closed vocabulary: gates and persistence read ONLY these values. The raw
    provider token is preserved separately (``raw_finish_reason``) so no
    provider-specific spelling leaks into a decision. Modelled as a ``StrEnum``
    to match the other closed vocabularies in the codebase
    (e.g. ``config/entitlements.CapabilityType``).
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_ERROR = "tool_error"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class NormalizedUsage:
    """Provider-neutral usage counters for one call.

    EVERY field is nullable and defaults to ``None``. UNKNOWN NEVER BECOMES
    ZERO: a missing counter stays null so downstream cost projection reports it
    as unknown/partial instead of a fabricated zero that is indistinguishable
    from a real zero. Never add a ``0`` default here.
    """

    uncached_input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    web_search_requests: int | None = None
    provider_cost_microusd: int | None = None


@dataclass(frozen=True, slots=True)
class AnswerEngineRequest:
    prompt: str
    system_instruction: str
    model: str
    timeout_seconds: float
    # Frozen measurement-mode policy the adapter must obey verbatim: whether to
    # attach retrieval/search tools, the output-token cap, and the reasoning pin
    # (``off`` | an explicit effort — see ``config/provider_catalog.RoutePolicy``).
    # All fields are mandatory; no adapter invents a route-policy fallback.
    retrieval_enabled: bool
    max_output_tokens: int
    reasoning_effort: str


@dataclass(frozen=True, slots=True)
class SearchEventResult:
    sequence: int
    query: str
    call_id: str = ""
    call_sequence: int = 0
    query_sequence: int = 0


@dataclass(frozen=True, slots=True)
class CitationResult:
    ordinal: int
    url: str
    title: str
    domain: str
    start_index: int | None
    end_index: int | None
    cited_text: str


@dataclass(frozen=True, slots=True)
class AnswerEngineResponse:
    # Provenance triple (invariant 10): logical engine requested, transport used
    # to reach it, and the concrete transport model that answered.
    logical_engine: str
    transport_provider: str
    transport_model: str
    answer_text: str
    search_used: bool
    search_events: tuple[SearchEventResult, ...]
    citations: tuple[CitationResult, ...]
    provider_metadata: dict = field(default_factory=dict)
    finish_reason: FinishReason = FinishReason.UNKNOWN
    raw_finish_reason: str = ""
    # Typed, all-nullable usage counters and the ONLY usage contract on this
    # response (unknown never becomes zero). Persistence serializes this typed
    # object through ``normalized_usage_dict``; there is one source of truth.
    normalized_usage: NormalizedUsage = field(default_factory=NormalizedUsage)
    latency_ms: int = 0
