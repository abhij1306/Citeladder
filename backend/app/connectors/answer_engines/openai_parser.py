"""Parser for the OpenAI Responses API web-search response.

Direct OpenAI (transport ``openai``) serves the ``chatgpt`` logical engine via
the Responses API with the built-in ``web_search`` tool. Emits the provenance
triple (``logical_engine`` / ``transport_provider`` / ``transport_model``)
instead of a single ``provider`` string (invariant 10).

Observed response shape (grounded):
    {
      "id": "resp_1",
      "object": "response",
      "status": "completed",
      "model": "gpt-5.4",
      "output": [
        {"type": "reasoning", "id": "rs_1", "summary": [...]},   # dropped
        {"type": "web_search_call", "id": "ws_1", "status": "completed",
         "action": {"type": "search", "query": "best running shoes"}},
        {"type": "message", "id": "msg_1", "role": "assistant",
         "content": [
            {"type": "output_text", "text": "...",
             "annotations": [
               {"type": "url_citation", "url": "https://publisher/x",
                "title": "Publisher", "start_index": 0, "end_index": 6}
             ]}
         ]}
      ],
      "usage": {"input_tokens": 40, "output_tokens": 60, "total_tokens": 100}
    }

Key facts used here:
  * The final answer lives in ``message`` items whose ``content`` blocks are
    ``output_text`` with inline ``url_citation`` annotations carrying the real
    publisher URL and character offsets.
  * ``web_search_call`` items carry the provider-generated query text under
    ``action.query`` (single) or ``action.queries`` (multiple). A call with no
    query text is preserved as a count-only empty-query event — never invented.
  * A valid answer may contain NO ``web_search_call`` item (model answered from
    memory). That is a real result, not an error. ``search_used`` is true when
    a search-call item OR a grounded citation proves search occurred.
  * ``reasoning`` items are never retained (no reasoning content, no secrets).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from app.connectors.answer_engines.contracts import (
    AnswerEngineResponse,
    CitationResult,
    FinishReason,
    NormalizedUsage,
    SearchEventResult,
)
from app.connectors.answer_engines.normalization import (
    cited_span,
    normalize_domain,
    normalized_usage_dict,
    sum_optional,
    usage_count,
    usage_mapping,
)

# Output item types we never carry into sanitized metadata (could echo the
# model's private chain-of-thought / secrets). Reasoning CONTENT stays dropped
# forever; only the reasoning token COUNT is read, from ``usage`` details.
_DROP_ITEM_TYPES = frozenset({"reasoning"})

# Responses API ``incomplete_details.reason`` -> canonical finish reason.
_OPENAI_INCOMPLETE_REASONS: dict[str, FinishReason] = {
    "max_output_tokens": FinishReason.LENGTH,
    "max_tokens": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}

# Responses API top-level ``status`` -> canonical finish reason, used only when
# no ``incomplete_details.reason`` was supplied.
_OPENAI_STATUSES: dict[str, FinishReason] = {
    "completed": FinishReason.STOP,
    "failed": FinishReason.ERROR,
    "cancelled": FinishReason.CANCELLED,
    "canceled": FinishReason.CANCELLED,
}


def _incomplete_reason(payload: Mapping[str, Any]) -> str:
    """The trimmed ``incomplete_details.reason`` token, or ``""`` when absent."""
    details = usage_mapping(payload.get("incomplete_details"))
    return str(details.get("reason") or "").strip()


def openai_raw_finish_reason(payload: Mapping[str, Any]) -> str:
    """The raw provider finish token: the incomplete reason, else the status.

    Preserved verbatim on the response and in sanitized metadata so no
    provider-specific spelling has to be reconstructed later.
    """
    return _incomplete_reason(payload) or str(payload.get("status") or "").strip()


def map_openai_finish_reason(payload: Mapping[str, Any]) -> FinishReason:
    """Map an OpenAI Responses payload to the canonical vocabulary.

    ``incomplete_details.reason`` WINS where supplied (it is the specific
    truncation/filter cause); otherwise the top-level ``status`` is mapped.
    Anything unrecognized — including an ``incomplete`` status with no reason —
    maps to ``FinishReason.UNKNOWN`` rather than being guessed at.
    """
    reason = _incomplete_reason(payload)
    if reason:
        return _OPENAI_INCOMPLETE_REASONS.get(reason, FinishReason.UNKNOWN)
    status = str(payload.get("status") or "").strip()
    return _OPENAI_STATUSES.get(status, FinishReason.UNKNOWN)


def normalize_openai_usage(
    payload: Mapping[str, Any], *, web_search_requests: int | None
) -> NormalizedUsage:
    """Normalize OpenAI Responses usage aliases into the typed counters.

    ``input_tokens`` INCLUDES cache reads on the Responses API, so the uncached
    line is ``input_tokens - cached_tokens`` when a cache split is reported.
    Reasoning tokens come from ``output_tokens_details.reasoning_tokens`` — the
    COUNT only; reasoning content stays dropped (``_DROP_ITEM_TYPES``). OpenAI
    reports no per-request cost, so ``provider_cost_microusd`` stays null.
    """
    usage = usage_mapping(payload.get("usage"))
    input_tokens = usage_count(usage, "input_tokens")
    cached = usage_count(
        usage_mapping(usage.get("input_tokens_details")),
        "cached_tokens",
        "cached_input_tokens",
    )
    uncached = input_tokens
    if input_tokens is not None and cached is not None:
        uncached = max(input_tokens - cached, 0)
    reported_output = usage_count(usage, "output_tokens")
    reasoning = usage_count(
        usage_mapping(usage.get("output_tokens_details")), "reasoning_tokens"
    )
    output = reported_output
    if reported_output is not None and reasoning is not None:
        # ``output_tokens`` INCLUDES reasoning tokens; the canonical fields are
        # disjoint cost lines, so the reported reasoning count is split out of
        # the plain output line instead of being counted twice.
        output = max(reported_output - reasoning, 0)
    total = usage_count(usage, "total_tokens")
    if total is None:
        total = sum_optional(input_tokens, reported_output)
    return NormalizedUsage(
        uncached_input_tokens=uncached,
        cached_input_tokens=cached,
        output_tokens=output,
        reasoning_tokens=reasoning,
        total_tokens=total,
        web_search_requests=web_search_requests,
    )


def _item_type(item: dict[str, Any]) -> str:
    return str(item.get("type") or "").strip()


def _output_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("output")
    if not isinstance(output, list):
        return []
    return [item for item in output if isinstance(item, dict)]


def _action_of(item: dict[str, Any]) -> dict[str, Any]:
    """The item's ``action`` dict, or ``{}`` when absent/non-dict."""
    action = item.get("action")
    return action if isinstance(action, dict) else {}


