"""Bundled headless-browser acquisition transport (rung 3 of the ladder).

The last rung. It renders a page locally with Patchright when server-rendered
evidence stays unusable — a JS shell, a challenge interstitial, or a response
too thin to analyze. There is deliberately no paid acquisition vendor and no
real-Chrome escalation anywhere in this module.

Ported from internal CrawlerAI (source commit
``bfc7663660285a70c88181c18005137d5f738d57``) as a MINIMAL generic observation
capability only:

| CrawlerAI source              | Ported here                                |
|-------------------------------|--------------------------------------------|
| ``browser_pool.py``           | ``_BrowserPool`` launch/context lifecycle   |
| ``browser_readiness.py``      | ``_wait_for_readiness`` DOM-settle wait     |
| ``browser_capture.py``        | ``_CaptureBuffer`` bounded same-site JSON   |
| ``browser_block_detection.py``| challenge diagnostics via the shared config |

Its extraction API, persistence, Celery/Redis wiring, UI, semantic extraction,
and real-Chrome code are deliberately NOT ported. Raw HTML and captured network
payloads stay worker-memory inputs: this returns a bounded ``FetchResult`` and
nothing here reaches PostgreSQL except normalized facts and hashes.

``SecureFetcher`` still owns canonicalization, scope, admission, and DNS
pinning. The transport receives a target that already passed every check and
must not navigate anywhere else — enforced by ``_validate_resolved_target`` and
by aborting any main-frame navigation that leaves the validated authority.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from types import ModuleType
from typing import Any
from urllib.parse import urlsplit

from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    FetchResult,
    ResolvedTarget,
)
from app.connectors.web_evidence.targets import validate_resolved_target
from app.core.config.site_health import (
    ERROR_ACQUISITION_UNAVAILABLE,
    ERROR_CONNECTION_FAILED,
    ERROR_RESPONSE_TOO_LARGE,
    ERROR_TIMEOUT,
    PERSISTED_RESPONSE_HEADERS,
    SITE_HEALTH_USER_AGENT,
    site_health_settings,
)

# Resource kinds that never contribute to analyzable evidence. Blocking them is
# a latency and politeness measure, not a stealth one: a crawl that renders a
# page does not need its fonts, images, or media.
_BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
_JSON_CONTENT_TYPES = ("application/json", "+json")


def _load_patchright() -> ModuleType:
    """Import Patchright, or fail closed with the standard unavailable token."""

    try:
        from patchright import async_api
    # An absent/incompatible optional dependency must not crash a crawl: the
    # caller treats an unavailable last rung as "keep the prior evidence".
    except Exception as exc:  # noqa: BLE001
        raise FetchError(
            "browser acquisition transport unavailable",
            error_code=ERROR_ACQUISITION_UNAVAILABLE,
        ) from exc
    return async_api


def _redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    """Keep only the config allowlist, matched case-insensitively."""

    lowered = {str(key).casefold(): str(value) for key, value in headers.items()}
    return {
        key: value
        for key in sorted(PERSISTED_RESPONSE_HEADERS)
        if (value := lowered.get(key.casefold(), ""))
    }


def _content_type(headers: dict[str, str]) -> str:
    for key, value in headers.items():
        if str(key).casefold() == "content-type":
            return str(value).split(";", 1)[0].strip().lower()
    return ""


def _content_length(headers) -> int | None:
    """The declared body size, or ``None`` when absent/unparseable."""

    try:
        return int(str(headers.get("content-length", "")).strip())
    except (AttributeError, TypeError, ValueError):
        return None


def _timeout_error_type() -> type[BaseException]:
    """Patchright's navigation-timeout class, or a never-matching fallback.

    Classifying on the exception TYPE rather than a message substring keeps a
    timeout distinguishable from a connection failure even when the driver
    changes its wording or runs in another locale.
    """

    try:
        return _load_patchright().TimeoutError
    # With no driver present nothing can raise its timeout: fall back to a
    # class that never matches so the general handler stays in charge.
    except Exception:  # noqa: BLE001
        return _NeverRaised


class _NeverRaised(Exception):
    """Sentinel exception type that is never raised."""


def _same_site(url: str, host: str) -> bool:
    try:
        candidate = (urlsplit(url).hostname or "").casefold().rstrip(".")
    except ValueError:
        return False
    return bool(candidate) and candidate == host.casefold().rstrip(".")


class _CaptureBuffer:
    """Bounded same-site JSON/XHR capture with redaction.

    A rendered page often carries its real content in an XHR payload rather
    than the served HTML. Recording a bounded, same-site, JSON-only slice of
    that traffic makes the evidence explainable without turning the crawler
    into a general traffic recorder: cross-origin responses, non-JSON bodies,
    and anything past the configured caps are dropped, and only URL + status +
    size are retained — never the payload itself, never a request header.
    """

    def __init__(
        self,
        *,
        host: str,
        max_responses: int,
        max_bytes: int,
        max_wire_bytes: int,
    ) -> None:
        self._host = host
        self._max_responses = max_responses
        self._max_bytes = max_bytes
        self._max_wire_bytes = max_wire_bytes
        self._total_bytes = 0
        self._tasks: set[asyncio.Task] = set()
        self.records: list[dict[str, str | int]] = []

    @property
    def full(self) -> bool:
        return (
            len(self.records) >= self._max_responses
            or self._total_bytes >= self._max_bytes
        )

    def schedule(self, response) -> None:
        """Observe a response without blocking Patchright's event dispatch.

        The task handle is retained so ``drain`` can settle it before the
        context closes; an unreferenced task can also be garbage-collected
        mid-flight, which silently drops captures.
        """

        if self.full:
            return
        task = asyncio.ensure_future(self.observe(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Settle every in-flight capture before the context is torn down."""

        pending = list(self._tasks)
        if not pending:
            return
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    async def observe(self, response) -> None:
        """Record one bounded same-site JSON response descriptor."""

        if self.full or not _same_site(response.url, self._host):
            return
        headers = response.headers
        content_type = str(headers.get("content-type", "")).lower()
        if not any(token in content_type for token in _JSON_CONTENT_TYPES):
            return
        # Check the declared size BEFORE reading: reading first would already
        # have pulled an oversized payload into this process, which is exactly
        # what the wire cap exists to prevent.
        declared = _content_length(headers)
        if declared is not None and declared > self._max_wire_bytes:
            return
        try:
            body = await response.body()
        # A body can be gone by the time it is read (navigation, abort), and a
        # drain cancels in-flight reads. Neither is worth failing a fetch over.
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            return
        size = len(body or b"")
        if size > self._max_wire_bytes or self._total_bytes + size > self._max_bytes:
            return
        self._total_bytes += size
        self.records.append(
            {
                "url": str(response.url)[:2048],
                "status": int(response.status),
                "bytes": size,
            }
        )


