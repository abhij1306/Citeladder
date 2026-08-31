"""Persist Site Health page analyses, evaluations, and issue snapshots."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.page_analysis import PageAnalysisResult, analyze_page
from app.analysis.site_health.rules import RuleEvaluation, creates_issue
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    DISCOVERY_STATUS_COMPLETED,
    EXTRACTOR_VERSION,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    SCORING_VERSION,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.site_health_traits import TRAITS_VERSION
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl, SiteUrlObservation
from app.workers.site_health.helpers import _utcnow
from app.workers.site_health.lifecycle_finalize import crawl_root_identity
from app.workers.site_health.phases.contracts import PhaseContext


async def _write_page_analysis(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    artifact_id: uuid.UUID,
    facts: dict,
) -> tuple[uuid.UUID, str]:
    """Create the page analysis + rule evaluations + issues + scores.

    One UUID-identified ``SitePageAnalysis`` (``artifact_id`` is provenance), one
    ordinary ``SiteRuleEvaluation`` per rule/analysis scope, a
    ``SiteIssue`` snapshot per actionable failing outcome (unique
    ``evaluation_id``), and the
    deterministic Web Fundamentals and AEO score/coverage/state projections
    stamped with their versions.
    """
    site_url_id = await _resolve_analysis_site_url_id(
        ctx, session, crawl=crawl, task=task
    )
    sitemap_member = bool(
        await session.scalar(
            select(SiteUrlObservation.id)
            .where(
                SiteUrlObservation.crawl_id == crawl.id,
                SiteUrlObservation.site_url_id == site_url_id,
                SiteUrlObservation.source_kind == OBSERVATION_SOURCE_SITEMAP,
            )
            .limit(1)
        )
    )
    site_facts = _root_site_facts(crawl, task)
    result = analyze_page(facts, sitemap_member=sitemap_member, site_facts=site_facts)
    await _refresh_analyzed_url_state(
        session,
        crawl=crawl,
        site_url_id=site_url_id,
        artifact_id=artifact_id,
        facts=facts,
    )
    analysis = _new_page_analysis(
        crawl=crawl,
        site_url_id=site_url_id,
        artifact_id=artifact_id,
        result=result,
    )
    await _supersede_and_store_analysis(session, analysis=analysis)
    await _persist_evaluations_and_issues(
        session,
        crawl=crawl,
        analysis=analysis,
        artifact_id=artifact_id,
        site_url_id=site_url_id,
        evaluations=result.evaluations,
    )
    return analysis.id, analysis.page_kind


def _root_site_facts(crawl: SiteCrawl, task: SiteCrawlTask) -> dict | None:
    if not crawl.site_facts:
        return None
    _root_canonical, root_hash = crawl_root_identity(crawl)
    return crawl.site_facts if root_hash and root_hash == task.url_hash else None


async def _refresh_analyzed_url_state(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID,
    artifact_id: uuid.UUID,
    facts: dict,
) -> SiteUrl | None:
    """Refresh mutable URL and admitted-observation fields from one fetch."""
    # Refresh the lightweight identity/observation state from the analyze
    # fetch. A Free sample URL is fetched ONLY by its analyze task (no
    # per-URL discover runs), so its admission-time observation row is
    # sparse (no title/status) until enriched here; without this the pages
    # table shows blank titles for 9 of 10 sampled URLs.
    site_url = await session.get(SiteUrl, site_url_id)
    if site_url is not None:
        title = str(facts.get("title") or "")
        if title:
            site_url.latest_title = title[:1024]
        site_url.latest_content_type = str(facts.get("content_type") or "")[:128]
        site_url.last_seen_crawl_id = crawl.id
        site_url.discovery_status = DISCOVERY_STATUS_COMPLETED
    observation = await session.scalar(
        select(SiteUrlObservation).where(
            SiteUrlObservation.crawl_id == crawl.id,
            SiteUrlObservation.site_url_id == site_url_id,
        )
    )
    if observation is not None and observation.status_code is None:
        # ``status_code``/``final_url`` are nested under ``delivery`` by the
        # parser (only ``content_type``/``title`` are top level). Reading
        # them off the root left every observation with a NULL status and a
        # blank final URL — and because the guard above keys on
        # ``status_code is None``, the block re-ran forever without ever
        # filling it. Same accessor the rule-eval path already uses.
        delivery = facts.get("delivery") or {}
        observation.status_code = delivery.get("status_code")
        observation.final_url = str(delivery.get("final_url") or "")[:2048]
        observation.content_type = str(facts.get("content_type") or "")[:128]
        observation.title = str(facts.get("title") or "")[:1024]
        observation.source_artifact_id = artifact_id
    return site_url


def _new_page_analysis(
    *,
    crawl: SiteCrawl,
    site_url_id: uuid.UUID,
    artifact_id: uuid.UUID,
    result: PageAnalysisResult,
) -> SitePageAnalysis:
    """Build the immutable analysis row before it becomes current."""
    return SitePageAnalysis(
        id=uuid.uuid4(),
        workspace_id=crawl.workspace_id,
        project_id=crawl.project_id,
        crawl_id=crawl.id,
        site_url_id=site_url_id,
        artifact_id=artifact_id,
        status=PAGE_ANALYSIS_STATUS_COMPLETED,
        web_fundamentals_score=result.scores.web_fundamentals_score,
        web_fundamentals_coverage=result.scores.web_fundamentals_coverage,
        web_fundamentals_state=result.scores.web_fundamentals_state,
        technical_earned_weight=result.scores.technical_earned_weight,
        technical_determinate_weight=result.scores.technical_determinate_weight,
        technical_expected_weight=result.scores.technical_expected_weight,
        technical_critical_complete=result.scores.technical_critical_complete,
        aeo_readiness_score=result.scores.aeo_readiness_score,
        aeo_measurement_coverage=result.scores.aeo_measurement_coverage,
        aeo_measurement_state=result.scores.aeo_measurement_state,
        aeo_measurement_reason=result.scores.aeo_measurement_reason,
        expected_checkpoint_profile=list(result.scores.expected_checkpoint_profile),
        readiness_dimensions=[
            item.to_dict() for item in result.scores.readiness_dimensions
        ],
        profile_version=PROFILE_VERSION,
        schema_contract_version=SCHEMA_CONTRACT_VERSION,
        presentation_version=PRESENTATION_VERSION,
        main_content_indexable=result.scores.main_content_indexable,
        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
        scoring_version=crawl.scoring_version or SCORING_VERSION,
        page_kind=result.assessment.page_kind,
        classifier_version=result.assessment.classifier_version,
        # Persist the bounded classifier evidence with the row (the
        # evaluation-time copy above is never persisted, by design).
        page_kind_evidence=result.assessment.to_evidence(),
        page_traits=list(result.traits),
        traits_version=TRAITS_VERSION,
        source_artifact_ids=[artifact_id],
        finalized_at=_utcnow(),
    )


async def _supersede_and_store_analysis(
    session: AsyncSession, *, analysis: SitePageAnalysis
) -> None:
    """Supersede the page's current analysis, then flush its new identity."""
    # Append-only: supersede any earlier current understanding of this PAGE
    # before inserting the new one.
    #
    # Matched on the page, not the artifact. A rerun fetches again and gets
    # a NEW artifact, so the artifact-keyed supersede never found the
    # previous analysis and left two live rows for one URL — which
    # ``build_crawl_knowledge`` then folded into one model, manufacturing
    # exactly the contradictions-out-of-a-rerun its docstring warns about.
    #
    await session.execute(
        update(SitePageAnalysis)
        .where(
            SitePageAnalysis.crawl_id == analysis.crawl_id,
            SitePageAnalysis.site_url_id == analysis.site_url_id,
            SitePageAnalysis.is_current.is_(True),
        )
        .values(is_current=False)
    )
    session.add(analysis)
    await session.flush()


