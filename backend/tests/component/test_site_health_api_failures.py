"""Site Health failure, frozen-copy, and dashboard evidence projections."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health_acquisition import (
    ERROR_HTTP_4XX,
    ERROR_HTTP_5XX,
    ERROR_ROBOTS_DENIED,
    ERROR_TIMEOUT,
    ERROR_URL_ADMISSION_REJECTED,
    FETCH_ATTEMPT_OUTCOME_ERROR,
)
from app.core.config.site_health_contracts import (
    ANALYSIS_STATUS_RUNNING,
    CRAWL_STATUS_RUNNING,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_USER,
)
from app.core.config.site_health_rules import (
    SITE_HEALTH_RULES_BY_ID,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_RETRY_WAIT,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl
from tests.component.site_health_api_helpers import (
    _hash,
    _register,
    _seed_failed_crawl,
    _seed_scenario,
)

pytestmark = pytest.mark.asyncio


async def test_failed_crawl_surfaces_failure_summary_and_root_errors(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """B1/B3: the failed crawl explains itself on every single-crawl read."""
    await _register(client, "failed@example.com")
    async with session_factory() as session:
        scn = await _seed_failed_crawl(session, email="failed@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    expected_summary = {
        "code": ERROR_HTTP_5XX,
        "message": "The site returned HTTP 500 after 3 attempts",
        "attempts": 3,
        "status_code": 500,
        "target_url": "https://broken.test/",
    }

    # Crawl summary carries the humanized failure summary (SH-2/SH-5).
    summary = await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["failure_summary"] == expected_summary

    # The list projection deliberately leaves it None (N+1 avoidance).
    listing = await client.get(
        f"/api/v1/site-crawls?project_id={scn.project_id}", headers=headers
    )
    assert listing.status_code == 200
    listed = [r for r in listing.json()["items"] if r["id"] == str(scn.crawl_id)]
    assert listed and listed[0]["failure_summary"] is None

    # Pages: no page rows exist for a root failure, but the failed root calls
    # ride alongside as root_errors (SH-4) in call order.
    pages = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages", headers=headers
    )
    assert pages.status_code == 200
    page_body = pages.json()
    assert page_body["items"] == []
    assert page_body["root_errors"] == [
        {
            "method": "GET",
            "target": "https://broken.test/",
            "outcome": FETCH_ATTEMPT_OUTCOME_ERROR,
            "error_code": ERROR_HTTP_5XX,
            "status_code": 500,
            "latency_ms": 100 * attempt_number,
        }
        for attempt_number in (1, 2, 3)
    ]

    # Dashboard: the crawl projection carries the summary AND the top-level
    # root_errors so the failed dashboard needs no second fetch.
    dashboard = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
    )
    assert dashboard.status_code == 200
    dash_body = dashboard.json()
    assert dash_body["crawl"]["failure_summary"] == expected_summary
    assert dash_body["root_errors"] == page_body["root_errors"]


async def test_healthy_crawl_has_no_failure_summary_or_root_errors(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The B1/B3 projections are null/empty on any crawl that did not fail."""
    await _register(client, "healthy@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="healthy@example.com")
    headers = {"X-Workspace-Id": str(scn.workspace_id)}

    summary = await client.get(f"/api/v1/site-crawls/{scn.crawl_id}", headers=headers)
    assert summary.status_code == 200
    assert summary.json()["failure_summary"] is None

    pages = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/pages", headers=headers
    )
    assert pages.status_code == 200
    assert pages.json()["root_errors"] == []

    dashboard = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
    )
    assert dashboard.status_code == 200
    dash_body = dashboard.json()
    assert dash_body["crawl"]["failure_summary"] is None
    assert dash_body["root_errors"] == []


async def test_issue_description_is_frozen_across_catalog_copy_changes(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "frozen-issue-description@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(
            session, email="frozen-issue-description@example.com"
        )

    rule = SITE_HEALTH_RULES_BY_ID["technical.title_present"]
    monkeypatch.setattr(
        rule, "description", "New catalog copy must not rewrite history."
    )
    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    listing = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues", headers=headers
    )
    detail = await client.get(
        f"/api/v1/site-crawls/{scn.crawl_id}/issues/{scn.canonical_issue_id}",
        headers=headers,
    )

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert listing.json()["items"][0]["description"] == (
        "The page has no HTML title element."
    )
    assert detail.json()["description"] == "The page has no HTML title element."


