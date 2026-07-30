# SSRF-safe async HTTP fetcher for the Site Health crawler (Task 3).
#
# Every safety property the plan requires lives here:
#   - trust_env=False (never read proxy/CA env of the host).
#   - MANUAL redirects only (follow_redirects=False): each hop is re-validated
#     through ``url_policy.resolve_target`` (scheme/port/userinfo/scope/DNS/
#     SSRF), so a redirect to a private/loopback/out-of-scope URL is rejected.
#   - A validated connection IP is PINNED for the dial while the original Host
#     header + TLS SNI are preserved (DNS-rebinding protection: we never let
#     the socket re-resolve the hostname).
#   - Independent wire-byte and DECODED-byte caps enforced while streaming, so
#     an oversized response OR a compression bomb aborts before it is buffered
#     or parsed (we decompress incrementally and measure output).
#   - Response headers redacted to the config allowlist (no cookies/auth).
#   - Per-request timeout and a redirect-count cap.
#
# The fetch is a PLAIN HTTP request and nothing more. There is deliberately no
# impersonation rung and no headless-browser rung: a site that blocks a
# well-identified crawler is telling us it is not AEO-ready, and that answer is
# the signal we report (``ERROR_BOT_BLOCKED``) rather than something to work
# around. ``is_bot_block_result`` classifies that outcome; nothing retries it.
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
import zlib
from collections.abc import Iterable
from dataclasses import replace
from urllib.parse import urljoin, urlsplit

import httpx

from app.connectors.web_evidence.contracts import (
    DnsResolver,
    FetchCallTrace,
    FetchError,
    FetchRequest,
    FetchResult,
    RedirectHop,
    ResolvedTarget,
)
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    resolve_target,
)
from app.core.config.site_health import (
    BOT_BLOCK_BODY_MARKERS,
    BOT_BLOCK_MARKER_SCAN_BYTES,
    ERROR_CONNECTION_FAILED,
    ERROR_MALFORMED_RESPONSE,
    ERROR_REDIRECT_LIMIT,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_SSRF_BLOCKED,
    ERROR_TIMEOUT,
    ERROR_UNSUPPORTED_CONTENT_TYPE,
    PERSISTED_RESPONSE_HEADERS,
    SITE_HEALTH_USER_AGENT,
    site_health_settings,
)

_REDIRECT_STATUSES: frozenset[int] = frozenset({301, 302, 303, 307, 308})

# Config-owned bot-block body markers as matchable bytes (ASCII-only tokens).
_BOT_BLOCK_MARKER_BYTES: tuple[bytes, ...] = tuple(
    marker.encode("ascii") for marker in BOT_BLOCK_BODY_MARKERS
)


def is_bot_block_result(result: FetchResult) -> bool:
    """Config-owned bot-block signature on a fetch RESULT (spec §5.4).

    True when a distinctive challenge-platform marker appears within the first
    ``BOT_BLOCK_MARKER_SCAN_BYTES`` of the decoded body. This is a
    CLASSIFICATION, not a retry trigger: the worker turns it into
    ``ERROR_BOT_BLOCKED`` so the page presents as ``blocked``.

    Deliberately marker-only. A bare 401/403/503 is NOT enough: those statuses
    used to be a cheap trigger to RETRY with impersonation, and only a second
    blocked response promoted the outcome to ``bot_blocked``. With no retry
    there is no corroborating evidence, so a status-only rule would relabel
    every members-only 401 and every transient 503 as bot protection. The
    challenge markers stand on their own; the statuses keep their ordinary
    ``http_4xx``/``http_5xx`` classification.
    """
    if not _BOT_BLOCK_MARKER_BYTES:
        return False
    prefix = result.body[:BOT_BLOCK_MARKER_SCAN_BYTES].lower()
    return any(marker in prefix for marker in _BOT_BLOCK_MARKER_BYTES)


def redact_headers(headers: httpx.Headers | dict) -> dict[str, str]:
    """Keep only the config-allowlisted response headers (lowercased keys).

    Everything else (Set-Cookie, Authorization echoes, etc.) is dropped so no
    sensitive header is ever persisted or logged.
    """
    out: dict[str, str] = {}
    items: Iterable[tuple[str, str]] = (
        headers.items() if hasattr(headers, "items") else []
    )
    for key, value in items:
        lk = str(key).lower()
        if lk in PERSISTED_RESPONSE_HEADERS:
            out[lk] = str(value)
    return out


def _content_type(headers: httpx.Headers) -> str:
    raw = headers.get("content-type", "")
    return str(raw).split(";", 1)[0].strip().lower()


def _content_type_gate_applies(status_code: int | None) -> bool:
    """Whether the content-type allowlist may reject this response.

    The allowlist exists to stop us downloading and parsing non-HTML CONTENT.
    An HTTP ERROR response is not content: its body is a diagnostic, and for a
    bot block it carries the very challenge markers we classify on. Rejecting
    one here hid the status behind ``unsupported_content_type`` — a 429 served
    as ``text/plain`` (the common WAF rate-limit shape) surfaced as a TERMINAL
    content-type failure instead of the retryable rate limit it is, and the
    whole crawl died on a transient block.

    So the gate applies to 2xx only — the responses whose body we actually
    keep as content. Error statuses are returned as results and classified
    from ``status_code`` by the caller; a 3xx body is discarded in favour of
    its ``Location``. The wire and decoded byte caps still bound the body on
    every path. An unknown status (``None``) keeps the gate ON — the
    conservative direction.
    """
    if status_code is None:
        return True
    return 200 <= status_code < 300