def _host_resolver_rule(target: ResolvedTarget) -> str:
    """Chromium host-resolver rule pinning the one validated address.

    The browser must connect to exactly the address ``resolve_target``
    validated, while still sending the original Host header and TLS SNI — the
    same DNS-rebinding protection the HTTP rungs get by pinning the socket.
    ``MAP <host> <ip>`` pins the target. Everything else maps to ``~NOTFOUND``
    so NO other name resolves through this browser at all — not loopback, not
    link-local, not an internal hostname. Without that catch-all rule a page
    could still reach any address by naming it, which is precisely the SSRF
    surface the HTTP rungs close by pinning their socket.
    """

    address = (
        f"[{target.connect_ip}]" if ":" in target.connect_ip else target.connect_ip
    )
    return f"MAP {target.host} {address},MAP * ~NOTFOUND"


async def _close_quietly(browser) -> None:
    """Close a browser without letting a dead process break the caller."""

    try:
        await browser.close()
    except Exception:  # noqa: BLE001
        pass


class _BrowserPool:
    """One launched browser per pinned address, with a fresh context per fetch.

    Chromium takes ``--host-resolver-rules`` only as a LAUNCH argument, so the
    validated-IP pin is a property of the browser process, not of a context.
    That makes the pin the pool's cache key: a target resolving to a different
    address gets its own browser rather than silently reusing one pinned
    elsewhere, which would let the second target dial an address it never
    validated. Contexts stay per-fetch so cookies and storage never leak
    between crawled pages.
    """

    def __init__(self, *, settings, user_agent: str) -> None:
        self._settings = settings
        self._user_agent = user_agent
        # Typed loosely: the driver is an optional dependency, so this module
        # must import and type-check without Patchright installed.
        self._playwright: Any = None
        # Insertion-ordered, so the first key is the least recently used once
        # every hit moves its key to the end.
        self._browsers: OrderedDict[str, Any] = OrderedDict()
        self._lock = asyncio.Lock()

    def _launch_args(self, rule: str) -> list[str]:
        args = ["--disable-dev-shm-usage", f"--host-resolver-rules={rule}"]
        # Chromium's sandbox is a real containment boundary around code fetched
        # from crawled sites, so it is NOT disabled by default. Platforms that
        # genuinely cannot provide the required kernel capability opt in
        # explicitly rather than every deployment silently running unsandboxed.
        if self._settings.browser_disable_sandbox:
            args.append("--no-sandbox")
        return args

    async def _browser_for(self, rule: str):
        async with self._lock:
            existing = self._browsers.get(rule)
            if existing is not None:
                self._browsers.move_to_end(rule)
                return existing
            api = _load_patchright()
            try:
                if self._playwright is None:
                    self._playwright = await api.async_playwright().start()
                browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=self._launch_args(rule),
                )
            except FetchError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise FetchError(
                    "browser acquisition could not launch",
                    error_code=ERROR_ACQUISITION_UNAVAILABLE,
                ) from exc
            # Each entry is a live browser PROCESS, so an unbounded pool leaks
            # one per distinct resolved address across a multi-host crawl.
            # Evict the least recently used before storing the new one.
            while (
                self._browsers
                and len(self._browsers) >= self._settings.browser_pool_max_browsers
            ):
                _evicted_rule, evicted = self._browsers.popitem(last=False)
                await _close_quietly(evicted)
            self._browsers[rule] = browser
            return browser

    async def new_context(self, *, target: ResolvedTarget):
        """A fresh context on a browser pinned to this target's address."""

        browser = await self._browser_for(_host_resolver_rule(target))
        return await browser.new_context(
            user_agent=self._user_agent,
            ignore_https_errors=False,
            service_workers="block",
        )

    async def aclose(self) -> None:
        async with self._lock:
            browsers = list(self._browsers.values())
            playwright, self._playwright = self._playwright, None
            self._browsers.clear()
            for browser in browsers:
                await _close_quietly(browser)
            if playwright is not None:
                try:
                    await playwright.stop()
                # Shutdown is best-effort: a driver that already died must not
                # mask an error or block the fetcher's close path.
                except Exception:  # noqa: BLE001
                    pass


