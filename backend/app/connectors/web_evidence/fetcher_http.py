"""HTTP transport and response-finalization stages for ``SecureFetcher``.

Rung 1 of the frozen acquisition ladder plus the policy gates every rung
shares. Redirects are followed MANUALLY so each hop is re-validated through
``url_policy.resolve_target`` (scheme/port/userinfo/scope/DNS/SSRF) and through
the hard-admission policy, and every real network call appends exactly one
``FetchCallTrace``.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urljoin

import httpx

from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResolvedTarget,
)
from app.connectors.web_evidence.fetcher_body import (
    charset,
    content_type,
    content_type_gate_applies,
    incremental_decoder,
    read_decoded_stream,
    redact_headers,
)
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    classify_url_admission,
    resolve_target,
)
from app.core.config.site_health_acquisition import (
    ERROR_CONNECTION_FAILED,
    ERROR_REDIRECT_LIMIT,
    ERROR_SSRF_BLOCKED,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_CONTENT_TYPE,
    ERROR_URL_ADMISSION_REJECTED,
    FETCH_PURPOSE_ANALYZE,
    FETCH_PURPOSE_DISCOVER,
    FETCH_PURPOSE_LINK_CHECK,
)
from app.core.config.site_health_crawl_policy import (
    URL_EXCLUSION_HARD_ASSET,
    URL_EXCLUSION_HARD_PATH,
    URL_EXCLUSION_HARD_QUERY,
    URL_EXCLUSION_TRACKING,
)

_ADMISSION_ENFORCED_PURPOSES = frozenset(
    {FETCH_PURPOSE_DISCOVER, FETCH_PURPOSE_ANALYZE, FETCH_PURPOSE_LINK_CHECK}
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
    """Raise when the hard-admission policy refuses ``url`` for ``purpose``.

    Applied to the requested URL and, identically, to every redirect hop:
    redirects must use the same hard-admission policy as roots and discovered
    links. Well-known robots/sitemap documents are connector infrastructure
    rather than page candidates and are handled by their dedicated request
    purposes.
    """
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


class HttpAcquisitionMixin:
    """Concrete HTTP hop, policy-resolution, and bounded-body stages."""

    async def _fetch_http(
        self: Any,
        request: FetchRequest,
        *,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        purpose: str,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
        acquisition: AcquisitionProvenance,
    ) -> FetchResult:
        """Perform httpx acquisition with one immutable trace per network hop."""
        max_wire, max_decoded, timeout, max_redirects = limits
        current_url = request.url
        redirect_chain: list[RedirectHop] = []
        started = time.monotonic()
        for hop in range(max_redirects + 1):
            target = await self._resolve(
                current_url,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                purpose=purpose,
            )
            client, httpx_request = self._build_httpx_request(
                method=request.method,
                target=target,
                extra_headers=request.headers,
                timeout=timeout,
            )
            hop_started = time.monotonic()
            try:
                response = await client.send(
                    httpx_request, stream=True, follow_redirects=False
                )
            except httpx.TimeoutException as exc:
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=None,
                    error_code=ERROR_TIMEOUT,
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                    acquisition=acquisition,
                )
                raise FetchError(
                    "request timed out", error_code=ERROR_TIMEOUT, retryable=True
                ) from exc
            except httpx.HTTPError as exc:
                # Send-phase transport failure (DNS blip, refused connection,
                # reset handshake): ``connection_failed``, the same token
                # ``_read_body`` uses for the identical failure mid-body.
                #
                # This used to be ``ssrf_blocked`` — not because it was one, but
                # because the deleted TLS-block escalation hook matched on that
                # token to trigger an impersonated retry. With the retry gone the
                # label is actively wrong: ``ssrf_blocked`` is in
                # ``POLICY_BLOCKING_ERROR_CODES``, so a transient connection
                # error presented the page as ``blocked`` (a policy denial) when
                # it is an ``error``. SSRF_BLOCKED now means only what it says —
                # a real policy denial, raised from ``_resolve``.
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=None,
                    error_code=ERROR_CONNECTION_FAILED,
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                    acquisition=acquisition,
                )
                raise FetchError(
                    f"connection error: {type(exc).__name__}",
                    error_code=ERROR_CONNECTION_FAILED,
                    retryable=True,
                ) from exc

            if response.status_code in _REDIRECT_STATUSES:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    # A redirect status without a target: treat as final.
                    self._trace(
                        attempts,
                        url=target.url,
                        method=request.method,
                        status_code=response.status_code,
                        error_code=None,
                        wire_bytes=0,
                        decoded_bytes=0,
                        ttfb_ms=None,
                        started=hop_started,
                        acquisition=acquisition,
                    )
                    return self._finalize_no_body(
                        request,
                        target,
                        response,
                        redirect_chain,
                        started,
                        acquisition,
                    )
                if hop >= max_redirects:
                    self._trace(
                        attempts,
                        url=target.url,
                        method=request.method,
                        status_code=response.status_code,
                        error_code=ERROR_REDIRECT_LIMIT,
                        wire_bytes=None,
                        decoded_bytes=None,
                        ttfb_ms=None,
                        started=hop_started,
                        acquisition=acquisition,
                    )
                    raise FetchError(
                        "too many redirects", error_code=ERROR_REDIRECT_LIMIT
                    )
                next_url = urljoin(target.url, location)
                redirect_chain.append(
                    RedirectHop(
                        from_url=target.url,
                        to_url=next_url,
                        status_code=response.status_code,
                    )
                )
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=response.status_code,
                    error_code=None,
                    # Redirect bodies are deliberately unread.
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                    acquisition=acquisition,
                )
                current_url = next_url
                continue

            # Terminal response: stream body under both caps.
            try:
                result = await self._read_body(
                    request=request,
                    target=target,
                    response=response,
                    redirect_chain=redirect_chain,
                    started=started,
                    max_wire=max_wire,
                    max_decoded=max_decoded,
                    acquisition=acquisition,
                )
            except FetchError as exc:
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=response.status_code,
                    error_code=exc.error_code,
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                    acquisition=acquisition,
                )
                raise
            self._trace(
                attempts,
                url=target.url,
                method=request.method,
                status_code=result.status_code,
                error_code=None,
                wire_bytes=result.wire_bytes,
                decoded_bytes=result.decoded_bytes,
                ttfb_ms=result.ttfb_ms,
                started=hop_started,
                acquisition=acquisition,
            )
            return result
        raise FetchError("too many redirects", error_code=ERROR_REDIRECT_LIMIT)

    async def _resolve(
        self: Any,
        url: str,
        *,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        purpose: str,
    ) -> ResolvedTarget:
        """Admission-check, canonicalize, and DNS-pin one URL or redirect hop."""
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
        except UrlPolicyError as exc:
            # Out-of-scope / disallowed scheme-port-userinfo on a redirect hop.
            raise FetchError(str(exc), error_code=ERROR_SSRF_BLOCKED) from exc

    def _finalize_no_body(
        self: Any,
        request: FetchRequest,
        target: ResolvedTarget,
        response: httpx.Response,
        redirect_chain: list[RedirectHop],
        started: float,
        acquisition: AcquisitionProvenance,
    ) -> FetchResult:
        latency = int((time.monotonic() - started) * 1000)
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            status_code=response.status_code,
            redacted_headers=redact_headers(response.headers),
            content_type=content_type(response.headers),
            http_version=response.http_version or "",
            body=b"",
            wire_bytes=0,
            decoded_bytes=0,
            ttfb_ms=latency,
            latency_ms=latency,
            redirect_chain=tuple(redirect_chain),
            charset=charset(response.headers),
            acquisition=acquisition,
        )

    async def _read_body(
        self: Any,
        *,
        request: FetchRequest,
        target: ResolvedTarget,
        response: httpx.Response,
        redirect_chain: list[RedirectHop],
        started: float,
        max_wire: int,
        max_decoded: int,
        acquisition: AcquisitionProvenance,
    ) -> FetchResult:
        """Stream one terminal response under both byte caps and finalize it."""
        ttfb = int((time.monotonic() - started) * 1000)
        media_type = content_type(response.headers)
        allowed = request.allowed_content_types
        # An empty status body (204/304) or HEAD carries no content-type; only
        # enforce the allowlist when one is set on the request. Error statuses
        # bypass the gate entirely (see ``content_type_gate_applies``).
        if (
            allowed
            and media_type
            and media_type not in allowed
            and content_type_gate_applies(response.status_code)
        ):
            await response.aclose()
            raise FetchError(
                f"unsupported content type: {media_type}",
                error_code=ERROR_UNSUPPORTED_CONTENT_TYPE,
                status_code=response.status_code,
            )
        decode, decompressor = incremental_decoder(
            response.headers.get("content-encoding", "")
        )
        try:
            wire_total, decoded_total, decoded_chunks = await read_decoded_stream(
                response,
                decode=decode,
                decompressor=decompressor,
                max_wire=max_wire,
                max_decoded=max_decoded,
            )
        except httpx.TimeoutException as exc:
            raise FetchError(
                "request timed out", error_code=ERROR_TIMEOUT, retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            # A stream-read failure (e.g. connection reset mid-body) after
            # ``send()`` succeeded: classify it the same way as the request
            # phase instead of letting it propagate as an unclassified error.
            raise FetchError(
                f"connection error: {type(exc).__name__}",
                error_code=ERROR_CONNECTION_FAILED,
                retryable=True,
            ) from exc
        finally:
            await response.aclose()
        latency = int((time.monotonic() - started) * 1000)
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            status_code=response.status_code,
            redacted_headers=redact_headers(response.headers),
            content_type=media_type,
            http_version=response.http_version or "",
            body=b"".join(decoded_chunks),
            wire_bytes=wire_total,
            decoded_bytes=decoded_total,
            ttfb_ms=ttfb,
            latency_ms=latency,
            redirect_chain=tuple(redirect_chain),
            charset=charset(response.headers),
            acquisition=acquisition,
        )
