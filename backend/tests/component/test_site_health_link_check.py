"""Link-check phase: target resolution, probe provenance, robots-denied targets.

Split from the former test_site_health_worker.py monolith; shared setup lives
in ``site_health_worker_helpers``.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_contracts import (
    CRAWL_STATUS_RUNNING,
    RULE_OUTCOME_PASS,
)
from app.core.config.task_queue import (
    TASK_STATUS_QUEUED,
    TASK_STATUS_SUCCEEDED,
)
from app.models.site_health.analysis import SiteLinkReference, SiteRuleEvaluation
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.workers.site_health_worker import (
    SiteHealthWorker,
)
from tests.component.site_health_worker_helpers import (
    _analyses_by_page_url,
    _ByteStream,
    _FakeResolver,
    _seed_analyze_phase_crawl,
    _seed_analyze_ready,
    _worker,
)


@pytest.mark.asyncio
async def test_link_check_resolves_relative_targets_and_records_probe_provenance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.core.config.site_health_contracts import (
        TASK_KIND_LINK_CHECK,
    )

    source_url = "https://example.com/base/page"
    seed, site_url_id, _task_id = await _seed_analyze_ready(
        session_factory, root=source_url
    )
    source_html = (
        b"<html><head><title>Links</title></head><body>"
        b'<a href="../ok">head works</a>'
        b'<a href="/fallback">get fallback</a>'
        b'<a href="missing">missing</a>'
        b"</body></html>"
    )
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method_path = (request.method, request.url.path)
        requests.append(method_path)
        if method_path == ("GET", "/base/page"):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=_ByteStream(source_html),
            )
        if method_path == ("HEAD", "/ok"):
            return httpx.Response(200, stream=_ByteStream(b""))
        if method_path == ("HEAD", "/fallback"):
            return httpx.Response(405, stream=_ByteStream(b""))
        if method_path == ("GET", "/fallback"):
            return httpx.Response(200, stream=_ByteStream(b"ok"))
        if method_path == ("HEAD", "/base/missing"):
            return httpx.Response(404, stream=_ByteStream(b""))
        return httpx.Response(404, stream=_ByteStream(b""))

    transport = httpx.MockTransport(handler)
    worker = SiteHealthWorker(
        session_factory=session_factory,
        owner="link-analyze",
        resolver=_FakeResolver(),
        transport=transport,
    )
    await worker.run_until_idle()

    # The analyze task's completion auto-enqueues this URL's ``link_check``
    # task (idempotent, same crawl/generation/url_hash slot); re-open the
    # crawl so the worker can run it (it terminalized after analyze).
    async with session_factory() as session:
        link_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_CHECK,
                SiteCrawlTask.site_url_id == site_url_id,
            )
        )
        assert link_task is not None
        link_task_id = link_task.id
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_RUNNING
        await session.commit()

    worker2 = SiteHealthWorker(
        session_factory=session_factory,
        owner="link-check",
        resolver=_FakeResolver(),
        transport=transport,
    )
    await worker2.run_until_idle()

    async with session_factory() as session:
        refs = (
            (
                await session.execute(
                    select(SiteLinkReference).where(
                        SiteLinkReference.workspace_id == seed.workspace_id
                    )
                )
            )
            .scalars()
            .all()
        )
        by_url = {ref.target_url: ref for ref in refs}
        assert set(by_url) == {
            "https://example.com/ok",
            "https://example.com/fallback",
            "https://example.com/base/missing",
        }
        assert all(ref.target_task_id == link_task_id for ref in refs)
        # The existing schema has no reachability/status column. Its semantic
        # evidence fingerprint exposes the outcome prefix and hashes the
        # method/status evidence without overloading rel.
        assert by_url["https://example.com/ok"].evidence_fingerprint.startswith(
            "reachable:"
        )
        assert by_url["https://example.com/fallback"].evidence_fingerprint.startswith(
            "reachable:"
        )
        assert by_url[
            "https://example.com/base/missing"
        ].evidence_fingerprint.startswith("unreachable:")
        assert len({ref.evidence_fingerprint for ref in refs}) == 3

    assert ("HEAD", "/ok") in requests
    assert ("GET", "/ok") not in requests
    assert requests.index(("HEAD", "/fallback")) < requests.index(("GET", "/fallback"))
    assert ("HEAD", "/base/missing") in requests
    assert ("GET", "/base/missing") not in requests


@pytest.mark.asyncio
async def test_reclaimed_link_check_does_not_reprobe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A reclaimed link-check task acks its durable references, no re-probe.

    Handoff finding 7: the link-check path commits ``SiteLinkReference`` rows
    BEFORE the out-of-transaction ``_queue.succeed()``. If that ack is lost the
    lease is reclaimed and the task re-runs. Without durable-ack recovery the
    reclaimed run would re-HEAD/GET every referenced link over the network. The
    reclaimed run must instead acknowledge the persisted references and never
    probe again.
    """
    from app.core.config.site_health_contracts import (
        TASK_KIND_LINK_CHECK,
    )

    source_url = "https://example.com/base/page"
    seed, site_url_id, _task_id = await _seed_analyze_ready(
        session_factory, root=source_url
    )
    source_html = (
        b"<html><head><title>Links</title></head><body>"
        b'<a href="/ok">ok</a>'
        b"</body></html>"
    )
    probe_paths: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        method_path = (request.method, request.url.path)
        if method_path == ("GET", "/base/page"):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                stream=_ByteStream(source_html),
            )
        # Any request to /ok is a link PROBE (HEAD/GET); record it.
        if request.url.path == "/ok":
            probe_paths.append(method_path)
            return httpx.Response(200, stream=_ByteStream(b""))
        return httpx.Response(404, stream=_ByteStream(b""))

    transport = httpx.MockTransport(handler)

    # Run analyze + link_check normally with one worker: the link_check task
    # is auto-enqueued and executed, probing /ok and committing its
    # ``SiteLinkReference`` row before acknowledging the queue.
    first = SiteHealthWorker(
        session_factory=session_factory,
        owner="link-first",
        resolver=_FakeResolver(),
        transport=transport,
    )
    await first.run_until_idle()

    async with session_factory() as session:
        link_task = await session.scalar(
            select(SiteCrawlTask).where(
                SiteCrawlTask.crawl_id == seed.crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_LINK_CHECK,
                SiteCrawlTask.site_url_id == site_url_id,
            )
        )
        assert link_task is not None
        link_task_id = link_task.id
        # The first run genuinely probed the link and committed one reference.
        assert probe_paths, "first run should have probed the link"
        probes_after_first = len(probe_paths)
        refs_after_first = await session.scalar(
            select(func.count())
            .select_from(SiteLinkReference)
            .where(SiteLinkReference.target_task_id == link_task_id)
        )
        assert refs_after_first == 1
        # Simulate a lost queue ack: the task committed its references but the
        # worker crashed/restarted before the out-of-transaction
        # ``_queue.succeed`` durably marked it done, so the lease is reclaimed
        # and the task is re-queued.
        await session.execute(
            update(SiteCrawlTask)
            .where(SiteCrawlTask.id == link_task_id)
            .values(
                status=TASK_STATUS_QUEUED,
                lease_owner=None,
                lease_expires_at=None,
            )
        )
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_RUNNING
        await session.commit()

    # Reclaimed run: must ack the durable references and NOT re-probe.
    reclaimed = SiteHealthWorker(
        session_factory=session_factory,
        owner="link-reclaimed",
        resolver=_FakeResolver(),
        transport=transport,
    )
    await reclaimed.run_until_idle()

    async with session_factory() as session:
        link_task = await session.get(SiteCrawlTask, link_task_id)
        assert link_task is not None
        refs_after_reclaim = await session.scalar(
            select(func.count())
            .select_from(SiteLinkReference)
            .where(SiteLinkReference.target_task_id == link_task_id)
        )
        assert link_task.status == TASK_STATUS_SUCCEEDED
        assert refs_after_reclaim == 1
    # No additional probes happened on the reclaimed run.
    assert len(probe_paths) == probes_after_first


