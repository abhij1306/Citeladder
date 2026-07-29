"""Domain normalization for citation classification.

Package-local, minimal helper the answer-engine parsers use to derive a clean
citation host from a URL or a domain-shaped title. The full text/alias
normalization suite lives with the analysis subsystem (B6); this file owns only
the domain form the adapters need so parsing has no cross-subsystem dependency.
"""

from __future__ import annotations

from typing import Any

from app.analysis.normalization import normalize_domain


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


# Re-exported, not reimplemented: this was a byte-identical copy of the
# analysis implementation, so the two could drift and silently classify the
# same citation host differently on either side of the pipeline. The analysis
# module is the authoritative home (it owns the wider text/alias normalization
# suite); the adapters keep importing it from here so their call sites are
# unchanged and this file stays their single normalization entry point.
__all__ = ["annotation_offset", "coerce_int", "normalize_domain"]
