"""Shared deterministic parsing for currency-qualified Commerce prices."""

from __future__ import annotations


def normalized_price_value(raw: str) -> str | None:
    """Normalize one locale-formatted numeric token after validating grouping."""
    separators = {separator for separator in ",." if separator in raw}
    if not separators:
        return raw if raw.isdigit() else None
    if len(separators) == 2:
        decimal_separator = max(separators, key=raw.rfind)
        thousands_separator = (separators - {decimal_separator}).pop()
        integer, fractional = raw.rsplit(decimal_separator, 1)
        if len(fractional) not in {1, 2} or not _valid_grouped_integer(
            integer, thousands_separator
        ):
            return None
        return f"{integer.replace(thousands_separator, '')}.{fractional}"
    separator = separators.pop()
    parts = raw.split(separator)
    if len(parts) == 2 and len(parts[1]) in {1, 2}:
        return f"{parts[0]}.{parts[1]}"
    return "".join(parts) if _valid_grouped_parts(parts) else None


def _valid_grouped_integer(value: str, separator: str) -> bool:
    return separator not in value or _valid_grouped_parts(value.split(separator))


def _valid_grouped_parts(parts: list[str]) -> bool:
    return bool(
        len(parts) > 1
        and 1 <= len(parts[0]) <= 3
        and all(len(part) == 3 for part in parts[1:])
    )