@pytest.mark.asyncio
async def test_link_check_honors_robots_and_skips_denied_targets(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Link-check probes honor robots.txt: a denied target is NOT probed
    (no HEAD/GET request) and records a distinct ``policy_skipped:``
    fingerprint, so the finalize pass's ``broken_internal_link`` counts
    only the actually-probed link as checked (the skipped one is neither
    checked nor broken)."""

    root = "https://example.com/rich"
    second = "https://example.com/plain"
    async with session_factory() as session:
        seed, _ids = await _seed_analyze_phase_crawl(
            session, root=root, urls=(root, second)
        )

    rich_html = (
        b"<html><head><title>Root page about widgets and gadgets</title>"
        b"</head><body><h1>Root</h1>"
        b"<p>Root body text with enough words to matter for the checks.</p>"
        b'<a href="https://example.com/blocked-link">blocked</a>'
        b'<a href="https://example.com/ok-link">ok</a>'
        b"</body></html>"
    )
    plain_html = (
        b"<html><head><title>Plain</title></head><body><p>plain</p></body></html>"
    )
    pages = {
        "/robots.txt": b"User-agent: *\nDisallow: /blocked-link\n",
        "/rich": rich_html,
        "/plain": plain_html,
        "/ok-link": b"<html><head><title>OK</title></head><body>ok</body></html>",
    }
    requests: list[tuple[str, str]] = []
    worker = _worker(session_factory, pages, owner="p2-linkrobots", requests=requests)
    await worker.run_until_idle()

    # The denied target was never probed; the allowed one was (HEAD first).
    assert ("HEAD", "/blocked-link") not in requests
    assert ("GET", "/blocked-link") not in requests
    assert ("HEAD", "/ok-link") in requests

    async with session_factory() as session:
        refs = (
            (
                await session.execute(
                    select(SiteLinkReference).where(
                        SiteLinkReference.workspace_id == seed.workspace_id
                    )
                )
            )
            .scalars()
            .all()
        )
        by_url = {ref.target_url: ref for ref in refs}
        assert set(by_url) == {
            "https://example.com/blocked-link",
            "https://example.com/ok-link",
        }
        assert by_url[
            "https://example.com/blocked-link"
        ].evidence_fingerprint.startswith("policy_skipped:")
        assert by_url["https://example.com/ok-link"].evidence_fingerprint.startswith(
            "reachable:"
        )

        # Finalize counted only the probed link; the policy-skipped one is
        # neither checked nor broken.
        by_page = await _analyses_by_page_url(session, seed)
        root_analysis = by_page["https://example.com/rich"]
        evals = {
            row.rule_id: row
            for row in (
                await session.execute(
                    select(SiteRuleEvaluation).where(
                        SiteRuleEvaluation.analysis_id == root_analysis.id
                    )
                )
            )
            .scalars()
            .all()
        }
        broken = evals["technical.broken_internal_link"]
        assert broken.outcome == RULE_OUTCOME_PASS
        assert broken.evidence["checked_count"] == 1
        assert broken.evidence["broken_count"] == 0
