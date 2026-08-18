"""Opt-in LIVE acceptance for acquisition rung 3 (bundled Patchright browser).

Skipped unless ``CITELADDER_LIVE_BROWSER_RUNG=1``. These tests make REAL network
calls and launch a REAL Chromium, because the properties they assert cannot be
observed any other way:

- the validated-IP pin is a Chromium LAUNCH argument, so only a live browser
  proves that a second host does not resolve;
- the route guard is enforced by the browser's network stack, so only a live
  page proves that an off-host ``fetch()`` is aborted;
- the reason rung 3 exists — recovering content that is not in the served
  HTML — is only observable against a page that really renders client-side.

Everything under ``tests/unit`` stubs the driver, which is why the ladder shipped
with a shell-detection gap that no stub could surface: the trigger measured the
whole response, and a real JS shell's response is not small.

Run:  CITELADDER_LIVE_BROWSER_RUNG=1 uv run pytest tests/live -q
"""

from __future__ import annotations

import os

import httpx
import pytest

from app.connectors.web_evidence.browser_transport import (
    PatchrightTransport,
    _host_resolver_rule,
)
from app.connectors.web_evidence.contracts import FetchError, FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.core.config.site_health_rules import (
    HTML_CONTENT_TYPES,
)

from app.core.config.site_health_runtime import (
    site_health_settings,
)

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CITELADDER_LIVE_BROWSER_RUNG") != "1",
        reason="live browser-rung acceptance is opt-in "
        "(CITELADDER_LIVE_BROWSER_RUNG=1)",
    ),
    pytest.mark.usefixtures("shell_fixture_is_reachable"),
]

# A long-standing public scraping-practice site. ``/js/`` builds its quote list
# client-side from a JavaScript array, so the served HTML contains none of it;
# ``/`` serves the same content rendered. One host, two acquisition outcomes.
JS_SHELL_URL = "https://quotes.toscrape.com/js/"
SERVER_RENDERED_URL = "https://quotes.toscrape.com/"
_OFF_HOST_URL = "https://example.com/"


@pytest.fixture(scope="session")
def shell_fixture_is_reachable() -> None:
    """Skip rather than FAIL when the public fixture site is unavailable.

    Every assertion below is about OUR transport. If the third-party site is
    down, rate-limiting, or has changed its markup, a red suite would report a
    defect in code that did not change — so the precondition is checked once and
    the suite skips with the real reason.
    """
    try:
        response = httpx.get(JS_SHELL_URL, timeout=20.0, follow_redirects=True)
    except httpx.HTTPError as exc:
        pytest.skip(f"live fixture host unreachable: {exc}")
    if response.status_code != 200:
        pytest.skip(f"live fixture returned {response.status_code}")
    # The served shell must NOT already contain the rendered quotes, or the
    # test that rendering recovers them would pass without rendering anything.
    if 'class="quote"' in response.text:
        pytest.skip("live fixture is no longer a client-rendered shell")


def _settings(**overrides):
    return site_health_settings.model_copy(
        update={"browser_enabled": True, "curl_cffi_enabled": False, **overrides}
    )


def _request(url: str) -> FetchRequest:
    return FetchRequest(
        url=url, purpose="analyze", allowed_content_types=HTML_CONTENT_TYPES
    )


async def _resolve(url: str, settings):
    """Resolve through the shipped SSRF-safe resolver, exactly as a crawl does."""
    async with SecureFetcher(resolver=SystemDnsResolver(), settings=settings) as f:
        return await f._resolve(
            url,
            root_registrable_domain=None,
            include_globs=None,
            exclude_globs=None,
            enforce_scope=False,
            purpose="analyze",
        )


async def test_launch_rule_pins_the_validated_address_and_blackholes_the_rest():
    target = await _resolve(JS_SHELL_URL, _settings())
    rule = _host_resolver_rule(target)

    assert f"MAP {target.host} {target.connect_ip}" in rule
    assert rule.endswith("MAP * ~NOTFOUND")


