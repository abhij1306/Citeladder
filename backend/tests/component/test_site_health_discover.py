"""Discover phase: inventory admission, robots policy, sitemaps, and fetching.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    ERROR_BOT_BLOCKED,
    ERROR_HTTP_4XX,
    ERROR_ROBOTS_DENIED,
    ERROR_ROBOTS_UNAVAILABLE,
    FETCH_ATTEMPT_OUTCOME_ERROR,
    FETCH_ATTEMPT_OUTCOME_SUCCESS,
    ROBOTS_FETCH_STATUS_FETCH_FAILED,
    ROBOTS_FETCH_STATUS_FETCHED,
    ROBOTS_FETCH_STATUS_NOT_FOUND,
)
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_COMPLETED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    CRAWL_STATUS_RUNNING,
    DISCOVERY_STATUS_COMPLETED,
    DISCOVERY_STATUS_RUNNING,
    DISCOVERY_STATUS_SAMPLE_COMPLETED,
    OBSERVATION_SOURCE_SITEMAP,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_SITE_SETUP,
)
from app.core.config.site_health_crawl_policy import (
    AUTOMATIC_MONITOR_LIMIT_KEY,
    SELECTION_SOURCE_FREE_SAMPLE,
)
from app.core.config.site_health_runtime import (
    site_health_settings,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.frontier import _store_frontier_candidates
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.schemas import AdmissionResult, FrontierCandidate
from app.domain.site_health.service import presentation_status_for
from app.models.site_health.acquisition import SiteFetchArtifact, SiteFetchAttempt
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl, SiteDiscoveryFrontier
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation
from app.workers.site_health.phases import site_setup as site_setup_phase
from app.workers.site_health.phases.discover_stages import (
    write_sitemap_observations,
)
from app.workers.site_health.scheduling import claim_for_lane, configured_lane_plan
from app.workers.site_health_worker import SiteHealthWorker
from tests.component.site_health_helpers import seed_site_crawl
from tests.component.site_health_worker_helpers import (
    _add_monitored_analyze_task,
    _ByteStream,
    _configure_crawl,
    _FakeResolver,
    _html,
    _HttpxHandlerTransport,
    _seed_analyze_ready,
    _seed_root_branches,
    _seed_root_discover,
    _seed_runtime,
    _worker,
)


@pytest.mark.asyncio
async def test_progressive_analysis_keeps_discovered_page_priority(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    child = "https://example.com/products/widget"
    seed = await _seed_root_discover(session_factory, root=root)
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.configuration = {
            **(crawl.configuration or {}),
            AUTOMATIC_MONITOR_LIMIT_KEY: 2,
        }
        await session.commit()
    worker = _worker(
        session_factory,
        {"/": _html([child]), "/products/widget": _html([])},
        owner="progressive-priority",
    )

    assert await worker.run_once() == 1

    _canonical, child_hash = canonical_identity(child)
    async with session_factory() as session:
        tasks_by_kind = {
            task.task_kind: task
            for task in (
                await session.scalars(
                    select(SiteCrawlTask).where(
                        SiteCrawlTask.crawl_id == seed.crawl_id,
                        SiteCrawlTask.url_hash == child_hash,
                    )
                )
            ).all()
        }
        # A discovered child carries ONLY a discover task at this point. Its
        # analysis is handed over by that fetch, so it can never wake to find
        # its own page unfetched and defer behind the rest of discovery.
        discover = tasks_by_kind[TASK_KIND_DISCOVER]
        assert discover.priority > 1
        assert TASK_KIND_ANALYZE not in tasks_by_kind

    # Once the child's own discover lands, its analysis is queued against the
    # artifact that fetch just wrote, so it never waits on its own page.
    # (The batch also carries the root's own analyze task, handed over by the
    # root discover that ran first.)
    assert await worker.run_once() >= 1
    async with session_factory() as session:
        child_analyze = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.url_hash == child_hash,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            )
        )
        assert child_analyze is not None

    # Analysis of a page already in hand outranks fetching another one, so the
    # analyzed counter moves as discovery proceeds rather than only after the
    # whole discovery tree has drained.
    processing_lane = next(
        lane
        for lane in configured_lane_plan()
        if TASK_KIND_ANALYZE in lane.preferred_kinds
    )
    claimed = await claim_for_lane(
        worker._queue, owner=worker.owner, lane=processing_lane
    )
    assert claimed is not None
    assert claimed.task_kind == TASK_KIND_ANALYZE
    assert claimed.priority > discover.priority


@pytest.mark.asyncio
async def test_markdown_document_is_successful_inventory_only_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    document = "https://example.com/agents.md"
    seed = await _seed_root_discover(session_factory, root=root)
    worker = _worker(
        session_factory,
        {
            "/": _html([document]),
            "/agents.md": (b"# Agent guidance", {"content-type": "text/markdown"}),
        },
        owner="document-inventory",
    )

    for _ in range(3):
        await worker.run_once()

    _canonical, document_hash = canonical_identity(document)
    async with session_factory() as session:
        site_url = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == seed.project_id,
                SiteUrl.url_hash == document_hash,
            )
        )
        assert site_url is not None
        assert site_url.corpus_disposition == "inventory_only"
        assert site_url.item_kind == "document"
        tasks = list(
            await session.scalars(
                select(SiteCrawlTask).where(
                    SiteCrawlTask.crawl_id == seed.crawl_id,
                    SiteCrawlTask.url_hash == document_hash,
                )
            )
        )
        assert [(task.task_kind, task.status) for task in tasks] == [
            (TASK_KIND_DISCOVER, TASK_STATUS_SUCCEEDED)
        ]
        artifact = await session.scalar(
            select(SiteFetchArtifact).where(SiteFetchArtifact.task_id == tasks[0].id)
        )
        assert artifact is not None
        assert artifact.content_type == "text/markdown"


@pytest.mark.asyncio
async def test_sitemap_observations_use_bounded_bulk_statements(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch_size = 3
    monkeypatch.setattr(site_health_settings, "admission_batch_size", batch_size)
    candidates: list[FrontierCandidate] = []
    site_url_ids: dict[str, str] = {}
    for ordinal in range(batch_size * 2 + 1):
        url = f"https://example.com/from-sitemap-{ordinal}"
        canonical, url_hash = canonical_identity(url)
        candidates.append(
            FrontierCandidate(
                url=canonical,
                url_hash=url_hash,
                depth=1,
                source_kind=OBSERVATION_SOURCE_SITEMAP,
                parent_position=0,
                link_ordinal=ordinal,
            )
        )
        site_url_ids[url_hash] = str(uuid.uuid4())

    class RecordingSession:
        def __init__(self) -> None:
            self.statements = []

        async def execute(self, statement):
            self.statements.append(statement)

    session = RecordingSession()
    crawl = SimpleNamespace(
        id=uuid.uuid4(), workspace_id=uuid.uuid4(), project_id=uuid.uuid4()
    )
    await write_sitemap_observations(
        session,
        crawl=crawl,
        candidates=candidates,
        admission=AdmissionResult(
            admitted=len(candidates),
            sample_capped=False,
            site_url_ids=site_url_ids,
        ),
    )

    assert len(session.statements) == 3
    persisted_urls = []
    for statement in session.statements:
        params = statement.compile().params
        persisted_urls.extend(
            value for key, value in params.items() if key.startswith("final_url_m")
        )
    assert persisted_urls == [candidate.url for candidate in candidates]


@pytest.mark.asyncio
async def test_full_allowance_discover_admits_children_and_completes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    # A full-allowance crawl using the discover-only phase fixture.
    seed = await _seed_root_discover(session_factory, root=root)

    pages = {
        "/": _html(
            [
                "https://example.com/a",
                "https://example.com/b",
                "https://example.com/men%3Futm_source%3Dhero",
                "https://external.org/x",  # out of scope -> not admitted
            ]
        ),
        "/a": _html([]),
        "/b": _html([]),
        "/men": _html([]),
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
        assert snapshot.web_fundamentals_score is None
        assert snapshot.aeo_readiness_score is None

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
        # Set subset, not `in` on each: these are EXACT normalized-URL matches.
        # `assert "https://example.com/" in urls` reads as a substring test to a
        # scanner (py/incomplete-url-substring-sanitization) even though `urls`
        # is a list, so spell the exact-membership intent out.
        assert {
            "https://example.com/",
            "https://example.com/a",
            "https://example.com/b",
            "https://example.com/men",
        } <= set(urls)
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
        assert obs_count == 4  # root + a + b + rewritten men link
        rewrite = await session.scalar(
            select(SiteUrlObservation).where(
                SiteUrlObservation.crawl_id == seed.crawl_id,
                SiteUrlObservation.rewrite_reason == "encoded_tracking_query_delimiter",
            )
        )
        assert rewrite is not None
        assert rewrite.observed_url == "https://example.com/men"
        assert rewrite.rewrite_version == "sh-link-rewrite-1"
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.crawl_id == seed.crawl_id)
        )
        assert artifact_count == 4

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
async def test_large_sitemap_frontier_is_persisted_in_bounded_batches(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A default-sized sitemap cannot exceed asyncpg's bind-parameter cap."""
    candidate_count = site_health_settings.max_sitemap_admitted_urls
    assert candidate_count >= 5_000

    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.configuration = {
            "root_registrable_domain": "example.com",
            "max_frontier_urls": candidate_count,
        }
        candidates = []
        for ordinal in range(candidate_count):
            url = f"https://example.com/catalog/item-{ordinal}"
            canonical, url_hash = canonical_identity(url)
            candidates.append(
                FrontierCandidate(
                    url=canonical,
                    url_hash=url_hash,
                    depth=1,
                    source_kind=OBSERVATION_SOURCE_SITEMAP,
                    parent_position=0,
                    link_ordinal=ordinal,
                )
            )

        await _store_frontier_candidates(
            session,
            crawl=crawl,
            candidates=candidates,
            configuration=dict(crawl.configuration),
        )
        await session.commit()

        stored = await session.scalar(
            select(func.count())
            .select_from(SiteDiscoveryFrontier)
            .where(SiteDiscoveryFrontier.crawl_id == crawl.id)
        )
        assert stored == candidate_count


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
    """Two sample crawls in the SAME workspace share the 10-URL budget."""
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
        from app.models.site_health.runtime import SiteHealthProfile

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
        await _seed_runtime(session, seed_a.workspace_id, monitored_urls=0)
        await session.commit()

        # Configure both crawls for sample mode.
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

    # Each root page links to in-scope children. The workspace-wide sample
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

        # Auto-enqueued analyze tasks retain their discovery value priority and
        # are now claimable and EXECUTED by the worker: the workspace-wide
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

        # At least one crawl reached the sample cap terminal state.
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
@pytest.mark.anyio
async def test_free_discovery_maps_past_the_sample_budget_without_analyzing(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free discovery keeps mapping past the analysis budget (inventory only).

    Discovery and analysis used to share ONE number, so a Free crawl stopped
    admitting URLs the moment its 10 analyze slots were spent: the user saw the
    first 10 URLs of their site and nothing else. They are now separate budgets
    — the inventory grows to ``sample_discovery_url_cap`` while only
    ``sample_url_limit`` URLs get a monitored membership and an analyze
    task. The over-budget URLs must be REAL inventory rows (identity +
    per-crawl observation, so the UI can list them) that cost no fetch.
    """
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    # A small cap keeps the test fast while still proving the split: 4 analyzed
    # out of 12 discovered is unambiguous about which budget bounds which.
    monkeypatch.setattr(site_health_settings, "sample_url_limit", 4)
    monkeypatch.setattr(site_health_settings, "sample_discovery_url_cap", 12)

    root = "https://example.com/"
    async with session_factory() as session:
        seed = await seed_site_crawl(session, task_count=0, root_url=root)
        # Written AFTER the settings patch above so the projected runtime row
        # freezes the small sample budget (the policy reads live settings).
        await _seed_runtime(session, seed.workspace_id, monitored_urls=0)
        await session.commit()
        await _configure_crawl(
            session,
            crawl_id=seed.crawl_id,
            sample_mode=True,
            count_disclosure=False,
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

    # 15 in-scope children — more than the discovery cap, far more than the
    # analysis budget, so both ceilings are genuinely exercised.
    links = [f"https://example.com/p{i}" for i in range(15)]
    pages = {"/": _html(links)}
    for i in range(15):
        pages[f"/p{i}"] = _html([])

    worker = _worker(session_factory, pages, owner="free-split")
    assert await worker.run_until_idle() > 0

    async with session_factory() as session:
        # Analysis stayed on its own budget.
        monitored = await session.scalar(
            select(func.count())
            .select_from(MonitoredSiteUrl)
            .where(
                MonitoredSiteUrl.workspace_id == seed.workspace_id,
                MonitoredSiteUrl.active.is_(True),
                MonitoredSiteUrl.selection_source == SELECTION_SOURCE_FREE_SAMPLE,
            )
        )
        assert monitored == 4
        analyze_count = await session.scalar(
            select(func.count())
            .select_from(SiteCrawlTask)
            .where(
                SiteCrawlTask.workspace_id == seed.workspace_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            )
        )
        assert analyze_count == 4

        # ...while the INVENTORY mapped well past it. This is the regression:
        # it used to equal the sample budget exactly.
        observed = await session.scalar(
            select(func.count())
            .select_from(SiteUrlObservation)
            .where(SiteUrlObservation.crawl_id == seed.crawl_id)
        )
        assert observed is not None
        assert observed > 4, "discovery must not stop at the analysis budget"
        # Soft cap: admission is batched, so landing slightly over the 12-URL
        # discovery cap is expected. The bound must stay STRICTLY below the
        # full 16-URL frontier (root + 15 children) — at `<= 16` the assertion
        # passed even when the cap was ignored entirely, so it proved nothing.
        assert observed < 16, "the discovery cap must bound the frontier"
        assert observed <= site_health_settings.sample_discovery_url_cap + 2

        # The unanalyzed remainder is real, listable inventory.
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SiteUrl)
                .where(SiteUrl.project_id == seed.project_id)
            )
        ) >= observed


@pytest.mark.anyio
async def test_discover_robots_denied_short_circuits_and_records_site_facts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A robots.txt that disallows our crawler denies the root WITHOUT a page
    fetch (non-retryable), yet the durable site-setup branch still records the
    AI-crawler stance (llms.txt + sitemap probes honor the same policy, so
    they are skipped too)."""
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
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
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            )
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
        assert robots.get("status") == ROBOTS_FETCH_STATUS_FETCHED
        assert robots.get("status_code") == 200
        assert robots.get("ai_crawlers") == {bot: "block" for bot in AI_CRAWLER_BOTS}
        llms = site_facts.get("llms_txt") or {}
        assert llms.get("fetched") is False
        assert llms.get("present") is False
        sitemap = site_facts.get("sitemap") or {}
        assert sitemap.get("fetched") is False
        assert sitemap.get("files") == []


