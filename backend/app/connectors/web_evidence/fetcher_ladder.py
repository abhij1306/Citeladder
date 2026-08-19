"""Acquisition-ladder stages used by :class:`SecureFetcher`.

The owning fetcher still coordinates admission and the overall request.  This
module keeps the curl/browser transport stages cohesive without introducing a
second public fetcher or a compatibility forwarding layer.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any, cast
from urllib.parse import urljoin

from app.connectors.web_evidence.acquisition import configured_ladder_trigger
from app.connectors.web_evidence.browser_recovery import (
    browser_result_or_prior,
    prior_or_error,
)
from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
    RedirectHop,
)
from app.connectors.web_evidence.fetcher_body import is_bot_block_result
from app.core.config.site_health_acquisition import (
    ACQUISITION_TRANSPORT_BROWSER,
    ACQUISITION_TRANSPORT_CURL_CFFI,
    ERROR_ACQUISITION_UNAVAILABLE,
    ERROR_REDIRECT_LIMIT,
    POLICY_BLOCKING_ERROR_CODES,
)

_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})


class AcquisitionLadderMixin:
    """Concrete curl and browser acquisition stages for ``SecureFetcher``."""

    async def _fetch_preferred_rung(
        self: Any,
        *,
        request: FetchRequest,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
        preferred_rung: int,
        initial_trigger: str,
    ) -> FetchResult | None:
        """Start at persisted rung 2 when host evidence requires it."""
        if preferred_rung != 2 or self._curl_transport is None:
            return None
        try:
            result = await self._fetch_curl(
                request=request,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                limits=limits,
                attempts=attempts,
                trigger=initial_trigger,
            )
        except FetchError as exc:
            can_render = (
                exc.error_code in self._settings.browser_continue_error_codes
                and self._settings.browser_enabled
                and self._browser_transport is not None
            )
            if not can_render:
                if not exc.attempts:
                    exc.attempts = tuple(attempts)
                raise
            return await self._continue_with_browser(
                request=request,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                limits=limits,
                attempts=attempts,
                trigger=initial_trigger,
                prior=None,
                fallback_error=exc,
            )
        result = replace(result, attempts=tuple(attempts))
        trigger = self._ladder_trigger(result)
        if trigger is None:
            return result
        return await self._continue_with_browser(
            request=request,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            enforce_scope=enforce_scope,
            limits=limits,
            attempts=attempts,
            trigger=trigger,
            prior=result,
        )

    def _ladder_trigger(self: Any, result: FetchResult) -> str | None:
        """Return the config-owned reason for entering a later rung."""
        return configured_ladder_trigger(
            result,
            settings=self._settings,
            has_challenge_marker=is_bot_block_result(result),
        )

    async def _continue_acquisition_ladder(
        self: Any,
        *,
        request: FetchRequest,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
        trigger: str,
        prior: FetchResult,
    ) -> FetchResult:
        """Run curl when available, then the local browser rung if needed."""
        curl_result = prior
        trigger_for_browser = trigger
        if self._curl_transport is not None:
            try:
                curl_result = await self._fetch_curl(
                    request=request,
                    root_registrable_domain=root_registrable_domain,
                    include_globs=include_globs,
                    exclude_globs=exclude_globs,
                    enforce_scope=enforce_scope,
                    limits=limits,
                    attempts=attempts,
                    trigger=trigger,
                )
            except FetchError as exc:
                if exc.error_code not in self._settings.browser_continue_error_codes:
                    if not exc.attempts:
                        exc.attempts = tuple(attempts)
                    raise
            else:
                curl_still_blocked = self._ladder_trigger(curl_result)
                if curl_still_blocked is None:
                    return curl_result
                trigger_for_browser = curl_still_blocked
        return await self._continue_with_browser(
            request=request,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            enforce_scope=enforce_scope,
            limits=limits,
            attempts=attempts,
            trigger=trigger_for_browser,
            prior=curl_result,
        )

    async def _fetch_curl(
        self: Any,
        *,
        request: FetchRequest,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
        trigger: str,
    ) -> FetchResult:
        """Run the pinned curl transport with manual redirect validation."""
        transport = self._curl_transport
        if transport is None:
            raise FetchError(
                "curl acquisition transport unavailable",
                error_code=ERROR_ACQUISITION_UNAVAILABLE,
            )
        max_wire, max_decoded, timeout, max_redirects = limits
        acquisition = AcquisitionProvenance(
            transport=ACQUISITION_TRANSPORT_CURL_CFFI,
            rung=2,
            trigger=trigger,
            impersonation_profile=self._settings.curl_cffi_impersonation_profile,
            policy_version=self._settings.acquisition_policy_version,
        )
        current_url = request.url
        redirect_chain: list[RedirectHop] = []
        for hop in range(max_redirects + 1):
            target = await self._resolve(
                current_url,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                purpose=request.purpose,
            )
            hop_started = time.monotonic()
            try:
                result = await transport.fetch(
                    request,
                    target,
                    max_wire_bytes=max_wire,
                    max_decoded_bytes=max_decoded,
                    timeout_seconds=timeout,
                )
            except FetchError as exc:
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                    acquisition=acquisition,
                )
                exc.attempts = tuple(attempts)
                raise
            location = result.redirect_location
            if result.status_code not in _REDIRECT_STATUSES or not location:
                self._trace_curl_result(
                    attempts, request, result, hop_started, acquisition
                )
                # Sonar models dataclasses.replace as DataclassInstance rather
                # than preserving the concrete dataclass type; narrow that gap.
                return cast(
                    FetchResult,
                    replace(
                        result,
                        requested_url=request.url,
                        redirect_chain=tuple(redirect_chain),
                        attempts=tuple(attempts),
                        acquisition=acquisition,
                    ),
                )
            if hop >= max_redirects:
                self._trace_curl_result(
                    attempts,
                    request,
                    result,
                    hop_started,
                    acquisition,
                    error_code=ERROR_REDIRECT_LIMIT,
                )
                raise FetchError(
                    "curl acquisition redirect limit",
                    error_code=ERROR_REDIRECT_LIMIT,
                    attempts=tuple(attempts),
                )
            next_url = urljoin(target.url, location)
            redirect_chain.append(
                RedirectHop(
                    from_url=target.url,
                    to_url=next_url,
                    status_code=result.status_code,
                )
            )
            self._trace_curl_result(attempts, request, result, hop_started, acquisition)
            current_url = next_url
        raise FetchError(
            "curl acquisition redirect limit",
            error_code=ERROR_REDIRECT_LIMIT,
            attempts=tuple(attempts),
        )

    def _trace_curl_result(
        self: Any,
        attempts: list[FetchCallTrace],
        request: FetchRequest,
        result: FetchResult,
        started: float,
        acquisition: AcquisitionProvenance,
        *,
        error_code: str | None = None,
    ) -> None:
        self._trace(
            attempts,
            url=result.final_url,
            method=request.method,
            status_code=result.status_code,
            error_code=error_code,
            wire_bytes=result.wire_bytes,
            decoded_bytes=result.decoded_bytes,
            ttfb_ms=result.ttfb_ms,
            started=started,
            acquisition=acquisition,
        )

    async def _continue_with_browser(
        self: Any,
        *,
        request: FetchRequest,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
        trigger: str,
        prior: FetchResult | None,
        fallback_error: FetchError | None = None,
    ) -> FetchResult:
        """Render the target locally when server evidence stays unusable.

        The last rung of the frozen ladder. The target is resolved through the
        same canonicalization, scope, hard-admission, and pinned-DNS checks as
        every other rung BEFORE the browser is allowed to navigate to it, so a
        rendered page can never reach an address the HTTP rungs would refuse.

        When no browser transport is configured this returns the prior result
        unchanged: an unavailable last rung is not itself a fetch failure.
        """
        transport = self._browser_transport
        if transport is None or not self._settings.browser_enabled:
            return prior_or_error(prior, fallback_error, attempts)
        max_wire, max_decoded, timeout, _max_redirects = limits
        acquisition = AcquisitionProvenance(
            transport=ACQUISITION_TRANSPORT_BROWSER,
            rung=3,
            trigger=trigger,
            options={
                "readiness_timeout_seconds": float(
                    self._settings.browser_readiness_timeout_seconds
                ),
                "navigation_timeout_seconds": float(
                    self._settings.browser_navigation_timeout_seconds
                ),
            },
            policy_version=self._settings.acquisition_policy_version,
        )
        started = time.monotonic()
        try:
            target = await self._resolve(
                request.url,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                purpose=request.purpose,
            )
        except FetchError as exc:
            exc.attempts = tuple(attempts)
            # A POLICY denial must surface: robots, admission, and scope apply
            # to rung 3 exactly as they do to rung 1, and swallowing one here
            # would let a render reach a URL the crawler is not allowed to
            # fetch. Anything else — a transient DNS or resolver failure — is
            # this rung being unavailable, and the prior server evidence stays
            # the crawl's answer rather than a page that already fetched
            # successfully being turned into a hard failure.
            if exc.error_code in POLICY_BLOCKING_ERROR_CODES:
                raise
            self._trace(
                attempts,
                url=request.url,
                method=request.method,
                status_code=exc.status_code,
                error_code=exc.error_code,
                wire_bytes=None,
                decoded_bytes=None,
                ttfb_ms=None,
                started=started,
                acquisition=acquisition,
            )
            return prior_or_error(prior, fallback_error, attempts)
        try:
            result = await transport.fetch(
                request,
                target,
                max_wire_bytes=max_wire,
                max_decoded_bytes=max_decoded,
                timeout_seconds=timeout,
            )
        except FetchError as exc:
            self._trace(
                attempts,
                url=target.url,
                method=request.method,
                status_code=exc.status_code,
                error_code=exc.error_code,
                wire_bytes=None,
                decoded_bytes=None,
                ttfb_ms=None,
                started=started,
                acquisition=acquisition,
            )
            # The browser rung is best-effort recovery: when it cannot render,
            # the prior server evidence remains the crawl's answer rather than
            # turning a usable-but-thin response into a hard failure.
            return prior_or_error(prior, fallback_error, attempts)
        self._trace(
            attempts,
            url=result.final_url or target.url,
            method=request.method,
            status_code=result.status_code,
            error_code=None,
            wire_bytes=result.wire_bytes,
            decoded_bytes=result.decoded_bytes,
            ttfb_ms=result.ttfb_ms,
            started=started,
            acquisition=acquisition,
        )
        return browser_result_or_prior(
            result,
            prior=prior,
            fallback_error=fallback_error,
            request=request,
            attempts=attempts,
            acquisition=acquisition,
            low_content_bytes=self._settings.browser_low_content_bytes,
        )