class PatchrightTransport:
    """Render one admitted target locally and return bounded evidence."""

    def __init__(
        self,
        *,
        settings=site_health_settings,
        user_agent: str = SITE_HEALTH_USER_AGENT,
    ) -> None:
        self._settings = settings
        self._user_agent = user_agent
        self._pool = _BrowserPool(settings=settings, user_agent=user_agent)

    async def aclose(self) -> None:
        await self._pool.aclose()

    async def fetch(
        self,
        request: FetchRequest,
        target: ResolvedTarget,
        *,
        max_wire_bytes: int,
        max_decoded_bytes: int,
        timeout_seconds: float,
    ) -> FetchResult:
        """Navigate, wait for readiness, and return the rendered document."""

        validate_resolved_target(target)
        started = time.monotonic()
        host = target.host.casefold().rstrip(".")
        capture = _CaptureBuffer(
            host=host,
            max_responses=self._settings.browser_max_captured_responses,
            max_bytes=self._settings.browser_max_captured_bytes,
            max_wire_bytes=max_wire_bytes,
        )

        context = await self._pool.new_context(target=target)
        try:
            page = await context.new_page()
            await self._guard_requests(page, host=host, capture=capture)
            # Navigation gets the tighter of the caller's budget and the
            # configured navigation ceiling: a generous per-request timeout
            # must not let one render hold a crawl slot indefinitely.
            navigation_budget = min(
                timeout_seconds, self._settings.browser_navigation_timeout_seconds
            )
            response = await self._navigate(page, target, navigation_budget)
            # Readiness shares the caller's deadline rather than extending it:
            # navigation + readiness must not exceed the budget the fetcher
            # allotted this rung, or a slow page silently doubles the timeout.
            elapsed = time.monotonic() - started
            await self._wait_for_readiness(page, remaining=timeout_seconds - elapsed)
            body = await self._rendered_body(page, max_decoded_bytes)
            headers = dict(response.headers) if response is not None else {}
            status = int(response.status) if response is not None else 200
            final_url = str(page.url or target.url)
            latency_ms = int((time.monotonic() - started) * 1000)
            return FetchResult(
                requested_url=request.url,
                final_url=final_url,
                status_code=status,
                redacted_headers=_redacted_headers(headers),
                content_type=_content_type(headers) or "text/html",
                http_version="",
                body=body,
                wire_bytes=len(body),
                decoded_bytes=len(body),
                ttfb_ms=None,
                latency_ms=latency_ms,
                charset="utf-8",
            )
        finally:
            # Settle capture tasks BEFORE closing the context: a pending
            # ``response.body()`` against a closing context raises into a
            # detached task and logs a spurious "task exception was never
            # retrieved". The context owns the page, the listeners, and its
            # share of browser memory, so closing it is what keeps a long
            # crawl bounded.
            await capture.drain()
            try:
                await context.close()
            except Exception:  # noqa: BLE001
                pass

    async def _rendered_body(self, page, max_decoded_bytes: int) -> bytes:
        """Serialize the rendered DOM, bounded in the page before transfer.

        The cap is applied by the browser (``+1`` byte so an exactly-at-cap
        document is distinguishable from an oversized one) rather than after
        materializing the whole document in this process, so a hostile page
        cannot force an unbounded string across the CDP boundary first.
        """

        try:
            html = await page.evaluate(
                "limit => document.documentElement.outerHTML.slice(0, limit)",
                max_decoded_bytes + 1,
            )
        # A page that cannot be serialized (navigated away, closed) has no
        # rendered evidence to offer.
        except Exception as exc:  # noqa: BLE001
            raise FetchError(
                "rendered document could not be read",
                error_code=ERROR_CONNECTION_FAILED,
                retryable=True,
            ) from exc
        body = str(html or "").encode("utf-8", errors="replace")
        if len(body) > max_decoded_bytes:
            raise FetchError(
                "rendered document exceeded the decoded cap",
                error_code=ERROR_RESPONSE_TOO_LARGE,
            )
        return body

    async def _guard_requests(self, page, *, host: str, capture: _CaptureBuffer):
        """Confine every request to the validated host and record JSON traffic.

        The fetcher validated exactly ONE authority. Guarding only main-frame
        navigation would still let subresources, XHR, and iframes reach any
        host the page names — addresses that never passed admission or the SSRF
        checks. So every request whose host is not the validated one is
        aborted, whatever its resource type.
        """

        async def _route(route, request):
            try:
                if request.resource_type in _BLOCKED_RESOURCE_TYPES:
                    await route.abort()
                    return
                if not _same_site(request.url, host):
                    await route.abort()
                    return
                await route.continue_()
            # A route can be resolved by the browser before we answer it; that
            # is not an acquisition failure.
            except Exception:  # noqa: BLE001
                pass

        await page.route("**/*", _route)
        page.on("response", capture.schedule)

    async def _navigate(self, page, target: ResolvedTarget, timeout_seconds: float):
        timeout_error = _timeout_error_type()
        try:
            return await page.goto(
                target.url,
                timeout=timeout_seconds * 1000,
                wait_until="domcontentloaded",
            )
        except timeout_error as exc:
            raise FetchError(
                "browser navigation timed out",
                error_code=ERROR_TIMEOUT,
                retryable=True,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise FetchError(
                "browser navigation failed",
                error_code=ERROR_CONNECTION_FAILED,
                retryable=True,
            ) from exc

    async def _wait_for_readiness(self, page, *, remaining: float) -> None:
        """Give client-rendered content a bounded chance to appear.

        ``domcontentloaded`` fires before a JS shell has rendered anything, so
        rendering without this wait routinely captures the same empty shell the
        HTTP rungs already saw. Waiting for the network to settle is bounded by
        whatever is LEFT of the caller's deadline and is best-effort: a page
        that never goes idle still yields whatever it rendered by then, which
        is strictly better evidence than the shell.
        """

        budget = min(self._settings.browser_readiness_timeout_seconds, remaining)
        if budget <= 0:
            return
        try:
            await page.wait_for_load_state("networkidle", timeout=budget * 1000)
        # A busy page (polling, websockets, ads) never reaches networkidle.
        # That is an expected outcome, not an acquisition failure.
        except Exception:  # noqa: BLE001
            pass
