"""SSRF-safe curl-cffi fetcher for web evidence.

``SecureFetcher`` is the single website-acquisition owner. It validates and
DNS-pins the requested URL and every redirect before the sole curl-cffi
transport receives it, applies the configured byte/time bounds, and returns an
immutable per-call trace. Raw bodies remain in-process only.
"""

from __future__ import annotations

import time
from dataclasses import replace
from urllib.parse import urljoin

from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    AcquisitionTransport,
    DnsResolver,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResolvedTarget,
)
from app.connectors.web_evidence.curl_transport import CurlCffiTransport
from app.connectors.web_evidence.url_policy import (
    UrlAdmissionRejected,
    UrlPolicyError,
    classify_url_admission,
    resolve_target,
)
from app.core.config.site_health_acquisition import (
    ACQUISITION_TRANSPORT_CURL_CFFI,
    ACQUISITION_TRIGGER_INITIAL,
    ERROR_REDIRECT_LIMIT,
    ERROR_SSRF_BLOCKED,
    ERROR_URL_ADMISSION_REJECTED,
    FETCH_PURPOSE_ANALYZE,
    FETCH_PURPOSE_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    URL_EXCLUSION_HARD_ASSET,
    URL_EXCLUSION_HARD_PATH,
    URL_EXCLUSION_HARD_QUERY,
    URL_EXCLUSION_TRACKING,
)
from app.core.config.site_health_runtime import site_health_settings

_ADMISSION_ENFORCED_PURPOSES = frozenset(
    {FETCH_PURPOSE_DISCOVER, FETCH_PURPOSE_ANALYZE}
)
_HARD_ADMISSION_EXCLUSION_CODES = frozenset(
    {
        URL_EXCLUSION_HARD_PATH,
        URL_EXCLUSION_HARD_ASSET,
        URL_EXCLUSION_HARD_QUERY,
        URL_EXCLUSION_TRACKING,
    }
)
_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})


def enforce_admission(
    url: str,
    *,
    root_registrable_domain: str | None,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
    purpose: str,
) -> None:
    """Reject a requested URL or redirect excluded by crawl admission."""
    admission = classify_url_admission(
        url,
        root_registrable_domain=root_registrable_domain,
        include_globs=include_globs,
        exclude_globs=exclude_globs,
        infrastructure_purpose=purpose,
    )
    if (
        purpose in _ADMISSION_ENFORCED_PURPOSES
        and admission.reason_code in _HARD_ADMISSION_EXCLUSION_CODES
    ):
        raise FetchError(
            "URL rejected by admission policy",
            error_code=ERROR_URL_ADMISSION_REJECTED,
        )


