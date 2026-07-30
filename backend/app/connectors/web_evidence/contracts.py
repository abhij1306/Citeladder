# Provider-neutral contracts for the secure web-evidence fetcher (Task 3).
#
# These are the transport-agnostic value types + protocols the Site Health
# crawler's URL policy, SSRF-safe fetcher, robots parser, and sitemap parser
# share. Everything here is immutable (frozen dataclasses) so a fetch result is
# safe to pass across the worker without accidental mutation, and there is NO
# raw HTML body field persisted anywhere downstream — only bounded decoded
# bytes handed to the parser in-process.
#
# The DNS resolver is a Protocol so the worker injects a real resolver in
# production and tests inject a fake one (no live internet — subplan test
# contract). The connection IP is pinned by the policy after validation so the
# fetcher connects to exactly the address that passed the SSRF checks while
# preserving the original Host header + TLS SNI.
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """A URL that passed canonicalization, scope, DNS, and SSRF validation.

    ``connect_ip`` is the single validated address the fetcher must dial; the
    original ``host``/``port`` are preserved so the request still sends the
    correct ``Host`` header and TLS SNI (DNS-rebinding protection: we never
    re-resolve the host at connect time).
    """

    url: str
    scheme: str
    host: str
    port: int
    connect_ip: str
    # Every resolved address that passed validation (diagnostic; connect_ip is
    # the one dialed). Empty when the resolver returned nothing.
    resolved_ips: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """One fetch to perform. ``purpose`` is a config FETCH_PURPOSE_* token."""

    url: str
    purpose: str
    method: str = "GET"
    # Extra request headers (merged over the fetcher's defaults). Never carries
    # credentials — the policy rejects userinfo before a request is built.
    headers: dict[str, str] = field(default_factory=dict)
    # Per-request overrides; None means "use the fetcher's configured value".
    max_wire_bytes: int | None = None
    max_decoded_bytes: int | None = None
    timeout_seconds: float | None = None
    max_redirects: int | None = None
    # Content types this request accepts; empty means the fetcher's default
    # allowlist for the purpose.
    allowed_content_types: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class RedirectHop:
    """One re-validated redirect hop (URLs only — never credentials)."""

    from_url: str
    to_url: str
    status_code: int


@dataclass(frozen=True, slots=True)
class FetchCallTrace:
    """One REAL network call made while serving a single ``SecureFetcher.fetch``.

    The per-network-call trace (T7): the fetch makes one network call per
    redirect hop, and EVERY such call appends exactly one entry — including
    blocked, failed, and cap-aborted calls — so a persistence layer (T8) can
    write one ``SiteFetchAttempt`` row per actual HTTP attempt (its documented
    append-only contract, invariant 3) without any call vanishing.

    Order/uniqueness key: ``(task_id, attempt_number, request_ordinal)``.
    ``attempt_number`` stays the QUEUE-attempt number owned by the worker;
    ``request_ordinal`` is the deterministic per-call ordinal assigned here,
    0-based across the whole ``fetch()`` call. When the fetch returns a
    result, the entry describing that result is always the LAST one.
    """

    request_ordinal: int
    url: str
    method: str
    # None when the call failed before any response was received.
    status_code: int | None
    # A config ``SITE_FETCH_ERROR_TOKENS`` value when the call itself failed
    # (timeout / cap abort / transport error); None when an HTTP response was
    # received — even a 4xx, since status classification is the caller's job.
    error_code: str | None
    # None = body deliberately unread (redirect hop) or counters unavailable.
    wire_bytes: int | None
    decoded_bytes: int | None
    ttfb_ms: int | None
    latency_ms: int | None


@dataclass(frozen=True, slots=True)
class FetchResult:
    """The bounded, redacted outcome of one successful fetch.

    ``body`` holds the decoded bytes (already capped) for in-process parsing;
    it is never persisted as-is. ``redacted_headers`` contains only the config
    allowlist. ``redirect_chain`` records every re-validated hop.
    """

    requested_url: str
    final_url: str
    status_code: int
    redacted_headers: dict[str, str]
    content_type: str
    http_version: str
    body: bytes
    wire_bytes: int
    decoded_bytes: int
    ttfb_ms: int | None
    latency_ms: int | None
    redirect_chain: tuple[RedirectHop, ...] = ()
    charset: str = ""
    # Per-network-call trace (T7): one entry per REAL network call made while
    # serving this fetch, in call order (see ``FetchCallTrace``). ``FetchError``
    # carries the same tuple so the trace survives failure; persisting it is
    # T8's job. Empty only for results built directly by tests/callers.
    attempts: tuple[FetchCallTrace, ...] = ()


class FetchError(Exception):
    """A classified fetch failure carrying a safe error token.

    ``error_code`` is one of the config ``SITE_FETCH_ERROR_TOKENS`` (e.g.
    ``ssrf_blocked``, ``redirect_limit``, ``response_too_large``, ``timeout``).
    The message is safe for logs/diagnostics: it never contains a raw body or a
    sensitive header. ``status_code``/``retry_after_seconds`` are populated when
    known (HTTP errors).
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        status_code: int | None = None,
        retry_after_seconds: float | None = None,
        retryable: bool = False,
        attempts: tuple[FetchCallTrace, ...] = (),
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        self.retryable = retryable
        # The same per-network-call trace ``FetchResult`` carries, so a
        # failed fetch (both rungs blocked, transport failure, cap abort)
        # does not lose the record of the calls it made (T7).
        self.attempts = attempts


@runtime_checkable
class DnsResolver(Protocol):
    """Async host -> IP resolver. Injected so tests never hit the network."""

    async def resolve(self, host: str, port: int) -> list[str]:
        """Return the resolved IP address strings for ``host``.

        May return IPv4 and/or IPv6 literals. An empty list (or a raised
        exception) means resolution failed; the policy treats that as
        ``dns_resolution_failed``.
        """
        ...
