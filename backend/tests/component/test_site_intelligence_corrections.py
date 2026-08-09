"""Durable correction provenance, precedence, withdrawal, and isolation."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.site_health import CRAWL_STATUS_RUNNING, TEMPORAL_STATE_CURRENT
from app.core.config.site_intelligence import (
    CORRECTION_SCOPE_ENTITY,
    CORRECTION_SCOPE_PROJECT,
    CORRECTION_STATE_WITHDRAWN,
    CORRECTION_TARGET_ASSERTION,
    DERIVATION_VISIBLE_TEXT,
    REVIEW_STATE_OBSERVED,
    VALUE_TYPE_MONEY,
)
from app.domain.site_health.comparison import (
    build_snapshot_comparison,
)
from app.domain.site_health.corrections import (
    CorrectionNotFoundError,
    CorrectionValidationError,
    create_correction,
    list_corrections,
    withdraw_correction,
)
from app.domain.site_health.service.intelligence import (
    get_knowledge_assertions,
    get_knowledge_contradictions,
)
from app.models.knowledge import (
    CorrectionTransition,
    KnowledgeAssertion,
    KnowledgeEntity,
    assertion_id,
    contradiction_group_id,
    entity_id,
)
from app.models.site_health import SiteCrawl, SiteHealthSnapshot
from app.models.user import User
from app.models.workspace import WorkspaceMember
from tests.component.site_health_helpers import seed_site_crawl

pytestmark = pytest.mark.asyncio


async def _register(client: httpx.AsyncClient, email: str) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 201


async def _knowledge_row(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    value: float,
    conflicting_value: float | None = None,
) -> tuple[KnowledgeEntity, KnowledgeAssertion]:
    entity = KnowledgeEntity(
        id=entity_id(crawl.id, "education.organization", "example.com"),
        workspace_id=crawl.workspace_id,
        project_id=crawl.project_id,
        crawl_id=crawl.id,
        entity_type_id="education.organization",
        identity_key="example.com",
        canonical_name="Example School",
        aliases=[],
        identifiers={},
        review_state=REVIEW_STATE_OBSERVED,
        evidence_refs=[
            {"source_kind": "site_fetch_artifact", "source_id": str(uuid.uuid4())}
        ],
        evidence_page_count=1,
        industry_pack_id="education",
        industry_pack_version="1.0.0",
        extractor_version="si-knowledge-1",
    )
    session.add(entity)
    await session.flush()

    def assertion(amount: float) -> KnowledgeAssertion:
        normalized = f"INR {amount:.2f}"
        return KnowledgeAssertion(
            id=assertion_id(
                crawl.id,
                entity.id,
                "education.fee_amount",
                "grade=8|year=2026",
                normalized,
            ),
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            subject_entity_id=entity.id,
            predicate_id="education.fee_amount",
            value_type=VALUE_TYPE_MONEY,
            raw_value=str(amount),
            normalized_value=normalized,
            numeric_value=amount,
            unit="annual",
            currency="INR",
            scope={"grade": "8", "year": "2026"},
            scope_key="grade=8|year=2026",
            scope_complete=True,
            temporal_state=TEMPORAL_STATE_CURRENT,
            evidence_refs=[
                {"source_kind": "site_fetch_artifact", "source_id": str(uuid.uuid4())}
            ],
            derivation_method=DERIVATION_VISIBLE_TEXT,
            extractor_version="si-knowledge-1",
            confidence=1.0,
            review_state=REVIEW_STATE_OBSERVED,
            contradiction_group_id=(
                contradiction_group_id(
                    crawl.id,
                    entity.id,
                    "education.fee_amount",
                    "grade=8|year=2026",
                )
                if conflicting_value is not None
                else None
            ),
            industry_pack_id="education",
            industry_pack_version="1.0.0",
        )

    primary = assertion(value)
    session.add(primary)
    if conflicting_value is not None:
        session.add(assertion(conflicting_value))
    await session.commit()
    return entity, primary


async def test_correction_survives_recompute_and_withdrawal_restores_derived_value(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        actor_id = await session.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == seed.workspace_id
            )
        )
        assert crawl is not None
        assert actor_id is not None
        _entity, assertion = await _knowledge_row(
            session, crawl=crawl, value=250_000, conflicting_value=275_000
        )

        correction = await create_correction(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            actor_user_id=actor_id,
            target_kind=CORRECTION_TARGET_ASSERTION,
            target_id=assertion.id,
            value=260_000,
            effective_scope=CORRECTION_SCOPE_PROJECT,
            effective_scope_id=None,
            effective_from=None,
            effective_to=None,
            value_metadata={"unit": "annual", "currency": "INR"},
            reason="The published fee excludes the mandatory annual charge.",
        )

        initial = await get_knowledge_assertions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=crawl.id,
        )
        assert {
            item["effective_value"]["numeric_value"] for item in initial["items"]
        } == {260_000}
        assert {item["numeric_value"] for item in initial["items"]} == {
            250_000,
            275_000,
        }
        contradiction = await get_knowledge_contradictions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=crawl.id,
        )
        assert contradiction["items"][0]["resolution_state"] == "corrected"
        assert len(contradiction["items"][0]["sides"]) == 2

        recrawl = SiteCrawl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            profile_id=seed.profile_id,
            status=CRAWL_STATUS_RUNNING,
            root_url="https://example.com/",
            random_seed="2",
        )
        session.add(recrawl)
        await session.flush()
        _entity2, recomputed = await _knowledge_row(
            session, crawl=recrawl, value=300_000
        )

        after_recompute = await get_knowledge_assertions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=recrawl.id,
        )
        recomputed_item = next(
            item
            for item in after_recompute["items"]
            if item["id"] == str(recomputed.id)
        )
        assert recomputed_item["numeric_value"] == 300_000
        assert recomputed_item["effective_value"]["numeric_value"] == 260_000
        assert recomputed_item["correction"]["source_target_id"] == str(assertion.id)
        assert str(recomputed.id) != str(assertion.id)

        await withdraw_correction(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            correction_id=correction.id,
            actor_user_id=actor_id,
            reason="The next crawl now includes the mandatory charge.",
        )
        restored = await get_knowledge_assertions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=recrawl.id,
        )
        assert restored["items"][0]["effective_value"]["numeric_value"] == 300_000
        assert restored["items"][0]["correction"] is None

        history = await list_corrections(
            session, workspace_id=seed.workspace_id, project_id=seed.project_id
        )
        assert history["items"][0]["state"] == CORRECTION_STATE_WITHDRAWN
        assert [
            event["transition_type"] for event in history["items"][0]["transitions"]
        ] == [
            "created",
            "withdrawn",
        ]
        transition_count = await session.scalar(
            select(func.count())
            .select_from(CorrectionTransition)
            .where(CorrectionTransition.correction_id == correction.id)
        )
        assert transition_count == 2


async def test_entity_scope_matches_the_projected_subject_before_precedence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        actor_id = await session.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == seed.workspace_id
            )
        )
        assert crawl is not None
        assert actor_id is not None
        subject, assertion = await _knowledge_row(session, crawl=crawl, value=250_000)
        unrelated = KnowledgeEntity(
            id=entity_id(crawl.id, "education.organization", "other.example"),
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            entity_type_id="education.organization",
            identity_key="other.example",
            canonical_name="Other School",
            aliases=[],
            identifiers={},
            review_state=REVIEW_STATE_OBSERVED,
            evidence_refs=[],
            evidence_page_count=0,
            industry_pack_id="education",
            industry_pack_version="1.0.0",
            extractor_version="si-knowledge-1",
        )
        session.add(unrelated)
        await session.commit()

        common = {
            "session": session,
            "workspace_id": seed.workspace_id,
            "project_id": seed.project_id,
            "actor_user_id": actor_id,
            "target_kind": CORRECTION_TARGET_ASSERTION,
            "target_id": assertion.id,
            "effective_from": None,
            "effective_to": None,
            "value_metadata": {"unit": "annual", "currency": "INR"},
        }
        await create_correction(
            **common,
            value=255_000,
            effective_scope=CORRECTION_SCOPE_PROJECT,
            effective_scope_id=None,
            reason="Project fallback.",
        )
        await create_correction(
            **common,
            value=999_000,
            effective_scope=CORRECTION_SCOPE_ENTITY,
            effective_scope_id=unrelated.id,
            reason="Applies only to the unrelated school.",
        )
        fallback = await get_knowledge_assertions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=crawl.id,
        )
        assert fallback["items"][0]["effective_value"]["numeric_value"] == 255_000

        subject_correction = await create_correction(
            **common,
            value=260_000,
            effective_scope=CORRECTION_SCOPE_ENTITY,
            effective_scope_id=subject.id,
            reason="Applies to this assertion subject.",
        )
        scoped = await get_knowledge_assertions(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=crawl.id,
        )
        assert scoped["items"][0]["effective_value"]["numeric_value"] == 260_000
        assert scoped["items"][0]["correction"]["id"] == str(subject_correction.id)


async def test_correction_target_is_workspace_and_project_authorized(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await seed_site_crawl(session)
        second = await seed_site_crawl(session)
        first_crawl = await session.get(SiteCrawl, first.crawl_id)
        second_actor = await session.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == second.workspace_id
            )
        )
        assert first_crawl is not None
        assert second_actor is not None
        _entity, assertion = await _knowledge_row(session, crawl=first_crawl, value=100)

        with pytest.raises(CorrectionNotFoundError):
            await create_correction(
                session,
                workspace_id=second.workspace_id,
                project_id=second.project_id,
                actor_user_id=second_actor,
                target_kind=CORRECTION_TARGET_ASSERTION,
                target_id=assertion.id,
                value=200,
                effective_scope=CORRECTION_SCOPE_PROJECT,
                effective_scope_id=None,
                effective_from=None,
                effective_to=None,
                value_metadata={"unit": "annual", "currency": "INR"},
                reason="Must not cross the workspace boundary.",
            )


async def test_unapplied_effective_scope_is_rejected_before_persistence(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        actor_id = await session.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == seed.workspace_id
            )
        )
        assert crawl is not None
        assert actor_id is not None
        _entity, assertion = await _knowledge_row(session, crawl=crawl, value=100)
        with pytest.raises(CorrectionValidationError, match="unsupported"):
            await create_correction(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                actor_user_id=actor_id,
                target_kind=CORRECTION_TARGET_ASSERTION,
                target_id=assertion.id,
                value=110,
                effective_scope="prompt",
                effective_scope_id=uuid.uuid4(),
                effective_from=None,
                effective_to=None,
                value_metadata={"unit": "annual", "currency": "INR"},
                reason="This scope has no projection consumer yet.",
            )


async def test_correction_api_persists_author_and_transition_contract(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    email = "correction-api@example.com"
    await _register(client, email)
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        crawl = await session.get(SiteCrawl, seed.crawl_id)
        api_user = await session.scalar(select(User).where(User.email == email))
        assert crawl is not None
        assert api_user is not None
        session.add(
            WorkspaceMember(
                workspace_id=seed.workspace_id,
                user_id=api_user.id,
                role="member",
            )
        )
        await session.commit()
        _entity, assertion = await _knowledge_row(session, crawl=crawl, value=125_000)

    headers = {"X-Workspace-Id": str(seed.workspace_id)}
    created = await client.post(
        f"/api/v1/projects/{seed.project_id}/knowledge/corrections",
        headers=headers,
        json={
            "target_kind": "assertion",
            "target_id": str(assertion.id),
            "value": 130_000,
            "currency": "INR",
            "unit": "annual",
            "effective_scope": "project",
            "reason": "Confirmed by the finance office.",
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["author_user_id"] == str(api_user.id)
    assert payload["corrected_value"]["numeric_value"] == 130_000

    listed = await client.get(
        f"/api/v1/projects/{seed.project_id}/knowledge/corrections",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["items"][0]["transitions"][0]["transition_type"] == "created"

    withdrawn = await client.post(
        f"/api/v1/projects/{seed.project_id}/knowledge/corrections/{payload['id']}/withdraw",
        headers=headers,
        json={"reason": "The site now publishes the confirmed fee."},
    )
    assert withdrawn.status_code == 200
    assert withdrawn.json()["state"] == "withdrawn"

    missing = await client.get(
        f"/api/v1/projects/{uuid.uuid4()}/knowledge/corrections",
        headers=headers,
    )
    assert missing.status_code == 404


async def test_compatible_snapshot_comparison_is_frozen_from_observed_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_site_crawl(session)
        prior_crawl = await session.get(SiteCrawl, seed.crawl_id)
        assert prior_crawl is not None
        await _knowledge_row(session, crawl=prior_crawl, value=100_000)
        prior_payload = {
            "manifest": {"pack_id": "education", "pack_version": "1.0.0"},
            "coverage": {
                "answered_ratio": 0.25,
                "denominator": 4,
                "questions": [{"question_id": "fees", "state": "missing"}],
            },
            "journeys": [{"journey_id": "admissions", "stages": []}],
            "dimensions": {
                "composite_score": 0.4,
                "composite_coverage": 0.5,
                "dimensions": [
                    {"dimension_id": "answerability", "score": 0.25, "coverage": 0.5}
                ],
            },
        }
        prior_snapshot = SiteHealthSnapshot(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            crawl_id=prior_crawl.id,
            selected_url_count=1,
            analyzed_url_count=1,
            technical_score=0.5,
            aeo_score=0.4,
            overall_score=0.45,
            issue_count=1,
            analyzer_version="analyzer-1",
            scoring_version="scoring-1",
            intelligence=prior_payload,
            intelligence_version="projection-1",
        )
        session.add(prior_snapshot)
        await session.commit()

        recrawl = SiteCrawl(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            profile_id=seed.profile_id,
            status=CRAWL_STATUS_RUNNING,
            root_url="https://example.com/",
            random_seed="comparison",
        )
        session.add(recrawl)
        await session.flush()
        await _knowledge_row(session, crawl=recrawl, value=120_000)
        current_payload = {
            "manifest": {"pack_id": "education", "pack_version": "1.0.0"},
            "coverage": {
                "answered_ratio": 0.5,
                "denominator": 4,
                "questions": [{"question_id": "fees", "state": "answered_strong"}],
            },
            "journeys": [
                {"journey_id": "admissions", "stages": [{"stage_id": "apply"}]}
            ],
            "dimensions": {
                "composite_score": 0.6,
                "composite_coverage": 0.75,
                "dimensions": [
                    {"dimension_id": "answerability", "score": 0.75, "coverage": 1.0}
                ],
            },
        }
        prior_id, comparison = await build_snapshot_comparison(
            session,
            crawl=recrawl,
            intelligence=current_payload,
            analyzer_version="analyzer-1",
            scoring_version="scoring-1",
            intelligence_version="projection-1",
            scores={
                "technical_score": 0.7,
                "aeo_score": 0.6,
                "overall_score": 0.65,
                "analyzed_url_count": 1,
                "issue_count": 0,
            },
        )

        assert prior_id == prior_snapshot.id
        assert comparison["available"] is True
        assert comparison["facts"]["changed_count"] == 1
        assert comparison["questions"]["changes"] == [
            {"question_id": "fees", "before": "missing", "after": "answered_strong"}
        ]
        assert comparison["dimensions"]["composite_score_delta"] == pytest.approx(0.2)
        assert comparison["scores"]["issue_count_delta"] == -1.0

        persisted_prior = await session.get(SiteHealthSnapshot, prior_snapshot.id)
        assert persisted_prior is not None
        assert persisted_prior.comparison is None