def _charset(headers: httpx.Headers) -> str:
    """Return the lowercased ``charset`` parameter of Content-Type, if any.

    Preserved separately from ``_content_type()`` (which intentionally strips
    parameters) so downstream HTML parsing can honor a non-UTF-8 charset
    instead of hard-coding UTF-8.
    """
    raw = str(headers.get("content-type", ""))
    for part in raw.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.strip().lower() == "charset":
            return value.strip().strip('"').strip("'").lower()
    return ""


def _incremental_decoder(content_encoding: str):
    """Return ``(decode_chunk, decompressor)`` for the wire encoding.

    ``decode_chunk`` is a ``callable(chunk)->bytes`` that feeds a chunk into the
    decompressor. ``decompressor`` is the underlying ``zlib`` object (``None``
    for identity/unknown encodings) so the caller can, after the stream ends,
    flush any buffered tail and inspect ``.eof`` — a gzip/deflate stream that
    was cut off mid-way never sets ``eof``, which is how a truncated response is
    detected (a truncated stream does not necessarily raise ``zlib.error``).

    Supports gzip and deflate (the encodings a compression bomb would use);
    ``identity``/unknown pass bytes through unchanged. brotli is not a
    dependency, so a ``br`` body is treated as opaque wire bytes (the wire cap
    still bounds it).
    """
    enc = str(content_encoding or "").strip().lower()
    if enc == "gzip":
        obj = zlib.decompressobj(16 + zlib.MAX_WBITS)
        return (lambda chunk: obj.decompress(chunk)), obj
    if enc == "deflate":
        obj = zlib.decompressobj()
        return (lambda chunk: obj.decompress(chunk)), obj
    return (lambda chunk: chunk), None


