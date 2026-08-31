"""Analyze phase: the live entitlement/membership guard, evidence persistence, scoring.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.site_health.parser import extract_page_facts
from app.core.config.site_health_acquisition import (
    AI_CRAWLER_BOTS,
    ERROR_ROBOTS_DENIED,
    FETCH_PURPOSE_DISCOVER,
)
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_CANCELLED,
    ANALYSIS_STATUS_COMPLETED,
    ANALYZER_VERSION,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_RUNNING,
    EXTRACTOR_VERSION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
    SCORING_VERSION,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
    TASK_KIND_SITE_SETUP,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_FREE_SAMPLE,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES
from app.core.config.site_health_taxonomy import (
    MIN_MEANINGFUL_WORDS,
)
from app.core.config.task_queue import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.normalization import canonical_identity
from app.domain.site_health.rerun import rerun_page
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl
from app.workers.site_health.phases import analyze as analyze_phase
from app.workers.site_health_worker import (
    SiteHealthWorker,
)
from tests.component.site_health_worker_helpers import (
    DEFAULT_SEED_MONITORED_URLS,
    _analyses_by_page_url,
    _ByteStream,
    _FakeResolver,
    _html,
    _HttpxHandlerTransport,
    _rich_html,
    _rich_page,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
    _seed_runtime,
    _thin_html,
    _worker,
)


@pytest.mark.asyncio
async def test_root_analysis_defers_until_durable_site_setup_commits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/"
    async with session_factory() as session:
        seed, ((_site_url_id, analyze_task_id),) = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root,), site_facts=None
        )
        _canonical, root_hash = canonical_identity(root)
        session.add(
            SiteCrawlTask(
                crawl_id=seed.crawl_id,
                workspace_id=seed.workspace_id,
                task_kind=TASK_KIND_SITE_SETUP,
                requested_url=root,
                url_hash=root_hash,
                idempotency_key=f"{seed.crawl_id}:{TASK_KIND_SITE_SETUP}:{root_hash}:0",
                status=TASK_STATUS_QUEUED,
                randomized_position=-1,
            )
        )
        await session.commit()

    requests: list[tuple[str, str]] = []
    worker = _worker(
        session_factory,
        {"/": _rich_page()},
        owner="root-setup-dependency",
        requests=requests,
    )
    claimed = await worker._queue.claim(
        owner=worker.owner,
        limit=1,
        kinds=[TASK_KIND_ANALYZE],
    )
    assert len(claimed) == 1
    await worker._execute_claimed(claimed[0])

    async with session_factory() as session:
        analyze_task = await session.get(SiteCrawlTask, analyze_task_id)
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert analyze_task is not None
        assert analyze_task.status == TASK_STATUS_QUEUED
        assert analyze_task.attempt_count == 0
        assert analysis_count == 0
    assert requests == []


@pytest.mark.asyncio
async def test_same_crawl_rerun_gets_a_new_analysis_for_reused_artifact(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/rich"
    seed, site_url_id, _analyze_task_id = await _seed_analyze_ready(
        session_factory,
        root=root,
    )
    _canonical, url_hash = canonical_identity(root)
    body = _rich_html()
    facts = extract_page_facts(
        body,
        final_url=root,
        content_type="text/html",
        status_code=200,
        wire_bytes=len(body),
        decoded_bytes=len(body),
    )
    async with session_factory() as session:
        discover_task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            site_url_id=site_url_id,
            task_kind=TASK_KIND_DISCOVER,
            requested_url=root,
            url_hash=url_hash,
            generation=0,
            idempotency_key=f"{seed.crawl_id}:discover:{url_hash}:0",
            status=TASK_STATUS_SUCCEEDED,
        )
        session.add(discover_task)
        await session.flush()
        artifact = SiteFetchArtifact(
            task_id=discover_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose=FETCH_PURPOSE_DISCOVER,
            requested_url=root,
            final_url=root,
            status_code=200,
            content_type="text/html",
            extractor_version=EXTRACTOR_VERSION,
            normalized_facts=facts,
        )
        session.add(artifact)
        await session.flush()
        discover_task.result_artifact_id = artifact.id
        await session.commit()
    worker = _worker(
        session_factory,
        {"/rich": _rich_html()},
        owner="same-crawl-rerun",
    )

    @asynccontextmanager
    async def reject_network_slot(_url: str):
        if _url:
            raise AssertionError("artifact-reuse analysis must not enter HostGate")
        yield

    worker._phase_context = replace(
        worker._phase_context, host_slot=reject_network_slot
    )

    async def keep_crawl_active(_task) -> None:
        return None

    monkeypatch.setattr(worker._lifecycle, "reconcile_after_task", keep_crawl_active)
    assert await worker.run_until_idle() == 1

    async with session_factory() as session:
        first = (
            await session.scalars(
                select(SitePageAnalysis).where(
                    SitePageAnalysis.crawl_id == seed.crawl_id
                )
            )
        ).one()
        result = await rerun_page(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            site_url_id=first.site_url_id,
        )
        await session.commit()
        assert result.created_new_crawl is False

    assert await worker.run_until_idle() == 1

    async with session_factory() as session:
        analyses = list(
            await session.scalars(
                select(SitePageAnalysis)
                .where(SitePageAnalysis.crawl_id == seed.crawl_id)
                .order_by(SitePageAnalysis.created_at, SitePageAnalysis.id)
            )
        )

    assert len(analyses) == 2
    assert analyses[0].id != analyses[1].id
    assert analyses[0].artifact_id == analyses[1].artifact_id
    assert [analysis.is_current for analysis in analyses] == [False, True]


@pytest.mark.asyncio
async def test_supported_html_marks_classification_expected_before_parser_failure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/parser-failure"
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory, root=root)
    worker = _worker(
        session_factory,
        {"/parser-failure": _rich_html()},
        owner="classification-parser-failure",
    )

    def fail_after_supported_html(*_args, **_kwargs):
        raise RuntimeError("parser failed after supported HTML acquisition")

    monkeypatch.setattr(analyze_phase, "extract_page_facts", fail_after_supported_html)

    assert await worker.run_until_idle() == 1

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == "crawl_task_crashed"
        assert task.classification_expected is True
        assert analysis_count == 0


@pytest.mark.asyncio
async def test_bodyless_success_is_not_in_classification_cohort(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/bodyless"
    _seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory, root=root)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            204,
            headers={"content-type": "text/html"},
            stream=_ByteStream(b""),
        )

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="classification-bodyless-response",
        resolver=_FakeResolver(),
        transport=_HttpxHandlerTransport(handler),
    )

    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_SUCCEEDED
        assert task.classification_expected is False


@pytest.mark.asyncio
async def test_reused_html_marks_classification_expected_before_persistence_failure(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = "https://example.com/reused-parser-output"
    seed, site_url_id, task_id = await _seed_analyze_ready(session_factory, root=root)
    _canonical, url_hash = canonical_identity(root)
    body = _rich_html()
    facts = extract_page_facts(
        body,
        final_url=root,
        content_type="text/html",
        status_code=200,
        wire_bytes=len(body),
        decoded_bytes=len(body),
    )
    async with session_factory() as session:
        discover_task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            site_url_id=site_url_id,
            task_kind=TASK_KIND_DISCOVER,
            requested_url=root,
            url_hash=url_hash,
            generation=0,
            idempotency_key=f"{seed.crawl_id}:discover:{url_hash}:0",
            status=TASK_STATUS_SUCCEEDED,
        )
        session.add(discover_task)
        await session.flush()
        artifact = SiteFetchArtifact(
            task_id=discover_task.id,
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            fetch_purpose=FETCH_PURPOSE_DISCOVER,
            requested_url=root,
            final_url=root,
            status_code=200,
            content_type="text/html",
            extractor_version=EXTRACTOR_VERSION,
            normalized_facts=facts,
        )
        session.add(artifact)
        await session.flush()
        discover_task.result_artifact_id = artifact.id
        await session.commit()

    async def fail_after_reuse(*_args, **_kwargs) -> None:
        raise RuntimeError("analysis persistence failed after artifact reuse")

    monkeypatch.setattr(analyze_phase, "_persist_analyze", fail_after_reuse)
    worker = _worker(
        session_factory,
        {},
        owner="classification-reuse-failure",
    )

    assert await worker.run_until_idle() == 1

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == "crawl_task_crashed"
        assert task.classification_expected is True
        assert analysis_count == 0


@pytest.mark.asyncio
async def test_analyze_fallback_acquisition_uses_host_gate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    root = "https://example.com/rich"
    await _seed_analyze_ready(session_factory, root=root)
    worker = _worker(
        session_factory,
        {"/rich": _rich_html()},
        owner="fallback-host-gate",
    )
    entered_urls: list[str] = []

    @asynccontextmanager
    async def record_network_slot(url: str):
        entered_urls.append(url)
        async with session_factory() as session:
            task = await session.scalar(
                select(SiteCrawlTask).where(SiteCrawlTask.requested_url == url)
            )
            assert task is not None
            assert task.status == TASK_STATUS_LEASED
        yield

    worker._phase_context = replace(
        worker._phase_context, host_slot=record_network_slot
    )

    assert await worker.run_once() == 1
    assert entered_urls == [root]


@pytest.mark.asyncio
async def test_analyze_guard_blocks_live_entitlement_downgrade_before_io(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory)
    async with session_factory() as session:
        await _seed_runtime(session, seed.workspace_id, monitored_urls=0)
        await session.commit()

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, stream=_ByteStream(b"unexpected"))

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="downgraded",
        resolver=_FakeResolver(),
        transport=_HttpxHandlerTransport(handler),
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.task_id == task_id)
        )
        assert requests == []
        assert task.status == TASK_STATUS_CANCELLED
        assert artifact_count == 0
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.analysis_status == ANALYSIS_STATUS_CANCELLED
        assert crawl.status == CRAWL_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_cancelled_user_analysis_does_not_penalize_applicable_free_sample(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Mixed cancelled+succeeded work is complete over applicable coverage."""
    seed, _user_site_url_id, user_task_id = await _seed_analyze_ready(session_factory)
    sample_url = "https://example.com/sample"
    canonical, sample_hash = canonical_identity(sample_url)
    async with session_factory() as session:
        sample_site_url = SiteUrl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            normalized_url=canonical,
            url_hash=sample_hash,
            display_url=canonical,
            host="example.com",
            depth=0,
        )
        session.add(sample_site_url)
        await session.flush()
        session.add(
            MonitoredSiteUrl(
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                profile_id=seed.profile_id,
                site_url_id=sample_site_url.id,
                active=True,
                selection_source=SELECTION_SOURCE_FREE_SAMPLE,
            )
        )
        sample_task = SiteCrawlTask(
            crawl_id=seed.crawl_id,
            workspace_id=seed.workspace_id,
            site_url_id=sample_site_url.id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url=sample_url,
            url_hash=sample_hash,
            generation=0,
            idempotency_key=f"{seed.crawl_id}:analyze:{sample_hash}:0",
            status=TASK_STATUS_QUEUED,
            priority=1,
            randomized_position=1,
        )
        session.add(sample_task)
        await _seed_runtime(session, seed.workspace_id, monitored_urls=0)
        await session.commit()
        sample_task_id = sample_task.id

    worker = _worker(
        session_factory,
        {"/sample": _rich_html()},
        owner="mixed-applicability",
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        user_task = await session.get(SiteCrawlTask, user_task_id)
        assert user_task is not None
        _sample_task = await session.get(SiteCrawlTask, sample_task_id)
        assert _sample_task is not None
        sample_task = _sample_task
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert user_task.status == TASK_STATUS_CANCELLED
        assert sample_task.status == TASK_STATUS_SUCCEEDED
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert snapshot.analyzed_url_count == 1
        assert snapshot.web_fundamentals_score is not None


@pytest.mark.asyncio
async def test_analyze_guard_discards_result_when_membership_removed_mid_fetch(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, site_url_id, task_id = await _seed_analyze_ready(session_factory)
    worker = _worker(
        session_factory,
        {"/rich": _rich_html()},
        owner="removed-mid-fetch",
    )
    original_fetch = analyze_phase._fetch_analyze
    fetched = False

    async def fetch_then_remove(ctx, **kwargs):
        nonlocal fetched
        outcome = await original_fetch(ctx, **kwargs)
        fetched = True
        async with session_factory() as session:
            await session.execute(
                update(MonitoredSiteUrl)
                .where(
                    MonitoredSiteUrl.workspace_id == seed.workspace_id,
                    MonitoredSiteUrl.site_url_id == site_url_id,
                )
                .values(active=False)
            )
            await session.commit()
        return outcome

    monkeypatch.setattr(analyze_phase, "_fetch_analyze", fetch_then_remove)
    await worker.run_until_idle()

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        artifact_count = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.task_id == task_id)
        )
        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert fetched is True
        assert task.status == TASK_STATUS_CANCELLED
        assert artifact_count == 0
        assert analysis_count == 0
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.analysis_status == ANALYSIS_STATUS_CANCELLED
        assert crawl.status == CRAWL_STATUS_COMPLETED


