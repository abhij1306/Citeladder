"""Crawl-finalize evaluation and persistence stage.

This mixin is deliberately kept beside :mod:`lifecycle`: it is part of the
same locked terminalization transaction, but has a separate ownership boundary
for cross-page evaluation and projection persistence.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.finalize import (
    evaluate_broken_internal_links,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
    evaluate_sitemap_url_unreachable,
)
from app.analysis.site_health.rules import RuleEvaluation, creates_issue
from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    EXTRACTOR_VERSION,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
)
from app.domain.site_health.coverage import crawl_coverage
from app.domain.site_health.normalization import canonical_identity, canonical_or_empty
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl, SiteUrlObservation
from app.workers.site_health.resolution_evidence import (
    Resolution,
    canonical_resolution_evaluations,
    fetch_resolutions,
    rate_limited_targets,
    resolution_set_evaluation,
)


def crawl_root_identity(crawl: SiteCrawl) -> tuple[str, str]:
    """Return ``(canonical, url_hash)`` for the crawl root."""
    try:
        return canonical_identity(crawl.root_url)
    except UrlPolicyError:
        return "", ""


def _sitemap_orphan_urls(
    sitemap_rows: Sequence[Any], *, root_canonical: str, linked_targets: set[str]
) -> list[str]:
    orphans: list[str] = []
    for _site_url_id, observed_url in sitemap_rows:
        observed = str(observed_url or "")
        canonical = canonical_or_empty(observed)
        if not canonical or canonical == root_canonical:
            continue
        if canonical in linked_targets or observed in orphans:
            continue
        orphans.append(observed)
    return orphans


def _root_analysis_id(
    rows: Sequence[Any], *, hash_by_site_url: dict[uuid.UUID, str], root_hash: str
) -> uuid.UUID | None:
    return next(
        (row.id for row in rows if hash_by_site_url.get(row.site_url_id) == root_hash),
        None,
    )


def _internal_link_targets(artifacts: Sequence[Any]) -> list[str]:
    """Return one observation per source→target graph edge.

    The graph identity is source plus target, so duplicate anchors extracted
    from one source collapse to one edge; the same target from different
    sources remains repeated and contributes to graph cardinality.
    """
    targets: list[str] = []
    for source_url, facts in artifacts:
        source_targets: set[str] = set()
        for anchor in ((facts or {}).get("links") or {}).get("anchors") or []:
            canonical = _canonical_internal_target(source_url, anchor)
            if canonical:
                source_targets.add(canonical)
        targets.extend(sorted(source_targets))
    return targets


def _canonical_internal_target(source_url: object, anchor: object) -> str:
    row = anchor if isinstance(anchor, dict) else {}
    if not bool(row.get("is_internal")):
        return ""
    return canonical_or_empty(urljoin(str(source_url or ""), str(row.get("url") or "")))


def _pass_through_hreflang_evaluation() -> RuleEvaluation:
    return evaluate_hreflang_conflict(
        alternate_count=0,
        checked_count=0,
        unchecked_count=0,
        missing_return_tags=[],
        rate_limited_count=0,
    )


def _cross_check_hreflang_alternates(
    alternates: list[dict],
    source_canonical: str,
    alternates_by_page: dict[str, list[dict]],
    rate_limited_targets: set[str],
) -> tuple[int, int, int, list[str]]:
    checked_count = 0
    unchecked_count = 0
    rate_limited_count = 0
    missing: list[str] = []
    for alternate in alternates:
        target_url = str(alternate.get("url") or "")
        target_canonical = canonical_or_empty(target_url)
        if not target_canonical:
            unchecked_count += 1
            continue
        if target_canonical == source_canonical:
            continue
        if target_canonical in rate_limited_targets:
            unchecked_count += 1
            rate_limited_count += 1
            continue
        target_alternates = alternates_by_page.get(target_canonical)
        if target_alternates is None:
            unchecked_count += 1
            continue
        checked_count += 1
        return_tag_found = any(
            canonical_or_empty(str(back.get("url") or "")) == source_canonical
            for back in target_alternates
        )
        if not return_tag_found and target_url not in missing:
            missing.append(target_url)
    return checked_count, unchecked_count, rate_limited_count, missing


def _evaluate_hreflang_for_page(
    alternates: list[dict],
    source_canonical: str | None,
    alternates_by_page: dict[str, list[dict]],
    rate_limited_targets: set[str],
) -> RuleEvaluation:
    if not alternates or not source_canonical:
        return _pass_through_hreflang_evaluation()
    checked, unchecked, rate_limited, missing = _cross_check_hreflang_alternates(
        alternates, source_canonical, alternates_by_page, rate_limited_targets
    )
    return evaluate_hreflang_conflict(
        alternate_count=len(alternates),
        checked_count=checked,
        unchecked_count=unchecked,
        missing_return_tags=missing,
        rate_limited_count=rate_limited,
    )


async def _crawl_hreflang_indexes(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
) -> tuple[
    list[tuple[uuid.UUID, str, list[dict]]],
    dict[str, list[dict]],
    dict[uuid.UUID, str],
]:
    artifacts = (
        await session.execute(
            select(
                SiteFetchArtifact.id,
                SiteFetchArtifact.final_url,
                SiteFetchArtifact.normalized_facts,
            )
            .where(
                SiteFetchArtifact.id.in_(artifact_by_analysis.values()),
                SiteFetchArtifact.crawl_id == crawl.id,
                SiteFetchArtifact.workspace_id == crawl.workspace_id,
            )
            .order_by(SiteFetchArtifact.id)
        )
    ).all()
    alternates_by_page: dict[str, list[dict]] = {}
    canonical_by_artifact: dict[uuid.UUID, str] = {}
    per_artifact: list[tuple[uuid.UUID, str, list[dict]]] = []
    for artifact_id, final_url, facts in artifacts:
        canonical = canonical_or_empty(str(final_url or ""))
        alternates = list((facts or {}).get("hreflang_alternates") or [])
        if canonical:
            canonical_by_artifact[artifact_id] = canonical
            alternates_by_page.setdefault(canonical, alternates)
        per_artifact.append((artifact_id, canonical, alternates))
    return per_artifact, alternates_by_page, canonical_by_artifact


async def _site_url_hashes(
    session: AsyncSession, *, crawl: SiteCrawl, site_url_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, str]:
    rows = await session.execute(
        select(SiteUrl.id, SiteUrl.url_hash).where(
            SiteUrl.id.in_(site_url_ids),
            SiteUrl.workspace_id == crawl.workspace_id,
            SiteUrl.project_id == crawl.project_id,
        )
    )
    return {row[0]: row[1] for row in rows}


def _source_link_evaluation(evaluation: RuleEvaluation) -> RuleEvaluation:
    """Make a source-page link observation participate as one graph entity.

    ``evaluate_broken_internal_links`` calculates normalized target-set results
    when it is used for the single, crawl-wide set.  Broken-link occurrences
    are now persisted per source page, so those per-source target ratios must
    not override the score rollup (which aggregates source observations).
    The bounded target evidence remains unchanged for the issue presenter.
    """
    return replace(
        evaluation,
        evidence={
            key: value
            for key, value in evaluation.evidence.items()
            if key not in {"normalized_score", "normalized_coverage"}
        },
    )


class CrawlFinalizeMixin:
    """Own cross-page finalize evaluation and projection persistence."""

    async def _run_crawl_finalize_pass(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        rows = await self._load_latest_analyses(session, crawl=crawl)
        if not rows:
            return
        artifact_by_analysis = {row.id: row.artifact_id for row in rows}
        site_url_by_analysis = {row.id: row.site_url_id for row in rows}
        resolutions = await fetch_resolutions(session, crawl=crawl)
        evaluations = await self._evaluate_hreflang_conflicts(
            session,
            crawl=crawl,
            rows=rows,
            artifact_by_analysis=artifact_by_analysis,
            resolutions=resolutions,
        )
        evaluations.extend(
            await self._evaluate_resolution_rules(
                session,
                crawl=crawl,
                rows=rows,
                artifact_by_analysis=artifact_by_analysis,
                site_url_by_analysis=site_url_by_analysis,
                resolutions=resolutions,
            )
        )
        evaluations.extend(
            await self._evaluate_sitemap_orphans(
                session,
                crawl=crawl,
                rows=rows,
                artifact_by_analysis=artifact_by_analysis,
                site_url_by_analysis=site_url_by_analysis,
            )
        )
        await self._persist_evaluations(
            session,
            crawl=crawl,
            evaluations=evaluations,
            artifact_by_analysis=artifact_by_analysis,
            site_url_by_analysis=site_url_by_analysis,
        )

    async def _load_latest_analyses(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> list[Any]:
        ranked = (
            select(
                SitePageAnalysis.id.label("id"),
                SitePageAnalysis.site_url_id.label("site_url_id"),
                SitePageAnalysis.artifact_id.label("artifact_id"),
                func.row_number()
                .over(
                    partition_by=SitePageAnalysis.site_url_id,
                    order_by=(
                        SitePageAnalysis.created_at.desc(),
                        SitePageAnalysis.id.desc(),
                    ),
                )
                .label("latest_rank"),
            )
            .where(
                SitePageAnalysis.workspace_id == crawl.workspace_id,
                SitePageAnalysis.project_id == crawl.project_id,
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                SitePageAnalysis.is_current.is_(True),
            )
            .subquery()
        )
        return list(
            (
                await session.execute(
                    select(
                        ranked.c.id, ranked.c.site_url_id, ranked.c.artifact_id
                    ).where(ranked.c.latest_rank == 1)
                )
            ).all()
        )

    async def _evaluate_hreflang_conflicts(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        rows: list[Any],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
        resolutions: dict[str, Resolution],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        (
            per_artifact,
            alternates_by_page,
            canonical_by_artifact,
        ) = await _crawl_hreflang_indexes(
            session, crawl=crawl, artifact_by_analysis=artifact_by_analysis
        )
        analysis_by_artifact = {row.artifact_id: row.id for row in rows}
        return [
            (
                analysis_by_artifact[artifact_id],
                _evaluate_hreflang_for_page(
                    alternates,
                    canonical_by_artifact.get(artifact_id),
                    alternates_by_page,
                    rate_limited_targets(resolutions),
                ),
            )
            for artifact_id, _canonical, alternates in per_artifact
        ]

    async def _evaluate_sitemap_orphans(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        rows: list[Any],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
        site_url_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        root_canonical, root_hash = crawl_root_identity(crawl)
        if not root_hash:
            return []
        site_url_rows = (
            await session.execute(
                select(SiteUrl.id, SiteUrl.url_hash).where(
                    SiteUrl.id.in_(site_url_by_analysis.values())
                )
            )
        ).all()
        hash_by_site_url = {row[0]: row[1] for row in site_url_rows}
        root_analysis_id = _root_analysis_id(
            rows, hash_by_site_url=hash_by_site_url, root_hash=root_hash
        )
        if root_analysis_id is None:
            return []
        sitemap_rows = (
            await session.execute(
                select(
                    SiteUrlObservation.site_url_id,
                    SiteUrlObservation.observed_url,
                ).where(
                    SiteUrlObservation.workspace_id == crawl.workspace_id,
                    SiteUrlObservation.project_id == crawl.project_id,
                    SiteUrlObservation.crawl_id == crawl.id,
                    SiteUrlObservation.source_kind == OBSERVATION_SOURCE_SITEMAP,
                )
            )
        ).all()
        artifacts = (
            await session.execute(
                select(SiteFetchArtifact.final_url, SiteFetchArtifact.normalized_facts)
                .join(
                    SitePageAnalysis,
                    SitePageAnalysis.artifact_id == SiteFetchArtifact.id,
                )
                .where(
                    SiteFetchArtifact.id.in_(artifact_by_analysis.values()),
                    SiteFetchArtifact.crawl_id == crawl.id,
                    SiteFetchArtifact.workspace_id == crawl.workspace_id,
                    SitePageAnalysis.workspace_id == crawl.workspace_id,
                    SitePageAnalysis.project_id == crawl.project_id,
                    SitePageAnalysis.crawl_id == crawl.id,
                )
            )
        ).all()
        linked_targets = _internal_link_targets(artifacts)
        orphans = _sitemap_orphan_urls(
            sitemap_rows,
            root_canonical=root_canonical,
            linked_targets=set(linked_targets),
        )
        coverage = await crawl_coverage(session, crawl=crawl)
        return [
            (
                root_analysis_id,
                evaluate_sitemap_orphan(
                    sitemap_url_count=len(sitemap_rows),
                    orphan_urls=orphans,
                    coverage_state=coverage.state,
                ),
            )
        ]

    async def _evaluate_resolution_rules(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        rows: list[Any],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
        site_url_by_analysis: dict[uuid.UUID, uuid.UUID],
        resolutions: dict[str, Resolution],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        """Build canonical, internal-link, and sitemap resolution results."""
        artifacts = (
            await session.execute(
                select(
                    SiteFetchArtifact.id,
                    SiteFetchArtifact.final_url,
                    SiteFetchArtifact.normalized_facts,
                ).where(
                    SiteFetchArtifact.id.in_(artifact_by_analysis.values()),
                    SiteFetchArtifact.crawl_id == crawl.id,
                    SiteFetchArtifact.workspace_id == crawl.workspace_id,
                )
            )
        ).all()
        analysis_ids_by_artifact: dict[uuid.UUID, list[uuid.UUID]] = {}
        for row in rows:
            analysis_ids_by_artifact.setdefault(row.artifact_id, []).append(row.id)
        evaluations = canonical_resolution_evaluations(
            artifacts,
            analysis_ids_by_artifact=analysis_ids_by_artifact,
            resolutions=resolutions,
        )

        for artifact_id, final_url, normalized_facts in artifacts:
            page_targets = _internal_link_targets(
                [(str(final_url or ""), normalized_facts)]
            )
            page_evaluation = _source_link_evaluation(
                resolution_set_evaluation(
                    page_targets,
                    resolutions=resolutions,
                    evaluator=evaluate_broken_internal_links,
                    failure_key="broken_urls",
                )
            )
            evaluations.extend(
                (analysis_id, page_evaluation)
                for analysis_id in analysis_ids_by_artifact[artifact_id]
            )

        _root_canonical, root_hash = crawl_root_identity(crawl)
        root_analysis_id = _root_analysis_id(
            rows,
            hash_by_site_url=await _site_url_hashes(
                session,
                crawl=crawl,
                site_url_ids=tuple(site_url_by_analysis.values()),
            ),
            root_hash=root_hash,
        )
        if root_analysis_id is None:
            return evaluations

        sitemap_rows = (
            await session.scalars(
                select(SiteUrlObservation.observed_url).where(
                    SiteUrlObservation.workspace_id == crawl.workspace_id,
                    SiteUrlObservation.project_id == crawl.project_id,
                    SiteUrlObservation.crawl_id == crawl.id,
                    SiteUrlObservation.source_kind == OBSERVATION_SOURCE_SITEMAP,
                )
            )
        ).all()
        sitemap_targets = {
            canonical
            for url in sitemap_rows
            if (canonical := canonical_or_empty(str(url or "")))
        }
        sitemap_evaluation = resolution_set_evaluation(
            sorted(sitemap_targets),
            resolutions=resolutions,
            evaluator=evaluate_sitemap_url_unreachable,
            failure_key="unreachable_urls",
        )
        evaluations.append(
            (
                root_analysis_id,
                sitemap_evaluation,
            )
        )
        return evaluations

    async def _persist_evaluations(
        self,
        session: AsyncSession,
        *,
        crawl: SiteCrawl,
        evaluations: list[tuple[uuid.UUID, RuleEvaluation]],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
        site_url_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> None:
        for analysis_id, ev in evaluations:
            artifact_id = artifact_by_analysis[analysis_id]
            inserted_id = await session.scalar(
                pg_insert(SiteRuleEvaluation)
                .values(
                    workspace_id=crawl.workspace_id,
                    analysis_id=analysis_id,
                    source_artifact_id=artifact_id,
                    rule_id=ev.rule_id,
                    dimension=ev.dimension,
                    category=ev.category,
                    severity=ev.severity,
                    finding_class=ev.finding_class,
                    scope=ev.scope,
                    weight=ev.weight,
                    outcome=ev.outcome,
                    display_applicability=ev.display_applicability,
                    score_applicability=ev.score_applicability,
                    expected_profile_membership=ev.expected_profile_membership,
                    reason_code=ev.reason_code,
                    score_roles=list(ev.score_roles),
                    checkpoint_family=ev.checkpoint_family,
                    readiness_dimension=ev.readiness_dimension,
                    readiness_weight=ev.readiness_weight,
                    evidence=ev.evidence,
                    supporting_artifact_ids=[artifact_id],
                    extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                    analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                    rule_version=ev.rule_version,
                )
                .on_conflict_do_nothing(
                    index_elements=[
                        "analysis_id",
                        "rule_id",
                        "source_architecture_id",
                    ]
                )
                .returning(SiteRuleEvaluation.id)
            )
            if inserted_id is None:
                continue
            if creates_issue(ev):
                session.add(
                    SiteIssue(
                        workspace_id=crawl.workspace_id,
                        project_id=crawl.project_id,
                        crawl_id=crawl.id,
                        site_url_id=site_url_by_analysis[analysis_id],
                        analysis_id=analysis_id,
                        evaluation_id=inserted_id,
                        source_artifact_id=artifact_id,
                        rule_id=ev.rule_id,
                        dimension=ev.dimension,
                        category=ev.category,
                        severity=ev.severity,
                        finding_class=ev.finding_class,
                        evidence=ev.evidence,
                        description=ev.description,
                        remediation=ev.remediation,
                        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                        rule_version=ev.rule_version,
                    )
                )
        await session.flush()

    async def _persist_snapshot(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        await persist_crawl_snapshot(session, crawl=crawl, persist_empty=True)
