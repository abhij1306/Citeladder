"""Shared fixtures for the Site Health worker component tests.

The worker tests were one 3,700-line module; they now mirror the worker's own
phase split (discover / analyze / link_check / terminalization / loop).
Everything those files build a crawl out of — the fake resolver, the stub
transports, the HTML fixtures and the crawl seeders — lives here, so each phase
file reads as assertions rather than setup.
"""

from __future__ import annotations

import gzip
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import (
    ANALYZER_VERSION,
    CAPABILITY_STARTER,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    EXTRACTOR_VERSION,
    SCORING_VERSION,
    SELECTION_SOURCE_USER,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.task_queue import (
    TASK_STATUS_QUEUED,
)
from app.domain.site_health.entitlements import set_entitlement
from app.domain.site_health.normalization import canonical_identity
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SitePageAnalysis,
    SiteUrl,
)
from app.workers.site_health_worker import (
    SiteHealthWorker,
)
from tests.component.site_health_helpers import seed_site_crawl

_PUBLIC_IP = "93.184.216.34"


class _FakeResolver:
    async def resolve(self, host: str, port: int) -> list[str]:
        return [_PUBLIC_IP]


def _html(links: list[str], *, title: str = "Page") -> bytes:
    anchors = "".join(f'<a href="{u}">l</a>' for u in links)
    return (
        f"<html><head><title>{title}</title></head><body>{anchors}</body></html>"
    ).encode()


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, data: bytes) -> None:
        self._data = data

    async def __aiter__(self):
        yield self._data

    async def aclose(self) -> None:
        return None


class _StubCurlSession:
    """Offline stand-in for the fetcher's rung-2 curl session (T7).

    Replays one scripted status so worker tests that return a bot-block
    signature status (401/403/503) never touch the real network when the
    curl_cffi escalation rung fires. ``body`` is the scripted decoded payload
    (default a tiny stub) so a winning rung 2 can serve real HTML.
    """

    def __init__(self, status: int, *, body: bytes = b"stub") -> None:
        self._status = status
        self._body = body

    async def __aenter__(self) -> _StubCurlSession:
        return self

    async def __aexit__(self, *exc) -> None:
        return None

    async def request(self, method, url, **kwargs):
        callback = kwargs.get("content_callback")
        if callback is not None:
            callback(self._body)
        return httpx.Response(self._status, headers={"content-type": "text/html"})


def _site_transport(
    pages: dict[str, bytes | tuple[bytes, dict[str, str]]],
    *,
    requests: list[tuple[str, str]] | None = None,
) -> httpx.MockTransport:
    """A mock transport serving ``pages`` (keyed by path) as text/html.

    Values are either raw body bytes (served with a bare text/html content
    type) or a ``(body, extra_headers)`` tuple for pages that need specific
    response headers (e.g. gzip content-encoding / HSTS). When ``requests``
    is given, every served (method, path) is appended to it.

    Any unknown path returns 404 so an out-of-scope/absent link is a clean
    fetch failure rather than an exception.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append((request.method, request.url.path))
        entry = pages.get(request.url.path)
        if entry is None:
            return httpx.Response(
                404,
                headers={"content-type": "text/html"},
                stream=_ByteStream(b"not found"),
            )
        if isinstance(entry, tuple):
            body, extra_headers = entry
            headers = {"content-type": "text/html", **extra_headers}
        else:
            body, headers = entry, {"content-type": "text/html"}
        return httpx.Response(
            200,
            headers=headers,
            stream=_ByteStream(body),
        )

    return httpx.MockTransport(handler)


async def _configure_crawl(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    sample_mode: bool,
    count_disclosure: bool,
) -> None:
    """Freeze the minimal worker-facing configuration onto a seeded crawl."""
    crawl = await session.get(SiteCrawl, crawl_id)
    assert crawl is not None
    crawl.sample_mode = sample_mode
    # The planner drives discovery -> running when queuing the crawl; mirror
    # that so the worker's sample_completed/completed transitions are valid.
    crawl.discovery_status = DISCOVERY_STATUS_RUNNING
    crawl.configuration = {
        "root_registrable_domain": "example.com",
        "include_globs": None,
        "exclude_globs": None,
        "count_disclosure": count_disclosure,
    }
    await session.commit()


def _worker(
    session_factory: async_sessionmaker[AsyncSession],
    pages: dict[str, bytes | tuple[bytes, dict[str, str]]],
    *,
    owner: str = "site-test",
    requests: list[tuple[str, str]] | None = None,
) -> SiteHealthWorker:
    return SiteHealthWorker(
        session_factory=session_factory,
        owner=owner,
        resolver=_FakeResolver(),
        transport=_site_transport(pages, requests=requests),
    )


async def _seed_root_only(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    root: str = "https://example.com/",
):
    """Seed a Starter crawl with a single root discover task, return the seed."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0, root_url=root)
        await set_entitlement(session, seed.workspace_id, CAPABILITY_STARTER)
        await session.commit()
        await _configure_crawl(
            session,
            crawl_id=seed.crawl_id,
            sample_mode=False,
            count_disclosure=True,
        )
        _canonical, root_hash = canonical_identity(root)
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=root,
                url_hash=root_hash,
                generation=0,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_DISCOVER}:root:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=0,
            )
        )
        await session.commit()
    return seed


