# Canonical API error codes + retryable classification (invariant 1).
#
# Every non-2xx API response carries the unified envelope built by
# ``app.core.errors`` — ``{detail, error: {code, message, request_id,
# retryable, details?}}``. The stable snake_case ``code`` vocabulary and the
# retryable classification rule live HERE, never inline in routers or
# handlers, so the machine-readable contract stays greppable and cannot drift
# between raise sites (WS-A A1).
#
# Domain-owned coded errors keep their existing codes where they already live
# (e.g. ``config/site_health_contracts.py``'s ``stale_selection_version`` /
# ``site_health_quota_exceeded`` / ``crawl_already_active``, opportunities'
# ``opportunity_superseded``) — this module owns the GENERIC vocabulary used
# by the envelope handlers and by raise sites that previously returned an
# uncoded string detail.
from __future__ import annotations

from typing import Final

# Server-side failures.
CODE_INTERNAL_ERROR: Final = "internal_error"
CODE_BAD_GATEWAY: Final = "bad_gateway"
CODE_SERVICE_UNAVAILABLE: Final = "service_unavailable"
CODE_GATEWAY_TIMEOUT: Final = "gateway_timeout"

# Client-side failures (generic; domain codes stay with their subsystems).
CODE_VALIDATION_ERROR: Final = "validation_error"
CODE_BAD_REQUEST: Final = "bad_request"
CODE_UNAUTHORIZED: Final = "unauthorized"
CODE_FORBIDDEN: Final = "forbidden"
CODE_NOT_FOUND: Final = "not_found"
CODE_METHOD_NOT_ALLOWED: Final = "method_not_allowed"
CODE_CONFLICT: Final = "conflict"
CODE_GONE: Final = "gone"
CODE_PAYLOAD_TOO_LARGE: Final = "payload_too_large"
CODE_UNSUPPORTED_MEDIA_TYPE: Final = "unsupported_media_type"
CODE_RATE_LIMITED: Final = "rate_limited"
CODE_INVALID_CURSOR: Final = "invalid_cursor"

# Fallback for a legacy ``HTTPException`` whose status has no mapped code.
CODE_HTTP_ERROR: Final = "http_error"

# Status -> default code for legacy raw ``HTTPException`` raises (string or
# uncoded detail). Coded raises always carry their own explicit code; this
# table is the shim's fallback so every response still has a stable code.
STATUS_DEFAULT_CODE: Final[dict[int, str]] = {
    400: CODE_BAD_REQUEST,
    401: CODE_UNAUTHORIZED,
    403: CODE_FORBIDDEN,
    404: CODE_NOT_FOUND,
    405: CODE_METHOD_NOT_ALLOWED,
    409: CODE_CONFLICT,
    410: CODE_GONE,
    413: CODE_PAYLOAD_TOO_LARGE,
    415: CODE_UNSUPPORTED_MEDIA_TYPE,
    422: CODE_VALIDATION_ERROR,
    429: CODE_RATE_LIMITED,
    500: CODE_INTERNAL_ERROR,
    502: CODE_BAD_GATEWAY,
    503: CODE_SERVICE_UNAVAILABLE,
    504: CODE_GATEWAY_TIMEOUT,
}

# The transient HTTP statuses a client may blindly retry (mirrors the
# frontend retry policy: retry 408/429/5xx + network errors, never a 4xx
# precondition/validation failure). Any 5xx is transient by definition.
RETRYABLE_STATUSES: Final[frozenset[int]] = frozenset({408, 429})


def is_retryable_status(status_code: int) -> bool:
    """Classify a status as retryable: 408/429 or any 5xx, never another 4xx."""
    return status_code in RETRYABLE_STATUSES or 500 <= status_code <= 599
