# SSRF-safe async HTTP fetcher for the Site Health crawler (Task 3).
#
# This module owns the fetcher's LIFECYCLE and its entry point. The concrete
# acquisition stages live beside it and are composed in, not duplicated:
#   - ``fetcher_body``   — content-type metadata, incremental decoding, and the
#                          wire/decoded byte caps;
#   - ``fetcher_http``   — rung 1 (httpx), URL admission, pinned resolution,
#                          redirect walking, and body finalization;
#   - ``fetcher_ladder`` — rungs 2 and 3 (curl_cffi, patchright) plus the
#                          config-owned trigger that enters them.
#
# Every safety property the plan requires is enforced across those modules:
#   - trust_env=False (never read proxy/CA env of the host).
#   - MANUAL redirects only (follow_redirects=False): each hop is re-validated
#     through ``url_policy.resolve_target`` (scheme/port/userinfo/scope/DNS/
#     SSRF), so a redirect to a private/loopback/out-of-scope URL is rejected.
#   - A validated connection IP is PINNED for the dial while the original Host
#     header + TLS SNI are preserved (DNS-rebinding protection: we never let
#     the socket re-resolve the hostname) — see ``_build_httpx_request``.
#   - Independent wire-byte and DECODED-byte caps enforced while streaming, so
#     an oversized response OR a compression bomb aborts before it is buffered
#     or parsed (we decompress incrementally and measure output).
#   - Response headers redacted to the config allowlist (no cookies/auth).
#   - Per-request timeout and a redirect-count cap.
#
# The acquisition ladder is frozen at three rungs, each entered only on
# config-owned evidence (``curl_trigger_for_result``) that the previous rung's
# response is unusable:
#   1. ``secure_httpx``   — ordinary server-rendered evidence;
#   2. ``curl_cffi``      — transport/challenge evidence justifies one retry;
#   3. ``patchright``     — a JS shell still needs local rendering.
# There is deliberately NO paid acquisition vendor and no real-Chrome
# escalation. A site that still blocks a well-identified crawler after the
# ladder is telling us it is not AEO-ready, and that answer is the signal we
# report (``ERROR_BOT_BLOCKED``) rather than something to work around further.
# ``fetcher_body.is_bot_block_result`` classifies that outcome; nothing retries
# past rung 3.
#
# Every REAL network call (every redirect hop) appends one ``FetchCallTrace``
# entry; the immutable trace is returned on BOTH ``FetchResult`` and
# ``FetchError`` so it survives failure. Persisting one ``SiteFetchAttempt``
# row per entry is T8's job.
#
# The DNS resolver and (optionally) the httpx transport are injected so tests
# run entirely offline with a fake resolver and ``httpx.MockTransport`` (no
# live internet — subplan test contract). There is NO raw-body persistence:
# the decoded bytes are handed back in-process for bounded parsing only.
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from urllib.parse import urlsplit

import httpx

from app.connectors.web_evidence.acquisition import (
    curl_cffi_pinned_resolution_supported,
)
from app.connectors.web_evidence.browser_transport import PatchrightTransport
from app.connectors.web_evidence.contracts import (
    AcquisitionProvenance,
    AcquisitionTransport,
    DnsResolver,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
    ResolvedTarget,
)
from app.connectors.web_evidence.curl_transport import CurlCffiTransport
from app.connectors.web_evidence.fetcher_http import (
    HttpAcquisitionMixin,
    enforce_admission,
)
from app.connectors.web_evidence.fetcher_ladder import AcquisitionLadderMixin
from app.core.config.site_health_acquisition import (
    ACQUISITION_TRANSPORT_HTTPX,
    ACQUISITION_TRIGGER_INITIAL,
    SITE_HEALTH_USER_AGENT,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)


