"""Rendered generation-context tests (real Postgres schema).

Proves the four blocks are assembled from what the project actually knows:
brand fields regardless of review state, the opportunity's own words, and
crawl pages ranked against the prompt. No provider calls.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.content.context_builder import (
    ContentContext,
    _selection_inputs,
    build_content_context,
    content_context_availability,
)
from app.models.brand import Brand, BrandProfile
from app.models.opportunity import Opportunity
from app.models.project import Project
from app.models.workspace import Workspace

_ROOT = "https://example.com/"


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    workspace = Workspace(name="Ctx WS")
    session.add(workspace)
    await session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Ctx Project",
        brand_name="Acme Schoolwear",
        country_code="AU",
        language_code="en-AU",
        benchmark_mode="consumer_like",
        default_repetitions=1,
        website_url=_ROOT,
    )
    session.add(project)
    await session.flush()
    return workspace.id, project.id


async def _seed_profile(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> BrandProfile:
    brand = Brand(project_id=project_id, name="Acme Schoolwear")
    session.add(brand)
    await session.flush()
    profile = BrandProfile(
        workspace_id=workspace_id,
        project_id=project_id,
        brand_id=brand.id,
        description="We sell school uniforms for Australian primary schools.",
        positioning="Mid-price, hard-wearing.",
        products_services=["polos", "shorts"],
        target_audience="Parents of primary-school children.",
        # Deliberately UNCONFIRMED: the retired envelope would have withheld
        # every one of these fields from the model.
        sources={},
    )
    session.add(profile)
    await session.flush()
    return profile


async def test_site_crawl_only_context_builds_without_brand_or_search(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The demo path: no brand profile, no Search Console, still a context."""
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        await session.commit()
        context = await build_content_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt="Write a buyer guide for kids schoolwear",
            brand_name="Acme Schoolwear",
            website=_ROOT,
            locale="AU en-AU",
        )
        # Project-level brand facts alone still render a usable brand block.
        assert "Acme Schoolwear" in context.brand_block
        assert "AU en-AU" in context.brand_block
        assert context.search_block == ""
        assert context.summary["search_connected"] is False
        assert context.summary["crawl_page_count"] == 0


async def test_unconfirmed_brand_fields_reach_the_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Unconfirmed fields are context, not claims — the old confirmed-only
    gate is why drafts came out generic."""
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        await _seed_profile(session, workspace_id=workspace_id, project_id=project_id)
        await session.commit()
        context = await build_content_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt="Write a buyer guide",
        )
        assert "Australian primary schools" in context.brand_block
        assert "Mid-price" in context.brand_block
        assert "polos, shorts" in context.brand_block
        assert set(context.summary["brand_fields"]) == {
            "description",
            "positioning",
            "products_services",
            "target_audience",
        }


async def test_opportunity_text_reaches_the_task_block(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The bug this replaces: opportunity_id was persisted and fingerprinted
    but its words never reached the model. Assert on content, not the id."""
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        opportunity = Opportunity(
            workspace_id=workspace_id,
            project_id=project_id,
            rule_id="r1",
            opportunity_type="content",
            severity="high",
            target_key="school-uniform-sizing",
            title="Competitors are cited more for sizing queries",
            remediation="Create stronger sizing guidance for common questions.",
            target_url=f"{_ROOT}schoolwear",
            target_theme="School uniform sizing",
            created_at=datetime.now(UTC),
        )
        session.add(opportunity)
        await session.commit()
        context = await build_content_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt="Draft a guide",
            opportunity=opportunity,
        )
        assert "Competitors are cited more for sizing queries" in context.task_block
        assert "Create stronger sizing guidance" in context.task_block
        assert "School uniform sizing" in context.task_block
        assert context.summary["opportunity_id"] == str(opportunity.id)


async def test_site_health_handoff_freezes_task_and_untrusted_evidence_separately(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        await session.commit()
        handoff = {
            "crawl_id": uuid.uuid4(),
            "site_url_id": uuid.uuid4(),
            "source_analysis_id": uuid.uuid4(),
            "dimension": "answerability",
            "checkpoint_ids": ["aeo.answer_first"],
            "expected_capability": ["Answer the primary question directly."],
            "remediation": ["Lead with a concise answer."],
            "observed_evidence": [{"opening": "background only"}],
            "page_kind": "faq",
            "page_traits": ["has_faq"],
            "normalized_url": f"{_ROOT}faq",
        }

        context = await build_content_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt="Improve this FAQ",
            site_health_handoff=handoff,
        )

        assert "Answer the primary question directly" in context.task_block
        assert "background only" not in context.task_block
        assert "SITE HEALTH OBSERVED EVIDENCE" in context.website_block
        assert "background only" in context.website_block
        assert context.summary["site_health_reference"] == {
            "crawl_id": str(handoff["crawl_id"]),
            "site_url_id": str(handoff["site_url_id"]),
            "source_analysis_id": str(handoff["source_analysis_id"]),
            "dimension": "answerability",
            "checkpoint_ids": ["aeo.answer_first"],
        }
        target_url, query_text = _selection_inputs("Improve this FAQ", None, handoff)
        assert target_url == f"{_ROOT}faq"
        assert "Lead with a concise answer" in query_text


async def test_snapshot_round_trips(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The worker rebuilds messages from the persisted snapshot, so a
    round-trip must preserve every block byte-for-byte."""
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        await _seed_profile(session, workspace_id=workspace_id, project_id=project_id)
        await session.commit()
        context = await build_content_context(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            prompt="Write a page",
            brand_name="Acme Schoolwear",
        )
        restored = ContentContext.from_snapshot(context.snapshot())
        assert restored == context
        assert restored.reference_blocks() == context.reference_blocks()


async def test_legacy_envelope_snapshot_reads_as_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Historical rows hold the retired envelope shape; they must degrade to
    an empty context rather than raising in the worker."""
    del session_factory
    legacy = ContentContext.from_snapshot(
        {"status": "included", "allowed_facts": [], "source_refs": []}
    )
    assert legacy.reference_blocks() == []
    assert legacy.status == "unavailable"


async def test_availability_reports_counts_without_projecting_pages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await _seed(session)
        await session.commit()
        preview = await content_context_availability(
            session, workspace_id=workspace_id, project_id=project_id
        )
        assert preview["crawl_available"] is False
        assert preview["crawl_page_count"] == 0
        assert preview["search_connected"] is False
