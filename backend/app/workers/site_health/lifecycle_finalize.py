"""Crawl-finalize evaluation and persistence stage.

This mixin is deliberately kept beside :mod:`lifecycle`: it is part of the
same locked terminalization transaction, but has a separate ownership boundary
for cross-page evaluation and projection persistence.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.finalize import (
    evaluate_broken_internal_link,
    evaluate_hreflang_conflict,
    evaluate_sitemap_orphan,
)
from app.analysis.site_health.rules import RuleEvaluation
from app.connectors.web_evidence.url_policy import UrlPolicyError
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    EXTRACTOR_VERSION,
    LINK_KIND_ANCHOR,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
)
from app.domain.site_health.normalization import canonical_identity, canonical_or_empty
from app.domain.site_health.snapshot import persist_crawl_snapshot
from app.models.site_health.acquisition import SiteFetchArtifact
from app.models.site_health.analysis import (
    SiteIssue,
    SiteLinkReference,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl, SiteUrlObservation


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


def _pass_through_hreflang_evaluation() -> RuleEvaluation:
    return evaluate_hreflang_conflict(
        alternate_count=0,
        checked_count=0,
        unchecked_count=0,
        missing_return_tags=[],
    )


def _cross_check_hreflang_alternates(
    alternates: list[dict],
    source_canonical: str,
    alternates_by_page: dict[str, list[dict]],
) -> tuple[int, int, list[str]]:
    checked_count = 0
    unchecked_count = 0
    missing: list[str] = []
    for alternate in alternates:
        target_url = str(alternate.get("url") or "")
        target_canonical = canonical_or_empty(target_url)
        if not target_canonical:
            unchecked_count += 1
            continue
        if target_canonical == source_canonical:
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
    return checked_count, unchecked_count, missing


def _evaluate_hreflang_for_page(
    alternates: list[dict],
    source_canonical: str | None,
    alternates_by_page: dict[str, list[dict]],
) -> RuleEvaluation:
    if not alternates or not source_canonical:
        return _pass_through_hreflang_evaluation()
    checked, unchecked, missing = _cross_check_hreflang_alternates(
        alternates, source_canonical, alternates_by_page
    )
    return evaluate_hreflang_conflict(
        alternate_count=len(alternates),
        checked_count=checked,
        unchecked_count=unchecked,
        missing_return_tags=missing,
    )


async def _crawl_hreflang_indexes(
    session: AsyncSession,
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
            .where(SiteFetchArtifact.id.in_(artifact_by_analysis.values()))
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


class CrawlFinalizeMixin:
    """Own cross-page finalize evaluation and projection persistence."""

    async def _run_crawl_finalize_pass(
        self, session: AsyncSession, *, crawl: SiteCrawl
    ) -> None:
        rows = await self._load_latest_analyses(session, crawl=crawl)
        if not rows:
            return
        analysis_ids = [row.id for row in rows]
        artifact_by_analysis = {row.id: row.artifact_id for row in rows}
        site_url_by_analysis = {row.id: row.site_url_id for row in rows}
        evaluations = await self._evaluate_broken_internal_links(
            session, analysis_ids=analysis_ids
        )
        evaluations.extend(
            await self._evaluate_hreflang_conflicts(
                session, rows=rows, artifact_by_analysis=artifact_by_analysis
            )
        )
        evaluations.extend(
            await self._evaluate_sitemap_orphans(
                session,
                crawl=crawl,
                rows=rows,
                analysis_ids=analysis_ids,
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
                SitePageAnalysis.crawl_id == crawl.id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
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

    async def _evaluate_broken_internal_links(
        self, session: AsyncSession, *, analysis_ids: list[uuid.UUID]
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        link_rows = (
            await session.execute(
                select(
                    SiteLinkReference.source_analysis_id,
                    SiteLinkReference.target_url,
                    SiteLinkReference.evidence_fingerprint,
                ).where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.is_internal.is_(True),
                )
            )
        ).all()
        checked: dict[uuid.UUID, int] = {}
        broken: dict[uuid.UUID, list[str]] = {}
        for source_analysis_id, target_url, fingerprint in link_rows:
            fp = str(fingerprint or "")
            if fp.startswith("policy_skipped:"):
                continue
            checked[source_analysis_id] = checked.get(source_analysis_id, 0) + 1
            if fp.startswith("unreachable:"):
                bucket = broken.setdefault(source_analysis_id, [])
                if target_url not in bucket:
                    bucket.append(target_url)
        return [
            (
                analysis_id,
                evaluate_broken_internal_link(
                    checked_count=checked.get(analysis_id, 0),
                    broken_urls=broken.get(analysis_id, []),
                ),
            )
            for analysis_id in analysis_ids
        ]

    async def _evaluate_hreflang_conflicts(
        self,
        session: AsyncSession,
        *,
        rows: list[Any],
        artifact_by_analysis: dict[uuid.UUID, uuid.UUID],
    ) -> list[tuple[uuid.UUID, RuleEvaluation]]:
        (
            per_artifact,
            alternates_by_page,
            canonical_by_artifact,
        ) = await _crawl_hreflang_indexes(session, artifact_by_analysis)
        analysis_by_artifact = {row.artifact_id: row.id for row in rows}
        return [
            (
                analysis_by_artifact[artifact_id],
                _evaluate_hreflang_for_page(
                    alternates,
                    canonical_by_artifact.get(artifact_id),
                    alternates_by_page,
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
        analysis_ids: list[uuid.UUID],
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
        root_analysis_id = next(
            (
                row.id
                for row in rows
                if hash_by_site_url.get(row.site_url_id) == root_hash
            ),
            None,
        )
        if root_analysis_id is None:
            return []
        sitemap_rows = (
            await session.execute(
                select(
                    SiteUrlObservation.site_url_id,
                    SiteUrlObservation.observed_url,
                ).where(
                    SiteUrlObservation.crawl_id == crawl.id,
                    SiteUrlObservation.source_kind == OBSERVATION_SOURCE_SITEMAP,
                )
            )
        ).all()
        anchor_rows = (
            await session.execute(
                select(SiteLinkReference.target_url).where(
                    SiteLinkReference.source_analysis_id.in_(analysis_ids),
                    SiteLinkReference.is_internal.is_(True),
                    SiteLinkReference.kind == LINK_KIND_ANCHOR,
                )
            )
        ).all()
        linked_targets = {
            canonical
            for (target_url,) in anchor_rows
            if (canonical := canonical_or_empty(str(target_url)))
        }
        orphans = _sitemap_orphan_urls(
            sitemap_rows, root_canonical=root_canonical, linked_targets=linked_targets
        )
        return [
            (
                root_analysis_id,
                evaluate_sitemap_orphan(
                    sitemap_url_count=len(sitemap_rows), orphan_urls=orphans
                ),
            )
        ]

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
                    weight=ev.weight,
                    outcome=ev.outcome,
                    evidence=ev.evidence,
                    supporting_artifact_ids=[artifact_id],
                    extractor_version=crawl.extractor_version or EXTRACTOR_VERSION,
                    analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
                    rule_version=ev.rule_version,
                )
                .on_conflict_do_nothing(index_elements=["analysis_id", "rule_id"])
                .returning(SiteRuleEvaluation.id)
            )
            if inserted_id is None:
                continue
            if ev.outcome == RULE_OUTCOME_FAIL:
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
