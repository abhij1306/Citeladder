"""Load persisted crawl evidence and write the observed architecture model."""

from __future__ import annotations

import copy
import uuid
from urllib.parse import urljoin

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analysis.site_health.architecture import (
    ArchitecturePage,
    build_observed_architecture,
    evaluate_architecture_rules,
)
from app.core.config.site_health_archetypes import (
    ARCHETYPE_POLICY_VERSION,
    ARCHITECTURE_FORMULA_VERSION,
)
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    EXTRACTOR_VERSION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_CATALOG_VERSION,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_PASS,
)
from app.core.config.site_health_link_metrics import LINK_METRIC_FORMULA_VERSION
from app.core.config.site_health_taxonomy import PAGE_KIND_HOMEPAGE
from app.domain.projects.shim import project_business_context
from app.domain.site_health.normalization import canonical_or_empty
from app.models.brand import Brand
from app.models.project import Project
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.architecture import SiteObservedArchitecture
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.links import SitePageLinkMetric
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import SiteUrl


def _normalize_breadcrumb_links(commerce: dict, *, base_url: str) -> None:
    for item in commerce.get("breadcrumb_links") or []:
        if isinstance(item, dict) and item.get("url"):
            item["url"] = canonical_or_empty(urljoin(base_url, str(item["url"])))


def _normalize_structured_relationships(blocks: list, *, base_url: str) -> None:
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("is_part_of_url"):
            block["is_part_of_url"] = canonical_or_empty(
                urljoin(base_url, str(block["is_part_of_url"]))
            )
        block["breadcrumb_items"] = [
            canonical
            for value in block.get("breadcrumb_items") or []
            if (canonical := canonical_or_empty(urljoin(base_url, str(value))))
        ]


def _normalized_relationship_facts(facts: dict, *, base_url: str) -> dict:
    normalized = copy.deepcopy(facts)
    _normalize_breadcrumb_links(normalized.get("commerce") or {}, base_url=base_url)
    _normalize_structured_relationships(
        normalized.get("structured_data") or [], base_url=base_url
    )
    return normalized


async def _business_context(
    session: AsyncSession, *, crawl: SiteCrawl
) -> tuple[uuid.UUID | None, dict]:
    project = await session.scalar(
        select(Project)
        .where(
            Project.id == crawl.project_id, Project.workspace_id == crawl.workspace_id
        )
        .options(selectinload(Project.brand).selectinload(Brand.profile))
    )
    if project is None:
        return None, {}
    profile = getattr(getattr(project, "brand", None), "profile", None)
    return getattr(profile, "id", None), project_business_context(project)


async def _architecture_pages(
    session: AsyncSession, *, crawl: SiteCrawl
) -> tuple[list[ArchitecturePage], list[uuid.UUID]]:
    rows = (
        await session.execute(
            select(SitePageAnalysis, SiteUrl, SiteFetchArtifact, SitePageLinkMetric)
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .join(
                SiteFetchArtifact, SiteFetchArtifact.id == SitePageAnalysis.artifact_id
            )
            .join(
                SitePageLinkMetric,
                (SitePageLinkMetric.site_url_id == SitePageAnalysis.site_url_id)
                & (SitePageLinkMetric.crawl_id == SitePageAnalysis.crawl_id),
            )
            .where(
                SitePageAnalysis.workspace_id == crawl.workspace_id,
                SitePageAnalysis.project_id == crawl.project_id,
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                SitePageAnalysis.is_current.is_(True),
                SiteUrl.workspace_id == crawl.workspace_id,
                SiteUrl.project_id == crawl.project_id,
                SiteFetchArtifact.workspace_id == crawl.workspace_id,
                SiteFetchArtifact.crawl_id == crawl.id,
                SitePageLinkMetric.workspace_id == crawl.workspace_id,
                SitePageLinkMetric.project_id == crawl.project_id,
                SitePageLinkMetric.extractor_version == crawl.extractor_version,
                SitePageLinkMetric.formula_version == LINK_METRIC_FORMULA_VERSION,
            )
            .order_by(SitePageAnalysis.site_url_id)
        )
    ).all()
    analysis_ids = [analysis.id for analysis, *_rest in rows]
    indexability_rows = (
        await session.execute(
            select(
                SiteRuleEvaluation.id,
                SiteRuleEvaluation.analysis_id,
                SiteRuleEvaluation.outcome,
            ).where(
                SiteRuleEvaluation.workspace_id == crawl.workspace_id,
                SiteRuleEvaluation.analysis_id.in_(analysis_ids),
                SiteRuleEvaluation.rule_id == "technical.indexable",
            )
        )
    ).all()
    indexability = {
        row.analysis_id: row.outcome == RULE_OUTCOME_PASS for row in indexability_rows
    }
    evaluation_ids = [row.id for row in indexability_rows]
    pages: list[ArchitecturePage] = []
    for analysis, site_url, artifact, metric in rows:
        url = canonical_or_empty(artifact.final_url or site_url.normalized_url)
        facts = _normalized_relationship_facts(
            dict(artifact.normalized_facts or {}), base_url=url
        )
        pages.append(
            ArchitecturePage(
                site_url_id=analysis.site_url_id,
                analysis_id=analysis.id,
                artifact_id=artifact.id,
                link_metric_id=metric.id,
                url=url,
                title=str(facts.get("title") or ""),
                meta_description=str(facts.get("meta_description") or ""),
                page_kind=analysis.page_kind,
                depth_from_home=metric.depth_from_home,
                inbound_count=metric.inbound_count,
                outbound_count=metric.outbound_count,
                indexable=indexability.get(analysis.id, False),
                facts=facts,
            )
        )
    return pages, evaluation_ids


