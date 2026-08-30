"""Shared persisted scenarios for the Site Health API component tests."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_acquisition import (
    ERROR_HTTP_5XX,
    FETCH_ATTEMPT_OUTCOME_ERROR,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_FAILED,
    INITIAL_TASK_GENERATION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_MISSING,
    TASK_KIND_ANALYZE,
    TASK_KIND_DISCOVER,
)
from app.core.config.site_health_crawl_policy import (
    SELECTION_SOURCE_USER,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_SUCCEEDED,
)
from app.domain.site_health.service.issues import issue_group_id
from app.models.project import Project
from app.models.site_health.acquisition import SiteFetchArtifact, SiteFetchAttempt
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.events import SiteCrawlEvent
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.runtime import SiteHealthProfile
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl, SiteUrlObservation
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember

pytestmark = pytest.mark.asyncio


def _hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:64]


@dataclass
class Scenario:
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    crawl_id: uuid.UUID
    monitored_url_id: uuid.UUID
    issue_url_id: uuid.UUID
    canonical_issue_id: uuid.UUID


async def _register(client: httpx.AsyncClient, email: str) -> None:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert reg.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


async def _seed_scenario(session: AsyncSession, *, email: str) -> Scenario:
    """Seed a completed crawl with 3 URLs, one monitored, one with an issue."""
    root = "https://acme.test/"
    workspace = Workspace(name="Acme WS")
    session.add(workspace)
    await session.flush()

    # The user was created by `/auth/register`; attach it to this workspace.
    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    )

    project = Project(
        workspace_id=workspace.id,
        name="Acme Site",
        brand_name="Acme",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=1,
        website_url=root,
    )
    session.add(project)
    await session.flush()

    profile = SiteHealthProfile(
        workspace_id=workspace.id,
        project_id=project.id,
        root_url=root,
        root_host="acme.test",
        registrable_domain="acme.test",
    )
    session.add(profile)
    await session.flush()

    crawl = SiteCrawl(
        workspace_id=workspace.id,
        project_id=project.id,
        profile_id=profile.id,
        status=CRAWL_STATUS_COMPLETED,
        root_url=root,
        random_seed="1",
        admitted_url_count=3,
        analyzed_url_count=2,
        failed_url_count=0,
        rule_catalog_version="v1",
    )
    session.add(crawl)
    await session.flush()

    # Three URLs, ordered a < b < c by normalized_url.
    urls: list[SiteUrl] = []
    for slug in ("a", "b", "c"):
        u = f"{root}{slug}"
        su = SiteUrl(
            workspace_id=workspace.id,
            project_id=project.id,
            normalized_url=u,
            url_hash=_hash(u),
            display_url=u,
            host="acme.test",
            latest_title=f"Page {slug}",
            latest_content_type="text/html",
            last_seen_crawl_id=crawl.id,
        )
        session.add(su)
        urls.append(su)
    await session.flush()
    url_a, url_b, _url_c = urls

    # Admit all three URLs to the crawl. Endpoint reads (page-detail, pages,
    # issues, history, exports) are scoped to URLs with a SiteUrlObservation
    # row for the crawl — exactly what the discover worker writes in production
    # — so the seed must record admission provenance or those reads 404.
    for depth, su in enumerate(urls):
        session.add(
            SiteUrlObservation(
                workspace_id=workspace.id,
                project_id=project.id,
                crawl_id=crawl.id,
                site_url_id=su.id,
                source_kind="root" if depth == 0 else "link",
                depth=depth,
                observed_url=su.normalized_url,
                final_url=su.normalized_url,
                status_code=200,
                content_type="text/html",
                title=su.latest_title or "",
            )
        )
    await session.flush()

    # Monitor url_a.
    session.add(
        MonitoredSiteUrl(
            workspace_id=workspace.id,
            project_id=project.id,
            profile_id=profile.id,
            site_url_id=url_a.id,
            active=True,
            selection_source=SELECTION_SOURCE_USER,
        )
    )

    # url_a + url_b get analyzed (classified article / product — v2 P1);
    # url_b gets a failing rule -> issue.
    for su, with_issue, page_kind in (
        (url_a, False, "article"),
        (url_b, True, "product"),
    ):
        task = SiteCrawlTask(
            crawl_id=crawl.id,
            workspace_id=workspace.id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url=su.normalized_url,
            url_hash=su.url_hash,
            site_url_id=su.id,
            generation=INITIAL_TASK_GENERATION,
            idempotency_key=f"{crawl.id}:analyze:{su.id}:0",
            status=TASK_STATUS_SUCCEEDED,
        )
        session.add(task)
        await session.flush()

        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=crawl.id,
            workspace_id=workspace.id,
            fetch_purpose="analyze",
            requested_url=su.normalized_url,
            final_url=su.normalized_url,
            status_code=200,
            content_type="text/html",
            decoded_bytes=2048,
            normalized_facts={
                "has_html": True,
                "title": su.latest_title,
                "meta_description": "desc",
                "robots": {"noindex": False, "nofollow": False},
                "canonical_url": su.normalized_url,
                "headings": {"h1_count": 1, "counts": {"h2": 2}},
                "images": {"count": 3, "missing_alt": 0},
                "body": {"word_count": 400},
                "structured_data": {"types": ["Article"], "count": 1},
                "links": {
                    "anchors": [
                        {"is_internal": True},
                        {"is_internal": False},
                    ]
                },
                "blocking_resources": {"total": 1},
            },
        )
        session.add(artifact)
        await session.flush()

        analysis = SitePageAnalysis(
            workspace_id=workspace.id,
            project_id=project.id,
            crawl_id=crawl.id,
            site_url_id=su.id,
            artifact_id=artifact.id,
            status=PAGE_ANALYSIS_STATUS_COMPLETED,
            web_fundamentals_score=90.0,
            web_fundamentals_coverage=1.0,
            web_fundamentals_state="measured",
            aeo_readiness_score=80.0,
            aeo_measurement_coverage=0.8,
            aeo_measurement_state="measured",
            analyzer_version="v1",
            scoring_version="v1",
            page_kind=page_kind,
            classifier_version="sh-classifier-1",
            # The bounded classifier evidence the analyze writer persists
            # alongside the classification (shape = to_evidence()).
            page_kind_evidence={
                "classifier_version": "sh-classifier-1",
                "classified_by": "path_pattern",
                "schema_suggested_type": None,
                "confidence": "medium",
                "tier": "route",
                "signals": [
                    {
                        "signal": "path_pattern",
                        "page_kind": page_kind,
                        "tier": "route",
                        "detail": "^/(blog|news|guides)(/|$)",
                    }
                ],
            },
        )
        session.add(analysis)
        await session.flush()

        if with_issue:
            evaluation = SiteRuleEvaluation(
                workspace_id=workspace.id,
                analysis_id=analysis.id,
                source_artifact_id=artifact.id,
                rule_id="technical.title_present",
                dimension="technical",
                category="meta",
                severity="critical",
                weight=1.0,
                outcome=RULE_OUTCOME_MISSING,
                evidence={"observed": "missing"},
                analyzer_version="v1",
                rule_version="v1",
            )
            session.add(evaluation)
            await session.flush()
            issue = SiteIssue(
                workspace_id=workspace.id,
                project_id=project.id,
                crawl_id=crawl.id,
                site_url_id=su.id,
                analysis_id=analysis.id,
                evaluation_id=evaluation.id,
                source_artifact_id=artifact.id,
                rule_id="technical.title_present",
                dimension="technical",
                category="meta",
                severity="critical",
                evidence={"observed": "missing"},
                description="The page has no HTML title element.",
                remediation="Add a <title> tag.",
                analyzer_version="v1",
                rule_version="v1",
            )
            session.add(issue)
            await session.flush()

    session.add(
        SiteCrawlEvent(
            crawl_id=crawl.id,
            event_type="crawl.completed",
            message="Crawl completed",
            payload={"analyzed": 2},
        )
    )
    # A discovery-progress event carrying a protected total-bearing field, so
    # the Free-redaction test can assert the API strips it rather than only
    # asserting on an event that never carried the sensitive key.
    session.add(
        SiteCrawlEvent(
            crawl_id=crawl.id,
            event_type="discovery.progress",
            message="discovery progress",
            payload={"discovered_total": 42, "admitted": 3},
        )
    )
    await session.commit()

    return Scenario(
        workspace_id=workspace.id,
        project_id=project.id,
        crawl_id=crawl.id,
        monitored_url_id=url_a.id,
        issue_url_id=url_b.id,
        canonical_issue_id=issue_group_id(crawl.id, "technical.title_present"),
    )


async def _add_second_crawl(
    session: AsyncSession,
    scn: Scenario,
    *,
    admit_slugs: tuple[str, ...],
) -> SiteCrawl:
    """Seed a later crawl for the same project that admits only ``admit_slugs``.

    Reuses the project's existing ``SiteUrl`` rows (a downgrade re-crawls the
    same site) but records a ``SiteUrlObservation`` only for the requested
    slugs, so the crawl's admitted set is a strict subset of the project's
    historical catalog.
    """
    profile = await session.scalar(
        select(SiteHealthProfile).where(SiteHealthProfile.project_id == scn.project_id)
    )
    assert profile is not None
    crawl = SiteCrawl(
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        profile_id=profile.id,
        status=CRAWL_STATUS_COMPLETED,
        root_url=profile.root_url,
        random_seed="2",
        admitted_url_count=len(admit_slugs),
        analyzed_url_count=0,
        failed_url_count=0,
        rule_catalog_version="v1",
    )
    session.add(crawl)
    await session.flush()

    for depth, slug in enumerate(admit_slugs):
        normalized = f"{profile.root_url}{slug}"
        su = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == scn.project_id,
                SiteUrl.normalized_url == normalized,
            )
        )
        assert su is not None
        session.add(
            SiteUrlObservation(
                workspace_id=scn.workspace_id,
                project_id=scn.project_id,
                crawl_id=crawl.id,
                site_url_id=su.id,
                source_kind="root" if depth == 0 else "link",
                depth=depth,
                observed_url=su.normalized_url,
                final_url=su.normalized_url,
                status_code=200,
                content_type="text/html",
                title=su.latest_title or "",
            )
        )
    await session.commit()
    return crawl


async def _seed_issue_for_url(
    session: AsyncSession,
    scn: Scenario,
    *,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    rule_id: str,
    dimension: str = "technical",
    category: str = "meta",
    severity: str = "critical",
) -> uuid.UUID:
    """Seed a full analyze task + artifact + analysis + evaluation + issue.

    ``SiteIssue`` requires non-null ``analysis_id`` / ``evaluation_id`` /
    ``source_artifact_id`` (and ``evaluation_id`` is unique), so an extra issue
    cannot be a bare row — it needs its own supporting rows, exactly like the
    base scenario. Returns the new issue id.
    """
    su = await session.get(SiteUrl, site_url_id)
    assert su is not None
    task = SiteCrawlTask(
        crawl_id=crawl_id,
        workspace_id=scn.workspace_id,
        task_kind=TASK_KIND_ANALYZE,
        requested_url=su.normalized_url,
        url_hash=su.url_hash,
        site_url_id=su.id,
        generation=INITIAL_TASK_GENERATION,
        idempotency_key=f"{crawl_id}:analyze:{su.id}:{rule_id}",
        status=TASK_STATUS_SUCCEEDED,
    )
    session.add(task)
    await session.flush()
    artifact = SiteFetchArtifact(
        task_id=task.id,
        crawl_id=crawl_id,
        workspace_id=scn.workspace_id,
        fetch_purpose="analyze",
        requested_url=su.normalized_url,
        final_url=su.normalized_url,
        status_code=200,
        content_type="text/html",
        decoded_bytes=1024,
        normalized_facts={"has_html": True},
    )
    session.add(artifact)
    await session.flush()
    analysis = SitePageAnalysis(
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        crawl_id=crawl_id,
        site_url_id=su.id,
        artifact_id=artifact.id,
        status=PAGE_ANALYSIS_STATUS_COMPLETED,
        analyzer_version="v1",
        scoring_version="v1",
    )
    session.add(analysis)
    await session.flush()
    evaluation = SiteRuleEvaluation(
        workspace_id=scn.workspace_id,
        analysis_id=analysis.id,
        source_artifact_id=artifact.id,
        rule_id=rule_id,
        dimension=dimension,
        category=category,
        severity=severity,
        weight=1.0,
        outcome=RULE_OUTCOME_MISSING,
        evidence={"observed": "missing"},
        analyzer_version="v1",
        rule_version="v1",
    )
    session.add(evaluation)
    await session.flush()
    issue = SiteIssue(
        workspace_id=scn.workspace_id,
        project_id=scn.project_id,
        crawl_id=crawl_id,
        site_url_id=su.id,
        analysis_id=analysis.id,
        evaluation_id=evaluation.id,
        source_artifact_id=artifact.id,
        rule_id=rule_id,
        dimension=dimension,
        category=category,
        severity=severity,
        evidence={"observed": "missing"},
        remediation="Fix it.",
        analyzer_version="v1",
        rule_version="v1",
    )
    session.add(issue)
    await session.flush()
    return issue.id


async def _seed_failed_crawl(session: AsyncSession, *, email: str) -> Scenario:
    """Seed a FAILED crawl whose root fetch lost 3 retried calls (HTTP 500).

    The evidence shape the worker persists for a fully-failed crawl: a
    terminally failed root discover task plus one ``SiteFetchAttempt`` error
    row per REAL network call — and NO SiteUrl rows at all (a root failure
    never admits a page).
    """
    root = "https://broken.test/"
    workspace = Workspace(name="Broken WS")
    session.add(workspace)
    await session.flush()

    user = await session.scalar(select(User).where(User.email == email))
    assert user is not None
    session.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    )

    project = Project(
        workspace_id=workspace.id,
        name="Broken Site",
        brand_name="Broken",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=1,
        website_url=root,
    )
    session.add(project)
    await session.flush()

    profile = SiteHealthProfile(
        workspace_id=workspace.id,
        project_id=project.id,
        root_url=root,
        root_host="broken.test",
        registrable_domain="broken.test",
    )
    session.add(profile)
    await session.flush()

    crawl = SiteCrawl(
        workspace_id=workspace.id,
        project_id=project.id,
        profile_id=profile.id,
        status=CRAWL_STATUS_FAILED,
        discovery_status="failed",
        analysis_status="failed",
        root_url=root,
        random_seed="1",
        discovered_url_count=0,
        admitted_url_count=0,
        analyzed_url_count=0,
        failed_url_count=1,
        inventory_complete=False,
        rule_catalog_version="v1",
        error_message="The site returned HTTP 500 after 3 attempts",
    )
    session.add(crawl)
    await session.flush()

    task = SiteCrawlTask(
        crawl_id=crawl.id,
        workspace_id=workspace.id,
        task_kind=TASK_KIND_DISCOVER,
        requested_url=root,
        url_hash=_hash(root),
        generation=INITIAL_TASK_GENERATION,
        idempotency_key=f"{crawl.id}:discover:root:0",
        status=TASK_STATUS_FAILED,
        depth=0,
        attempt_count=3,
        error_code=ERROR_HTTP_5XX,
        error_detail="the server returned HTTP 500",
    )
    session.add(task)
    await session.flush()

    for attempt_number in (1, 2, 3):
        session.add(
            SiteFetchAttempt(
                task_id=task.id,
                crawl_id=crawl.id,
                workspace_id=workspace.id,
                attempt_number=attempt_number,
                request_ordinal=0,
                method="GET",
                target_host="broken.test",
                outcome=FETCH_ATTEMPT_OUTCOME_ERROR,
                error_code=ERROR_HTTP_5XX,
                status_code=500,
                latency_ms=100 * attempt_number,
            )
        )
    await session.commit()
    return Scenario(
        workspace_id=workspace.id,
        project_id=project.id,
        crawl_id=crawl.id,
        monitored_url_id=uuid.uuid4(),  # unused by these tests
        issue_url_id=uuid.uuid4(),
        canonical_issue_id=uuid.uuid4(),
    )
