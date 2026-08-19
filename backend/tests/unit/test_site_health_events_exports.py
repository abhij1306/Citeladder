"""Site Health SSE stream boundary tests."""

from __future__ import annotations

import uuid

import pytest

from app.api.site_health import events_exports
from app.domain.site_health.service import SiteHealthNotFoundError


class _Session:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_event_stream_stops_when_crawl_disappears(monkeypatch) -> None:
    async def missing_crawl(*_: object, **__: object) -> object:
        raise SiteHealthNotFoundError("crawl not found")

    monkeypatch.setattr(events_exports, "SessionLocal", _Session)
    monkeypatch.setattr(events_exports.service, "load_crawl_for_stream", missing_crawl)

    stream = events_exports._event_stream(
        uuid.uuid4(), uuid.uuid4(), last_event_id=None
    )
    with pytest.raises(StopAsyncIteration):
        await anext(stream)
