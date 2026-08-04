"""Pure policy helpers for Site Health's server-owned acquisition ladder.

The fetcher owns URL validation, redirects, bounded streaming, and the actual
network clients. This module owns only deterministic rung selection so no
transport can silently broaden the crawler's security policy.
"""

from __future__ import annotations

import sys

from app.connectors.web_evidence.contracts import FetchResult
from app.core.config.site_health import (
    ACQUISITION_TRIGGER_BLOCK_STATUS,
    ACQUISITION_TRIGGER_CHALLENGE,
    ACQUISITION_TRIGGER_LOW_CONTENT,
)


def curl_cffi_pinned_resolution_supported() -> bool:
    """Whether curl-cffi can meet this process's validated-IP contract.

    The current Windows worker platform cannot reliably bind curl-cffi's DNS
    override, TLS SNI, and peer verification to the IP selected by
    ``resolve_target``. Other platforms are supported only when the installed
    binding accepts libcurl's ``RESOLVE`` option. The probe performs no network
    I/O and fails closed on an absent or incompatible binding.
    """

    if sys.platform.startswith("win"):
        return False
    try:
        from curl_cffi import Curl, CurlOpt
    # An incompatible optional binding must fail closed regardless of error type.
    except Exception:  # noqa: BLE001
        return False
    try:
        curl = Curl()
        try:
            curl.setopt(CurlOpt.RESOLVE, ["citeladder.invalid:443:127.0.0.1"])
        finally:
            curl.close()
    # Capability probing is intentionally isolated from application work.
    except Exception:  # noqa: BLE001
        return False
    return True


def curl_trigger_for_result(
    result: FetchResult,
    *,
    has_challenge_marker: bool,
    trigger_statuses: tuple[int, ...],
    low_content_bytes: int,
) -> str | None:
    """Return the sole configured reason that permits a curl rung.

    Priority is deterministic and evidence-based. A regular timeout, policy
    rejection, redirect issue, or oversized response does not get retried by a
    different transport.
    """

    if has_challenge_marker:
        return ACQUISITION_TRIGGER_CHALLENGE
    if result.status_code in trigger_statuses:
        return ACQUISITION_TRIGGER_BLOCK_STATUS
    if low_content_bytes and 200 <= result.status_code < 300:
        if result.decoded_bytes < low_content_bytes:
            return ACQUISITION_TRIGGER_LOW_CONTENT
    return None