def _action_queries(action: dict[str, Any]) -> list[str]:
    """Ordered, non-blank query strings from a web_search_call action.

    Accepts a single ``query`` string and/or a ``queries`` list; preserves
    order and never fabricates text.
    """
    queries: list[str] = []
    single = str(action.get("query") or "").strip()
    if single:
        queries.append(single)
    raw_queries = action.get("queries")
    if isinstance(raw_queries, (list, tuple)):
        for raw in raw_queries:
            text = str(raw or "").strip()
            if text:
                queries.append(text)
    return queries


def _search_events(
    items: list[dict[str, Any]],
) -> tuple[tuple[SearchEventResult, ...], int]:
    """Ordered search events + the count of web_search_call items.

    Each provider query becomes a ``SearchEventResult``. A call that carries no
    query text is preserved as a single count-only empty-query event rather
    than being dropped or invented.
    """
    events: list[SearchEventResult] = []
    call_count = 0
    sequence = 0
    for item in items:
        if _item_type(item) != "web_search_call":
            continue
        call_id = str(item.get("id") or item.get("call_id") or "")
        queries = _action_queries(_action_of(item))
        if queries:
            for query_sequence, text in enumerate(queries):
                events.append(
                    SearchEventResult(
                        sequence=sequence,
                        query=text,
                        call_id=call_id,
                        call_sequence=call_count,
                        query_sequence=query_sequence,
                    )
                )
                sequence += 1
        else:
            # Count-only: a search happened but the query text is unavailable.
            events.append(
                SearchEventResult(
                    sequence=sequence,
                    query="",
                    call_id=call_id,
                    call_sequence=call_count,
                    query_sequence=0,
                )
            )
            sequence += 1
        call_count += 1
    return tuple(events), call_count


def _text_blocks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for item in items:
        if _item_type(item) != "message":
            continue
        for block in item.get("content") or []:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "")
            if block_type in ("output_text", "text", "") or "text" in block:
                blocks.append(block)
    return blocks


