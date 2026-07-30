"""Discover phase: inventory admission, robots policy, sitemaps, the fetch ladder.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import time
import uuid
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import (
    AI_CRAWLER_BOTS,
    ANALYSIS_STATUS_COMPLETED,
    CAPABILITY_FREE,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    ERROR_BOT_BLOCKED,
    ERROR_HTTP_4XX,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
    OBSERVATION_SOURCE_SITEMAP,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PASS,
    SELECTION_SOURCE_FREE_SAMPLE,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.entitlements import set_entitlement
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.service import presentation_status_for
from app.models.site_health import (
    MonitoredSiteUrl,
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteFetchAttempt,
    SiteHealthSnapshot,
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
    SiteUrlObservation,
)
from app.workers.site_health_worker import (
    _OUTCOME_ERROR,
    _OUTCOME_SUCCESS,
    SiteHealthWorker,
)
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    _add_monitored_analyze_task,
    _ByteStream,
    _configure_crawl,
    _FakeResolver,
    _html,
    _seed_analyze_ready,
    _seed_root_discover,
    _worker,
)


@pytest.mark.asyncio
async def test_starter_discover_admits_children_and_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    # A Starter crawl with the single root discover task the planner queues.
    seed = await _seed_root_discover(session_factory, root=root)

    pages = {
        "/": _html(
            [
                "https://example.com/a",
                "https://example.com/b",
                "https://external.org/x",  # out of scope -> not admitted
            ]
        ),
        "/a": _html([]),
        "/b": _html([]),
    }
    worker = _worker(session_factory, pages)
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.inventory_complete is True
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED

        # A crawl with no analyze tasks still terminalizes the independent
        # analysis lifecycle and persists an explicit empty/null-score snapshot.
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.selected_url_count == 0
        assert snapshot.analyzed_url_count == 0
        assert snapshot.technical_score is None
        assert snapshot.aeo_score is None
        assert snapshot.overall_score is None

        # Root + 2 in-scope children admitted; external.org excluded.
        # A set: the assertions below are exact whole-URL membership checks,
        # never substring matching. CodeQL's py/incomplete-url-substring-
        # sanitization still flags them because it cannot infer the SQLAlchemy
        # return type and keys on the URL-shaped literal alone; alert #2 is
        # dismissed as a false positive rather than contorting these asserts.
        urls = set(
            (
                await session.execute(
                    select(SiteUrl.normalized_url).where(
                        SiteUrl.project_id == seed.project_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert "https://example.com/" in urls
        assert "https://example.com/a" in urls
        assert "https://example.com/b" in urls
        assert not any(urlsplit(u).hostname == "external.org" for u in urls)

        # Host populated on the identity rows (not blank).
        hosts = (
            (
                await session.execute(
                    select(SiteUrl.host).where(SiteUrl.project_id == seed.project_id)
                )
            )
            .scalars()
            .all()
        )
        assert all(h == "example.com" for h in hosts)

        # Immutable evidence written for each fetched URL.
        obs_count = await session.scalar(
            select(func.count())
            .select_from(SiteUrlObservation)
            .where(SiteUrlObservation.crawl_id == seed.crawl_id)
        )
        assert obs_count == 3  # root + a + b
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.crawl_id == seed.crawl_id)
        )
        assert artifact_count == 3

        # Every discover task succeeded.
        statuses = (
            (
                await session.execute(
                    select(SiteCrawlTask.status).where(
                        SiteCrawlTask.crawl_id == seed.crawl_id,
                        SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert statuses and all(s == TASK_STATUS_SUCCEEDED for s in statuses)

        # Every succeeded discover task points at its fetch artifact (mirrors
        # the audit worker's result_artifact_id contract).
        result_artifact_ids = (
            (
                await session.execute(
                    select(SiteCrawlTask.result_artifact_id).where(
                        SiteCrawlTask.crawl_id == seed.crawl_id,
                        SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert result_artifact_ids and all(
            aid is not None for aid in result_artifact_ids
        )

        # First attempt row is numbered 1 (not 0).
        attempt_numbers = (
            (
                await session.execute(
                    select(SiteFetchAttempt.attempt_number).where(
                        SiteFetchAttempt.crawl_id == seed.crawl_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert attempt_numbers and all(n == 1 for n in attempt_numbers)


@pytest.mark.asyncio
async def test_inventory_rows_present_before_crawl_terminalizes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Run only the root discover batch; children remain queued.

    Proves inventory (SiteUrl + observation) is durable progressively, before
    discovery/crawl reach a terminal state.
    """
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)

    pages = {
        "/": _html(["https://example.com/a", "https://example.com/b"]),
        "/a": _html([]),
        "/b": _html([]),
    }
    worker = _worker(session_factory, pages)
    # A single batch: claim + run the root task only (children now queued).
    await worker.run_once()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        # Crawl is still active (children pending) but inventory already exists.
        assert crawl.status == CRAWL_STATUS_RUNNING
        admitted = await session.scalar(
            select(func.count())
            .select_from(SiteUrl)
            .where(SiteUrl.project_id == seed.project_id)
        )
        assert admitted is not None
        assert admitted >= 3  # root + 2 children admitted during discovery
        pending_children = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                SiteCrawlTask.status == TASK_STATUS_QUEUED,
            )
        )
        assert pending_children == 2