class SecureFetcher(HttpAcquisitionMixin, AcquisitionLadderMixin):
    """Shared SSRF-safe HTTP fetcher (httpx).

    Construct with the injected DNS ``resolver`` and, optionally, an httpx
    ``transport`` (tests pass ``httpx.MockTransport``). When a transport is
    injected the fetcher sends to the canonical URL as-is (so the mock can
    match it); in production (no transport) it pins the validated connection
    IP while preserving Host + SNI.
    """

    def __init__(
        self,
        *,
        resolver: DnsResolver,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
        client_provider: Callable[[ResolvedTarget], httpx.AsyncClient] | None = None,
        settings=site_health_settings,
        browser_transport: AcquisitionTransport | None = None,
        curl_transport: AcquisitionTransport | None = None,
        curl_pinned_resolution_supported: bool | None = None,
        user_agent: str = SITE_HEALTH_USER_AGENT,
    ) -> None:
        self._resolver = resolver
        self._settings = settings
        self._user_agent = user_agent
        self._injected_transport = transport
        self._browser_transport = browser_transport
        self._curl_pinned_resolution_supported = (
            curl_cffi_pinned_resolution_supported()
            if curl_pinned_resolution_supported is None
            else curl_pinned_resolution_supported
        )
        self._curl_transport = curl_transport
        self._owns_curl_transport = False
        if (
            self._curl_transport is None
            and settings.curl_cffi_enabled
            and self._curl_pinned_resolution_supported
        ):
            self._curl_transport = CurlCffiTransport(
                impersonation_profile=settings.curl_cffi_impersonation_profile,
                user_agent=user_agent,
            )
            self._owns_curl_transport = True
        # Only a transport WE created may be closed on exit. An injected one is
        # owned by the caller and is commonly shared across fetchers (see
        # other bounded acquisition workers, which build one fetcher per task);
        # closing it here would shut down the shared browser after the first
        # fetch and leave every later task with a dead rung.
        self._owns_browser_transport = False
        if self._browser_transport is None and settings.browser_enabled:
            self._browser_transport = PatchrightTransport(
                settings=settings,
                user_agent=user_agent,
            )
            self._owns_browser_transport = True
        # In production we pin the IP ourselves, so the transport must never
        # re-resolve or read the host environment (invariant: trust_env=False).
        if client is not None and client_provider is not None:
            raise ValueError("client and client_provider are mutually exclusive")
        self._client_provider = client_provider
        self._owns_client = client is None and client_provider is None
        self._client = client
        if self._owns_client:
            self._client = self.build_client(
                transport=transport,
                settings=settings,
                user_agent=user_agent,
            )
        self._pin_ip = transport is None

    @staticmethod
    def build_client(
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        settings=site_health_settings,
        user_agent: str = SITE_HEALTH_USER_AGENT,
    ) -> httpx.AsyncClient:
        """Build the secure HTTP session used by one fetcher or worker.

        Keeping construction here prevents a pooled worker client from
        drifting from the connector's security boundary. Redirects remain
        manual, environment proxies stay disabled, and production requests
        still carry the per-request pinned-IP/SNI extensions.
        """
        return httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            headers={"user-agent": user_agent},
        )

    async def __aenter__(self) -> SecureFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close every rung this fetcher constructed.

        Each teardown runs in a ``finally`` so an earlier failure cannot strand
        a later one — the browser rung owns OS PROCESSES, not just sockets, and
        leaving one to garbage collection strands a headless browser per
        fetcher. An injected client belongs to the caller and is deliberately
        left running so its connection pool can be reused by later tasks.
        """
        try:
            if self._owns_client and self._client is not None:
                await self._client.aclose()
        finally:
            try:
                if self._owns_curl_transport and self._curl_transport is not None:
                    await self._curl_transport.aclose()
            finally:
                if self._owns_browser_transport and self._browser_transport is not None:
                    await self._browser_transport.aclose()

    def _limits(self, request: FetchRequest) -> tuple[int, int, float, int]:
        s = self._settings
        return (
            request.max_wire_bytes or s.max_response_wire_bytes,
            request.max_decoded_bytes or s.max_response_decoded_bytes,
            request.timeout_seconds or s.request_timeout_seconds,
            request.max_redirects
            if request.max_redirects is not None
            else s.max_redirects,
        )

    def _build_httpx_request(
        self,
        *,
        method: str,
        target: ResolvedTarget,
        extra_headers: dict[str, str],
        timeout: float,
    ) -> tuple[httpx.AsyncClient, httpx.Request]:
        client = (
            self._client_provider(target)
            if self._client_provider is not None
            else self._client
        )
        if client is None:
            raise RuntimeError("secure HTTP client is unavailable")
        headers = dict(extra_headers)
        if self._pin_ip:
            # Dial the pinned, validated IP but keep Host + SNI = original host
            # (DNS-rebinding protection). httpcore uses the sni_hostname
            # extension for the TLS handshake.
            parts = urlsplit(target.url)
            host_header = target.host
            if target.port not in (80, 443):
                host_header = f"{target.host}:{target.port}"
            ip_literal = (
                f"[{target.connect_ip}]"
                if ":" in target.connect_ip
                else target.connect_ip
            )
            dial_url = parts._replace(netloc=f"{ip_literal}:{target.port}").geturl()
            headers["host"] = host_header
            return (
                client,
                client.build_request(
                    method,
                    dial_url,
                    headers=headers,
                    timeout=timeout,
                    extensions={"sni_hostname": target.host},
                ),
            )
        return (
            client,
            client.build_request(method, target.url, headers=headers, timeout=timeout),
        )

    async def fetch(
        self,
        request: FetchRequest,
        *,
        root_registrable_domain: str | None = None,
        include_globs: list[str] | None = None,
        exclude_globs: list[str] | None = None,
        enforce_scope: bool = False,
        preferred_rung: int = 1,
        initial_trigger: str = ACQUISITION_TRIGGER_INITIAL,
    ) -> FetchResult:
        """Fetch ``request.url`` with full SSRF + size + redirect enforcement.

        Re-validates the initial URL and every redirect hop. Returns a bounded,
        redacted ``FetchResult`` (including 4xx/5xx — the caller classifies the
        status); raises ``FetchError`` with a safe token for SSRF, redirect
        limit, oversize, unsupported content type, or timeout.

        A bot-blocked response is returned as the result it is — there is no
        retry and no impersonation. The per-network-call trace is carried on
        the returned ``FetchResult.attempts`` AND on any raised
        ``FetchError.attempts`` (dual-field design), so the trace survives
        failure; the entry describing a returned result is always the last.
        """
        enforce_admission(
            request.url,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            purpose=request.purpose,
        )

        limits = self._limits(request)
        attempts: list[FetchCallTrace] = []
        preferred = await self._fetch_preferred_rung(
            request=request,
            root_registrable_domain=root_registrable_domain,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            enforce_scope=enforce_scope,
            limits=limits,
            attempts=attempts,
            preferred_rung=preferred_rung,
            initial_trigger=initial_trigger,
        )
        if preferred is not None:
            return preferred
        initial = AcquisitionProvenance(
            transport=ACQUISITION_TRANSPORT_HTTPX,
            rung=1,
            trigger=initial_trigger,
            policy_version=self._settings.acquisition_policy_version,
        )
        try:
            result = await self._fetch_http(
                request,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                purpose=request.purpose,
                limits=limits,
                attempts=attempts,
                acquisition=initial,
            )
        except FetchError as exc:
            if not exc.attempts:
                exc.attempts = tuple(attempts)
            raise
        result = replace(result, attempts=tuple(attempts), acquisition=initial)
        trigger = self._ladder_trigger(result)
        # Continue while ANY later rung is enabled. Gating the whole ladder on
        # ``curl_cffi_enabled`` alone made rung 3 unreachable for a deployment
        # that runs the browser without curl — the evidence said "retry" and
        # the ladder stopped anyway.
        ladder_available = (
            self._settings.curl_cffi_enabled or self._settings.browser_enabled
        )
        if trigger is None or not ladder_available:
            return result
        return await self._continue_acquisition_ladder(
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

    def _trace(
        self,
        attempts: list[FetchCallTrace],
        *,
        url: str,
        method: str,
        status_code: int | None,
        error_code: str | None,
        wire_bytes: int | None,
        decoded_bytes: int | None,
        ttfb_ms: int | None,
        started: float,
        acquisition: AcquisitionProvenance,
    ) -> None:
        """Append ONE immutable trace entry for ONE real network call."""
        attempts.append(
            FetchCallTrace(
                request_ordinal=len(attempts),
                url=url,
                method=method,
                status_code=status_code,
                error_code=error_code,
                wire_bytes=wire_bytes,
                decoded_bytes=decoded_bytes,
                ttfb_ms=ttfb_ms,
                latency_ms=int((time.monotonic() - started) * 1000),
                acquisition=acquisition,
            )
        )
