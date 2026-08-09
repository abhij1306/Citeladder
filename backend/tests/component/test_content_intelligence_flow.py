"""Education and Commerce acceptance flows for Content Intelligence."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.content import content_settings
from app.core.config.site_health import (
    CRAWL_STATUS_COMPLETED,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    TASK_KIND_ANALYZE,
)
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.models.project import Project
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteHealthProfile,
    SiteHealthSnapshot,
    SitePageAnalysis,
    SiteUrl,
)
from app.workers.content_worker import ContentWorker


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201


async def _create_project(client: httpx.AsyncClient, pack_id: str) -> uuid.UUID:
    response = await client.post(
        "/api/v1/projects",
        json={
            "name": f"{pack_id.title()} Content",
            "brand_name": "Acceptance",
            "website_url": "https://acceptance.example",
            "country_code": "US",
            "language_code": "en-US",
            "industry": pack_id,
            "benchmark_mode": "consumer_like",
            "default_repetitions": 1,
        },
    )
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


def _provider_transport(output: str) -> httpx.MockTransport:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "content-acceptance-model",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": output},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 12,
                    "total_tokens": 22,
                },
            },
        )

    return httpx.MockTransport(handler)


async def _seed_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: uuid.UUID,
    pack_id: str,
    question_id: str,
    question: str,
    observed: bool,
    created_at: datetime,
) -> SiteHealthSnapshot:
    async with session_factory() as session:
        project = await session.get(Project, project_id)
        assert project is not None
        profile = await session.scalar(
            select(SiteHealthProfile).where(SiteHealthProfile.project_id == project_id)
        )
        if profile is None:
            profile = SiteHealthProfile(
                workspace_id=project.workspace_id,
                project_id=project.id,
                root_url="https://acceptance.example/",
                root_host="acceptance.example",
                registrable_domain="acceptance.example",
            )
            session.add(profile)
            await session.flush()
        crawl = SiteCrawl(
            workspace_id=project.workspace_id,
            project_id=project.id,
            profile_id=profile.id,
            status=CRAWL_STATUS_COMPLETED,
            root_url="https://acceptance.example/",
            random_seed=uuid.uuid4().hex,
            completed_at=created_at,
            created_at=created_at,
        )
        session.add(crawl)
        await session.flush()
        target_url = "https://acceptance.example/help"
        site_url = await session.scalar(
            select(SiteUrl).where(
                SiteUrl.project_id == project_id,
                SiteUrl.normalized_url == target_url,
            )
        )
        if site_url is None:
            site_url = SiteUrl(
                workspace_id=project.workspace_id,
                project_id=project.id,
                normalized_url=target_url,
                url_hash=hashlib.sha256(target_url.encode()).hexdigest(),
                display_url=target_url,
                host="acceptance.example",
            )
            session.add(site_url)
            await session.flush()
        task = SiteCrawlTask(
            crawl_id=crawl.id,
            workspace_id=project.workspace_id,
            site_url_id=site_url.id,
            task_kind=TASK_KIND_ANALYZE,
            requested_url=target_url,
            url_hash=site_url.url_hash,
            idempotency_key=f"{crawl.id}:acceptance",
            status=TASK_STATUS_SUCCEEDED,
        )
        session.add(task)
        await session.flush()
        facts: dict[str, object] = {
            "title": "Help",
            "headings": {"h1_texts": ["Help"]},
        }
        if observed:
            facts["faq"] = [{"question": question, "answer": "Contact our team."}]
        artifact = SiteFetchArtifact(
            task_id=task.id,
            crawl_id=crawl.id,
            workspace_id=project.workspace_id,
            fetch_purpose="analyze",
            requested_url=target_url,
            final_url=target_url,
            status_code=200,
            content_type="text/html",
            content_hash=hashlib.sha256(str(facts).encode()).hexdigest(),
            normalized_facts=facts,
            created_at=created_at,
        )
        session.add(artifact)
        await session.flush()
        analysis = SitePageAnalysis(
            workspace_id=project.workspace_id,
            project_id=project.id,
            crawl_id=crawl.id,
            site_url_id=site_url.id,
            artifact_id=artifact.id,
            status=PAGE_ANALYSIS_STATUS_COMPLETED,
            page_kind="faq",
            industry_role_id=(
                "education.admissions" if pack_id == "education" else "commerce.policy"
            ),
            temporal_state="current",
            analyzer_version="acceptance-analyzer-v1",
            scoring_version="acceptance-scoring-v1",
            classifier_version="acceptance-classifier-v1",
            industry_pack_id=pack_id,
            industry_pack_version="1.0.0",
            created_at=created_at,
        )
        session.add(analysis)
        await session.flush()
        snapshot = SiteHealthSnapshot(
            workspace_id=project.workspace_id,
            project_id=project.id,
            crawl_id=crawl.id,
            selected_url_count=1,
            analyzed_url_count=1,
            source_analysis_ids=[analysis.id],
            source_artifact_ids=[artifact.id],
            analyzer_version="acceptance-analyzer-v1",
            scoring_version="acceptance-scoring-v1",
            intelligence_version="site-intelligence-v1",
            intelligence={
                "manifest": {"pack_id": pack_id, "pack_version": "1.0.0"},
                "coverage": {
                    "questions": [
                        {
                            "question_id": question_id,
                            "label": question,
                            "state": "complete" if observed else "missing",
                            "journey_stage_id": "decision",
                            "reason": "acceptance_fixture",
                            "answering_role_ids": [analysis.industry_role_id],
                        }
                    ]
                },
            },
            created_at=created_at,
        )
        session.add(snapshot)
        await session.commit()
        await session.refresh(snapshot)
        return snapshot


@pytest.mark.parametrize(
    ("pack_id", "question_id", "question"),
    [
        (
            "education",
            "admissions.requirements",
            "What are the admission requirements?",
        ),
        ("commerce", "returns.policy", "What is the returns policy?"),
    ],
)
async def test_gap_to_recrawl_verification_without_fact_promotion(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    pack_id: str,
    question_id: str,
    question: str,
) -> None:
    monkeypatch.setattr(
        content_settings, "mistral_api_key", SecretStr("acceptance-key")
    )
    await _register(client, f"content-{pack_id}@example.com")
    project_id = await _create_project(client, pack_id)
    first_snapshot = await _seed_snapshot(
        session_factory,
        project_id=project_id,
        pack_id=pack_id,
        question_id=question_id,
        question=question,
        observed=False,
        created_at=datetime.now(UTC) - timedelta(minutes=2),
    )

    strategy = await client.post(
        "/api/v1/content/strategy/recompute", params={"project_id": str(project_id)}
    )
    assert strategy.status_code == 200
    assert strategy.json()["site_snapshot_id"] == str(first_snapshot.id)
    unsupported_brief = await client.post(
        "/api/v1/content/briefs",
        json={
            "project_id": str(project_id),
            "question_id": question_id,
            "kind": "section",
        },
    )
    assert unsupported_brief.status_code == 422
    brief = await client.post(
        "/api/v1/content/briefs",
        json={
            "project_id": str(project_id),
            "question_id": question_id,
            "kind": "faq",
            "target_url": "https://acceptance.example/help",
            "title": f"{pack_id.title()} FAQ",
        },
    )
    assert brief.status_code == 201
    brief_body = brief.json()
    assert brief_body["allowed_facts"] == []
    assert brief_body["prohibited_claims"] == []

    context = await client.post(f"/api/v1/content/briefs/{brief_body['id']}/context")
    assert context.status_code == 200
    context_hash = context.json()["manifest_hash"]
    site_before = await client.get(f"/api/v1/projects/{project_id}/site-intelligence")
    knowledge_before = await client.get(
        f"/api/v1/projects/{project_id}/knowledge/assertions"
    )
    assert site_before.status_code == knowledge_before.status_code == 200
    generation = await client.post(
        f"/api/v1/content/briefs/{brief_body['id']}/generate",
        json={"skill_id": "faq_visible"},
        headers={"Idempotency-Key": f"{pack_id}-acceptance"},
    )
    assert generation.status_code == 201
    generation_id = generation.json()["id"]
    worker = ContentWorker(
        session_factory=session_factory,
        owner=f"{pack_id}-worker",
        transport=_provider_transport(f"## {question}\n\nContact our team."),
    )
    assert await worker.run_until_idle() == 1

    site_after = await client.get(f"/api/v1/projects/{project_id}/site-intelligence")
    knowledge_after = await client.get(
        f"/api/v1/projects/{project_id}/knowledge/assertions"
    )
    assert site_after.json() == site_before.json()
    assert knowledge_after.json() == knowledge_before.json()
    assert "Contact our team" not in str(knowledge_after.json())

    validation = await client.get(
        f"/api/v1/content/generations/{generation_id}/validation"
    )
    assert validation.status_code == 200
    assert validation.json()["status"] == "passed"
    assert validation.json()["context_manifest_hash"] == context_hash
    revision = await client.post(
        f"/api/v1/content/generations/{generation_id}/revision", json={}
    )
    assert revision.status_code == 201
    revision_id = revision.json()["id"]
    blocked_edit = await client.put(
        f"/api/v1/content/revisions/{revision_id}",
        json={
            "visible_content": f"## {question}\n\nContact our team in 2027.",
            "structured_data": None,
        },
    )
    assert blocked_edit.status_code == 200
    assert blocked_edit.json()["validation_snapshot"]["source"] == "revision"
    assert blocked_edit.json()["validation_snapshot"]["status"] == "blocked"
    blocked_save = await client.post(
        f"/api/v1/content/revisions/{revision_id}/transition",
        json={"state": "saved", "target_url": "", "reason": "reviewed"},
    )
    assert blocked_save.status_code == 409
    corrected_edit = await client.put(
        f"/api/v1/content/revisions/{revision_id}",
        json={
            "visible_content": f"## {question}\n\nContact our team.",
            "structured_data": None,
        },
    )
    assert corrected_edit.status_code == 200
    assert corrected_edit.json()["validation_snapshot"]["source"] == "revision"
    assert corrected_edit.json()["validation_snapshot"]["status"] == "passed"
    saved = await client.post(
        f"/api/v1/content/revisions/{revision_id}/transition",
        json={"state": "saved", "target_url": "", "reason": "reviewed"},
    )
    assert saved.status_code == 200
    claimed = await client.post(
        f"/api/v1/content/revisions/{revision_id}/transition",
        json={
            "state": "published_claimed",
            "target_url": "https://acceptance.example/help",
            "reason": "published by reviewer",
        },
    )
    assert claimed.status_code == 200

    later_snapshot = await _seed_snapshot(
        session_factory,
        project_id=project_id,
        pack_id=pack_id,
        question_id=question_id,
        question=question,
        observed=True,
        created_at=datetime.now(UTC) + timedelta(minutes=1),
    )
    verification = await client.post(
        f"/api/v1/content/revisions/{revision_id}/verifications",
        json={"site_snapshot_id": str(later_snapshot.id)},
    )
    assert verification.status_code == 201
    assert verification.json()["status"] == "observed"
    assert verification.json()["comparison"]["causality"] == "descriptive_only"
    assert verification.json()["coverage"] == {
        "observed": 2,
        "required": 2,
        "target_page_available": True,
    }