def _rich_html() -> bytes:
    """A page that passes most rules (in-band title + meta description,
    canonical, single h1, og, JSON-LD WebPage + Organization, author + date
    meta, a question heading, >=100 words of body text, one external
    citation).

    Served via :func:`_rich_page` (gzip + HSTS) it passes EVERY per-page rule
    applicable to an ``other`` page. Note the 140-word body is deliberately
    thin FOR AN ARTICLE (>= 300 words) so the per-type thin-content minimum
    stays testable.
    """
    words = " ".join(f"word{i}" for i in range(140))
    return (
        "<html><head>"
        "<title>Rich Page - everything about Acme widgets</title>"
        '<meta name="description" content="A rich descriptive page about Acme '
        'widgets, their features, and pricing plans.">'
        '<link rel="canonical" href="https://example.com/rich">'
        '<meta property="og:title" content="Rich Page">'
        '<meta property="og:description" content="Rich desc">'
        '<meta name="author" content="Jane Doe">'
        '<meta property="article:published_time" content="2026-01-01T00:00:00Z">'
        '<script type="application/ld+json">'
        '{"@type":"Organization","name":"Acme","url":"https://example.com",'
        '"sameAs":["https://twitter.com/acme"],'
        '"logo":"https://example.com/logo.png"}'
        "</script>"
        '<script type="application/ld+json">'
        '{"@type":"WebPage","name":"Rich Page","url":"https://example.com/rich"}'
        "</script>"
        "</head><body>"
        "<h1>Rich Page Heading</h1>"
        f"<p>{words}</p>"
        "<h2>What makes Acme widgets reliable?</h2>"
        '<a href="https://example.com/other">internal</a>'
        '<a href="https://external.org/x">external</a>'
        "</body></html>"
    ).encode()


def _rich_page() -> tuple[bytes, dict[str, str]]:
    """The rich page served the way a well-run site serves it: gzipped and
    with HSTS, so the delivery rules (``technical.uncompressed_html`` /
    ``technical.hsts_present``) pass too."""
    return (
        gzip.compress(_rich_html()),
        {
            "content-encoding": "gzip",
            "strict-transport-security": "max-age=63072000; includeSubDomains",
        },
    )


def _thin_html() -> bytes:
    """A page that FAILS several rules (no meta desc, no canonical, no h1,
    no og, no structured data, thin text)."""
    return b"<html><head><title>Thin</title></head><body><p>too short</p></body></html>"