def _citation_from_annotation(
    block: dict[str, Any], annotation: object, ordinal: int
) -> CitationResult | None:
    if not isinstance(annotation, dict):
        return None
    if str(annotation.get("type") or "") != "url_citation":
        return None
    url = str(annotation.get("url") or "").strip()
    title = str(annotation.get("title") or "").strip()
    if not url and not title:
        return None
    start, end, cited_text = cited_span(str(block.get("text") or ""), annotation)
    return CitationResult(
        ordinal=ordinal,
        url=url,
        title=title,
        domain=normalize_domain(urlparse(url).hostname or title),
        start_index=start,
        end_index=end,
        cited_text=cited_text,
    )


def _citations(blocks: list[dict[str, Any]]) -> tuple[CitationResult, ...]:
    citations: list[CitationResult] = []
    for block in blocks:
        for annotation in block.get("annotations") or []:
            citation = _citation_from_annotation(block, annotation, len(citations))
            if citation is not None:
                citations.append(citation)
    return tuple(citations)


def _safe_item_metadata(item: dict[str, Any]) -> dict[str, Any] | None:
    item_type = _item_type(item)
    if item_type in _DROP_ITEM_TYPES:
        return None
    common = {"type": item_type, "id": item.get("id")}
    if item_type == "web_search_call":
        action = _action_of(item)
        return {
            **common,
            "status": item.get("status"),
            "action": {
                "type": action.get("type"),
                "query": action.get("query"),
                "queries": action.get("queries") or [],
            },
        }
    if item_type == "message":
        content = [
            {
                "type": block.get("type"),
                "text": block.get("text"),
                "annotations": block.get("annotations") or [],
            }
            for block in item.get("content") or []
            if isinstance(block, dict)
        ]
        return {**common, "content": content}
    return None


def _sanitize_metadata(
    payload: dict[str, Any],
    items: list[dict[str, Any]],
    usage: NormalizedUsage,
) -> dict[str, Any]:
    """Keep observable, non-sensitive provider fields only.

    Retains id/object/status/model/usage and a redacted evidence envelope of
    search-call actions + message text/annotations. Reasoning items are dropped
    entirely and no credentials, raw headers, or request echo are retained.
    """
    item_types = [_item_type(item) for item in items]
    evidence_items = [
        safe for item in items if (safe := _safe_item_metadata(item)) is not None
    ]
    return {
        "id": payload.get("id"),
        "object": payload.get("object"),
        "status": payload.get("status"),
        "model": payload.get("model"),
        "usage": normalized_usage_dict(usage),
        "incomplete_details": payload.get("incomplete_details"),
        # Raw provider finish token preserved verbatim next to the canonical
        # mapping on the response.
        "raw_finish_reason": openai_raw_finish_reason(payload),
        "native_search_requested": True,
        "query_text_available": any(
            _item_type(item) == "web_search_call" and _action_queries(_action_of(item))
            for item in items
        ),
        "item_types": item_types,
        "evidence_items": evidence_items,
    }


def parse_openai_response(
    payload: dict[str, Any],
    *,
    logical_engine: str,
    transport_provider: str,
    requested_model: str,
    latency_ms: int,
) -> AnswerEngineResponse:
    items = _output_items(payload)

    events, call_count = _search_events(items)
    blocks = _text_blocks(items)
    answer_text = "\n\n".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if str(block.get("text") or "").strip()
    )
    citations = _citations(blocks)

    # Search is proven by a search-call item or a grounded citation.
    search_used = call_count > 0 or bool(citations)

    usage = normalize_openai_usage(payload, web_search_requests=call_count)
    raw_finish_reason = openai_raw_finish_reason(payload)

    return AnswerEngineResponse(
        # Preserve chatgpt/openai/gpt-5.4 provenance; use the provider-returned
        # model only when present.
        logical_engine=logical_engine,
        transport_provider=transport_provider,
        transport_model=str(payload.get("model") or requested_model),
        answer_text=answer_text,
        search_used=search_used,
        search_events=events,
        citations=citations,
        provider_metadata=_sanitize_metadata(payload, items, usage),
        finish_reason=map_openai_finish_reason(payload),
        raw_finish_reason=raw_finish_reason,
        normalized_usage=usage,
        latency_ms=latency_ms,
    )
