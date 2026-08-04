"""Security and response-shaping tests for the pinned curl transport."""

from __future__ import annotations

import pytest
from curl_cffi.requests.exceptions import RequestException
from curl_cffi.requests.headers import Headers

from app.connectors.web_evidence import curl_transport
from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    ResolvedTarget,
)

_PUBLIC_IP = "93.184.216.34"


def _target(
    *, url: str = "https://example.com/", host: str = "example.com"
) -> ResolvedTarget:
    return ResolvedTarget(
        url=url,
        scheme="https",
        host=host,
        port=443,
        connect_ip=_PUBLIC_IP,
        resolved_ips=(_PUBLIC_IP,),
    )


class _Response:
    def __init__(self, headers: Headers | None = None) -> None:
        self.headers = headers or Headers({"content-type": "text/html; charset=UTF-8"})
        self.primary_ip = _PUBLIC_IP
        self.download_size = 4
        self.status_code = 302
        self.http_version = "2"
        self.quit_now = None
        self.closed = False

    async def aiter_content(self):
        yield b"body"

    async def aclose(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, response: _Response | Exception) -> None:
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        return None

    async def request(self, *_args, **_kwargs):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


async def _fetch(monkeypatch, response: _Response | Exception, *, target=None):
    monkeypatch.setattr(
        curl_transport, "AsyncSession", lambda **_kwargs: _Session(response)
    )
    transport = curl_transport.CurlCffiTransport(impersonation_profile="chrome")
    return await transport.fetch(
        FetchRequest(url="https://example.com/", purpose="discover"),
        target or _target(),
        max_wire_bytes=1_000,
        max_decoded_bytes=1_000,
        timeout_seconds=5,
    )


@pytest.mark.asyncio
async def test_fetch_rejects_url_host_that_does_not_match_resolve_host(
    monkeypatch,
) -> None:
    response = _Response()
    target = _target(host="attacker.example")
    with pytest.raises(FetchError) as exc:
        await _fetch(monkeypatch, response, target=target)

    assert exc.value.error_code == "acquisition_unavailable"


@pytest.mark.asyncio
async def test_location_is_transient_and_not_added_to_persisted_headers(
    monkeypatch,
) -> None:
    response = _Response(
        Headers(
            [
                ("Content-Type", "text/html; charset=UTF-8"),
                ("Location", "/next"),
                ("Set-Cookie", "session=secret"),
            ]
        )
    )

    result = await _fetch(monkeypatch, response)

    assert result.redirect_location == "/next"
    assert result.content_type == "text/html"
    assert result.charset == "utf-8"
    assert "location" not in result.redacted_headers
    assert "set-cookie" not in result.redacted_headers
    assert response.closed is True


@pytest.mark.asyncio
async def test_repeated_location_header_fails_closed(monkeypatch) -> None:
    response = _Response(
        Headers(
            [
                ("Content-Type", "text/html"),
                ("Location", "/one"),
                ("location", "/two"),
            ]
        )
    )

    with pytest.raises(FetchError) as exc:
        await _fetch(monkeypatch, response)

    assert exc.value.error_code == "malformed_response"


@pytest.mark.asyncio
async def test_repeated_content_type_header_fails_closed(monkeypatch) -> None:
    response = _Response(
        Headers(
            [
                ("Content-Type", "text/html"),
                ("content-type", "application/json"),
            ]
        )
    )

    with pytest.raises(FetchError) as exc:
        await _fetch(monkeypatch, response)

    assert exc.value.error_code == "malformed_response"


@pytest.mark.asyncio
async def test_connection_failure_retains_safe_curl_error_code(monkeypatch) -> None:
    failure = RequestException("request URL omitted", code=7)
    with pytest.raises(FetchError) as exc:
        await _fetch(monkeypatch, failure)

    assert str(exc.value) == "curl acquisition connection failed"
    assert exc.value.transport_error_code == 7


@pytest.mark.asyncio
async def test_request_headers_override_defaults_case_insensitively(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    def session_factory(**kwargs):
        captured.update(kwargs["headers"])
        return _Session(_Response())

    monkeypatch.setattr(curl_transport, "AsyncSession", session_factory)
    transport = curl_transport.CurlCffiTransport(
        impersonation_profile="chrome", user_agent="CiteLadder default"
    )
    await transport.fetch(
        FetchRequest(
            url="https://example.com/",
            purpose="discover",
            headers={"User-Agent": "Workspace crawler"},
        ),
        _target(),
        max_wire_bytes=1_000,
        max_decoded_bytes=1_000,
        timeout_seconds=5,
    )

    assert captured["user-agent"] == "Workspace crawler"
    assert "User-Agent" not in captured