@pytest.mark.asyncio
async def test_root_and_site_setup_branches_converge_durably(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
    setup_started = asyncio.Event()
    release_setup = asyncio.Event()
    site_facts = {
        "robots": {"status": ROBOTS_FETCH_STATUS_NOT_FOUND},
        "llms_txt": {"fetched": False},
        "sitemap": {"fetched": False, "files": []},
    }

    async def blocked_site_setup(*_args, **_kwargs):
        setup_started.set()
        await release_setup.wait()
        return site_facts, ()

    monkeypatch.setattr(site_health_settings, "worker_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "global_concurrency", 2)
    monkeypatch.setattr(site_health_settings, "acquisition_lane_reserve", 1)
    monkeypatch.setattr(site_setup_phase, "collect_site_setup", blocked_site_setup)
    worker = _worker(
        session_factory,
        {"/": _html([])},
        owner="durable-root-setup",
    )

    run = asyncio.create_task(worker.run_once())
    await asyncio.wait_for(setup_started.wait(), timeout=5)
    for _ in range(100):
        async with session_factory() as session:
            discover_status = await session.scalar(
                select(SiteCrawlTask.status).where(
                    SiteCrawlTask.crawl_id == seed.crawl_id,
                    SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                )
            )
            crawl = await session.get(SiteCrawl, seed.crawl_id)
        if discover_status == TASK_STATUS_SUCCEEDED:
            break
        await asyncio.sleep(0.01)
    else:
        pytest.fail("root discovery did not complete beside blocked site setup")

    assert crawl is not None
    assert crawl.discovery_status == DISCOVERY_STATUS_RUNNING
    assert crawl.site_facts is None
    release_setup.set()
    assert await asyncio.wait_for(run, timeout=5) == 2

    async with session_factory() as session:
        setup_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_SITE_SETUP,
            )
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert setup_task is not None
        assert setup_task.status == TASK_STATUS_SUCCEEDED
        assert crawl is not None
        assert crawl.discovery_status == DISCOVERY_STATUS_COMPLETED
        assert crawl.site_facts == site_facts


@pytest.mark.asyncio
async def test_reclaimed_site_setup_acknowledges_persisted_evidence_without_refetch(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
    first = _worker(session_factory, {"/": _html([])}, owner="setup-ack-fails")

    async def drop_queue_ack(**_kwargs) -> bool:
        return False

    monkeypatch.setattr(first._queue, "succeed", drop_queue_ack)
    claimed = await first._queue.claim(
        owner=first.owner,
        limit=1,
        kinds=[TASK_KIND_SITE_SETUP],
    )
    assert len(claimed) == 1
    await first._execute_claimed(claimed[0])

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, claimed[0].id)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert task is not None
        assert task.status == TASK_STATUS_RUNNING
        assert crawl is not None
        assert crawl.site_facts is not None
        persisted_facts = dict(crawl.site_facts)
        task.status = TASK_STATUS_QUEUED
        task.lease_owner = None
        task.lease_expires_at = None
        await session.commit()

    requests: list[tuple[str, str]] = []
    reclaimed = _worker(
        session_factory,
        {},
        owner="setup-reclaimed",
        requests=requests,
    )
    replay = await reclaimed._queue.claim(
        owner=reclaimed.owner,
        limit=1,
        kinds=[TASK_KIND_SITE_SETUP],
    )
    assert len(replay) == 1
    await reclaimed._execute_claimed(replay[0])

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, claimed[0].id)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED
        assert crawl is not None
        assert crawl.site_facts == persisted_facts
    assert requests == []


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

    policy, body, status = await worker._robots.ensure(authority)
    assert requests == [("GET", "/robots.txt")]
    # The default mock 404s unknown paths: allow-all, status recorded, no body.
    assert status == 404
    assert body is None
    assert policy.can_fetch(f"{authority}/anything") is True
    assert policy.unavailable is False

    # Within the TTL the cached entry is reused (no second fetch).
    cached_policy, cached_body, cached_status = await worker._robots.ensure(authority)
    assert cached_policy is policy
    assert (cached_body, cached_status) == (body, status)
    assert requests == [("GET", "/robots.txt")]

    # Aging the entry past the TTL forces a re-fetch on the next ensure.
    worker._robots._fetched_at[authority] = (
        time.monotonic() - site_health_settings.robots_cache_ttl_seconds - 1.0
    )
    refreshed_policy, _, refreshed_status = await worker._robots.ensure(authority)
    assert requests == [("GET", "/robots.txt"), ("GET", "/robots.txt")]
    assert refreshed_status == 404
    assert refreshed_policy.can_fetch(f"{authority}/anything") is True


