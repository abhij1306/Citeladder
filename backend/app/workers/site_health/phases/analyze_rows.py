"""Persist Site Health page analyses, evaluations, and issue snapshots."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.page_kinds import PageKindAssessment, classify
from app.analysis.site_health.page_traits import derive_traits
from app.analysis.site_health.rules import RuleEvaluation, evaluate_all
from app.analysis.site_health.scoring import AnalysisScores, score_analysis
from app.core.config.site_health_contracts import (
    ANALYZER_VERSION,
    DISCOVERY_STATUS_COMPLETED,
    EXTRACTOR_VERSION,
    OBSERVATION_SOURCE_SITEMAP,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_OUTCOME_FAIL,
    SCORING_VERSION,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.site_health_rule_types import FINDING_CLASS_DIAGNOSTIC
from app.core.config.site_health_traits import TRAITS_VERSION
from app.models.site_health.analysis import (
    SiteIssue,
    SitePageAnalysis,
    SiteRuleEvaluation,
)
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.queue import SiteCrawlTask
from app.models.site_health.urls import SiteUrl, SiteUrlObservation
from app.workers.site_health.helpers import (
    _is_crawl_finalize_rule,
    _utcnow,
)
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
    ``SiteIssue`` snapshot per FAIL (unique ``evaluation_id``), and the
    deterministic Technical/AEO/overall scores stamped with the versions.
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
    assessment, traits, evaluations, scores = _prepare_page_evaluation(
        crawl=crawl, task=task, facts=facts, sitemap_member=sitemap_member
    )
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
        assessment=assessment,
        traits=traits,
        scores=scores,
    )
    await _supersede_and_store_analysis(session, analysis=analysis)
    await _persist_evaluations_and_issues(
        session,
        crawl=crawl,
        analysis=analysis,
        artifact_id=artifact_id,
        site_url_id=site_url_id,
        evaluations=evaluations,
    )
    return analysis.id, analysis.page_kind


def _prepare_page_evaluation(
    *,
    crawl: SiteCrawl,
    task: SiteCrawlTask,
    facts: dict[str, Any],
    sitemap_member: bool = False,
) -> tuple[PageKindAssessment, tuple[str, ...], list[RuleEvaluation], AnalysisScores]:
    """Classify and score a shallow evaluation-only copy of fetched facts."""
    # Evaluation-time enrichment goes onto a SHALLOW COPY, never the facts
    # dict the caller handed ``_write_artifact``: that dict IS the artifact's
    # ``normalized_facts``, and the persisted evidence must carry only what
    # the extractor produced (the injected keys below are provenance of this
    # analysis, not of the fetch). Copying makes that independent of insert
    # ordering / JSON-mutation tracking rather than relying on the flush
    # having already serialized the pre-injection value.
    eval_facts = dict(facts)
    # v2 P1: classify the page type and inject it into the facts dict
    # BEFORE rule evaluation, so page_kind applicability tokens, per-type
    # thin-content minimums, and weight overrides resolve against it
    # (spec §5.1 pipeline slot; evaluate_all keeps its pure (facts)
    # signature). The type + classifier version persist on the analysis
    # row for provenance (invariant 4).
    assessment = classify(
        str((facts.get("delivery") or {}).get("final_url") or ""), facts
    )
    eval_facts["page_kind"] = assessment.page_kind
    eval_facts["page_kind_evidence"] = assessment.to_evidence()
    # Traits are derived from the SAME facts but never from the page kind, so
    # they stay independent observations rather than consequences of the
    # classification. A product page with an FAQ block carries both.
    traits = derive_traits(
        str((facts.get("delivery") or {}).get("final_url") or ""), facts
    )
    eval_facts["page_traits"] = list(traits)
    eval_facts["sitemap_member"] = sitemap_member
    # v2 P2 (spec §5.3): inside the crawl ROOT's own analysis only, inject
    # the crawl's site_facts so site_root-scoped rules (AI-crawler access,
    # llms.txt) evaluate exactly once per crawl, anchored on this analysis.
    # Injected into the copy only, so the persisted normalized_facts
    # deliberately do NOT carry it (same as page_kind).
    if crawl.site_facts:
        _root_canonical, root_hash = crawl_root_identity(crawl)
        if root_hash and root_hash == task.url_hash:
            eval_facts["site"] = crawl.site_facts
    evaluations: list[RuleEvaluation] = [
        ev
        for ev in evaluate_all(eval_facts)
        # The analyze writer NEVER persists crawl_finalize-scoped
        # evaluations (no placeholder not_applicable rows): the unique
        # ordinary analysis/rule scope stays free for the finalize pass,
        # which solely owns those rules' rows (single-writer per scope).
        if not _is_crawl_finalize_rule(ev.rule_id)
    ]
    scores = score_analysis(
        evaluations,
        page_kind=assessment.page_kind,
        page_traits=traits,
        page_kind_evidence=assessment.to_evidence(),
    )
    return assessment, traits, evaluations, scores


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
    assessment: PageKindAssessment,
    traits: tuple[str, ...],
    scores: AnalysisScores,
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
        technical_integrity_score=scores.technical_integrity_score,
        technical_integrity_coverage=scores.technical_integrity_coverage,
        technical_integrity_state=scores.technical_integrity_state,
        technical_earned_weight=scores.technical_earned_weight,
        technical_determinate_weight=scores.technical_determinate_weight,
        technical_expected_weight=scores.technical_expected_weight,
        technical_critical_complete=scores.technical_critical_complete,
        aeo_readiness_score=scores.aeo_readiness_score,
        aeo_measurement_coverage=scores.aeo_measurement_coverage,
        aeo_measurement_state=scores.aeo_measurement_state,
        expected_checkpoint_profile=list(scores.expected_checkpoint_profile),
        readiness_dimensions=[item.to_dict() for item in scores.readiness_dimensions],
        profile_version=PROFILE_VERSION,
        schema_contract_version=SCHEMA_CONTRACT_VERSION,
        presentation_version=PRESENTATION_VERSION,
        main_content_indexable=scores.main_content_indexable,
        analyzer_version=crawl.analyzer_version or ANALYZER_VERSION,
        scoring_version=crawl.scoring_version or SCORING_VERSION,
        page_kind=assessment.page_kind,
        classifier_version=assessment.classifier_version,
        # Persist the bounded classifier evidence with the row (the
        # evaluation-time copy above is never persisted, by design).
        page_kind_evidence=assessment.to_evidence(),
        page_traits=list(traits),
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
    evaluations: list[RuleEvaluation],
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
        if (
            ev.outcome == RULE_OUTCOME_FAIL
            and ev.finding_class != FINDING_CLASS_DIAGNOSTIC
        ):
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
