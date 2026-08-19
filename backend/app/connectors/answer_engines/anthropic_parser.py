"""Parser for Anthropic Messages API web-search responses.

Ported from the reference ``ai_visibility/anthropic_parser.py``; emits the
provenance triple instead of a single ``provider`` string (invariant 10).

Anthropic returns a block list rather than a single message string:

  - ``text`` blocks carry the answer, each with an optional ``citations`` list
    of ``web_search_result_location`` entries (url/title/cited_text).
  - ``server_tool_use`` blocks (``name == "web_search"``) carry the actual
    search query text when the provider returns it.
  - ``usage.server_tool_use.web_search_requests`` counts the searches performed.
  - ``stop_reason`` carries the raw provider finish token, mapped to the
    canonical ``FinishReason`` vocabulary by ``map_anthropic_finish_reason``.
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
    normalize_domain,
    normalized_usage_dict,
    sum_optional,
    usage_count,
    usage_mapping,
)

# Raw Anthropic ``stop_reason`` -> canonical finish reason. Closed map: an
# unlisted value maps to UNKNOWN rather than being guessed at.
#   * ``pause_turn`` (long-running server tool turn) and ``tool_use`` are not
#     terminal generation outcomes, so neither is reported as ``stop``.
_ANTHROPIC_FINISH_REASONS: dict[str, FinishReason] = {
    "end_turn": FinishReason.STOP,
    "stop_sequence": FinishReason.STOP,
    "max_tokens": FinishReason.LENGTH,
    "refusal": FinishReason.CONTENT_FILTER,
    "pause_turn": FinishReason.UNKNOWN,
    "tool_use": FinishReason.UNKNOWN,
}


def map_anthropic_finish_reason(raw: object) -> FinishReason:
    """Map an Anthropic ``stop_reason`` to the canonical vocabulary.

    Pure function; anything absent or unrecognized maps to
    ``FinishReason.UNKNOWN`` (never guessed). The raw token is preserved
    separately on the response.
    """
    return _ANTHROPIC_FINISH_REASONS.get(str(raw or "").strip(), FinishReason.UNKNOWN)


def normalize_anthropic_usage(
    payload: Mapping[str, Any], *, search_events: int
) -> NormalizedUsage:
    """Normalize Anthropic usage aliases into the canonical typed counters.

    ``input_tokens`` on the Messages API EXCLUDES both cache reads AND cache
    writes, so neither can be dropped: cache reads come from
    ``cache_read_input_tokens``, and the cache-WRITE count
    (``cache_creation_input_tokens``) is folded into ``uncached_input_tokens``
    because a cache write is billed as ordinary (in fact premium) uncached
    input — leaving it out understated both the normalized input and the
    derived total. Anthropic reports no thinking-token count and no
    per-request cost, so those stay null (unknown never becomes zero). The
    web-search count prefers the reported value and falls back to observed
    ``server_tool_use`` blocks only when the provider reported none at all.
    """
    usage = usage_mapping(payload.get("usage"))
    server_tool_use = usage_mapping(usage.get("server_tool_use"))
    uncached = sum_optional(
        usage_count(usage, "input_tokens"),
        usage_count(usage, "cache_creation_input_tokens", "cacheCreationInputTokens"),
    )
    cached = usage_count(usage, "cache_read_input_tokens", "cacheReadInputTokens")
    output = usage_count(usage, "output_tokens")
    searches = usage_count(server_tool_use, "web_search_requests")
    if searches is None and search_events:
        searches = search_events
    total = usage_count(usage, "total_tokens")
    if total is None:
        total = sum_optional(uncached, cached, output)
    return NormalizedUsage(
        uncached_input_tokens=uncached,
        cached_input_tokens=cached,
        output_tokens=output,
        # Anthropic reports no separate thinking-token counter (thinking tokens
        # are billed inside ``output_tokens``) and no per-request cost, so both
        # stay null rather than becoming a fabricated zero.
        total_tokens=total,
        web_search_requests=searches,
    )


def _blocks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _anthropic_citation(
    annotation: dict[str, Any], ordinal: int
) -> CitationResult | None:
    if str(annotation.get("type") or "") != "web_search_result_location":
        return None
    url = str(annotation.get("url") or "").strip()
    if not url:
        return None
    title = str(annotation.get("title") or "").strip()
    return CitationResult(
        ordinal=ordinal,
        url=url,
        title=title,
        domain=normalize_domain(urlparse(url).hostname or title),
        start_index=None,
        end_index=None,
        cited_text=str(annotation.get("cited_text") or ""),
    )


def _text_block_citations(
    block: dict[str, Any], ordinal: int
) -> tuple[str | None, list[CitationResult]]:
    if str(block.get("type") or "") != "text":
        return None, []
    text = str(block.get("text") or "").strip()
    citations: list[CitationResult] = []
    for annotation in block.get("citations") or []:
        if not isinstance(annotation, dict):
            continue
        citation = _anthropic_citation(annotation, ordinal + len(citations))
        if citation is not None:
            citations.append(citation)
    return text or None, citations


def _answer_and_citations(
    blocks: list[dict[str, Any]],
) -> tuple[str, tuple[CitationResult, ...]]:
    texts: list[str] = []
    citations: list[CitationResult] = []
    for block in blocks:
        text, block_citations = _text_block_citations(block, len(citations))
        if text:
            texts.append(text)
        citations.extend(block_citations)
    return "\n\n".join(texts), tuple(citations)


def _search_events(
    blocks: list[dict[str, Any]],
) -> tuple[SearchEventResult, ...]:
    events: list[SearchEventResult] = []
    for block in blocks:
        if str(block.get("type") or "") != "server_tool_use":
            continue
        if str(block.get("name") or "") != "web_search":
            continue
        query = str((block.get("input") or {}).get("query") or "")
        events.append(SearchEventResult(sequence=len(events), query=query))
    return tuple(events)


def parse_anthropic_message(
    payload: dict[str, Any],
    *,
    logical_engine: str,
    transport_provider: str,
    requested_model: str,
    latency_ms: int,
) -> AnswerEngineResponse:
    blocks = _blocks(payload)
    answer_text, citations = _answer_and_citations(blocks)
    search_events = _search_events(blocks)

    usage = normalize_anthropic_usage(payload, search_events=len(search_events))
    raw_finish_reason = str(payload.get("stop_reason") or "")
    return AnswerEngineResponse(
        logical_engine=logical_engine,
        transport_provider=transport_provider,
        transport_model=str(payload.get("model") or requested_model),
        answer_text=answer_text,
        # A known-zero search count means no search; an unknown count falls
        # back to the observed server_tool_use blocks (already folded into the
        # normalized count above).
        search_used=bool(usage.web_search_requests),
        search_events=search_events,
        citations=citations,
        provider_metadata={
            "id": payload.get("id"),
            "type": payload.get("type"),
            "model": payload.get("model") or requested_model,
            "usage": normalized_usage_dict(usage),
            "native_search_requested": True,
            # Anthropic exposes the real query text on server_tool_use blocks.
            "query_text_available": True,
            "stop_reason": payload.get("stop_reason"),
            "raw_finish_reason": raw_finish_reason,
        },
        finish_reason=map_anthropic_finish_reason(raw_finish_reason),
        raw_finish_reason=raw_finish_reason,
        normalized_usage=usage,
        latency_ms=latency_ms,
    )