async def _add_monitored_analyze_task(
    session: AsyncSession,
    seed,
    url: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one monitored SiteUrl + its QUEUED analyze task; return their ids."""
    canonical, url_hash = canonical_identity(url)
    site_url = SiteUrl(
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        normalized_url=canonical,
        url_hash=url_hash,
        display_url=canonical,
        host="example.com",
        depth=0,
    )
    session.add(site_url)
    await session.flush()
    session.add(
        MonitoredSiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            profile_id=seed.profile_id,
            site_url_id=site_url.id,
            active=True,
            selection_source=SELECTION_SOURCE_USER,
        )
    )
    analyze_task = SiteCrawlTask(
        crawl_id=seed.crawl_id,
        workspace_id=seed.workspace_id,
        site_url_id=site_url.id,
        task_kind=TASK_KIND_ANALYZE,
        requested_url=url,
        url_hash=url_hash,
        generation=0,
        idempotency_key=f"{seed.crawl_id}:{TASK_KIND_ANALYZE}:{url_hash}:0",
        status=TASK_STATUS_QUEUED,
        priority=1,
        randomized_position=0,
    )
    session.add(analyze_task)
    await session.flush()  # populate the client-side UUID defaults
    return site_url.id, analyze_task.id


def _mark_analysis_ready(
    crawl: SiteCrawl, *, url_count: int, site_facts: dict | None = None
) -> None:
    """Put a seeded crawl into the post-discovery analyze-phase state."""
    crawl.discovery_status = DISCOVERY_STATUS_COMPLETED
    crawl.discovered_url_count = url_count
    crawl.inventory_complete = True
    crawl.extractor_version = EXTRACTOR_VERSION
    crawl.analyzer_version = ANALYZER_VERSION
    crawl.scoring_version = SCORING_VERSION
    crawl.site_facts = site_facts
    crawl.configuration = {
        "root_registrable_domain": "example.com",
        "include_globs": None,
        "exclude_globs": None,
        "count_disclosure": True,
    }


async def _seed_analyze_phase_crawl(
    session: AsyncSession,
    *,
    root: str,
    urls: tuple[str, ...],
    capability: str = CAPABILITY_STARTER,
    site_facts: dict | None = None,
):
    """Seed a Starter crawl already through discovery: every URL monitored
    with one QUEUED analyze task (the analyze-phase starting state).

    Returns ``(seed, ids)`` where ``ids`` holds one
    ``(site_url_id, analyze_task_id)`` pair per URL, in ``urls`` order.
    """
    seed = await seed_site_crawl(session, task_count=0, root_url=root)
    await set_entitlement(session, seed.workspace_id, capability)
    await session.commit()
    crawl = await session.get(SiteCrawl, seed.crawl_id)
    assert crawl is not None
    _mark_analysis_ready(crawl, url_count=len(urls), site_facts=site_facts)
    ids = [await _add_monitored_analyze_task(session, seed, url) for url in urls]
    await session.commit()
    return seed, ids


async def _analyses_by_page_url(
    session: AsyncSession, seed
) -> dict[str, SitePageAnalysis]:
    """The crawl's analyses keyed by their page's normalized URL."""
    analyses = (
        (
            await session.execute(
                select(SitePageAnalysis).where(
                    SitePageAnalysis.crawl_id == seed.crawl_id
                )
            )
        )
        .scalars()
        .all()
    )
    url_by_site_url_id = {
        row[0]: row[1]
        for row in (
            await session.execute(
                select(SiteUrl.id, SiteUrl.normalized_url).where(
                    SiteUrl.project_id == seed.project_id
                )
            )
        ).all()
    }
    return {url_by_site_url_id[a.site_url_id]: a for a in analyses}


async def _seed_analyze_ready(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    root: str = "https://example.com/rich",
    capability: str = CAPABILITY_STARTER,
):
    """Seed a Starter crawl with a monitored URL + one queued analyze task."""
    async with session_factory() as session:
        seed, ((site_url_id, analyze_task_id),) = await _seed_analyze_phase_crawl(
            session, root=root, capability=capability, urls=(root,)
        )
        return seed, site_url_id, analyze_task_id


async def _seed_root_discover(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    root: str,
    capability: str = CAPABILITY_STARTER,
    sample_mode: bool = False,
):
    """Seed a crawl with a single QUEUED root discover task (the planner's
    output), ready for one worker run."""
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0, root_url=root)
        await set_entitlement(session, seed.workspace_id, capability)
        await session.commit()
        await _configure_crawl(
            session,
            crawl_id=seed.crawl_id,
            sample_mode=sample_mode,
            count_disclosure=True,
        )
        _canonical, root_hash = canonical_identity(root)
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=root,
                url_hash=root_hash,
                generation=0,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_DISCOVER}:root:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=0,
            )
        )
        await session.commit()
        return seed