@pytest.mark.asyncio
async def test_free_sample_stops_at_ten_across_two_projects(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two Free crawls in the SAME workspace share the 10-URL sample budget."""
    # Every URL below is on the one host, so the 0.5s politeness delay would
    # serialize ~20 fetches into ~10s of pure sleeping. The budget accounting
    # under test is delay-independent, so zero it (same treatment as the
    # concurrency tests further down this file).
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    root_a = "https://example.com/"
    async with session_factory() as session:
        seed_a = await seed_site_crawl(session, task_count=0, root_url=root_a)
        # Second project in the SAME workspace.
        from app.models.project import Project
        from app.models.site_health import SiteHealthProfile

        project_b = Project(
            workspace_id=seed_a.workspace_id,
            name="Acme Site B",
            brand_name="Acme Corp",
            country_code="AU",
            language_code="en-AU",
            benchmark_mode="consumer_like",
            default_repetitions=1,
            website_url=root_a,
        )
        session.add(project_b)
        await session.flush()
        profile_b = SiteHealthProfile(
            workspace_id=seed_a.workspace_id,
            project_id=project_b.id,
            root_url=root_a,
            root_host="example.com",
            registrable_domain="example.com",
        )
        session.add(profile_b)
        await session.flush()
        crawl_b = SiteCrawl(
            workspace_id=seed_a.workspace_id,
            project_id=project_b.id,
            profile_id=profile_b.id,
            status=CRAWL_STATUS_RUNNING,
            root_url=root_a,
            random_seed="1",
            sample_mode=True,
        )
        session.add(crawl_b)
        await session.flush()
        crawl_b_id = crawl_b.id
        await set_entitlement(session, seed_a.workspace_id, CAPABILITY_FREE)
        await session.commit()

        # Configure both crawls for Free sample mode.
        await _configure_crawl(
            session,
            crawl_id=seed_a.crawl_id,
            sample_mode=True,
            count_disclosure=False,
        )
        await _configure_crawl(
            session,
            crawl_id=crawl_b_id,
            sample_mode=True,
            count_disclosure=False,
        )

        # Seed crawl A's root discover task only. Crawl B's root is seeded
        # AFTER worker A drains, so worker A cannot claim it (the discover
        # claim is workspace-global): this guarantees each worker exercises
        # exactly one project's frontier and B genuinely contributes to the
        # shared workspace budget.
        _canonical, root_hash = canonical_identity(root_a)

        def _root_task(crawl_id: uuid.UUID) -> SiteCrawlTask:
            return SiteCrawlTask(
                crawl_id=crawl_id,
                workspace_id=seed_a.workspace_id,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=root_a,
                url_hash=root_hash,
                generation=0,
                idempotency_key=f"{crawl_id}:{TASK_KIND_DISCOVER}:root:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=0,
            )

        session.add(_root_task(seed_a.crawl_id))
        await session.commit()

    # Each root page links to in-scope children. The workspace-wide Free
    # budget is 10, and the root/fetched identity itself now also consumes
    # one slot of that budget (it goes through admission too, not just its
    # child links), so project A's root + 6 children (7) plus project B's
    # root (1) leave exactly 2 slots for project B's children.
    links_a = [f"https://example.com/a{i}" for i in range(6)]
    links_b = [f"https://example.com/b{i}" for i in range(8)]
    pages = {"/": _html(links_a)}
    for i in range(6):
        pages[f"/a{i}"] = _html([])

    # Run crawl A's worker first: it admits the root + all 6 /a* URLs.
    worker_a = _worker(session_factory, pages, owner="site-a")
    processed_a = await worker_a.run_until_idle()
    assert processed_a > 0

    # Now seed crawl B's root and run its worker: /b* URLs must top up the
    # shared workspace budget to exactly 10.
    async with session_factory() as session:
        session.add(_root_task(crawl_b_id))
        await session.commit()

    pages_b = {"/": _html(links_b)}
    for i in range(8):
        pages_b[f"/b{i}"] = _html([])
    worker_b = _worker(session_factory, pages_b, owner="site-b")
    processed_b = await worker_b.run_until_idle()
    # Worker B must actually do work, otherwise the shared-cap intent (project
    # B contributing to the workspace budget) is never exercised.
    assert processed_b > 0

    async with session_factory() as session:
        # Workspace-wide free_sample monitored rows capped at exactly 10.
        sample_count = await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.workspace_id == seed_a.workspace_id,
                MonitoredSiteUrl.active.is_(True),
                MonitoredSiteUrl.selection_source == SELECTION_SOURCE_FREE_SAMPLE,
            )
        )
        assert sample_count == 10

        # Project B genuinely contributed to the shared budget: at least one
        # /b* URL was admitted as a free-sample monitored row.
        monitored_urls = (
            (
                await session.execute(
                    select(SiteUrl.normalized_url)
                    .join(
                        MonitoredSiteUrl,
                        MonitoredSiteUrl.site_url_id == SiteUrl.id,
                    )
                    .where(
                        MonitoredSiteUrl.workspace_id == seed_a.workspace_id,
                        MonitoredSiteUrl.active.is_(True),
                        MonitoredSiteUrl.selection_source
                        == SELECTION_SOURCE_FREE_SAMPLE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any(u in set(links_b) for u in monitored_urls)

        # Auto-enqueued analyze tasks (priority=1 by the Free sample path) are
        # now claimable and EXECUTED by the worker (Task 5): the workspace-wide
        # free-sample cap of 10 still holds (10 monitored URLs -> 10 analyze
        # tasks total), but they are succeeded rather than left queued.
        analyze_statuses = (
            (
                await session.execute(
                    select(SiteCrawlTask.status).where(
                        SiteCrawlTask.workspace_id == seed_a.workspace_id,
                        SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert analyze_statuses
        assert all(s == TASK_STATUS_SUCCEEDED for s in analyze_statuses)
        assert len(analyze_statuses) == 10

        # Each executed analyze task produced a completed page analysis.
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.workspace_id == seed_a.workspace_id)
        )
        assert analysis_count == 10

        # At least one crawl reached the Free cap terminal state.
        crawl_a = await session.get(SiteCrawl, seed_a.crawl_id)
        assert crawl_a is not None
        _crawl_b = await session.get(SiteCrawl, crawl_b_id)
        assert _crawl_b is not None
        crawl_b = _crawl_b
        assert crawl_a.status == CRAWL_STATUS_COMPLETED
        assert crawl_b.status == CRAWL_STATUS_COMPLETED
        assert DISCOVERY_STATUS_SAMPLE_COMPLETED in (
            crawl_a.discovery_status,
            crawl_b.discovery_status,
        )


@pytest.mark.asyncio
async def test_discover_robots_denied_short_circuits_and_records_site_facts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A robots.txt that disallows our crawler denies the root WITHOUT a page
    fetch (non-retryable), yet the depth-0 site setup still records the
    AI-crawler stance (llms.txt + sitemap probes honor the same policy, so
    they are skipped too)."""
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)
    pages = {
        "/robots.txt": b"User-agent: *\nDisallow: /\n",
        "/llms.txt": b"# Acme llms\n",
    }
    requests: list[tuple[str, str]] = []
    worker = _worker(session_factory, pages, owner="p2-deny", requests=requests)
    await worker.run_until_idle()

    # robots.txt was fetched once; the denied root page was NEVER fetched, and
    # the llms/sitemap probes were skipped (they honor the same policy).
    assert ("GET", "/robots.txt") in requests
    assert ("GET", "/") not in requests
    assert ("GET", "/llms.txt") not in requests
    assert ("GET", "/sitemap.xml") not in requests

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == ERROR_ROBOTS_DENIED

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_FAILED
        # The site setup evidence survived the denied root (display copy).
        site_facts = crawl.site_facts or {}
        robots = site_facts.get("robots") or {}
        assert robots.get("fetched") is True
        assert robots.get("status_code") == 200
        assert robots.get("ai_crawlers") == {bot: "block" for bot in AI_CRAWLER_BOTS}
        llms = site_facts.get("llms_txt") or {}
        assert llms.get("fetched") is False
        assert llms.get("present") is False
        sitemap = site_facts.get("sitemap") or {}
        assert sitemap.get("fetched") is False
        assert sitemap.get("files") == []


