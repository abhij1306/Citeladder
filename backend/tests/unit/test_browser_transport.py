"""Focused regression tests for bounded Patchright acquisition."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.connectors.web_evidence.browser_transport import PatchrightTransport
from app.connectors.web_evidence.contracts import (
    FetchError,
    FetchRequest,
    ResolvedTarget,
)
from app.core.config.site_health_acquisition import (
    ERROR_RESPONSE_TOO_LARGE,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)


class _Session:
    def __init__(self) -> None:
        self.listener = None

    async def send(self, _method: str) -> None:
        return None

    def on(self, _event: str, listener) -> None:
        self.listener = listener

    def emit(self, amount: int) -> None:
        assert self.listener is not None
        self.listener({"encodedDataLength": amount, "dataLength": amount})


class _Page:
    url = "https://example.com/"

    def __init__(self, session: _Session) -> None:
        self.session = session
        self.queued_amount = 0

    async def route(self, _pattern: str, _handler) -> None:
        return None

    async def evaluate(self, _script: str, _limit: int) -> dict[str, object]:
        if self.queued_amount:
            asyncio.get_running_loop().call_soon(self.session.emit, self.queued_amount)
        return {"size": 15, "html": "<html></html>"}


class _Context:
    def __init__(self) -> None:
        self.session = _Session()
        self.page = _Page(self.session)

    async def new_page(self) -> _Page:
        return self.page

    async def new_cdp_session(self, _page: _Page) -> _Session:
        return self.session

    async def close(self) -> None:
        return None


class _Pool:
    def __init__(self, context: _Context) -> None:
        self.context = context

    async def new_context(self, *, target: ResolvedTarget) -> _Context:
        del target
        return self.context

    async def release(self, *, target: ResolvedTarget) -> None:
        del target
        return None

    async def aclose(self) -> None:
        return None


class _Transport(PatchrightTransport):
    def __init__(
        self, amounts: list[int], *, stall: bool, queued_amount: int = 0
    ) -> None:
        super().__init__(settings=site_health_settings)
        self.context = _Context()
        self._pool = _Pool(self.context)
        self.amounts = amounts
        self.stall = stall
        self.context.page.queued_amount = queued_amount
        self.navigation_started = asyncio.Event()
        self.navigation_stopped = asyncio.Event()

    async def _navigate(self, page, target, timeout_seconds):
        del page, target, timeout_seconds
        for amount in self.amounts:
            self.context.session.emit(amount)
        if self.stall:
            self.navigation_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.navigation_stopped.set()
        return SimpleNamespace(headers={"content-type": "text/html"}, status=200)

    async def _wait_for_readiness(self, page, *, remaining: float) -> None:
        del page, remaining
        return None


_TARGET = ResolvedTarget(
    url="https://example.com/",
    scheme="https",
    host="example.com",
    port=443,
    connect_ip="93.184.216.34",
    resolved_ips=("93.184.216.34",),
)
_REQUEST = FetchRequest(url=_TARGET.url, purpose="analyze")


@pytest.mark.asyncio
async def test_browser_aborts_when_cumulative_wire_budget_is_exceeded() -> None:
    transport = _Transport([60, 50], stall=True)
    with pytest.raises(FetchError) as exc_info:
        await transport.fetch(
            _REQUEST,
            _TARGET,
            max_wire_bytes=100,
            max_decoded_bytes=1_000,
            timeout_seconds=5,
        )
    assert exc_info.value.error_code == ERROR_RESPONSE_TOO_LARGE


@pytest.mark.asyncio
async def test_browser_accepts_a_response_within_both_byte_budgets() -> None:
    result = await _Transport([40, 50], stall=False).fetch(
        _REQUEST,
        _TARGET,
        max_wire_bytes=100,
        max_decoded_bytes=1_000,
        timeout_seconds=5,
    )
    assert result.status_code == 200
    assert result.body == b"<html></html>"
    assert result.wire_bytes == 90


@pytest.mark.asyncio
async def test_browser_rechecks_wire_budget_after_acquisition_completes() -> None:
    transport = _Transport([60], stall=False, queued_amount=50)

    with pytest.raises(FetchError) as exc_info:
        await transport.fetch(
            _REQUEST,
            _TARGET,
            max_wire_bytes=100,
            max_decoded_bytes=1_000,
            timeout_seconds=5,
        )

    assert exc_info.value.error_code == ERROR_RESPONSE_TOO_LARGE


@pytest.mark.asyncio
async def test_cancelling_fetch_stops_stalled_acquisition() -> None:
    transport = _Transport([], stall=True)
    fetch = asyncio.create_task(
        transport.fetch(
            _REQUEST,
            _TARGET,
            max_wire_bytes=100,
            max_decoded_bytes=1_000,
            timeout_seconds=5,
        )
    )
    await transport.navigation_started.wait()

    fetch.cancel()
    with pytest.raises(asyncio.CancelledError):
        await fetch

    assert transport.navigation_stopped.is_set()
