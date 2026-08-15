"""Crawl-scoped link-graph input assembly, persistence, and queue lifecycle."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.link_graph import (
    LinkGraphNodeInput,
    LinkGraphReferenceInput,
    LinkGraphResult,
    analyze_link_graph,
)
from app.core.config.site_health import (
    CRAWL_STATUS_COMPLETED,
    LINK_KIND_ANCHOR,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_ID_TECHNICAL_INDEXABLE,
    RULE_OUTCOME_PASS,
    TASK_KIND_ANALYZE,
)
from app.core.config.site_link_graph import (
    LINK_GRAPH_ANALYZER_VERSION,
    LINK_GRAPH_MAX_NODES,
    LINK_GRAPH_MAX_REFERENCES,
    LINK_GRAPH_NODE_TITLE_MAX_LENGTH,
)
from app.domain.site_health.normalization import canonical_or_empty
from app.models.site_health import (
    SiteCrawl,
    SiteCrawlTask,
    SiteFetchArtifact,
    SiteLinkGraphEdge,
    SiteLinkGraphNode,
    SiteLinkGraphSnapshot,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
    SiteUrl,
)


@dataclass(frozen=True)
class _GraphInputs:
    nodes: list[LinkGraphNodeInput]
    references: list[LinkGraphReferenceInput]
    source_analysis_ids: list[uuid.UUID]
    source_artifact_ids: list[uuid.UUID]
    root_site_url_id: uuid.UUID | None
    coverage: dict
    limitations: tuple[str, ...]
    complete_coverage: bool
    page_analyzer_version: str
    extractor_version: str
    external_anchor_count: int


def _source_hash(inputs: _GraphInputs) -> str:
    material = {
        "analysis_ids": [str(item) for item in inputs.source_analysis_ids],
        "artifact_ids": [str(item) for item in inputs.source_artifact_ids],
        "page_analyzer_version": inputs.page_analyzer_version,
        "extractor_version": inputs.extractor_version,
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


async def _selected_analyses(
    session: AsyncSession, crawl: SiteCrawl
) -> tuple[list[tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]], bool]:
    rows = list(
        (
            await session.execute(
                select(SitePageAnalysis, SiteFetchArtifact, SiteUrl)
                .join(
                    SiteFetchArtifact,
                    SiteFetchArtifact.id == SitePageAnalysis.artifact_id,
                )
                .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
                .where(
                    SitePageAnalysis.workspace_id == crawl.workspace_id,
                    SitePageAnalysis.project_id == crawl.project_id,
                    SitePageAnalysis.crawl_id == crawl.id,
                    SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                    SitePageAnalysis.is_current.is_(True),
                    SitePageAnalysis.analyzer_version == crawl.analyzer_version,
                    SiteFetchArtifact.extractor_version == crawl.extractor_version,
                    SiteFetchArtifact.content_type.ilike("%html%"),
                )
                .order_by(SitePageAnalysis.site_url_id, SitePageAnalysis.id)
                .limit(LINK_GRAPH_MAX_NODES + 1)
            )
        ).all()
    )
    selected = [tuple(row) for row in rows[:LINK_GRAPH_MAX_NODES]]
    return selected, len(rows) > LINK_GRAPH_MAX_NODES


async def _indexable_analysis_ids(
    session: AsyncSession, analysis_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    if not analysis_ids:
        return set()
    return set(
        (
            await session.scalars(
                select(SiteRuleEvaluation.analysis_id).where(
                    SiteRuleEvaluation.analysis_id.in_(analysis_ids),
                    SiteRuleEvaluation.rule_id == RULE_ID_TECHNICAL_INDEXABLE,
                    SiteRuleEvaluation.outcome == RULE_OUTCOME_PASS,
                )
            )
        ).all()
    )


def _node_maps(
    rows: list[tuple[SitePageAnalysis, SiteFetchArtifact, SiteUrl]],
    indexable_ids: set[uuid.UUID],
) -> tuple[
    list[LinkGraphNodeInput],
    dict[uuid.UUID, uuid.UUID],
    dict[str, uuid.UUID],
]:
    nodes: list[LinkGraphNodeInput] = []
    artifact_targets: dict[uuid.UUID, uuid.UUID] = {}
    url_targets: dict[str, uuid.UUID] = {}
    for analysis, artifact, site_url in rows:
        facts = artifact.normalized_facts or {}
        nodes.append(
            LinkGraphNodeInput(
                site_url_id=site_url.id,
                source_analysis_id=analysis.id,
                normalized_url=site_url.normalized_url,
                title=str(facts.get("title") or site_url.latest_title or "")[
                    :LINK_GRAPH_NODE_TITLE_MAX_LENGTH
                ],
                indexable=analysis.id in indexable_ids,
                page_nofollow=bool((facts.get("robots") or {}).get("nofollow")),
            )
        )
        artifact_targets[artifact.id] = site_url.id
        for url in (site_url.normalized_url, artifact.final_url):
            canonical = canonical_or_empty(url)
            if canonical:
                url_targets[canonical] = site_url.id
    return nodes, artifact_targets, url_targets


async def _references(
    session: AsyncSession,
    *,
    analysis_ids: list[uuid.UUID],
    source_url_ids: dict[uuid.UUID, uuid.UUID],
    artifact_targets: dict[uuid.UUID, uuid.UUID],
    url_targets: dict[str, uuid.UUID],
) -> tuple[list[LinkGraphReferenceInput], int, bool]:
    if not analysis_ids:
        return [], 0, False
    rows = list(
        (
            await session.scalars(
                select(SiteLinkReference)
                .where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.kind == LINK_KIND_ANCHOR,
                )
                .order_by(SiteLinkReference.source_analysis_id, SiteLinkReference.id)
                .limit(LINK_GRAPH_MAX_REFERENCES + 1)
            )
        ).all()
    )
    truncated = len(rows) > LINK_GRAPH_MAX_REFERENCES
    external_count = sum(
        not row.is_internal for row in rows[:LINK_GRAPH_MAX_REFERENCES]
    )
    references: list[LinkGraphReferenceInput] = []
    for row in rows[:LINK_GRAPH_MAX_REFERENCES]:
        if not row.is_internal:
            continue
        target_id = (
            artifact_targets.get(row.target_artifact_id)
            if row.target_artifact_id is not None
            else None
        )
        canonical_target = canonical_or_empty(row.target_url)
        if target_id is None:
            target_id = url_targets.get(canonical_target)
        references.append(
            LinkGraphReferenceInput(
                source_site_url_id=source_url_ids[row.source_analysis_id],
                target_site_url_id=target_id,
                # Resolved targets retain their persisted display URL. An
                # unresolved target needs the same canonical identity used by
                # resolution so equivalent fragments/query ordering/default
                # ports collapse into one observation edge.
                target_url=(row.target_url if target_id else canonical_target)
                or row.target_url,
                rel=row.rel,
                anchor_text=row.anchor_text,
            )
        )
    return references, external_count, truncated


async def _expected_analysis_count(
    session: AsyncSession, *, crawl_id: uuid.UUID
) -> int:
    """Count the distinct HTML-analysis population scheduled for this crawl."""
    return int(
        await session.scalar(
            select(func.count(func.distinct(SiteCrawlTask.site_url_id))).where(
                SiteCrawlTask.crawl_id == crawl_id,
                SiteCrawlTask.task_kind == TASK_KIND_ANALYZE,
                SiteCrawlTask.site_url_id.is_not(None),
            )
        )
        or 0
    )


def _coverage(
    crawl: SiteCrawl,
    *,
    expected_count: int,
    node_count: int,
    nodes_truncated: bool,
    refs_truncated: bool,
) -> tuple[int, bool, tuple[str, ...]]:
    selected = expected_count or node_count
    complete = (
        crawl.status == CRAWL_STATUS_COMPLETED
        and node_count >= selected
        and not nodes_truncated
        and not refs_truncated
    )
    limitations: list[str] = []
    if not complete:
        limitations.append(
            f"Observed topology covers {node_count} of {selected} "
            "scheduled HTML analyses."
        )
    if nodes_truncated:
        limitations.append(
            f"Node projection is bounded to {LINK_GRAPH_MAX_NODES} rows."
        )
    if refs_truncated:
        limitations.append(
            f"Link evidence is bounded to {LINK_GRAPH_MAX_REFERENCES} observations."
        )
    return selected, complete, tuple(limitations)


async def load_graph_inputs(session: AsyncSession, crawl: SiteCrawl) -> _GraphInputs:
    rows, nodes_truncated = await _selected_analyses(session, crawl)
    expected_count = await _expected_analysis_count(session, crawl_id=crawl.id)
    analysis_ids = [analysis.id for analysis, _artifact, _url in rows]
    artifact_ids = [artifact.id for _analysis, artifact, _url in rows]
    indexable_ids = await _indexable_analysis_ids(session, analysis_ids)
    nodes, artifact_targets, url_targets = _node_maps(rows, indexable_ids)
    source_url_ids = {
        analysis.id: site_url.id for analysis, _artifact, site_url in rows
    }
    references, external_count, refs_truncated = await _references(
        session,
        analysis_ids=analysis_ids,
        source_url_ids=source_url_ids,
        artifact_targets=artifact_targets,
        url_targets=url_targets,
    )
    selected, complete, limitations = _coverage(
        crawl,
        expected_count=expected_count,
        node_count=len(nodes),
        nodes_truncated=nodes_truncated,
        refs_truncated=refs_truncated,
    )
    root_id = url_targets.get(canonical_or_empty(crawl.root_url))
    return _GraphInputs(
        nodes=nodes,
        references=references,
        source_analysis_ids=analysis_ids,
        source_artifact_ids=artifact_ids,
        root_site_url_id=root_id,
        coverage={
            "crawl_status": crawl.status,
            "selected_url_count": selected,
            "analyzed_html_node_count": len(nodes),
            "analysis_ratio": round(len(nodes) / selected, 4) if selected else None,
            "complete": complete,
        },
        limitations=limitations,
        complete_coverage=complete,
        page_analyzer_version=crawl.analyzer_version,
        extractor_version=crawl.extractor_version,
        external_anchor_count=external_count,
    )


def _summary(result: LinkGraphResult, external_anchor_count: int) -> dict:
    return {
        "node_count": len(result.nodes),
        "edge_count": len(result.edges),
        "followed_edge_count": sum(edge.followed for edge in result.edges),
        "nofollow_edge_count": sum(not edge.followed for edge in result.edges),
        "unresolved_internal_target_count": sum(
            edge.target_site_url_id is None for edge in result.edges
        ),
        "external_anchor_count": external_anchor_count,
        "near_orphan_count": sum(node.near_orphan for node in result.nodes),
        "weak_authority_count": sum(node.weak_authority for node in result.nodes),
        "over_linked_count": sum(node.over_linked for node in result.nodes),
        "hub_count": sum(node.hub for node in result.nodes),
        "authority_concentrated": result.authority_concentrated,
        "pagerank_iterations": result.pagerank_iterations,
        "pagerank_converged": result.pagerank_converged,
        "anchor_text_distribution": [
            {"text": text, "count": count}
            for text, count in result.anchor_text_distribution
        ],
    }


async def build_link_graph_snapshot(
    session: AsyncSession, *, crawl: SiteCrawl
) -> SiteLinkGraphSnapshot | None:
    """Build and atomically persist one immutable graph snapshot."""
    inputs = await load_graph_inputs(session, crawl)
    if not inputs.nodes:
        return None
    source_hash = _source_hash(inputs)
    existing = await session.scalar(
        select(SiteLinkGraphSnapshot).where(
            SiteLinkGraphSnapshot.workspace_id == crawl.workspace_id,
            SiteLinkGraphSnapshot.crawl_id == crawl.id,
            SiteLinkGraphSnapshot.source_analysis_hash == source_hash,
            SiteLinkGraphSnapshot.analyzer_version == LINK_GRAPH_ANALYZER_VERSION,
        )
    )
    if existing is not None:
        return existing
    prior_id = await session.scalar(
        select(SiteLinkGraphSnapshot.id)
        .where(
            SiteLinkGraphSnapshot.workspace_id == crawl.workspace_id,
            SiteLinkGraphSnapshot.crawl_id == crawl.id,
        )
        .order_by(
            SiteLinkGraphSnapshot.created_at.desc(), SiteLinkGraphSnapshot.id.desc()
        )
        .limit(1)
    )
    result = analyze_link_graph(
        inputs.nodes,
        inputs.references,
        root_site_url_id=inputs.root_site_url_id,
        complete_coverage=inputs.complete_coverage,
        limitations=inputs.limitations,
    )
    snapshot_id = await session.scalar(
        pg_insert(SiteLinkGraphSnapshot)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            supersedes_id=prior_id,
            state=result.state,
            root_site_url_id=result.root_site_url_id,
            source_analysis_hash=source_hash,
            source_analysis_ids=inputs.source_analysis_ids,
            source_artifact_ids=inputs.source_artifact_ids,
            analyzer_version=LINK_GRAPH_ANALYZER_VERSION,
            page_analyzer_version=inputs.page_analyzer_version,
            extractor_version=inputs.extractor_version,
            coverage=inputs.coverage,
            limitations=list(result.limitations),
            summary=_summary(result, inputs.external_anchor_count),
        )
        .on_conflict_do_nothing(
            index_elements=[
                "workspace_id",
                "crawl_id",
                "source_analysis_hash",
                "analyzer_version",
            ]
        )
        .returning(SiteLinkGraphSnapshot.id)
    )
    if snapshot_id is None:
        return await session.scalar(
            select(SiteLinkGraphSnapshot).where(
                SiteLinkGraphSnapshot.workspace_id == crawl.workspace_id,
                SiteLinkGraphSnapshot.crawl_id == crawl.id,
                SiteLinkGraphSnapshot.source_analysis_hash == source_hash,
                SiteLinkGraphSnapshot.analyzer_version == LINK_GRAPH_ANALYZER_VERSION,
            )
        )
    session.add_all(
        [
            SiteLinkGraphNode(
                snapshot_id=snapshot_id,
                workspace_id=crawl.workspace_id,
                site_url_id=node.site_url_id,
                source_analysis_id=node.source_analysis_id,
                normalized_url=node.normalized_url,
                title=node.title,
                indexable=node.indexable,
                pagerank=node.pagerank,
                click_depth=node.click_depth,
                followed_inbound_count=node.followed_inbound_count,
                followed_outbound_count=node.followed_outbound_count,
                near_orphan=node.near_orphan,
                weak_authority=node.weak_authority,
                over_linked=node.over_linked,
                hub=node.hub,
                suggested_source_ids=list(node.suggested_source_ids),
            )
            for node in result.nodes
        ]
    )
    session.add_all(
        [
            SiteLinkGraphEdge(
                snapshot_id=snapshot_id,
                workspace_id=crawl.workspace_id,
                source_site_url_id=edge.source_site_url_id,
                target_site_url_id=edge.target_site_url_id,
                target_key=str(edge.target_site_url_id or edge.target_url),
                target_url=edge.target_url,
                followed=edge.followed,
                occurrence_count=edge.occurrence_count,
                followed_occurrence_count=edge.followed_occurrence_count,
                nofollow_occurrence_count=edge.nofollow_occurrence_count,
                anchor_texts=list(edge.anchor_texts),
            )
            for edge in result.edges
        ]
    )
    await session.flush()
    return await session.get(SiteLinkGraphSnapshot, snapshot_id)


__all__ = [
    "build_link_graph_snapshot",
    "load_graph_inputs",
]