def _root_page(pages: list[ArchitecturePage]) -> ArchitecturePage | None:
    return next(
        (page for page in pages if page.page_kind == PAGE_KIND_HOMEPAGE), None
    ) or (pages[0] if pages else None)


async def _persist_rule_evaluations(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    architecture_id: uuid.UUID,
    root: ArchitecturePage,
    pages: list[ArchitecturePage],
    evaluations: list,
) -> None:
    supporting_artifact_ids = [page.artifact_id for page in pages]
    for evaluation in evaluations:
        evaluation_id = await session.scalar(
            pg_insert(SiteRuleEvaluation)
            .values(
                workspace_id=crawl.workspace_id,
                analysis_id=root.analysis_id,
                source_artifact_id=root.artifact_id,
                source_architecture_id=architecture_id,
                rule_id=evaluation.rule_id,
                dimension=evaluation.dimension,
                category=evaluation.category,
                severity=evaluation.severity,
                finding_class=evaluation.finding_class,
                weight=evaluation.weight,
                outcome=evaluation.outcome,
                display_applicability=evaluation.display_applicability,
                score_applicability=evaluation.score_applicability,
                expected_profile_membership=evaluation.expected_profile_membership,
                reason_code=evaluation.reason_code,
                score_roles=list(evaluation.score_roles),
                checkpoint_family=evaluation.checkpoint_family,
                readiness_dimension=evaluation.readiness_dimension,
                readiness_weight=evaluation.readiness_weight,
                evidence=evaluation.evidence,
                supporting_artifact_ids=supporting_artifact_ids,
                extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                rule_version=evaluation.rule_version,
            )
            .on_conflict_do_nothing(constraint="uq_site_rule_evaluation")
            .returning(SiteRuleEvaluation.id)
        )
        if evaluation_id is None or evaluation.outcome != RULE_OUTCOME_FAIL:
            continue
        session.add(
            SiteIssue(
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                site_url_id=root.site_url_id,
                analysis_id=root.analysis_id,
                evaluation_id=evaluation_id,
                source_artifact_id=root.artifact_id,
                rule_id=evaluation.rule_id,
                dimension=evaluation.dimension,
                category=evaluation.category,
                severity=evaluation.severity,
                finding_class=evaluation.finding_class,
                evidence=evaluation.evidence,
                description=evaluation.description,
                remediation=evaluation.remediation,
                analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                rule_version=evaluation.rule_version,
            )
        )


async def persist_observed_architecture(
    session: AsyncSession, *, crawl: SiteCrawl
) -> int:
    """Persist one idempotent model and its root-anchored structural rules."""
    coverage = await session.scalar(
        select(SiteHealthSnapshot).where(
            SiteHealthSnapshot.workspace_id == crawl.workspace_id,
            SiteHealthSnapshot.project_id == crawl.project_id,
            SiteHealthSnapshot.crawl_id == crawl.id,
        )
    )
    if coverage is None:
        return 0
    pages, source_evaluation_ids = await _architecture_pages(session, crawl=crawl)
    root = _root_page(pages)
    if root is None:
        return 0
    source_brand_profile_id, business_context = await _business_context(
        session, crawl=crawl
    )
    model = build_observed_architecture(
        pages=pages,
        coverage_state=coverage.coverage_state,
        business_context=business_context,
    )
    inserted_id = await session.scalar(
        pg_insert(SiteObservedArchitecture)
        .values(
            workspace_id=crawl.workspace_id,
            project_id=crawl.project_id,
            crawl_id=crawl.id,
            source_snapshot_id=coverage.id,
            source_brand_profile_id=source_brand_profile_id,
            coverage_state=coverage.coverage_state,
            page_count=len(model.pages),
            page_kinds=list(model.page_kinds),
            internal_linking=model.internal_linking,
            structure_depth=model.structure_depth,
            hierarchy=list(model.pages),
            archetype=model.archetype.as_dict(),
            source_analysis_ids=[page.analysis_id for page in pages],
            source_artifact_ids=[page.artifact_id for page in pages],
            source_evaluation_ids=source_evaluation_ids,
            source_link_metric_ids=[page.link_metric_id for page in pages],
            extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
            analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
            rule_version=crawl.rule_catalog_version or RULE_CATALOG_VERSION,
            architecture_formula_version=ARCHITECTURE_FORMULA_VERSION,
            archetype_policy_version=ARCHETYPE_POLICY_VERSION,
        )
        .on_conflict_do_nothing(constraint="uq_site_observed_architecture")
        .returning(SiteObservedArchitecture.id)
    )
    if inserted_id is None:
        return 0
    evaluations = evaluate_architecture_rules(
        model=model, source_pages=pages, coverage_state=coverage.coverage_state
    )
    await _persist_rule_evaluations(
        session,
        crawl=crawl,
        architecture_id=inserted_id,
        root=root,
        pages=pages,
        evaluations=evaluations,
    )
    await session.flush()
    return 1


__all__ = ["persist_observed_architecture"]