@pytest.mark.asyncio
async def test_reclaimed_analyze_acknowledges_already_persisted_analysis(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory)
    first = _worker(
        session_factory,
        {"/rich": _rich_html()},
        owner="ack-fails",
    )

    async def drop_queue_ack(**_kwargs) -> None:
        return None

    first._phase_context = replace(
        first._phase_context, finalize_queue_row=drop_queue_ack
    )
    assert await first.run_once() == 1

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_RUNNING
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.id == task_id)
            .values(
                status=TASK_STATUS_QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        await session.commit()

    requests: list[httpx.Request] = []

    def should_not_refetch(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500, stream=_ByteStream(b"unexpected"))

    reclaimed = SiteHealthWorker(
        session_factory=session_factory,
        owner="reclaimed",
        resolver=_FakeResolver(),
        transport=_HttpxHandlerTransport(should_not_refetch),
    )
    await reclaimed.run_until_idle()

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        artifacts = await session.scalar(
            select(func.count())
            .select_from(SiteFetchArtifact)
            .where(SiteFetchArtifact.task_id == task_id)
        )
        analyses = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert task.status == TASK_STATUS_SUCCEEDED
        assert artifacts == 1
        assert analyses == 1
        # The reclaimed analyze task itself must never refetch its own target.
        assert not any(
            req.method == "GET" and req.url.path == "/rich" for req in requests
        )


@pytest.mark.asyncio
async def test_analyze_task_persists_analysis_evaluations_issues_scores(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, site_url_id, _task_id = await _seed_analyze_ready(session_factory)
    pages = {"/rich": _rich_page(), "/other": _rich_html()}
    worker = _worker(session_factory, pages, owner="analyze-rich")
    await worker.run_until_idle()

    async with session_factory() as session:
        analysis = (
            await session.execute(
                select(SitePageAnalysis).where(
                    SitePageAnalysis.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert analysis.status == PAGE_ANALYSIS_STATUS_COMPLETED
        assert analysis.web_fundamentals_score is not None
        # `other` is classifier abstention, so AEO is unmeasured rather than a
        # perfect score from the few universal rules that remain applicable.
        assert analysis.page_kind == "other"
        assert analysis.aeo_readiness_score is None
        assert analysis.aeo_measurement_coverage is None
        assert analysis.aeo_measurement_state == "not_measured"
        assert analysis.aeo_measurement_reason == "page_purpose_unresolved"
        assert analysis.site_url_id == site_url_id

        eval_count = await session.scalar(
            select(func.count())
            .select_from(SiteRuleEvaluation)
            .where(SiteRuleEvaluation.analysis_id == analysis.id)
        )
        # Every canonical catalog entry has exactly one owning phase; the
        # combined page/finalize/architecture writers therefore emit one row
        # per rule without a parallel Product catalog.
        assert eval_count == len(SITE_HEALTH_RULES)

        # A rich page passes every rule, so no issues are snapshotted.
        issue_count = await session.scalar(
            select(func.count())
            .select_from(SiteIssue)
            .where(SiteIssue.crawl_id == seed.crawl_id)
        )
        assert issue_count == 0

        # An immutable artifact carries the normalized facts (no raw body).
        artifact = await session.get(SiteFetchArtifact, analysis.artifact_id)
        assert artifact is not None
        assert artifact.normalized_facts is not None
        assert (
            artifact.normalized_facts.get("title")
            == "Rich Page - everything about Acme widgets"
        )

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.analysis_status == ANALYSIS_STATUS_COMPLETED
        assert crawl.analyzed_url_count == 1

        snapshot = (
            await session.execute(
                select(SiteHealthSnapshot).where(
                    SiteHealthSnapshot.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        assert snapshot.analyzed_url_count == 1
        assert snapshot.web_fundamentals_score is not None
        assert snapshot.issue_count == issue_count


@pytest.mark.asyncio
async def test_analyze_persists_page_kind_classifier_and_current_versions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """v2 P1: the analyze task classifies the page, injects page_kind into
    the facts before rule evaluation, and stamps the current versions on the
    persisted rows."""
    from app.core.config.site_health_contracts import (
        CLASSIFIER_VERSION,
    )

    assert (ANALYZER_VERSION, SCORING_VERSION, CLASSIFIER_VERSION) == (
        "sh-analyzer-1",
        "sh-scoring-1",
        "sh-classifier-1",
    )

    seed, _site_url_id, _task_id = await _seed_analyze_ready(
        session_factory, root="https://example.com/blog/post-1"
    )
    pages = {"/blog/post-1": _rich_html()}
    worker = _worker(session_factory, pages, owner="analyze-p1")
    await worker.run_until_idle()

    async with session_factory() as session:
        analysis = (
            await session.execute(
                select(SitePageAnalysis).where(
                    SitePageAnalysis.crawl_id == seed.crawl_id
                )
            )
        ).scalar_one()
        # The /blog/ path pattern classified the page as an article.
        assert analysis.page_kind == "article"
        assert analysis.classifier_version == "sh-classifier-1"
        assert analysis.analyzer_version == "sh-analyzer-1"
        assert analysis.scoring_version == "sh-scoring-1"

        # The bounded classifier evidence persisted WITH the row (it used to
        # be computed, injected into the facts dict after the artifact flush,
        # and dropped). Its classifier_version matches the row's stamp.
        evidence = analysis.page_kind_evidence
        assert evidence is not None
        assert evidence["classifier_version"] == analysis.classifier_version
        assert evidence["classified_by"] == "path_pattern"
        assert evidence["confidence"] == "medium"
        assert evidence["tier"] == "route"
        assert evidence["signals"][0]["signal"] == "path_pattern"
        assert evidence["signals"][0]["page_kind"] == "article"

        # facts["page_kind"] reached rule evaluation: the thin-content check
        # read the per-type (article) minimum, not the v1 global.
        thin = (
            await session.execute(
                select(SiteRuleEvaluation).where(
                    SiteRuleEvaluation.analysis_id == analysis.id,
                    SiteRuleEvaluation.rule_id == "technical.thin_content",
                )
            )
        ).scalar_one()
        assert thin.evidence["page_kind"] == "article"
        assert thin.evidence["minimum"] == MIN_MEANINGFUL_WORDS
        # A 140-word article used to be "thin" against a 300-word floor. It is
        # short, not defective, and the analyzer cannot tell the difference --
        # so the only thing still reported here is an actually empty page.
        assert thin.outcome == RULE_OUTCOME_SATISFIED
        assert thin.evidence["word_count"] >= MIN_MEANINGFUL_WORDS

        # The crawl rollup carries the per-page-type breakdown.
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        summary = crawl.score_summary or {}
        assert summary.get("scoring_version") == "sh-scoring-1"
        by_page_kind = summary.get("by_page_kind") or {}
        assert set(by_page_kind) == {"article"}
        assert by_page_kind["article"]["analyzed_count"] == 1
        assert by_page_kind["article"]["web_fundamentals_score"] is not None


@pytest.mark.asyncio
async def test_minimal_page_reports_only_observable_issues(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _site_url_id, _task_id = await _seed_analyze_ready(
        session_factory, root="https://example.com/thin"
    )
    pages = {"/thin": _thin_html()}
    worker = _worker(session_factory, pages, owner="analyze-thin")
    await worker.run_until_idle()

    async with session_factory() as session:
        issues = (
            (
                await session.execute(
                    select(SiteIssue.rule_id).where(SiteIssue.crawl_id == seed.crawl_id)
                )
            )
            .scalars()
            .all()
        )
        # Missing optional metadata and merely short copy are advisory or
        # abstained signals. The observable document defects remain issues.
        assert set(issues) == {
            "web.accessibility_document_language",
            "web.mobile_viewport",
        }


@pytest.mark.asyncio
async def test_analyze_robots_denied_fails_task_without_page_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The analyze task enforces robots too: denied URL -> non-retryable
    ``robots_denied`` failure (mapped to ``blocked`` in presentation), no
    page fetch, no analysis row."""
    seed, _site_url_id, task_id = await _seed_analyze_ready(session_factory)
    pages = {"/robots.txt": b"User-agent: *\nDisallow: /\n"}
    requests: list[tuple[str, str]] = []
    worker = _worker(session_factory, pages, owner="p2-adeny", requests=requests)
    await worker.run_until_idle()

    # Only the robots fetch happened — never the denied page.
    assert requests == [("GET", "/robots.txt")]

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, task_id)
        assert task is not None
        assert task.status == TASK_STATUS_FAILED
        assert task.error_code == ERROR_ROBOTS_DENIED

        analysis_count = await session.scalar(
            select(func.count())
            .select_from(SitePageAnalysis)
            .where(SitePageAnalysis.crawl_id == seed.crawl_id)
        )
        assert analysis_count == 0

        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        assert crawl.analysis_status == ANALYSIS_STATUS_CANCELLED
        assert crawl.status == CRAWL_STATUS_COMPLETED
        assert crawl.partial_reason in (None, "")


@pytest.mark.asyncio
async def test_analyze_injects_site_facts_on_root_analysis_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """``facts["site"]`` is injected ONLY into the crawl root's analysis: the
    site_root rules (AI-crawler stance, llms.txt) evaluate exactly once per
    crawl, anchored there; every other page's rows for them are N/A. The
    injected copy never leaks into the persisted artifact facts."""
    root = "https://example.com/"
    second = "https://example.com/a"
    site_facts = {
        "robots": {
            "fetched": True,
            "url": "https://example.com/robots.txt",
            "status_code": 200,
            "ai_crawlers": {
                **{bot: "allow" for bot in AI_CRAWLER_BOTS},
                "GPTBot": "block",
            },
            "sitemaps": ["https://example.com/sitemap.xml"],
        },
        "llms_txt": {
            "fetched": True,
            "url": "https://example.com/llms.txt",
            "status_code": 200,
            "present": True,
        },
        "sitemap": {"fetched": True, "files": ["https://example.com/sitemap.xml"]},
    }
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, second), site_facts=site_facts
        )

    pages = {"/": _html([]), "/a": _html([])}
    worker = _worker(session_factory, pages, owner="p2-inject")
    await worker.run_until_idle()

    async with session_factory() as session:
        by_url = await _analyses_by_page_url(session, seed)
        assert len(by_url) == 2
        root_analysis = by_url["https://example.com/"]
        other_analysis = by_url["https://example.com/a"]

        async def _eval(rule_id, analysis_id):
            return await session.scalar(
                select(SiteRuleEvaluation).where(
                    SiteRuleEvaluation.analysis_id == analysis_id,
                    SiteRuleEvaluation.rule_id == rule_id,
                )
            )

        # Root: the injected stance blocks GPTBot -> the stance rule FAILS;
        # llms.txt is present -> PASS. Provenance is the current rule catalog.
        stance = await _eval("technical.ai_crawler_access", root_analysis.id)
        assert stance is not None
        assert stance.outcome == RULE_OUTCOME_MISSING
        assert stance.evidence["blocked"] == ["GPTBot"]
        assert stance.rule_version == RULE_CATALOG_VERSION == "sh-rules-1"
        llms = await _eval("aeo.llms_txt_present", root_analysis.id)
        assert llms is not None
        assert llms.outcome == RULE_OUTCOME_SATISFIED

        # Non-root: the same rules are N/A (no injection).
        other_stance = await _eval("technical.ai_crawler_access", other_analysis.id)
        assert other_stance is not None
        assert other_stance.outcome == RULE_OUTCOME_NOT_APPLICABLE
        other_llms = await _eval("aeo.llms_txt_present", other_analysis.id)
        assert other_llms is not None
        assert other_llms.outcome == RULE_OUTCOME_NOT_APPLICABLE

        # The injected site copy never lands in the immutable artifact facts,
        # which DO carry the current extractor stamp + the P2 fields. Compared
        # against the config constant rather than a literal: this assertion is
        # about the artifact carrying the version that produced it, not about
        # any particular version number.
        artifact = await session.get(SiteFetchArtifact, root_analysis.artifact_id)
        assert artifact is not None
        facts = artifact.normalized_facts or {}
        assert "site" not in facts
        assert facts.get("extractor_version") == EXTRACTOR_VERSION
        for key in (
            "author",
            "dates",
            "landmarks",
            "question_heading_ratio",
            "hreflang_alternates",
            "inline_script_chars",
        ):
            assert key in facts, key


@pytest.mark.asyncio
async def test_rerun_from_completed_crawl_worker_analyzes_only_reran_url(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Handoff finding 1: a rerun from a COMPLETED crawl runs on a new crawl.

    The domain mints a fresh single-page rerun crawl (no discover root task);
    the worker must analyze ONLY the reran URL and must never re-crawl the site
    (no discover fetch of the root).
    """
    from app.domain.site_health.rerun import rerun_page

    source_url = "https://example.com/rich"
    seed, site_url_id, analyze_task_id = await _seed_analyze_ready(
        session_factory, root=source_url
    )

    # Drive the source crawl to a terminal (COMPLETED) state with the URL
    # already analyzed, mirroring the "re-audit from a completed crawl" case.
    async with session_factory() as session:
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_COMPLETED
        crawl.analysis_status = ANALYSIS_STATUS_COMPLETED
        # The seeded analyze task is already accounted for by the source crawl.
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.id == analyze_task_id)
            .values(status=TASK_STATUS_SUCCEEDED)
        )
        await session.commit()

    # Invoke the domain rerun (what the API endpoint calls). Because there is
    # no active crawl, it mints a fresh rerun crawl.
    async with session_factory() as session:
        from app.domain.site_health.entitlements import resolve_runtime

        runtime = await resolve_runtime(session, seed.workspace_id)
        assert runtime.monitored_url_limit == DEFAULT_SEED_MONITORED_URLS
        result = await rerun_page(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            site_url_id=site_url_id,
        )
        await session.commit()

    assert result.created_new_crawl is True
    new_crawl_id = result.crawl_id
    assert new_crawl_id != seed.crawl_id

    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.path == "/rich":
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=_ByteStream(_rich_html()),
            )
        return httpx.Response(404, stream=_ByteStream(b""))

    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="rerun-worker",
        resolver=_FakeResolver(),
        transport=_HttpxHandlerTransport(handler),
    )
    await worker.run_until_idle()

    async with session_factory() as session:
        # The new crawl's analyze task ran and produced a completed analysis
        # for the reran URL.
        tasks = (
            (
                await session.execute(
                    select(SiteCrawlTask).where(SiteCrawlTask.crawl_id == new_crawl_id)
                )
            )
            .scalars()
            .all()
        )
        analyze_tasks = [t for t in tasks if t.task_kind == TASK_KIND_ANALYZE]
        discover_tasks = [t for t in tasks if t.task_kind == TASK_KIND_DISCOVER]
        # No discover task at all -> the site is never re-crawled.
        assert discover_tasks == []
        assert len(analyze_tasks) == 1
        assert analyze_tasks[0].status == TASK_STATUS_SUCCEEDED
        assert analyze_tasks[0].site_url_id == site_url_id

        analyses = (
            (
                await session.execute(
                    select(SitePageAnalysis).where(
                        SitePageAnalysis.crawl_id == new_crawl_id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(analyses) == 1
        assert analyses[0].site_url_id == site_url_id
        assert analyses[0].status == ANALYSIS_STATUS_COMPLETED

        new_crawl = await session.get(SiteCrawl, new_crawl_id)
        assert new_crawl is not None
        # The rerun crawl terminalizes cleanly.
        assert new_crawl.status in (
            CRAWL_STATUS_COMPLETED,
            CRAWL_STATUS_RUNNING,
        )

    # The worker performs only the robots policy fetch and the requested-page
    # analysis fetch. It never re-crawls the site or probes referenced links.
    gets = [path for method, path in requests if method == "GET"]
    assert gets == ["/robots.txt", "/rich"]