@pytest.mark.asyncio
async def test_discover_robots_404_records_not_found_and_crawls_fail_open(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """SH-1 (B2): a 404 robots.txt means the site HAS no robots.txt.

    That is ``not_found`` — crawling proceeds fail-open and the AI-crawler
    stance defaults to allow — NOT ``fetch_failed`` (robots unreachable),
    and the crawl completes normally.
    """
    seed = await _seed_root_branches(session_factory, root="https://example.com/")
    # No "/robots.txt" key -> the mock transport 404s it; the root serves.
    worker = _worker(session_factory, {"/": _html([])}, owner="robots-404")
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        site_facts = crawl.site_facts or {}
        robots = site_facts.get("robots") or {}
        assert robots.get("fetched") is False
        assert robots.get("status") == ROBOTS_FETCH_STATUS_NOT_FOUND
        assert robots.get("status_code") == 404
        # Fail-open: no robots.txt means no restrictions for any AI bot.
        assert robots.get("ai_crawlers") == {bot: "allow" for bot in AI_CRAWLER_BOTS}


@pytest.mark.asyncio
async def test_discover_robots_5xx_fails_unavailable_without_page_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """RFC 9309: a 5xx robots.txt is a complete (temporary) disallow.

    The root discover fails non-retryable as ``robots_unavailable``
    (distinct from a parse-based ``robots_denied``) WITHOUT a page fetch —
    the llms/sitemap probes honor the same temporary deny-all — while the
    durable site-setup branch still records the robots evidence (5xx status, not
    fetched)."""
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
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
        transport=_HttpxHandlerTransport(handler),
    )
    await worker.run_until_idle()

    # Only the robots fetch happened — never the page, llms, or sitemaps.
    assert requests == [("GET", "/robots.txt")]

    async with session_factory() as session:
        task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
            )
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
        # SH-1 (B2): a 5xx robots.txt is fetch_failed, NOT not_found — the
        # site's robots endpoint misbehaved; the stance is genuinely unknown.
        assert robots.get("status") == ROBOTS_FETCH_STATUS_FETCH_FAILED
        assert robots.get("status_code") == 503
        llms = site_facts.get("llms_txt") or {}
        assert llms.get("fetched") is False
        sitemap = site_facts.get("sitemap") or {}
        assert sitemap.get("fetched") is False


