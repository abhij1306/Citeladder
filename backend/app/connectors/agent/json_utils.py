"""Shared normalization helpers for model adapters."""


def strip_json_fence(content: str) -> str:
    """Normalize the harmless JSON fences emitted by some model hosts."""
    stripped = content.strip()
    if not stripped.startswith("```"):
        return stripped
    opening, separator, remainder = stripped.partition("\n")
    if not separator or opening.casefold() not in {"```", "```json"}:
        return stripped
    body = remainder.rstrip()
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()
