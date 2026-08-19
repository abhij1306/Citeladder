"""Tolerant parser for the Gemini Interactions API grounded-search response.

Ported from the reference ``ai_visibility/gemini_parser.py``. Adapted to emit
the provenance triple (``logical_engine`` / ``transport_provider`` /
``transport_model``) instead of a single ``provider`` string (invariant 10).

Observed response shape (grounded):
    {
      "status": "completed",
      "model": "...",
      "usage": {...},
      "steps": [
        {"type": "thought", "signature": "..."},            # dropped
        {"type": "model_output", "content": [
            {"type": "text", "text": "...",
             "annotations": [
               {"type": "url_citation", "url": "<redirect>",
                "title": "<publisher-domain>",
                "start_index": 514, "end_index": 623}
             ]}
        ]},
        {"type": "google_search_call",
         "arguments": {"queries": ["...", "..."]}},
        {"type": "google_search_result", ...}
      ]
    }

Key facts used here:
  * The citation ``url`` is a Google grounding-redirect URL, NOT the publisher
    URL. The publisher domain is carried in ``title``; we derive the citation
    domain from ``title``.
  * A valid answer may contain no ``google_search_call`` step (model answered
    from memory). That is a real benchmark result, not an error.
  * REST vs SDK casing differs; we accept both snake_case and camelCase offsets.
  * Usage arrives under the provider-native camelCase aliases
    (``promptTokenCount`` / ``candidatesTokenCount`` / ``thoughtsTokenCount`` /
    ``cachedContentTokenCount`` / ``totalTokenCount``). They are NORMALIZED here
    into the canonical counters — no raw provider usage dict is passed through.
  * ``thought`` steps stay dropped (no thought CONTENT is retained); only the
    thought TOKEN COUNT is read, from usage.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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

_DROP_STEP_TYPES = frozenset({"thought"})

# Raw Gemini candidate/interaction finish reason -> canonical vocabulary.
# Closed map; anything unlisted maps to UNKNOWN rather than being guessed at.
_GEMINI_FINISH_REASONS: dict[str, FinishReason] = {
    "STOP": FinishReason.STOP,
    "MAX_TOKENS": FinishReason.LENGTH,
    "SAFETY": FinishReason.CONTENT_FILTER,
    "RECITATION": FinishReason.CONTENT_FILTER,
    "BLOCKLIST": FinishReason.CONTENT_FILTER,
    "PROHIBITED_CONTENT": FinishReason.CONTENT_FILTER,
    "SPII": FinishReason.CONTENT_FILTER,
    "IMAGE_SAFETY": FinishReason.CONTENT_FILTER,
    # Error-ish terminations: the generation aborted, it did not complete.
    "OTHER": FinishReason.ERROR,
    "ERROR": FinishReason.ERROR,
    "FAILED": FinishReason.ERROR,
    "MALFORMED_FUNCTION_CALL": FinishReason.ERROR,
    "UNEXPECTED_TOOL_CALL": FinishReason.ERROR,
    "CANCELLED": FinishReason.CANCELLED,
}


def map_gemini_finish_reason(raw: object) -> FinishReason:
    """Map a Gemini finish reason to the canonical vocabulary.

    Pure function; case-insensitive on the provider token (REST returns the
    SCREAMING_SNAKE form). Absent, ``FINISH_REASON_UNSPECIFIED``, or otherwise
    unrecognized values map to ``FinishReason.UNKNOWN`` — never guessed.
    """
    return _GEMINI_FINISH_REASONS.get(
        str(raw or "").strip().upper(), FinishReason.UNKNOWN
    )


def gemini_raw_finish_reason(payload: Mapping[str, Any]) -> str:
    """The raw provider finish token from an Interactions payload.

    Prefers the top-level interaction ``finish_reason``/``finishReason``, then
    the first candidate's (the Generate Content shape), then the interaction
    ``status``. Returned verbatim so no provider spelling is lost.
    """
    for key in ("finish_reason", "finishReason"):
        raw = str(payload.get(key) or "").strip()
        if raw:
            return raw
    candidates = payload.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            for key in ("finish_reason", "finishReason"):
                raw = str(candidate.get(key) or "").strip()
                if raw:
                    return raw
    return str(payload.get("status") or "").strip()


def normalize_gemini_usage(
    payload: Mapping[str, Any], *, web_search_requests: int | None
) -> NormalizedUsage:
    """Normalize Gemini's native usage aliases into the typed counters.

    ``promptTokenCount`` INCLUDES cached content tokens, so the uncached input
    line subtracts ``cachedContentTokenCount`` when a cache split is reported.
    ``thoughtsTokenCount`` is the thinking-token COUNT (thought content stays
    dropped) and is NOT part of ``candidatesTokenCount``, so the output line is
    left as reported. Google reports no per-request cost, so
    ``provider_cost_microusd`` stays null (unknown never becomes zero).
    """
    usage = usage_mapping(payload.get("usage") or payload.get("usageMetadata"))
    prompt = usage_count(usage, "promptTokenCount", "prompt_token_count")
    cached = usage_count(usage, "cachedContentTokenCount", "cached_content_token_count")
    uncached = prompt
    if prompt is not None and cached is not None:
        uncached = max(prompt - cached, 0)
    output = usage_count(usage, "candidatesTokenCount", "candidates_token_count")
    reasoning = usage_count(usage, "thoughtsTokenCount", "thoughts_token_count")
    total = usage_count(usage, "totalTokenCount", "total_token_count", "total_tokens")
    if total is None:
        total = sum_optional(prompt, output, reasoning)
    return NormalizedUsage(
        uncached_input_tokens=uncached,
        cached_input_tokens=cached,
        output_tokens=output,
        reasoning_tokens=reasoning,
        total_tokens=total,
        web_search_requests=web_search_requests,
    )


def _step_type(step: dict[str, Any]) -> str:
    return str(step.get("type") or step.get("step_type") or "").strip()


def _extract_queries(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    call_sequence = 0
    for step in steps:
        if _step_type(step) != "google_search_call":
            continue
        args = step.get("arguments") or step.get("args") or {}
        if not isinstance(args, dict):
            args = {}
        call_id = str(step.get("id") or step.get("call_id") or "")
        raw_queries = args.get("queries")
        if not isinstance(raw_queries, (list, tuple)):
            raw_queries = []
        for query_sequence, raw in enumerate(raw_queries):
            text = str(raw or "").strip()
            if text:
                queries.append(
                    {
                        "query": text,
                        "call_id": call_id,
                        "call_sequence": call_sequence,
                        "query_sequence": query_sequence,
                    }
                )
        call_sequence += 1
    return queries


def _text_blocks(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for step in steps:
        if _step_type(step) != "model_output":
            continue
        for block in step.get("content") or []:
            if isinstance(block, dict) and (
                block.get("type") in (None, "text") or "text" in block
            ):
                blocks.append(block)
    return blocks


def _extract_citations(blocks: list[dict[str, Any]]) -> list[CitationResult]:
    citations: list[CitationResult] = []
    ordinal = 0
    for block in blocks:
        text = str(block.get("text") or "")
        for annotation in block.get("annotations") or []:
            if not isinstance(annotation, dict):
                continue
            if str(annotation.get("type") or "") != "url_citation":
                continue
            url = str(annotation.get("url") or "").strip()
            title = str(annotation.get("title") or "").strip()
            if not url and not title:
                continue
            # Derive cited text from the answer where offsets are valid, rather
            # than trusting a possibly-stale provider-duplicated field.
            start, end, cited_text = cited_span(text, annotation)
            citations.append(
                CitationResult(
                    ordinal=ordinal,
                    url=url,
                    title=title,
                    domain=normalize_domain(title),
                    start_index=start,
                    end_index=end,
                    cited_text=cited_text,
                )
            )
            ordinal += 1
    return citations


def _safe_step_common(step: dict[str, Any], step_type: str) -> dict[str, Any]:
    return {
        "type": step_type,
        "id": step.get("id"),
        "call_id": step.get("call_id") or step.get("callId"),
    }


def _safe_search_call_metadata(
    step: dict[str, Any], common: dict[str, Any]
) -> dict[str, Any]:
    arguments = step.get("arguments") or step.get("args") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    queries = arguments.get("queries")
    return {
        **common,
        "arguments": {"queries": queries if isinstance(queries, list) else []},
    }


def _safe_model_output_metadata(
    step: dict[str, Any], common: dict[str, Any]
) -> dict[str, Any]:
    content = [
        {
            "type": block.get("type"),
            "text": block.get("text"),
            "annotations": block.get("annotations") or [],
        }
        for block in step.get("content") or []
        if isinstance(block, dict)
    ]
    return {**common, "content": content}


def _safe_step_metadata(step: dict[str, Any]) -> dict[str, Any] | None:
    step_type = _step_type(step)
    common = _safe_step_common(step, step_type)
    if step_type == "google_search_call":
        return _safe_search_call_metadata(step, common)
    if step_type == "google_search_result":
        return common
    if step_type == "model_output":
        return _safe_model_output_metadata(step, common)
    return None


def sanitize_metadata(
    payload: dict[str, Any], usage: NormalizedUsage | None = None
) -> dict[str, Any]:
    """Keep observable, non-sensitive provider fields only.

    Retains status/model/object, the NORMALIZED usage (never the raw provider
    usage dict), the raw finish token, and a redacted evidence envelope
    containing search-call grouping, model output, and citation annotations.
    Strips thought steps/signatures and never carries credentials.
    """
    steps = [
        step
        for step in (payload.get("steps") or [])
        if isinstance(step, dict) and _step_type(step) not in _DROP_STEP_TYPES
    ]
    step_types = [_step_type(step) for step in steps]
    evidence_steps = [
        safe for step in steps if (safe := _safe_step_metadata(step)) is not None
    ]
    normalized = (
        usage
        if usage is not None
        else normalize_gemini_usage(payload, web_search_requests=None)
    )
    return {
        "interaction_id": payload.get("id"),
        "status": payload.get("status"),
        "model": payload.get("model"),
        "object": payload.get("object"),
        "usage": normalized_usage_dict(normalized),
        # Raw provider finish token preserved verbatim next to the canonical
        # mapping on the response.
        "raw_finish_reason": gemini_raw_finish_reason(payload),
        "step_types": step_types,
        "evidence_steps": evidence_steps,
    }


def _interaction_content(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[CitationResult], int]:
    steps = [
        step
        for step in (payload.get("steps") or [])
        if isinstance(step, dict) and _step_type(step) not in _DROP_STEP_TYPES
    ]
    queries = _extract_queries(steps)
    blocks = _text_blocks(steps)
    answer_text = "\n\n".join(
        str(block.get("text") or "").strip()
        for block in blocks
        if str(block.get("text") or "").strip()
    )
    return (
        steps,
        queries,
        answer_text,
        _extract_citations(blocks),
        sum(1 for step in steps if _step_type(step) == "google_search_call"),
    )


def parse_interaction(
    payload: dict[str, Any],
    *,
    logical_engine: str,
    transport_provider: str,
    model: str,
    latency_ms: int,
) -> AnswerEngineResponse:
    steps, queries, answer_text, citations, search_calls = _interaction_content(payload)
    search_used = search_calls > 0
    usage = normalize_gemini_usage(payload, web_search_requests=search_calls)
    raw_finish_reason = gemini_raw_finish_reason(payload)

    return AnswerEngineResponse(
        logical_engine=logical_engine,
        transport_provider=transport_provider,
        transport_model=str(payload.get("model") or model),
        answer_text=answer_text,
        search_used=search_used,
        search_events=tuple(
            SearchEventResult(sequence=index, **query)
            for index, query in enumerate(queries)
        ),
        citations=tuple(citations),
        provider_metadata=sanitize_metadata(payload, usage),
        finish_reason=map_gemini_finish_reason(raw_finish_reason),
        raw_finish_reason=raw_finish_reason,
        normalized_usage=usage,
        latency_ms=latency_ms,
    )