class SecureFetcher:
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
        settings=site_health_settings,
        user_agent: str = SITE_HEALTH_USER_AGENT,
    ) -> None:
        self._resolver = resolver
        self._settings = settings
        self._user_agent = user_agent
        self._injected_transport = transport
        # In production we pin the IP ourselves, so the transport must never
        # re-resolve or read the host environment (invariant: trust_env=False).
        self._client = httpx.AsyncClient(
            transport=transport,
            follow_redirects=False,
            trust_env=False,
            timeout=httpx.Timeout(settings.request_timeout_seconds),
            headers={"user-agent": user_agent},
        )
        self._pin_ip = transport is None

    async def __aenter__(self) -> SecureFetcher:
        return self

    async def __aexit__(self, *exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

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
    ) -> httpx.Request:
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
            return self._client.build_request(
                method,
                dial_url,
                headers=headers,
                timeout=timeout,
                extensions={"sni_hostname": target.host},
            )
        return self._client.build_request(
            method, target.url, headers=headers, timeout=timeout
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
        limits = self._limits(request)
        attempts: list[FetchCallTrace] = []
        try:
            result = await self._fetch_http(
                request,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
                limits=limits,
                attempts=attempts,
            )
        except FetchError as exc:
            if not exc.attempts:
                exc.attempts = tuple(attempts)
            raise
        return replace(result, attempts=tuple(attempts))

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
            )
        )

    async def _fetch_http(
        self,
        request: FetchRequest,
        *,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
        limits: tuple[int, int, float, int],
        attempts: list[FetchCallTrace],
    ) -> FetchResult:
        """The httpx fetch. One trace entry per real network call."""
        (
            max_wire,
            max_decoded,
            timeout,
            max_redirects,
        ) = limits

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
            )
            httpx_request = self._build_httpx_request(
                method=request.method,
                target=target,
                extra_headers=request.headers,
                timeout=timeout,
            )
            hop_started = time.monotonic()
            try:
                response = await self._client.send(httpx_request, stream=True)
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
                )
                raise FetchError(
                    "request timed out",
                    error_code=ERROR_TIMEOUT,
                    retryable=True,
                ) from exc
            except httpx.HTTPError as exc:
                # Network-level failure: classify as SSRF-adjacent connection
                # error but keep the message safe.
                self._trace(
                    attempts,
                    url=target.url,
                    method=request.method,
                    status_code=None,
                    error_code=ERROR_SSRF_BLOCKED,
                    wire_bytes=None,
                    decoded_bytes=None,
                    ttfb_ms=None,
                    started=hop_started,
                )
                raise FetchError(
                    f"connection error: {type(exc).__name__}",
                    error_code=ERROR_SSRF_BLOCKED,
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
                    )
                    return self._finalize_no_body(
                        request, target, response, redirect_chain, started
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
                    )
                    raise FetchError(
                        "too many redirects",
                        error_code=ERROR_REDIRECT_LIMIT,
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
            )
            return result

        raise FetchError("too many redirects", error_code=ERROR_REDIRECT_LIMIT)

    async def _resolve(
        self,
        url: str,
        *,
        root_registrable_domain: str | None,
        include_globs: list[str] | None,
        exclude_globs: list[str] | None,
        enforce_scope: bool,
    ) -> ResolvedTarget:
        try:
            return await resolve_target(
                url,
                resolver=self._resolver,
                root_registrable_domain=root_registrable_domain,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                enforce_scope=enforce_scope,
            )
        except UrlPolicyError as exc:
            # Out-of-scope / disallowed scheme-port-userinfo on a redirect hop.
            raise FetchError(str(exc), error_code=ERROR_SSRF_BLOCKED) from exc

    def _finalize_no_body(
        self,
        request: FetchRequest,
        target: ResolvedTarget,
        response: httpx.Response,
        redirect_chain: list[RedirectHop],
        started: float,
    ) -> FetchResult:
        latency = int((time.monotonic() - started) * 1000)
        return FetchResult(
            requested_url=request.url,
            final_url=target.url,
            status_code=response.status_code,
            redacted_headers=redact_headers(response.headers),
            content_type=_content_type(response.headers),
            http_version=response.http_version or "",
            body=b"",
            wire_bytes=0,
            decoded_bytes=0,
            ttfb_ms=latency,
            latency_ms=latency,
            redirect_chain=tuple(redirect_chain),
            charset=_charset(response.headers),
        )

    async def _read_body(
        self,
        *,
        request: FetchRequest,
        target: ResolvedTarget,
        response: httpx.Response,
        redirect_chain: list[RedirectHop],
        started: float,
        max_wire: int,
        max_decoded: int,
    ) -> FetchResult:
        ttfb = int((time.monotonic() - started) * 1000)
        content_type = _content_type(response.headers)
        allowed = request.allowed_content_types
        # An empty status body (204/304) or HEAD carries no content-type; only
        # enforce the allowlist when one is set on the request. Error statuses
        # bypass the gate entirely (see ``_content_type_gate_applies``).
        if (
            allowed
            and content_type
            and content_type not in allowed
            and _content_type_gate_applies(response.status_code)
        ):
            await response.aclose()
            raise FetchError(
                f"unsupported content type: {content_type}",
                error_code=ERROR_UNSUPPORTED_CONTENT_TYPE,
                status_code=response.status_code,
            )

        decode, decompressor = _incremental_decoder(
            response.headers.get("content-encoding", "")
        )
        wire_total = 0
        decoded_total = 0
        decoded_chunks: list[bytes] = []
        try:
            async for raw in response.aiter_raw():
                wire_total += len(raw)
                if wire_total > max_wire:
                    raise FetchError(
                        "response exceeded wire byte cap",
                        error_code=ERROR_RESPONSE_TOO_LARGE,
                    )
                try:
                    out = decode(raw)
                except zlib.error as exc:
                    # Malformed gzip/deflate: never mix raw wire bytes into a
                    # partially-decoded body (that would silently corrupt
                    # ``FetchResult.body``). Fail the fetch instead.
                    raise FetchError(
                        "malformed compressed response body",
                        error_code=ERROR_MALFORMED_RESPONSE,
                    ) from exc
                if out:
                    decoded_total += len(out)
                    if decoded_total > max_decoded:
                        raise FetchError(
                            "response exceeded decoded byte cap (compression bomb)",
                            error_code=ERROR_RESPONSE_TOO_LARGE,
                        )
                    decoded_chunks.append(out)
            if decompressor is not None:
                # Flush any tail buffered inside the decompressor, then confirm
                # the stream actually ended. A truncated gzip/deflate body
                # (connection cut before the final block) yields fewer bytes
                # WITHOUT raising ``zlib.error`` and leaves ``eof`` False; if
                # we accepted it we would silently persist a partial page as if
                # it were complete. The flushed tail is still subject to the
                # decoded cap so a bomb cannot smuggle bytes past the loop.
                try:
                    tail = decompressor.flush()
                except zlib.error as exc:
                    raise FetchError(
                        "malformed compressed response body",
                        error_code=ERROR_MALFORMED_RESPONSE,
                    ) from exc
                if tail:
                    decoded_total += len(tail)
                    if decoded_total > max_decoded:
                        raise FetchError(
                            "response exceeded decoded byte cap (compression bomb)",
                            error_code=ERROR_RESPONSE_TOO_LARGE,
                        )
                    decoded_chunks.append(tail)
                if not decompressor.eof:
                    raise FetchError(
                        "truncated compressed response body",
                        error_code=ERROR_MALFORMED_RESPONSE,
                        retryable=True,
                    )
        except httpx.TimeoutException as exc:
            raise FetchError(
                "request timed out",
                error_code=ERROR_TIMEOUT,
                retryable=True,
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
            content_type=content_type,
            http_version=response.http_version or "",
            body=b"".join(decoded_chunks),
            wire_bytes=wire_total,
            decoded_bytes=decoded_total,
            ttfb_ms=ttfb,
            latency_ms=latency,
            redirect_chain=tuple(redirect_chain),
            charset=_charset(response.headers),
        )
