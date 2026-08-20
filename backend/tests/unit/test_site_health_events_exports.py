"""Site Health SSE stream boundary tests."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_event_stream_drains_a_full_backlog_page(monkeypatch) -> None:
    crawl_id = uuid.uuid4()
    events = [
        SimpleNamespace(
            id=uuid.uuid4(),
            crawl_id=crawl_id,
            event_type="crawl.progress",
            message="progress",
            payload={},
            created_at=None,
        )
        for _ in range(3)
    ]
    calls: list[tuple[uuid.UUID | None, int | None]] = []

    async def load_crawl(*_: object, **__: object) -> object:
        return SimpleNamespace(status="completed")

    async def load_events(
        *_: object,
        after: uuid.UUID | None,
        limit: int | None = None,
        **__: object,
    ) -> list[object]:
        calls.append((after, limit))
        return events[:2] if after is None else events[2:]

    monkeypatch.setattr(events_exports, "SessionLocal", _Session)
    monkeypatch.setattr(events_exports.service, "load_crawl_for_stream", load_crawl)
    monkeypatch.setattr(events_exports.service, "load_events", load_events)
    monkeypatch.setattr(
        events_exports.service, "crawl_count_disclosure", lambda _: True
    )
    monkeypatch.setattr(events_exports.site_health_settings, "max_event_page", 2)
    monkeypatch.setattr(
        events_exports.site_health_settings, "sse_max_duration_seconds", 0
    )

    stream = events_exports._event_stream(uuid.uuid4(), crawl_id, last_event_id=None)
    frames = [frame async for frame in stream]

    assert len(frames) == 3
    assert calls == [(None, 2), (events[1].id, 2)]