@pytest.mark.asyncio
async def test_discover_site_setup_llms_stance_sitemap_and_finalize_orphan(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Full-allowance pipeline in ONE run (the real production flow):

    The durable site-setup branch parses robots (per-bot stance + declared sitemap),
    probes llms.txt, ingests the sitemap tree into in-scope admissions, caches
    the robots policy across every task, and persists the bounded
    ``site_facts`` display copy on the crawl row. When the crawl terminalizes,
    the crawl_finalize pass runs: ``sitemap_orphan`` fails for the sitemap URL
    no internal link reaches, and ``hreflang_conflict`` is N/A — both at
    config-owned weights, with the orphan issue in the snapshot rollup.
    """
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
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
    # The analyze task deliberately backs off when its discover dependency is
    # still committing; let that bounded defer mature, then drain it.
    await asyncio.sleep(site_health_settings.analysis_dependency_retry_seconds)
    await worker.run_until_idle()

    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert requests.count(("GET", "/")) == 1

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
        shared_artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
        assert shared_artifact is not None
        assert shared_artifact.fetch_purpose == "discover"
        assert shared_artifact.normalized_facts is not None
        analyze_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
            )
        )
        assert analyze_task is not None
        assert analyze_task.result_artifact_id == shared_artifact.id
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
        assert orphan.outcome == RULE_OUTCOME_MISSING
        assert orphan.evidence["orphan_count"] == 1
        assert orphan.evidence["orphan_urls"] == ["https://example.com/sm-2"]
        # Both admitted sitemap URLs carry the sitemap-source observation.
        assert orphan.evidence["sitemap_url_count"] == 2

        hreflang = evals["technical.hreflang_conflict"]
        assert hreflang.outcome == RULE_OUTCOME_NOT_APPLICABLE
        assert hreflang.evidence["reason"] == "no_hreflang"

        # Cluster rules preserve their config-owned measurement weights.
        assert orphan.weight == 1.0
        assert hreflang.weight == 2.0

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
async def test_sitemap_attempt_limit_includes_failed_child_documents(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A large blocked sitemap tree cannot monopolize the crawl worker."""
    monkeypatch.setattr(site_health_settings, "max_sitemap_documents", 5)
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    root = "https://example.com/"
    seed = await _seed_root_branches(session_factory, root=root)
    child_refs = "".join(
        f"<sitemap><loc>https://example.com/child-{index}.xml</loc></sitemap>"
        for index in range(100)
    )
    sitemap_index = f"<sitemapindex>{child_refs}</sitemapindex>".encode()
    pages: dict[str, bytes | tuple[bytes, dict[str, str]]] = {
        "/robots.txt": b"Sitemap: https://example.com/index.xml\n",
        "/index.xml": (sitemap_index, {"content-type": "application/xml"}),
        "/": _html([]),
    }
    requests: list[tuple[str, str]] = []

    worker = _worker(session_factory, pages, requests=requests)
    await worker.run_until_idle()

    sitemap_requests = [
        path
        for method, path in requests
        if method == "GET" and (path == "/index.xml" or path.startswith("/child-"))
    ]
    assert sitemap_requests == [
        "/index.xml",
        "/child-0.xml",
        "/child-1.xml",
        "/child-2.xml",
        "/child-3.xml",
    ]
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_requested_page_limit_stays_closed_while_children_are_unobserved(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconciliation cannot reopen a full crawl's reserved URL budget."""
    monkeypatch.setattr(site_health_settings, "per_host_delay_seconds", 0.0)
    root = "https://example.com/"
    seed = await _seed_root_discover(session_factory, root=root)
    first_level = [f"https://example.com/page-{index}" for index in range(30)]
    second_level = [f"https://example.com/deep-{index}" for index in range(30)]
    pages = {"/": _html(first_level)}
    pages.update({f"/page-{index}": _html(second_level) for index in range(30)})
    pages.update({f"/deep-{index}": _html([]) for index in range(30)})
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        # The production planner reserves the root as the first admission.
        crawl.admitted_url_count = 1
        crawl.discovery_requested_count = 10
        crawl.configuration = {
            **dict(crawl.configuration or {}),
            "requested_page_limit": 10,
        }
        await session.commit()

    worker = _worker(session_factory, pages)
    await worker.run_until_idle()

    async with session_factory() as session:
        discover_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(
                    SiteCrawlTask.crawl_id == seed.crawl_id,
                    SiteCrawlTask.task_kind == TASK_KIND_DISCOVER,
                )
            )
            or 0
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert discover_count == 10
        assert crawl.admitted_url_count == 10
        assert crawl.status == CRAWL_STATUS_COMPLETED


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
        assert row.outcome == FETCH_ATTEMPT_OUTCOME_SUCCESS
        assert row.artifact_id == artifact.id
        assert row.acquisition_transport == "curl_cffi"
        assert row.acquisition_rung == 1
        assert row.acquisition_trigger == "initial"
        assert row.acquisition_options is None
        assert artifact.acquisition_transport == "curl_cffi"
        assert artifact.acquisition_rung == 1
        assert artifact.acquisition_trigger == "initial"
        assert artifact.acquisition_options is None


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
        transport=_HttpxHandlerTransport(handler),
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
        assert rows[0].outcome == FETCH_ATTEMPT_OUTCOME_ERROR
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
        transport=_HttpxHandlerTransport(handler),
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
        assert rows[0].outcome == FETCH_ATTEMPT_OUTCOME_ERROR
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


@pytest.mark.asyncio
async def test_a_cold_crawl_analyzes_as_it_discovers(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The analyzed count must rise while discovery is still running.

    Discovery and analysis share one queue, and analyze tasks used to be
    created at admission -- long before their page had been fetched. Each one
    woke, found its own discover task still in flight, and deferred, which
    pushed its `available_at` further back and sent it behind every task
    queued since. A cold crawl therefore drained its whole discovery tree
    first: 405 pages fetched against 3 analyzed in seven minutes, with the
    analyzed counter sitting at zero long enough that the crawl read as hung
    and got cancelled. Analysis is now handed over by the fetch itself, so it
    interleaves.

    Also pins the other half: one fetch per URL, not one per phase.
    """
    # One task at a time, which is where the starvation was visible: with a
    # wide batch the queue drains in two passes and hides the ordering.
    monkeypatch.setattr(site_health_settings, "worker_concurrency", 1)
    root = "https://example.com/"
    children = [f"https://example.com/products/p-{index}" for index in range(6)]
    seed = await _seed_root_discover(session_factory, root=root)
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.configuration = {
            **(crawl.configuration or {}),
            AUTOMATIC_MONITOR_LIMIT_KEY: len(children) + 1,
        }
        await session.commit()
    requests: list[tuple[str, str]] = []
    worker = _worker(
        session_factory,
        {
            "/": _html(children),
            **{f"/products/p-{index}": _html([]) for index in range(6)},
        },
        owner="cold-crawl",
        requests=requests,
    )

    analyzed_after_each_run: list[int] = []
    for _ in range(40):
        if await worker.run_once() == 0:
            break
        async with session_factory() as session:
            analyzed_after_each_run.append(
                int(
                    await session.scalar(
                        select(func.count())
                        .select_from(SiteCrawlTask)
                        .where(
                            SiteCrawlTask.crawl_id == seed.crawl_id,
                            SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                            SiteCrawlTask.status == TASK_STATUS_SUCCEEDED,
                        )
                    )
                    or 0
                )
            )

    # Analysis begins while discovery is still running. Before the handover,
    # every analyze task deferred behind the whole discovery tree, so this
    # list stayed at zero until the very last runs.
    assert analyzed_after_each_run, "the crawl did no work at all"
    total_runs = len(analyzed_after_each_run)
    assert analyzed_after_each_run[total_runs // 2] > 0, (
        f"analysis had not started by the halfway point: {analyzed_after_each_run}"
    )
    # And every discovered page is analyzed by the end -- the root included,
    # whose discover task carries no site_url_id of its own.
    assert analyzed_after_each_run[-1] == len(children) + 1

    # Every task is claimed exactly once. An analyze task that exists before
    # its page has been fetched burns a claim discovering it must wait, then
    # re-queues itself further back -- the loop that starved analysis on a
    # real site. Handed over by the fetch, it is never claimed early, so the
    # number of working runs equals the number of tasks with nothing to spare.
    async with session_factory() as session:
        task_count = int(
            await session.scalar(
                select(func.count())
                .select_from(SiteCrawlTask)
                .where(SiteCrawlTask.crawl_id == seed.crawl_id)
            )
            or 0
        )
    assert total_runs == task_count

    # No page is fetched twice: the analyze phase reuses the artifact the
    # discover phase already wrote for the same URL.
    fetched_paths = [path for method, path in requests if method == "GET"]
    duplicated = {path for path in fetched_paths if fetched_paths.count(path) > 1} - {
        "/robots.txt"
    }
    assert not duplicated, f"pages fetched more than once: {sorted(duplicated)}"
