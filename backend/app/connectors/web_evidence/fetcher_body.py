"""Bot-block classification over bounded fetched bodies."""

from __future__ import annotations

from app.connectors.web_evidence.contracts import FetchResult
from app.core.config.site_health_acquisition import (
    BOT_BLOCK_BODY_MARKERS,
    BOT_BLOCK_MARKER_SCAN_BYTES,
)

_BOT_BLOCK_MARKER_BYTES: tuple[bytes, ...] = tuple(
    marker.lower().encode("ascii") for marker in BOT_BLOCK_BODY_MARKERS
)


def is_bot_block_result(result: FetchResult) -> bool:
    """Classify a distinctive challenge interstitial without retrying it."""
    prefix = result.body[:BOT_BLOCK_MARKER_SCAN_BYTES].lower()
    if not any(marker in prefix for marker in _BOT_BLOCK_MARKER_BYTES):
        return False
    meaningful_document = (
        200 <= result.status_code < 300
        and b"<h1" in prefix
        and (b"<main" in prefix or b"<article" in prefix)
    )
    return not meaningful_document