@pytest.mark.asyncio
async def test_robots_cache_honors_ttl_and_4xx_is_allow_all(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The per-authority robots cache expires after
    ``robots_cache_ttl_seconds`` (the next ensure re-fetches), and a 4xx
    robots.txt parses to allow-all (RFC 9309: no robots.txt == no
    restrictions)."""
    requests: list[tuple[str, str]] = []
    worker = _worker(session_factory, {}, owner="robots-ttl", requests=requests)
    authority = "https://example.com"

    policy, body, status = await worker._ensure_robots_policy(authority)
    assert requests == [("GET", "/robots.txt")]
    # The default mock 404s unknown paths: allow-all, status recorded, no body.
    assert status == 404
    assert body is None
    assert policy.can_fetch(f"{authority}/anything") is True
    assert policy.unavailable is False

    # Within the TTL the cached entry is reused (no second fetch).
    cached_policy, cached_body, cached_status = await worker._ensure_robots_policy(
        authority
    )
    assert cached_policy is policy
    assert (cached_body, cached_status) == (body, status)
    assert requests == [("GET", "/robots.txt")]

    # Aging the entry past the TTL forces a re-fetch on the next ensure.
    worker._robots_cache_ts[authority] = (
        time.monotonic() - site_health_settings.robots_cache_ttl_seconds - 1.0
    )
    refreshed_policy, _, refreshed_status = await worker._ensure_robots_policy(
        authority
    )
    assert requests == [("GET", "/robots.txt"), ("GET", "/robots.txt")]
    assert refreshed_status == 404
    assert refreshed_policy.can_fetch(f"{authority}/anything") is True


@pytest.mark.asyncio
async def test_discover_robots_5xx_fails_unavailable_without_page_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """RFC 9309: a 5xx robots.txt is a complete (temporary) disallow.

    The root discover fails non-retryable as ``robots_unavailable``
    (distinct from a parse-based ``robots_denied``) WITHOUT a page fetch —
    the llms/sitemap probes honor the same temporary deny-all — while the
    depth-0 site setup still records the robots evidence (5xx status, not
    fetched)."""
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/robots.txt":
            return httpx.Response(503, stream=_ByteStream(b"busy"))
        return httpx.Response(404, stream=_ByteStream(b"not found"))

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="p2-robots5xx",
        resolver=_FakeResolver(),
        transport=httpx.MockTransport(handler),
    )
    await worker.run_until_idle()

    # Only the robots fetch happened — never the page, llms, or sitemaps.
    assert requests == [("GET", "/robots.txt")]

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == ERROR_ROBOTS_UNAVAILABLE

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_FAILED
        site_facts = crawl.site_facts or {}
        robots = site_facts.get("robots") or {}
        assert robots.get("fetched") is False
        assert robots.get("status_code") == 503
        llms = site_facts.get("llms_txt") or {}
        assert llms.get("fetched") is False
        sitemap = site_facts.get("sitemap") or {}
        assert sitemap.get("fetched") is False


@pytest.mark.asyncio
async def test_discover_site_setup_llms_stance_sitemap_and_finalize_orphan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full Starter pipeline in ONE run (the real production flow):

    The depth-0 site setup parses robots (per-bot stance + declared sitemap),
    probes llms.txt, ingests the sitemap tree into in-scope admissions, caches
    the robots policy across every task, and persists the bounded
    ``site_facts`` display copy on the crawl row. When the crawl terminalizes,
    the crawl_finalize pass runs: ``sitemap_orphan`` fails for the sitemap URL
    no internal link reaches, ``broken_internal_link`` passes (the one linked
    target is reachable), and ``hreflang_conflict`` is N/A — all at weight
    0.0, with the orphan issue in the snapshot rollup.
    """
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)
    # Seed the root's monitored membership + analyze task UPFRONT (next to the
    # planner's discover task) so discovery, sitemap ingestion, and analysis
    # all land inside one terminalization/snapshot.
    async with session_factory() as session:
        await _add_monitored_analyze_task(session, seed, root)
        await session.commit()

    robots = (
        b"User-agent: GPTBot\n"
        b"Disallow: /\n\n"
        b"User-agent: *\n"
        b"Allow: /\n"
        b"Sitemap: https://example.com/sitemap.xml\n"
    )
    urlset = (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        b"<url><loc>https://example.com/sm-1</loc></url>"
        b"<url><loc>https://example.com/sm-2</loc></url>"
        b"<url><loc>https://external.org/out-of-scope</loc></url>"
        b"</urlset>"
    )
    pages: dict[str, bytes | tuple[bytes, dict[str, str]]] = {
        "/robots.txt": robots,
        "/llms.txt": b"# Acme\nSee https://example.com/docs\n",
        "/sitemap.xml": (urlset, {"content-type": "application/xml"}),
        # The root links /sm-1 only: /sm-2 reaches inventory via the sitemap
        # alone, which is exactly the orphan signal.
        "/": _html(["https://example.com/sm-1"]),
        "/sm-1": _html([]),
        "/sm-2": _html([]),
    }
    requests: list[tuple[str, str]] = []
    worker = _worker(session_factory, pages, owner="p2-setup", requests=requests)
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED

        # The robots policy was fetched ONCE for the whole crawl (the root +
        # both child discovers + the sitemap-tree walk + the analyze task all
        # share the per-authority cache).
        assert requests.count(("GET", "/robots.txt")) == 1
        assert ("GET", "/llms.txt") in requests
        assert ("GET", "/sitemap.xml") in requests

        site_facts = crawl.site_facts or {}
        robots_facts = site_facts.get("robots") or {}
        assert robots_facts.get("fetched") is True
        assert robots_facts.get("status_code") == 200
        assert robots_facts.get("ai_crawlers") == {
            **{bot: "allow" for bot in AI_CRAWLER_BOTS},
            "GPTBot": "block",
        }
        assert robots_facts.get("sitemaps") == ["https://example.com/sitemap.xml"]
        llms = site_facts.get("llms_txt") or {}
        assert llms.get("fetched") is True
        assert llms.get("status_code") == 200
        assert llms.get("present") is True
        sitemap_facts = site_facts.get("sitemap") or {}
        assert sitemap_facts.get("fetched") is True
        assert sitemap_facts.get("files") == ["https://example.com/sitemap.xml"]

        # Sitemap URLs admitted at depth 1; the out-of-scope one filtered.
        urls = (
            await session.execute(
                select(SiteUrl.normalized_url, SiteUrl.depth).where(
                    SiteUrl.project_id == seed.project_id
                )
            )
        ).all()
        by_url = {row[0]: row[1] for row in urls}
        assert by_url.get("https://example.com/sm-1") == 1
        assert by_url.get("https://example.com/sm-2") == 1
        assert not any(urlsplit(url).hostname == "external.org" for url in by_url)

        # /sm-2 (never linked) carries the sitemap provenance observation.
        sm2_obs = await session.scalar(
            select(SiteUrlObservation.source_kind)
            .select_from(SiteUrlObservation)
            .join(SiteUrl, SiteUrl.id == SiteUrlObservation.site_url_id)
            .where(
                SiteUrlObservation.crawl_id == seed.crawl_id,
                SiteUrl.normalized_url == "https://example.com/sm-2",
            )
        )
        assert sm2_obs == OBSERVATION_SOURCE_SITEMAP

        # --- The finalize pass ran at terminalization (single snapshot). ---
        analysis = (
            await session.execute(
                select(SitePageAnalysis).where(
                    SitePageAnalysis.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        evals = {
            row.rule_id: row
            for row in (
                await session.execute(
                    select(SiteRuleEvaluation).where(
                        SiteRuleEvaluation.analysis_id == analysis.id
                    )
                )
            )
            .scalars()
            .all()
        }
        orphan = evals["technical.sitemap_orphan"]
        assert orphan.outcome == RULE_OUTCOME_FAIL
        assert orphan.evidence["orphan_count"] == 1
        assert orphan.evidence["orphan_urls"] == ["https://example.com/sm-2"]
        # Both admitted sitemap URLs carry the sitemap-source observation.
        assert orphan.evidence["sitemap_url_count"] == 2

        broken = evals["technical.broken_internal_link"]
        assert broken.outcome == RULE_OUTCOME_PASS
        assert broken.evidence["checked_count"] == 1
        assert broken.evidence["broken_count"] == 0

        hreflang = evals["technical.hreflang_conflict"]
        assert hreflang.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert hreflang.evidence["reason"] == "no_hreflang"

        # Every crawl_finalize rule is weight-0: issues, never denominators.
        assert orphan.weight == 0.0
        assert broken.weight == 0.0
        assert hreflang.weight == 0.0

        # The orphan issue landed and the (single) snapshot counted it.
        issues = (
            (
                await session.execute(
                    select(SiteIssue.rule_id).where(SiteIssue.crawl_id == seed.crawl_id)
                )
            )
            .scalars()
            .all()
        )
        assert "technical.sitemap_orphan" in issues

        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        assert snapshot.issue_count == len(issues)


@pytest.mark.asyncio
async def test_plain_fetch_persists_one_attempt_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A plain fetch persists ONE attempt row (ordinal 0) linked to the
    artifact — one row per real network call, and there is exactly one."""
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)
    pages = {"/": _html([], title="Home")}
    worker = _worker(session_factory, pages, owner="p3-plain")
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED

        artifact = await session.scalar(
            select(SiteFetchArtifact).where(SiteFetchArtifact.task_id == task.id)
        )
        assert artifact is not None

        rows = (
            (
                await session.execute(
                    select(SiteFetchAttempt).where(SiteFetchAttempt.task_id == task.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        row = rows[0]
        assert row.attempt_number == 1
        assert row.request_ordinal == 0
        assert row.status_code == 200
        assert row.outcome == _OUTCOME_SUCCESS
        assert row.artifact_id == artifact.id


@pytest.mark.asyncio
async def test_plain_403_without_challenge_marker_stays_http_4xx(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A bare 403 with no challenge marker keeps the generic ``http_4xx``.

    Status alone is NOT a bot-block signal (see ``is_bot_block_result``): a
    members-only 403 must not be relabelled as bot protection. One attempt row
    persists, with no artifact.
    """
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(
                403,
                headers={"content-type": "text/html"},
                stream=_ByteStream(b"<html><body>Members only</body></html>"),
            )
        return httpx.Response(404, stream=_ByteStream(b"not found"))

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="p3-plain403",
        resolver=_FakeResolver(),
        transport=httpx.MockTransport(handler),
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == ERROR_HTTP_4XX

        rows = (
            (
                await session.execute(
                    select(SiteFetchAttempt).where(SiteFetchAttempt.task_id == task.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status_code == 403
        assert rows[0].outcome == _OUTCOME_ERROR
        assert rows[0].error_code == ERROR_HTTP_4XX
        assert rows[0].artifact_id is None

        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.task_id == task.id)
        )
        assert artifact_count == 0


@pytest.mark.asyncio
async def test_bot_block_presents_blocked_via_bot_blocked_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A challenge-marker response -> terminal ``bot_blocked`` + ``blocked``.

    The analyze fetch returns 403 with a challenge-platform marker, so the
    task fails non-retryably with ``ERROR_BOT_BLOCKED`` (never the generic
    ``http_4xx``), persists one attempt row not linked to an artifact, writes
    NO analyzable artifact (the blocked response lives in the trace only), and
    presents the URL as ``blocked`` via ``POLICY_BLOCKING_ERROR_CODES``.
    """
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rich":
            return httpx.Response(
                403,
                headers={"content-type": "text/html"},
                stream=_ByteStream(b"<html><body>Just a moment...</body></html>"),
            )
        return httpx.Response(404, stream=_ByteStream(b"not found"))

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="p3-blocked",
        resolver=_FakeResolver(),
        transport=httpx.MockTransport(handler),
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == ERROR_BOT_BLOCKED

        # The blocked call persists as an attempt, never linked to an artifact.
        rows = (
            (
                await session.execute(
                    select(SiteFetchAttempt)
                    .where(SiteFetchAttempt.task_id == task_id)
                    .order_by(SiteFetchAttempt.request_ordinal)
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].status_code == 403
        assert rows[0].artifact_id is None
        assert rows[0].outcome == _OUTCOME_ERROR
        assert rows[0].error_code == ERROR_BOT_BLOCKED

        # No analyzable artifact was created from the blocked response.
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.task_id == task_id)
        )
        assert artifact_count == 0
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert analysis_count == 0

        # Presentation: the terminal ``bot_blocked`` task renders ``blocked``.
        assert presentation_status_for(
            analysis=None, monitored=True, latest_analyze_task=task
        ) == ("blocked", ERROR_BOT_BLOCKED)