async def test_pinned_browser_cannot_resolve_any_other_host():
    """The DNS pin in isolation — no route guard, so only the pin can block."""
    settings = _settings()
    target = await _resolve(JS_SHELL_URL, settings)
    transport = PatchrightTransport(settings=settings)
    try:
        context = await transport._pool.new_context(target=target)
        page = await context.new_page()
        with pytest.raises(Exception, match="ERR_NAME_NOT_RESOLVED"):
            await page.goto(_OFF_HOST_URL, timeout=15_000)
        await context.close()
    finally:
        await transport.aclose()


async def test_off_host_request_from_a_live_page_is_aborted():
    """The PRODUCTION route guard, installed exactly as ``fetch`` installs it.

    Uses ``PatchrightTransport.route_handler`` rather than a local copy: a
    duplicated handler in a test proves only that the duplicate works.
    """
    settings = _settings()
    target = await _resolve(JS_SHELL_URL, settings)
    transport = PatchrightTransport(settings=settings)
    intercepted: list[str] = []
    try:
        context = await transport._pool.new_context(target=target)
        page = await context.new_page()
        guard = PatchrightTransport.route_handler(target)

        async def _route(route, request):
            intercepted.append(request.url)
            await guard(route, request)

        await page.route("**/*", _route)
        await page.goto(target.url, timeout=30_000, wait_until="domcontentloaded")
        outcome = await page.evaluate(
            """async url => {
                try {
                    const r = await fetch(url, {mode: 'no-cors'});
                    return 'reached:' + r.type;
                } catch (e) { return 'blocked:' + e.name; }
            }""",
            _OFF_HOST_URL,
        )

        assert str(outcome).startswith("blocked"), outcome
        assert any(url.startswith(_OFF_HOST_URL) for url in intercepted)
        await context.close()
    finally:
        await transport.aclose()


async def test_rendering_recovers_content_absent_from_the_served_html():
    settings = _settings()
    target = await _resolve(JS_SHELL_URL, settings)
    transport = PatchrightTransport(settings=settings)
    try:
        result = await transport.fetch(
            _request(JS_SHELL_URL),
            target,
            max_wire_bytes=settings.max_response_wire_bytes,
            max_decoded_bytes=settings.max_response_decoded_bytes,
            timeout_seconds=30.0,
        )
    finally:
        await transport.aclose()

    assert result.status_code == 200
    # Built client-side from a JS array; the served document has none of these.
    assert result.body.decode("utf-8", "replace").count('class="quote"') >= 5


async def test_oversized_render_is_refused_not_silently_truncated():
    settings = _settings()
    target = await _resolve(JS_SHELL_URL, settings)
    transport = PatchrightTransport(settings=settings)
    try:
        with pytest.raises(FetchError) as excinfo:
            await transport.fetch(
                _request(JS_SHELL_URL),
                target,
                max_wire_bytes=settings.max_response_wire_bytes,
                max_decoded_bytes=2048,
                timeout_seconds=30.0,
            )
    finally:
        await transport.aclose()

    assert excinfo.value.error_code == "response_too_large"


async def test_full_ladder_escalates_a_real_js_shell_to_the_browser():
    """The regression this slice fixed: a real shell must actually reach rung 3."""
    async with SecureFetcher(
        resolver=SystemDnsResolver(), settings=_settings()
    ) as fetcher:
        result = await fetcher.fetch(
            _request(JS_SHELL_URL),
            root_registrable_domain=None,
            enforce_scope=False,
        )

    rungs = [a.acquisition.rung for a in result.attempts if a.acquisition]
    assert rungs == [1, 3], rungs
    assert result.acquisition is not None
    assert result.acquisition.rung == 3
    assert result.acquisition.transport == "patchright"
    assert result.acquisition.trigger == "js_shell"
    assert result.body.decode("utf-8", "replace").count('class="quote"') >= 5


async def test_server_rendered_page_never_pays_for_a_render():
    async with SecureFetcher(
        resolver=SystemDnsResolver(), settings=_settings()
    ) as fetcher:
        result = await fetcher.fetch(
            _request(SERVER_RENDERED_URL),
            root_registrable_domain=None,
            enforce_scope=False,
        )

    assert [a.acquisition.rung for a in result.attempts if a.acquisition] == [1]
