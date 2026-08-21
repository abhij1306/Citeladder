"""Offline contracts for the sole SSRF-pinned curl acquisition path."""

from __future__ import annotations

from collections.abc import Iterable

import pytest

from app.connectors.web_evidence.contracts import (
    AcquisitionTransport,
    FetchError,
    FetchRequest,
    FetchResult,
    ResolvedTarget,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.fetcher_body import is_bot_block_result
from app.core.config.site_health_acquisition import FETCH_PURPOSE_ANALYZE

_PUBLIC_IP = "93.184.216.34"


class _FakeResolver:
    def __init__(self, mapping: dict[str, list[str]] | None = None) -> None:
        self._mapping = mapping or {}

    async def resolve(self, host: str, port: int) -> list[str]:
        del port
        return list(self._mapping.get(host, [_PUBLIC_IP]))


class _SequenceTransport(AcquisitionTransport):
    def __init__(self, outcomes: Iterable[FetchResult | FetchError]) -> None:
        self._outcomes = iter(outcomes)
        self.requests: list[FetchRequest] = []
        self.targets: list[ResolvedTarget] = []
        self.closed = False

    async def fetch(
        self,
        request: FetchRequest,
        target: ResolvedTarget,
        *,
        max_wire_bytes: int,
        max_decoded_bytes: int,
        timeout_seconds: float,
    ) -> FetchResult:
        assert max_wire_bytes > 0
        assert max_decoded_bytes > 0
        assert timeout_seconds > 0
        self.requests.append(request)
        self.targets.append(target)
        outcome = next(self._outcomes)
        if isinstance(outcome, FetchError):
            raise outcome
        return outcome

    async def aclose(self) -> None:
        self.closed = True


def _result(
    *,
    url: str = "https://example.com/",
    status: int = 200,
    body: bytes = b"<html><main><h1>Page</h1></main></html>",
    location: str = "",
) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status_code=status,
        redacted_headers={"content-type": "text/html"},
        content_type="text/html",
        http_version="2",
        body=body,
        wire_bytes=len(body),
        decoded_bytes=len(body),
        ttfb_ms=1,
        latency_ms=2,
        redirect_location=location,
    )


def _request(url: str = "https://example.com/") -> FetchRequest:
    return FetchRequest(url=url, purpose=FETCH_PURPOSE_ANALYZE)


@pytest.mark.asyncio
async def test_fetch_uses_only_curl_provenance_and_one_trace() -> None:
    transport = _SequenceTransport([_result()])
    async with SecureFetcher(resolver=_FakeResolver(), transport=transport) as fetcher:
        result = await fetcher.fetch(_request())

    assert result.status_code == 200
    assert result.acquisition is not None
    assert result.acquisition.transport == "curl_cffi"
    assert result.acquisition.rung == 1
    assert result.acquisition.trigger == "initial"
    assert len(result.attempts) == 1
    assert result.attempts[0].acquisition == result.acquisition
    assert transport.closed is False  # caller owns injected transports


@pytest.mark.asyncio
async def test_redirects_are_resolved_and_traced_per_network_call() -> None:
    transport = _SequenceTransport(
        [
            _result(status=302, location="/final"),
            _result(url="https://example.com/final", body=b"final"),
        ]
    )
    fetcher = SecureFetcher(resolver=_FakeResolver(), transport=transport)

    result = await fetcher.fetch(_request())

    assert [target.url for target in transport.targets] == [
        "https://example.com/",
        "https://example.com/final",
    ]
    assert result.final_url == "https://example.com/final"
    assert len(result.redirect_chain) == 1
    assert [attempt.status_code for attempt in result.attempts] == [302, 200]


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_blocked_before_second_call() -> None:
    transport = _SequenceTransport(
        [_result(status=302, location="https://internal.example/secret")]
    )
    fetcher = SecureFetcher(
        resolver=_FakeResolver({"internal.example": ["10.0.0.5"]}),
        transport=transport,
    )
    request = _request()

    with pytest.raises(FetchError, match="private|blocked") as excinfo:
        await fetcher.fetch(request)

    assert excinfo.value.error_code == "ssrf_blocked"
    assert len(transport.targets) == 1


@pytest.mark.asyncio
async def test_redirect_scope_is_revalidated() -> None:
    transport = _SequenceTransport(
        [_result(status=302, location="https://other.example/final")]
    )
    fetcher = SecureFetcher(resolver=_FakeResolver(), transport=transport)
    request = _request()

    with pytest.raises(FetchError) as excinfo:
        await fetcher.fetch(
            request,
            root_registrable_domain="example.com",
            enforce_scope=True,
        )

    assert excinfo.value.error_code == "ssrf_blocked"
    assert len(transport.targets) == 1


@pytest.mark.asyncio
async def test_redirect_limit_keeps_the_last_call_in_failure_trace() -> None:
    transport = _SequenceTransport(
        [
            _result(status=302, location="/second"),
            _result(url="https://example.com/second", status=302, location="/third"),
        ]
    )
    fetcher = SecureFetcher(resolver=_FakeResolver(), transport=transport)
    request = FetchRequest(
        url="https://example.com/",
        purpose=FETCH_PURPOSE_ANALYZE,
        max_redirects=1,
    )

    with pytest.raises(FetchError) as excinfo:
        await fetcher.fetch(request)

    assert excinfo.value.error_code == "redirect_limit"
    assert [attempt.error_code for attempt in excinfo.value.attempts] == [
        None,
        "redirect_limit",
    ]


@pytest.mark.asyncio
async def test_hard_excluded_url_never_reaches_transport() -> None:
    transport = _SequenceTransport([])
    fetcher = SecureFetcher(resolver=_FakeResolver(), transport=transport)
    request = _request("https://example.com/image.png")

    with pytest.raises(FetchError) as excinfo:
        await fetcher.fetch(request)

    assert excinfo.value.error_code == "url_admission_rejected"
    assert transport.targets == []


@pytest.mark.asyncio
async def test_transport_failure_carries_curl_trace() -> None:
    transport = _SequenceTransport(
        [FetchError("timed out", error_code="timeout", retryable=True)]
    )
    fetcher = SecureFetcher(resolver=_FakeResolver(), transport=transport)
    request = _request()

    with pytest.raises(FetchError) as excinfo:
        await fetcher.fetch(request)

    assert excinfo.value.retryable is True
    assert len(excinfo.value.attempts) == 1
    attempt = excinfo.value.attempts[0]
    assert attempt.error_code == "timeout"
    assert attempt.acquisition is not None
    assert attempt.acquisition.transport == "curl_cffi"


def test_challenge_script_appended_to_real_document_is_not_a_bot_block() -> None:
    body = (
        b"<html><main><article><h1>Privacy Policy</h1><p>Real content.</p>"
        b"</article></main><script src='/cdn-cgi/challenge-platform/x.js'>"
        b"</script></html>"
    )
    assert is_bot_block_result(_result(body=body)) is False


def test_challenge_interstitial_is_a_bot_block() -> None:
    result = _result(
        body=b"<html><title>Just a moment...</title><div>cf-chl</div></html>"
    )
    assert is_bot_block_result(result) is True
