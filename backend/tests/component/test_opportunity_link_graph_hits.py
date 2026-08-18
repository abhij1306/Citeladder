"""Complete-coverage link signals mapped into the existing Opportunity owner."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_link_graph import LINK_GRAPH_ANALYZER_VERSION
from app.domain.opportunities import recompute
from app.models.opportunity import Opportunity
from app.models.site_health.analysis import SitePageAnalysis
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.graph import SiteLinkGraphNode, SiteLinkGraphSnapshot
from tests.component.opportunity_helpers import Scenario, _seed_scenario


async def _add_graph(
    session: AsyncSession, *, complete: bool
) -> tuple[Scenario, SiteLinkGraphSnapshot]:
    scenario = await _seed_scenario(session)
    crawl = await session.get(SiteCrawl, scenario.crawl_id)
    assert crawl is not None
    analyses = list(
        (
            await session.scalars(
                select(SitePageAnalysis)
                .where(SitePageAnalysis.crawl_id == crawl.id)
                .order_by(SitePageAnalysis.id)
            )
        ).all()
    )
    assert len(analyses) >= 2
    snapshot = SiteLinkGraphSnapshot(
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
        crawl_id=crawl.id,
        state="available" if complete else "incomplete",
        root_site_url_id=analyses[0].site_url_id,
        source_analysis_hash=("c" if complete else "p") * 64,
        source_analysis_ids=[row.id for row in analyses],
        source_artifact_ids=[row.artifact_id for row in analyses],
        analyzer_version=LINK_GRAPH_ANALYZER_VERSION,
        page_analyzer_version=crawl.analyzer_version,
        extractor_version=crawl.extractor_version,
        coverage={"complete": complete, "analysis_ratio": 1.0 if complete else 0.5},
        limitations=[] if complete else ["Observed topology is partial."],
        summary={"node_count": len(analyses)},
    )
    session.add(snapshot)
    await session.flush()
    source = SiteLinkGraphNode(
        snapshot_id=snapshot.id,
        workspace_id=scenario.workspace_id,
        site_url_id=analyses[0].site_url_id,
        source_analysis_id=analyses[0].id,
        normalized_url="https://acme.test/source",
        title="CRM guide",
        indexable=True,
        pagerank=0.8,
        click_depth=0,
        followed_inbound_count=2,
        followed_outbound_count=2,
    )
    target = SiteLinkGraphNode(
        snapshot_id=snapshot.id,
        workspace_id=scenario.workspace_id,
        site_url_id=analyses[1].site_url_id,
        source_analysis_id=analyses[1].id,
        normalized_url="https://acme.test/crm",
        title="CRM page",
        indexable=True,
        pagerank=0.01,
        click_depth=None,
        followed_inbound_count=1,
        followed_outbound_count=0,
        near_orphan=True,
        weak_authority=True,
        suggested_source_ids=[analyses[0].site_url_id],
    )
    session.add_all([source, target])
    await session.commit()
    return scenario, snapshot


async def test_complete_graph_maps_only_approved_signals_with_sources(
    db_session: AsyncSession,
) -> None:
    scenario, snapshot = await _add_graph(db_session, complete=True)

    await recompute.recompute(
        db_session,
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
    )
    rows = list(
        (
            await db_session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.project_id == scenario.project_id,
                    Opportunity.rule_id.in_(
                        ["site_link_near_orphan", "site_link_weak_authority"]
                    ),
                    Opportunity.superseded_at.is_(None),
                )
                .order_by(Opportunity.rule_id)
            )
        ).all()
    )

    assert [row.rule_id for row in rows] == [
        "site_link_near_orphan",
        "site_link_weak_authority",
    ]
    assert all(
        row.evidence["link_graph_snapshot_id"] == str(snapshot.id) for row in rows
    )
    assert all(
        row.evidence["suggested_sources"][0]["url"].endswith("/source") for row in rows
    )
    assert all(len(row.source_analysis_ids or []) == 2 for row in rows)


async def test_partial_graph_emits_no_link_opportunities(
    db_session: AsyncSession,
) -> None:
    scenario, _snapshot = await _add_graph(db_session, complete=False)

    await recompute.recompute(
        db_session,
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
    )
    count = await db_session.scalar(
        select(func.count())
        .select_from(Opportunity)
        .where(
            Opportunity.project_id == scenario.project_id,
            Opportunity.rule_id.in_(
                ["site_link_near_orphan", "site_link_weak_authority"]
            ),
            Opportunity.superseded_at.is_(None),
        )
    )
    assert count == 0


async def test_complete_graph_does_not_promote_a_non_indexable_weak_target(
    db_session: AsyncSession,
) -> None:
    scenario, snapshot = await _add_graph(db_session, complete=True)
    target = await db_session.scalar(
        select(SiteLinkGraphNode).where(
            SiteLinkGraphNode.snapshot_id == snapshot.id,
            SiteLinkGraphNode.weak_authority.is_(True),
        )
    )
    assert target is not None
    target.indexable = False
    await db_session.commit()

    await recompute.recompute(
        db_session,
        workspace_id=scenario.workspace_id,
        project_id=scenario.project_id,
    )
    count = await db_session.scalar(
        select(func.count())
        .select_from(Opportunity)
        .where(
            Opportunity.project_id == scenario.project_id,
            Opportunity.rule_id.in_(
                ["site_link_near_orphan", "site_link_weak_authority"]
            ),
            Opportunity.superseded_at.is_(None),
        )
    )
    assert count == 0
