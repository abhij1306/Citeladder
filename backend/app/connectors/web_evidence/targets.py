"""Shared validation for an already-resolved acquisition target.

Every transport rung below ``SecureFetcher`` receives a ``ResolvedTarget`` the
fetcher has already canonicalized, scope-checked, DNS-resolved, and pinned. A
rung must still fail closed if the target's URL authority does not match the
authority that was actually validated — otherwise a rung could connect to one
host while the policy approved another.

Lives here rather than inside one transport so every rung shares exactly one
definition of that check.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from app.connectors.web_evidence.contracts import FetchError, ResolvedTarget
from app.connectors.web_evidence.url_policy import split_host_port
from app.core.config.site_health import ERROR_ACQUISITION_UNAVAILABLE


def validate_resolved_target(target: ResolvedTarget) -> None:
    """Fail closed unless the requested authority is exactly the pinned one."""

    try:
        requested_host, requested_port = split_host_port(target.url)
    except (TypeError, ValueError) as exc:
        raise FetchError(
            "acquisition received an invalid resolved target",
            error_code=ERROR_ACQUISITION_UNAVAILABLE,
        ) from exc
    requested_scheme = urlsplit(target.url).scheme.casefold()
    if (
        requested_host != target.host.casefold().rstrip(".")
        or requested_port != target.port
        or requested_scheme != target.scheme.casefold()
    ):
        raise FetchError(
            "acquisition target did not match its validated authority",
            error_code=ERROR_ACQUISITION_UNAVAILABLE,
        )