async def _persist_evaluations_and_issues(
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    analysis: SitePageAnalysis,
    artifact_id: uuid.UUID,
    site_url_id: uuid.UUID,
    evaluations: tuple[RuleEvaluation, ...],
) -> None:
    """Persist ordered evaluations and issues in two dependency batches."""
    evaluation_ids: list[uuid.UUID] = []
    failed: list[tuple[RuleEvaluation, uuid.UUID]] = []
    for ev in evaluations:
        evaluation_id = uuid.uuid4()
        evaluation = SiteRuleEvaluation(
            id=evaluation_id,
            workspace_id=crawl.workspace_id,
            analysis_id=analysis.id,
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
        session.add(evaluation)
        evaluation_ids.append(evaluation_id)
        if creates_issue(ev):
            failed.append((ev, evaluation_id))
    analysis.source_evaluation_ids = evaluation_ids
    # Evaluation rows depend on the already-flushed analysis. Flush them as
    # one batch so issue foreign keys are valid without one sync per rule.
    await session.flush()
    for ev, evaluation_id in failed:
        session.add(
            SiteIssue(
                workspace_id=crawl.workspace_id,
                project_id=crawl.project_id,
                crawl_id=crawl.id,
                site_url_id=site_url_id,
                analysis_id=analysis.id,
                evaluation_id=evaluation_id,
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
    # Keep every potentially failing insert before the final locked lease guard.
    await session.flush()


async def _resolve_analysis_site_url_id(
    ctx: PhaseContext,
    session: AsyncSession,
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
) -> uuid.UUID:
    """Resolve the SiteUrl identity for an analyze task's URL.

    Prefers the task's own ``site_url_id`` (set at admission for monitored
    URLs); falls back to a lookup / conflict-safe create keyed on the
    canonical url hash so an analyze task never fails for a missing row.
    """
    if task.site_url_id is not None:
        return task.site_url_id
    resolved = await ctx.resolve_site_url_id(
        session, crawl=crawl, url=task.requested_url, depth=task.depth
    )
    if resolved is None:
        # Only reachable when the URL cannot be canonicalized at all —
        # admission already canonicalized it, so treat as a hard bug. A
        # retry at depth 0 used to sit here, but ``_resolve_site_url_id``
        # returns None only for an uncanonicalizable URL: depth never
        # affects that, so the retry could not have changed the outcome.
        raise RuntimeError(
            f"could not resolve SiteUrl identity for {task.requested_url!r}"
        )
    return resolved