async def test_dashboard_projects_failure_breakdown_and_evidence_activity(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """S03: persisted task evidence distinguishes blocked, waiting, and stalled."""
    await _register(client, "progress-evidence@example.com")
    now = datetime.now(UTC)
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="progress-evidence@example.com")
        crawl = await session.get(SiteCrawl, scn.crawl_id)
        assert crawl is not None
        crawl.status = CRAWL_STATUS_RUNNING
        crawl.analysis_status = ANALYSIS_STATUS_RUNNING
        crawl.completed_at = None

        for index, error_code in enumerate(
            (ERROR_ROBOTS_DENIED, ERROR_HTTP_4XX, ERROR_HTTP_5XX, ERROR_TIMEOUT),
            start=1,
        ):
            url = f"https://acme.test/progress-{index}"
            site_url = SiteUrl(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                normalized_url=url,
                url_hash=_hash(url),
                display_url=url,
                host="acme.test",
                last_seen_crawl_id=crawl.id,
            )
            session.add(site_url)
            await session.flush()
            session.add(
                MonitoredSiteUrl(
                    workspace_id=scn.workspace_id,
                    project_id=scn.project_id,
                    profile_id=crawl.profile_id,
                    site_url_id=site_url.id,
                    active=True,
                    selection_source=SELECTION_SOURCE_USER,
                )
            )
            session.add(
                SiteCrawlTask(
                    crawl_id=crawl.id,
                    workspace_id=scn.workspace_id,
                    site_url_id=site_url.id,
                    task_kind=TASK_KIND_ANALYZE,
                    requested_url=url,
                    url_hash=site_url.url_hash,
                    idempotency_key=f"{crawl.id}:analyze:progress:{index}",
                    status=TASK_STATUS_FAILED,
                    error_code=error_code,
                )
            )

        wait_url = "https://acme.test/host-wait"
        waiting_site_url = SiteUrl(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            normalized_url=wait_url,
            url_hash=_hash(wait_url),
            display_url=wait_url,
            host="acme.test",
            last_seen_crawl_id=crawl.id,
        )
        session.add(waiting_site_url)
        await session.flush()
        session.add(
            MonitoredSiteUrl(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                profile_id=crawl.profile_id,
                site_url_id=waiting_site_url.id,
                active=True,
                selection_source=SELECTION_SOURCE_USER,
            )
        )
        waiting_task = SiteCrawlTask(
            crawl_id=crawl.id,
            workspace_id=scn.workspace_id,
            site_url_id=waiting_site_url.id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url=wait_url,
            url_hash=waiting_site_url.url_hash,
            idempotency_key=f"{crawl.id}:analyze:host-wait",
            status=TASK_STATUS_LEASED,
            lease_owner="progress-worker",
            lease_expires_at=now + timedelta(minutes=1),
            heartbeat_at=now,
        )
        session.add(waiting_task)
        retry_url = "https://acme.test/retrying-timeout"
        retry_site_url = SiteUrl(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            normalized_url=retry_url,
            url_hash=_hash(retry_url),
            display_url=retry_url,
            host="acme.test",
            last_seen_crawl_id=crawl.id,
        )
        session.add(retry_site_url)
        await session.flush()
        retry_timeout = SiteCrawlTask(
            crawl_id=crawl.id,
            workspace_id=scn.workspace_id,
            site_url_id=retry_site_url.id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url=retry_url,
            url_hash=retry_site_url.url_hash,
            idempotency_key=f"{crawl.id}:analyze:retry-timeout",
            status=TASK_STATUS_RETRY_WAIT,
            available_at=now + timedelta(minutes=2),
            error_code=ERROR_TIMEOUT,
        )
        session.add(retry_timeout)
        await session.commit()

    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    response = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
    )
    assert response.status_code == 200
    counters = response.json()["crawl"]["counters"]
    assert counters["failure_breakdown"] == {
        "robots_denied": 1,
        "http_4xx": 1,
        "http_5xx": 1,
        "timeout": 1,
    }
    assert counters["blocked"] == 1
    assert counters["errors"] == 3
    assert counters["activity"]["state"] == "waiting"
    assert counters["activity"]["reason"] == "host_gate"
    assert counters["activity"]["queue_depth"] == 2
    assert counters["activity"]["next_available_at"] is not None

    async with session_factory() as session:
        task = await session.get(SiteCrawlTask, waiting_task.id)
        assert task is not None
        task.lease_expires_at = now - timedelta(seconds=1)
        await session.commit()

    stalled = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
    )
    assert stalled.status_code == 200
    stalled_activity = stalled.json()["crawl"]["counters"]["activity"]
    assert stalled_activity["state"] == "stalled"
    assert stalled_activity["reason"] == "expired_lease"
    assert stalled_activity["queue_depth"] == 2
    assert stalled_activity["next_available_at"] is not None


