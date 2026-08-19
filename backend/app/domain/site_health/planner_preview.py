"""Bounded, persistence-free crawl input preview parsing."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from io import StringIO


def _json_rows(
    raw: str, *, max_bytes: int, error: Callable[[str], Exception]
) -> list[str]:
    try:
        return preview_rows(json.loads(raw), "json", max_bytes=max_bytes, error=error)
    except (TypeError, ValueError) as exc:
        raise error("invalid JSON preview input") from exc


def _structured_rows(
    content: object,
    *,
    max_bytes: int,
    error: Callable[[str], Exception],
) -> list[str] | None:
    if isinstance(content, list):
        _ensure_structured_size(content, max_bytes=max_bytes, error=error)
        return [str(value) for value in content]
    if not isinstance(content, dict):
        return None
    _ensure_structured_size(content, max_bytes=max_bytes, error=error)
    values = content.get("urls", content.get("items", []))
    if not isinstance(values, list):
        raise error("JSON preview input must contain a URL list")
    return [
        str(value.get("url", "")) if isinstance(value, dict) else str(value)
        for value in values
    ]


def _ensure_structured_size(
    content: list | dict,
    *,
    max_bytes: int,
    error: Callable[[str], Exception],
) -> None:
    """Reject an oversized structured value without creating one JSON string."""
    encoded_bytes = 0
    exceeded = False
    try:
        for chunk in json.JSONEncoder(
            ensure_ascii=False, separators=(",", ":")
        ).iterencode(content):
            encoded_bytes += len(chunk.encode("utf-8"))
            if encoded_bytes > max_bytes:
                exceeded = True
                break
    except (TypeError, ValueError) as exc:
        raise error("invalid JSON preview input") from exc
    if exceeded:
        raise error("preview input is too large")


def preview_rows(
    content: object,
    input_format: str,
    *,
    max_bytes: int,
    error: Callable[[str], Exception],
) -> list[str]:
    structured = _structured_rows(content, max_bytes=max_bytes, error=error)
    if structured is not None:
        return structured
    raw = str(content or "")
    if len(raw.encode("utf-8")) > max_bytes:
        raise error("preview input is too large")
    if input_format == "csv":
        return [row[0] if row else "" for row in csv.reader(StringIO(raw))]
    if input_format == "json":
        return _json_rows(raw, max_bytes=max_bytes, error=error)
    return raw.splitlines()
