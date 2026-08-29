"""Shared adapter/parser helpers: request policy, usage counts, citation hosts.

Package-local, minimal helper the answer-engine parsers use to derive a clean
citation host from a URL or a domain-shaped title. The full text/alias
normalization suite lives with the analysis subsystem (B6); this file owns only
the domain form the adapters need so parsing has no cross-subsystem dependency.

It also owns the NULLABLE usage-count coercion the parsers use to fill
``NormalizedUsage`` (unknown never becomes zero, so an absent or malformed
provider counter stays ``None`` instead of collapsing into a fabricated zero)
and the single resolver for the frozen output-token cap, so all three adapters
read the cap the same way instead of each re-deriving it (invariant 2).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from app.analysis.normalization import normalize_domain
from app.connectors.answer_engines.contracts import (
    AnswerEngineRequest,
    NormalizedUsage,
)
from app.connectors.answer_engines.errors import ProviderError
from app.core.config.provider_catalog import ERROR_UNKNOWN


def output_token_cap(request: AnswerEngineRequest) -> int:
    """The frozen per-call output cap for a provider payload.

    An adapter never re-reads live policy for a value the request already froze
    (invariant 9), and invalid callers fail instead of falling back.
    """
    if request.max_output_tokens <= 0:
        raise ProviderError(
            "max_output_tokens must be frozen before execution",
            error_code=ERROR_UNKNOWN,
            retryable=False,
        )
    return request.max_output_tokens


def annotation_offset(annotation: dict[str, Any], *keys: str) -> int | None:
    """First integer-coercible offset among ``keys`` on a citation annotation.

    Accepts both snake_case and camelCase offset keys (REST vs SDK casing).
    Returns ``None`` when no key is present or the value is not int-coercible.
    """
    for key in keys:
        if key in annotation and annotation[key] is not None:
            try:
                return int(annotation[key])
            except (TypeError, ValueError):
                continue
    return None


def cited_span(
    text: str, annotation: dict[str, Any]
) -> tuple[int | None, int | None, str]:
    """``(start, end, cited_text)`` for one citation annotation against its text.

    Owns the single span-validity rule every offset-based parser shares: the
    cited text is sliced from the answer only when both offsets are present
    AND address a valid span; anything else drops to ``(None, None, "")`` —
    a possibly-stale provider offset is never trusted over the answer text.
    """
    start = annotation_offset(annotation, "start_index", "startIndex")
    end = annotation_offset(annotation, "end_index", "endIndex")
    if start is not None and end is not None and 0 <= start < end <= len(text):
        return start, end, text[start:end]
    return None, None, ""


def coerce_int(value: object, default: int = 0) -> int:
    """Best-effort integer coercion that never raises.

    Returns ``default`` when ``value`` is missing or not int-coercible, so
    malformed provider usage payloads degrade gracefully instead of crashing
    the worker path.
    """
    # ``bool`` is an ``int`` subclass; reject it explicitly so a stray boolean
    # (e.g. ``True`` in a usage field) falls back to the default rather than
    # silently coercing to 1/0.
    if (
        value is None
        or isinstance(value, bool)
        or not isinstance(value, (int, float, str))
    ):
        return default
    try:
        # int(float("inf"))/int("nan") raise OverflowError/ValueError; treat any
        # non-int-coercible or non-finite value as the default.
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def optional_count(value: object) -> int | None:
    """Nullable, non-negative token/request count from a provider payload.

    Returns ``None`` for absent, boolean, negative, non-finite, fractional, or
    otherwise non-int-coercible values. A literal zero stays zero (a reported
    zero is real evidence); UNKNOWN NEVER BECOMES ZERO, so callers must keep
    the ``None`` rather than coalescing it.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        if not math.isfinite(value) or value < 0 or not value.is_integer():
            return None
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value.strip(), 10)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def usage_count(usage: Mapping[str, Any], *keys: str) -> int | None:
    """First present usage alias wins, normalized to a nullable count.

    Providers spell the same counter differently across REST/SDK casings and
    API generations (e.g. ``promptTokenCount`` vs ``prompt_token_count``); the
    parser passes the alias chain in precedence order. A present-but-malformed
    key suppresses the remaining fallbacks so a bad value never silently reads
    a different field.
    """
    for key in keys:
        if key in usage:
            return optional_count(usage.get(key))
    return None


def usage_mapping(value: object) -> Mapping[str, Any]:
    """A usage-like payload as a mapping; ``{}`` when absent or malformed."""
    return value if isinstance(value, Mapping) else {}


def sum_optional(*values: int | None) -> int | None:
    """Sum of the KNOWN components, or ``None`` when none are known.

    Used for a derived total: with no known component the total is unknown, not
    zero.
    """
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def normalized_usage_dict(usage: NormalizedUsage) -> dict[str, int | None]:
    """The typed usage as the canonical JSON shape for persistence/metadata.

    Emits the SAME granular field names the cost projection prefers
    (``uncached_input_tokens`` … ``search_requests``) and preserves nulls: an
    unknown counter is serialized as ``None``, never dropped-to-zero. Cost is
    micro-USD (``provider_cost_microusd``) — never a fabricated dollar zero.

    The two ``total_*_tokens`` aliases are the LEGACY parser spellings kept for
    readers not yet migrated to the typed usage (``app/analysis/scoring.py``
    aggregates run token totals from them). They carry the same values as the
    granular keys, which take precedence in the projection, and go away with
    the last legacy reader.
    """
    return {
        "uncached_input_tokens": usage.uncached_input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_tokens": usage.reasoning_tokens,
        "total_tokens": usage.total_tokens,
        "search_requests": usage.web_search_requests,
        "provider_cost_microusd": usage.provider_cost_microusd,
        "total_input_tokens": usage.uncached_input_tokens,
        "total_output_tokens": usage.output_tokens,
    }


# Re-exported, not reimplemented: this was a byte-identical copy of the
# analysis implementation, so the two could drift and silently classify the
# same citation host differently on either side of the pipeline. The analysis
# module is the authoritative home (it owns the wider text/alias normalization
# suite); the adapters keep importing it from here so their call sites are
# unchanged and this file stays their single normalization entry point.
__all__ = [
    "annotation_offset",
    "cited_span",
    "coerce_int",
    "normalize_domain",
    "normalized_usage_dict",
    "optional_count",
    "output_token_cap",
    "sum_optional",
    "usage_count",
    "usage_mapping",
]