class SecureFetcher:
    """Validate, DNS-pin, and acquire web evidence with curl-cffi only."""

    def __init__(
        self,
        *,
        resolver: DnsResolver,
        transport: AcquisitionTransport | None = None,
        settings=site_health_settings,
    ) -> None:
        self._resolver = resolver
        self._settings = settings
        self._transport = transport or CurlCffiTransport(
            impersonation_profile=settings.curl_cffi_impersonation_profile
        )
        self._owns_transport = transport is None

    async def __aenter__(self) -> SecureFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_transport:
            await self._transport.aclose()

    def _limits(self, request: FetchRequest) -> tuple[int, int, float, int]:
        settings = self._settings
        return (
            request.max_wire_bytes or settings.max_response_wire_bytes,
            request.max_decoded_bytes or settings.max_response_decoded_bytes,
            request.timeout_seconds or settings.request_timeout_seconds,
            request.max_redirects
            if request.max_redirects is not None
            else settings.max_redirects,
        )

    async def fetch(
        self,
        request: FetchRequest,
        *,
        root_registrable_domain: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        enforce_scope: bool = False,
    ) -> FetchResult:
        """Fetch one URL with manual, revalidated redirects and bounded traces."""
        enforce_admission(
            request.url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            purpose=request.purpose,
        )
        max_wire, max_decoded, timeout, max_redirects = self._limits(request)
        acquisition = AcquisitionProvenance(
            transport=ACQUISITION_TRANSPORT_CURL_CFFI,
            rung=1,
            trigger=ACQUISITION_TRIGGER_INITIAL,
            impersonation_profile=self._settings.curl_cffi_impersonation_profile,
            policy_version=self._settings.acquisition_policy_version,
        )
        attempts: list[FetchCallTrace] = []
        redirects: list[RedirectHop] = []
        current_url = request.url

        for hop in range(max_redirects + 1):
            target = await self._resolve(
                current_url,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                purpose=request.purpose,
            )
            started = time.monotonic()
            try:
                result = await self._transport.fetch(
                    replace(request, url=target.url),
                    target,
                    max_wire_bytes=max_wire,
                    max_decoded_bytes=max_decoded,
                    timeout_seconds=timeout,
                )
            except FetchError as exc:
                self._trace(
                    attempts,
                    target=target,
                    request=request,
                    started=started,
                    acquisition=acquisition,
                    error=exc,
                )
                exc.attempts = tuple(attempts)
                raise

            location = result.redirect_location
            is_redirect = result.status_code in _REDIRECT_STATUSES and bool(location)
            error_code = (
                ERROR_REDIRECT_LIMIT if is_redirect and hop >= max_redirects else None
            )
            self._trace(
                attempts,
                target=target,
                request=request,
                started=started,
                acquisition=acquisition,
                result=result,
                error_code=error_code,
            )
            if not is_redirect:
                completed: FetchResult = replace(
                    result,
                    requested_url=request.url,
                    redirect_chain=tuple(redirects),
                    attempts=tuple(attempts),
                    acquisition=acquisition,
                )
                return completed
            if hop >= max_redirects:
                raise FetchError(
                    "curl acquisition redirect limit",
                    error_code=ERROR_REDIRECT_LIMIT,
                    attempts=tuple(attempts),
                )
            next_url = urljoin(target.url, location)
            redirects.append(
                RedirectHop(
                    from_url=target.url,
                    to_url=next_url,
                    status_code=result.status_code,
                )
            )
            current_url = next_url

        raise FetchError(
            "curl acquisition redirect limit",
            error_code=ERROR_REDIRECT_LIMIT,
            attempts=tuple(attempts),
        )

    async def _resolve(
        self,
        url: str,
        *,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        purpose: str,
    ) -> ResolvedTarget:
        enforce_admission(
            url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            purpose=purpose,
        )
        try:
            return await resolve_target(
                url,
                resolver=self._resolver,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                infrastructure_purpose=purpose,
            )
        except UrlAdmissionRejected as exc:
            # Our own admission policy, not a network risk. Kept distinct from
            # ERROR_SSRF_BLOCKED so the crawl can drop the URL from its
            # applicable set instead of carrying it as a failed page forever.
            raise FetchError(str(exc), error_code=ERROR_URL_ADMISSION_REJECTED) from exc
        except UrlPolicyError as exc:
            raise FetchError(str(exc), error_code=ERROR_SSRF_BLOCKED) from exc

    @staticmethod
    def _trace(
        attempts: list[FetchCallTrace],
        *,
        target: ResolvedTarget,
        request: FetchRequest,
        started: float,
        acquisition: AcquisitionProvenance,
        result: FetchResult | None = None,
        error: FetchError | None = None,
        error_code: str | None = None,
    ) -> None:
        status_code = (
            result.status_code
            if result is not None
            else error.status_code
            if error
            else None
        )
        attempts.append(
            FetchCallTrace(
                request_ordinal=len(attempts),
                url=result.final_url if result is not None else target.url,
                method=request.method,
                status_code=status_code,
                error_code=error_code or (error.error_code if error else None),
                wire_bytes=result.wire_bytes if result is not None else None,
                decoded_bytes=result.decoded_bytes if result is not None else None,
                ttfb_ms=result.ttfb_ms if result is not None else None,
                latency_ms=int((time.monotonic() - started) * 1000),
                acquisition=acquisition,
            )
        )