async def test_policy_excluded_url_leaves_both_sides_of_the_analyzed_ratio(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A URL rejected by our own policy is an exclusion, never a failed page.

    ``/customer_authentication/redirect`` is same-host and passes admission at
    discovery, so it reserves a page of budget; only when the fetch resolves
    does it 302 onto ``account.<domain>`` and get rejected. Counting that as a
    failure is what made every Shopify crawl report ``analyzed`` one short of
    ``discovered`` -- 499/500 -- forever. It has to leave BOTH sides.
    """
    await _register(client, "policy-excluded@example.com")
    async with session_factory() as session:
        scn = await _seed_scenario(session, email="policy-excluded@example.com")
        crawl = await session.get(SiteCrawl, scn.crawl_id)
        assert crawl is not None
        # Absolute counts are disclosed only when the crawl froze that in.
        crawl.sample_mode = False
        crawl.configuration = {**(crawl.configuration or {}), "count_disclosure": True}
        # Four admitted URLs; two turn out to be auth redirectors. The second
        # is rejected before a durable SiteUrl identity can be attached.
        crawl.admitted_url_count = 4
        excluded_url = "https://acme.test/customer_authentication/redirect"
        site_url = SiteUrl(
            workspace_id=scn.workspace_id,
            project_id=scn.project_id,
            normalized_url=excluded_url,
            url_hash=_hash(excluded_url),
            display_url=excluded_url,
            host="acme.test",
            last_seen_crawl_id=crawl.id,
        )
        session.add(site_url)
        await session.flush()
        session.add(
            MonitoredSiteUrl(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                profile_id=crawl.profile_id,
                site_url_id=site_url.id,
                active=True,
                selection_source=SELECTION_SOURCE_USER,
            )
        )
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=scn.workspace_id,
                site_url_id=site_url.id,
                task_kind=TASK_KIND_ANALYZE,
                requested_url=excluded_url,
                url_hash=site_url.url_hash,
                idempotency_key=f"{crawl.id}:analyze:auth-redirect",
                status=TASK_STATUS_FAILED,
                error_code=ERROR_URL_ADMISSION_REJECTED,
            )
        )
        identityless_url = "https://acme.test/account/redirect"
        session.add(
            SiteCrawlTask(
                crawl_id=crawl.id,
                workspace_id=scn.workspace_id,
                site_url_id=None,
                task_kind=TASK_KIND_DISCOVER,
                requested_url=identityless_url,
                url_hash=_hash(identityless_url),
                idempotency_key=f"{crawl.id}:discover:identityless-redirect",
                status=TASK_STATUS_FAILED,
                error_code=ERROR_URL_ADMISSION_REJECTED,
            )
        )
        await session.commit()

    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    dashboard = await client.get(
        f"/api/v1/projects/{scn.project_id}/site-health", headers=headers
    )
    assert dashboard.status_code == 200
    counters = dashboard.json()["crawl"]["counters"]

    # Four URLs were admitted and two were excluded, including the one without
    # a SiteUrl identity, so the denominator is 2 rather than 3 or 4.
    assert counters["discovered"] == 2
    # And it is neither an error nor a "blocked" page: nothing went wrong.
    assert counters["errors"] == 0
    assert counters["blocked"] == 0
