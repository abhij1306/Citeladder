"""URL helpers shared by the worker loop and its phase mixins.

Lives here rather than in ``site_health_worker`` because the phase modules
import it and the worker imports them — the other direction would be a cycle.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def authority_key(url: str) -> str:
    """The ``scheme://host:port`` authority a robots.txt policy is keyed by.

    Robots policies are per (scheme, host, port); the default port is filled
    in so ``https://example.com`` and ``https://example.com:443`` share one
    policy. Returns ``""`` for an unparseable URL (the caller then skips
    robots enforcement — the URL policy will reject it downstream anyway).
    """
    try:
        parts = urlsplit(url)
        scheme = (parts.scheme or "").lower()
        host = (parts.hostname or "").lower()
        try:
            port = parts.port
        except ValueError:
            port = None
    except ValueError:
        return ""
    if not scheme or not host:
        return ""
    if port is None:
        port = 443 if scheme == "https" else 80
    return f"{scheme}://{host}:{port}"
