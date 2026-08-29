from __future__ import annotations

import uuid
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import (
    AnalysisEvidence,
    DetectorHit,
    PromptSnapshotEvidence,
    SiteEvidence,
    SiteIssueEvidence,
    SiteUrlEvidence,
    VisibilityEvidence,
    detect_brand_absent_high_value_prompt,
    detect_owned_page_not_cited,
    detect_site_issue_opportunities,
)
from app.analysis.opportunities.earned_detector import (
    detect_earned_source_opportunities,
)
from app.analysis.opportunities.scoring import priority_score
from app.analysis.opportunities.source_mix import (
    build_source_projection,
    empty_source_projection,
)
from app.analysis.opportunities.source_patterns import CitationEvidence
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    CONFIRMED_DECLINE_GAP_NORMALIZER,
    CONFIRMED_DECLINE_MIN_FACTOR,
    FORMULA_VERSION,
    MIN_PRIORITY_TO_SURFACE,
    OPPORTUNITY_RULES_BY_ID,
    RECOMPUTE_MAX_ANALYSES,
    RECOMPUTE_MAX_ISSUES,
    RULE_VERSION,
    STATUS_OPEN,
)
from app.core.config.site_health_contracts import (
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.site_health_rules import (
    FINDING_CLASS_DEFECT,
)
from app.domain.opportunities.change_hits import load_change_hits
from app.domain.opportunities.commerce_hits import load_commerce_opportunity_hits
from app.domain.opportunities.common import (
    _AUDIT_NOT_FOUND,
    _CRAWL_NOT_FOUND,
    _require_project,
    _utcnow,
)
from app.domain.opportunities.demand_hits import load_demand_hits
from app.domain.opportunities.errors import (
    OpportunityNotFoundError,
)
from app.domain.opportunities.site_coverage import site_coverage
from app.domain.opportunities.snapshot_build import build_snapshot
from app.domain.opportunities.snapshot_projection import project_snapshot
from app.domain.prompts.locks import acquire_project_lock
from app.domain.prompts.normalization import prompt_text_hash
from app.models.analysis import (
    Citation,
    CompetitorMention,
    MetricSnapshot,
    PromptMetricSnapshot,
    ResponseAnalysis,
)
from app.models.audit import Audit, AuditPromptSnapshot
from app.models.brand import OwnedDomain
from app.models.demand import DemandSnapshot
from app.models.opportunity import (
    Opportunity,
    OpportunitySnapshot,
)
from app.models.site_health.analysis import SiteIssue
from app.models.site_health.crawl import SiteCrawl
from app.models.site_health.urls import SiteUrl

__all__ = ["recompute"]

_DASHBOARD_READY_STATUSES = (AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED)
_EVIDENCE_CRAWL_STATUSES = (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_CANCELLED,
)


async def _resolve_source[SourceT: Audit | SiteCrawl](
    session: AsyncSession,
    model: type[SourceT],
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    source_id: uuid.UUID | None,
    ready_statuses: tuple[str, ...],
    not_found_detail: str,
) -> SourceT | None:
    """Explicit source (404 if foreign) else the latest usable one.

    Shared by the audit (dashboard-ready statuses) and the Site Health crawl
    (terminal statuses) resolution: an explicit id must belong to the
    workspace + project, and the default picks the most recent row in a
    usable status (``completed_at`` first, ``created_at`` tie-break).
    """
    if source_id is not None:
        source = await session.scalar(
            select(model).where(
                model.id == source_id,
                model.workspace_id == workspace_id,
                model.project_id == project_id,
            )
        )
        if source is None:
            raise OpportunityNotFoundError(not_found_detail)
        return source
    return await session.scalar(
        select(model)
        .where(
            model.workspace_id == workspace_id,
            model.project_id == project_id,
            model.status.in_(ready_statuses),
        )
        .order_by(model.completed_at.desc().nullslast(), model.created_at.desc())
        .limit(1)
    )


def _visibility_credits(
    citations: list[Citation], mentions: list[CompetitorMention]
) -> tuple[dict[uuid.UUID, int], dict[uuid.UUID, set[str]]]:
    """Fold owned citations and competitor identities by analysis."""
    owned_counts: dict[uuid.UUID, int] = {}
    competitor_names: dict[uuid.UUID, set[str]] = {}
    for citation in citations:
        if citation.is_owned:
            owned_counts[citation.analysis_id] = (
                owned_counts.get(citation.analysis_id, 0) + 1
            )
        if citation.matched_competitor:
            competitor_names.setdefault(citation.analysis_id, set()).add(
                citation.matched_competitor
            )
    for mention in mentions:
        if mention.competitor_name:
            competitor_names.setdefault(mention.analysis_id, set()).add(
                mention.competitor_name
            )
    return owned_counts, competitor_names


def _citations_by_analysis(
    citations: list[Citation],
) -> dict[uuid.UUID, tuple[CitationEvidence, ...]]:
    """Project persisted citations into detector evidence, keyed by analysis.

    Carries the analyzer's OWN identity verdicts (``is_owned`` /
    ``matched_competitor``) forward untouched — the source-pattern taxonomy
    classifies only what the analyzer already left as third party. Input order
    is the caller's query order (analysis, then ordinal), which is what makes
    the summarized representative citation per domain deterministic.
    """
    grouped: dict[uuid.UUID, list[CitationEvidence]] = {}
    for citation in citations:
        grouped.setdefault(citation.analysis_id, []).append(
            CitationEvidence(
                domain=citation.domain or "",
                url=citation.url or "",
                title=citation.title or "",
                is_owned=citation.is_owned,
                matched_competitor=citation.matched_competitor,
            )
        )
    return {analysis_id: tuple(rows) for analysis_id, rows in grouped.items()}


async def _load_visibility_evidence(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit: Audit
) -> tuple[VisibilityEvidence, MetricSnapshot | None]:
    """Load analyses/citations/mentions/snapshots + the metric snapshot."""
    analyses = list(
        (
            await session.scalars(
                select(ResponseAnalysis)
                .where(
                    ResponseAnalysis.audit_id == audit.id,
                    ResponseAnalysis.workspace_id == workspace_id,
                )
                .order_by(
                    ResponseAnalysis.prompt_index.asc(),
                    ResponseAnalysis.id.asc(),
                )
                .limit(RECOMPUTE_MAX_ANALYSES)
            )
        ).all()
    )
    analysis_ids = [a.id for a in analyses]

    owned_counts: dict[uuid.UUID, int] = {}
    competitor_names: dict[uuid.UUID, set[str]] = {}
    citation_evidence: dict[uuid.UUID, tuple[CitationEvidence, ...]] = {}
    if analysis_ids:
        citations = list(
            (
                await session.scalars(
                    select(Citation)
                    .where(Citation.analysis_id.in_(analysis_ids))
                    .order_by(Citation.analysis_id.asc(), Citation.ordinal.asc())
                )
            ).all()
        )
        mentions = list(
            (
                await session.scalars(
                    select(CompetitorMention)
                    .where(CompetitorMention.analysis_id.in_(analysis_ids))
                    .order_by(
                        CompetitorMention.created_at.asc(), CompetitorMention.id.asc()
                    )
                )
            ).all()
        )
        owned_counts, competitor_names = _visibility_credits(citations, mentions)
        citation_evidence = _citations_by_analysis(citations)

    snapshots = list(
        (
            await session.scalars(
                select(AuditPromptSnapshot)
                .where(AuditPromptSnapshot.audit_id == audit.id)
                .order_by(AuditPromptSnapshot.prompt_index.asc())
            )
        ).all()
    )
    owned_domains = list(
        (
            await session.scalars(
                select(OwnedDomain.domain)
                .where(OwnedDomain.project_id == audit.project_id)
                .order_by(OwnedDomain.domain.asc())
            )
        ).all()
    )
    metric_snapshot = await session.scalar(
        select(MetricSnapshot).where(
            MetricSnapshot.audit_id == audit.id,
            MetricSnapshot.workspace_id == workspace_id,
        )
    )
    evidence = VisibilityEvidence(
        audit_id=audit.id,
        analyses=tuple(
            AnalysisEvidence(
                analysis_id=a.id,
                prompt_index=a.prompt_index,
                logical_engine=a.logical_engine or "",
                owned_citation_count=owned_counts.get(a.id, 0),
                competitor_names=tuple(sorted(competitor_names.get(a.id, ()))),
                citations=citation_evidence.get(a.id, ()),
                artifact_id=a.artifact_id,
                entity_assessments=tuple(a.entity_assessments or []),
            )
            for a in analyses
        ),
        prompt_snapshots=tuple(
            PromptSnapshotEvidence(
                prompt_index=s.prompt_index,
                prompt_id=s.prompt_id,
                text=s.text or "",
                theme=s.theme or "",
                intent=s.intent or "",
                buyer_stage=s.buyer_stage or "",
                prompt_intent=s.prompt_intent or "",
                snapshot_id=s.id,
            )
            for s in snapshots
        ),
        owned_domains=tuple(sorted(owned_domains)),
    )
    return evidence, metric_snapshot


async def _latest_snapshot(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> OpportunitySnapshot | None:
    """The project's most recent snapshot, or ``None`` if never computed.

    Shared by ``get_summary`` and by ``recompute``'s no-evidence path, where
    returning the PREVIOUS snapshot is what keeps a recompute from destroying
    the live set. ``_resolve_source`` only accepts a TERMINAL crawl and a
    dashboard-ready audit, so "no source resolved" is the normal state while a
    crawl is still running — and superseding on it emptied the Opportunities
    screen mid-crawl. Absent evidence is not evidence of absence: zero hits
    WITH a source still supersedes (a genuinely clean project), zero SOURCES
    changes nothing.
    """
    return await session.scalar(
        select(OpportunitySnapshot)
        .where(
            OpportunitySnapshot.workspace_id == workspace_id,
            OpportunitySnapshot.project_id == project_id,
        )
        .order_by(OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc())
        .limit(1)
    )


async def _load_site_evidence(
    session: AsyncSession, *, workspace_id: uuid.UUID, crawl: SiteCrawl
) -> SiteEvidence:
    issues = list(
        (
            await session.scalars(
                select(SiteIssue)
                .where(
                    SiteIssue.crawl_id == crawl.id,
                    SiteIssue.workspace_id == workspace_id,
                    SiteIssue.finding_class == FINDING_CLASS_DEFECT,
                )
                .order_by(SiteIssue.created_at.asc(), SiteIssue.id.asc())
                .limit(RECOMPUTE_MAX_ISSUES)
            )
        ).all()
    )
    url_ids = sorted({issue.site_url_id for issue in issues})
    urls: list[SiteUrl] = []
    if url_ids:
        urls = list(
            (
                await session.scalars(
                    select(SiteUrl)
                    .where(SiteUrl.id.in_(url_ids))
                    .order_by(SiteUrl.id.asc())
                )
            ).all()
        )
    coverage, limitations = site_coverage(crawl)
    return SiteEvidence(
        crawl_id=crawl.id,
        issues=tuple(
            SiteIssueEvidence(
                issue_id=issue.id,
                rule_id=issue.rule_id,
                severity=issue.severity or "",
                category=issue.category or "",
                finding_class=issue.finding_class,
                site_url_id=issue.site_url_id,
                evidence=issue.evidence or {},
            )
            for issue in issues
        ),
        urls=tuple(
            SiteUrlEvidence(site_url_id=url.id, normalized_url=url.normalized_url)
            for url in urls
        ),
        coverage=coverage,
        limitations=tuple(limitations),
    )


async def _confirmed_decline_hits(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit: Audit
) -> list[DetectorHit]:
    """Project confirmed prompt movements into the shared opportunity model."""
    rows = list(
        (
            await session.scalars(
                select(PromptMetricSnapshot)
                .where(
                    PromptMetricSnapshot.workspace_id == workspace_id,
                    PromptMetricSnapshot.audit_id == audit.id,
                    PromptMetricSnapshot.decline_confirmed.is_(True),
                )
                .order_by(PromptMetricSnapshot.prompt_index.asc())
            )
        ).all()
    )
    return [
        DetectorHit(
            rule_id="confirmed_prompt_decline",
            target_key=(
                f"prompt:{row.prompt_id}"
                if row.prompt_id is not None
                else f"prompt-index:{audit.id}:{row.prompt_index}"
            ),
            target_prompt_id=row.prompt_id,
            target_url=None,
            target_theme=None,
            evidence={
                "prompt": row.prompt_text,
                "rolling_four": row.rolling_four,
                "immediate_delta": row.immediate_delta,
                "engines": sorted(row.per_engine_scores),
                "engine_agreement": row.engine_agreement,
                "repetition_agreement": row.repetition_agreement,
                "trend_confidence": row.trend_confidence,
                "components": row.components,
                "content_goal": "Improve the owned answer for this prompt.",
            },
            source_analysis_ids=tuple(row.source_analysis_ids or []),
            source_issue_ids=(),
            source_metric_ids=(str(row.id),),
            value_factor=max(CONFIRMED_DECLINE_MIN_FACTOR, row.trend_confidence),
            gap_factor=max(
                CONFIRMED_DECLINE_MIN_FACTOR,
                min(
                    1.0,
                    abs(float(row.immediate_delta or 0.0))
                    / CONFIRMED_DECLINE_GAP_NORMALIZER,
                ),
            ),
        )
        for row in rows
    ]


async def _collect_recompute_hits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit: Audit | None,
    crawl: SiteCrawl | None,
    explicit_audit: bool,
) -> tuple[
    Audit | None,
    DemandSnapshot | None,
    list[DetectorHit],
    dict,
    dict,
    list[dict],
]:
    hits: list[DetectorHit] = []
    source_mix, action_path_mix, domain_rollups = _empty_projection()
    demand_snapshot, demand_hits = await load_demand_hits(
        session, workspace_id=workspace_id, project_id=project_id
    )
    hits.extend(demand_hits)
    if audit is not None:
        audit, audit_hits, projections = await _audit_hits(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit=audit,
            explicit_audit=explicit_audit,
        )
        hits.extend(audit_hits)
        source_mix, action_path_mix, domain_rollups = projections
    if crawl is not None:
        site = await _load_site_evidence(
            session, workspace_id=workspace_id, crawl=crawl
        )
        hits.extend(detect_site_issue_opportunities(site))
        hits.extend(
            await load_change_hits(session, workspace_id=workspace_id, crawl=crawl)
        )
    return audit, demand_snapshot, hits, source_mix, action_path_mix, domain_rollups


async def _audit_hits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit: Audit,
    explicit_audit: bool,
) -> tuple[Audit | None, list[DetectorHit], tuple[dict, dict, list[dict]]]:
    visibility, metric_snapshot = await _load_visibility_evidence(
        session, workspace_id=workspace_id, audit=audit
    )
    if metric_snapshot is None and not explicit_audit:
        return None, [], _empty_projection()
    visibility_hits = detect_brand_absent_high_value_prompt(
        visibility
    ) + detect_owned_page_not_cited(visibility)
    gap_indices = {
        int(hit.evidence["prompt_index"])
        for hit in visibility_hits
        if "prompt_index" in hit.evidence
    }
    projections = build_source_projection(
        analyses=visibility.analyses,
        snapshots=visibility.prompt_snapshots,
        gap_prompt_indices=gap_indices,
    )
    _stamp_source_projections(
        audit=audit,
        snapshots=visibility.prompt_snapshots,
        gap_indices=gap_indices,
        projections=projections[:2],
    )
    visibility_hits.extend(detect_earned_source_opportunities(projections[2]))
    if metric_snapshot is not None:
        metric_ids = (str(metric_snapshot.id),)
        visibility_hits = [
            replace(hit, source_metric_ids=metric_ids) for hit in visibility_hits
        ]
    visibility_hits.extend(
        await load_commerce_opportunity_hits(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            audit_id=audit.id,
        )
    )
    visibility_hits.extend(
        await _confirmed_decline_hits(session, workspace_id=workspace_id, audit=audit)
    )
    return audit, visibility_hits, projections


def _empty_projection() -> tuple[dict, dict, list[dict]]:
    """The canonical "nothing to project" source mix (no gap in scope)."""
    empty = empty_source_projection()
    return empty, dict(empty), []


def _stamp_source_projections(*, audit, snapshots, gap_indices, projections) -> None:
    selected = [row for row in snapshots if row.prompt_index in gap_indices]
    for projection in projections:
        projection["audit_id"] = str(audit.id)
        projection["prompt_snapshot_ids"] = [
            str(row.snapshot_id) if row.snapshot_id else None for row in selected
        ]
        projection["gap_keys"] = sorted(prompt_text_hash(row.text) for row in selected)


def _score_hits(hits: list[DetectorHit]) -> list[tuple[DetectorHit, float]]:
    scored: list[tuple[DetectorHit, float]] = []
    seen_targets: set[tuple[str, str]] = set()
    for hit in hits:
        rule = OPPORTUNITY_RULES_BY_ID[hit.rule_id]
        score = priority_score(
            severity=rule.severity,
            value_factor=hit.value_factor,
            gap_factor=hit.gap_factor,
        )
        target = (hit.rule_id, hit.target_key)
        if score >= MIN_PRIORITY_TO_SURFACE and target not in seen_targets:
            seen_targets.add(target)
            scored.append((hit, score))
    return sorted(scored, key=lambda item: (item[0].rule_id, item[0].target_key))


def _snapshot_is_current(
    current: OpportunitySnapshot | None,
    *,
    audit: Audit | None,
    crawl: SiteCrawl | None,
    demand_snapshot: DemandSnapshot | None,
) -> bool:
    if current is None:
        return False
    return (
        current.audit_id == (audit.id if audit else None)
        and current.site_crawl_id == (crawl.id if crawl else None)
        and current.demand_snapshot_id
        == (demand_snapshot.id if demand_snapshot else None)
        and current.demand_source_revision
        == (demand_snapshot.source_hash if demand_snapshot else None)
        and current.analyzer_version == ANALYZER_VERSION
        and current.rule_version == RULE_VERSION
        and current.formula_version == FORMULA_VERSION
    )


async def _write_recompute(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit: Audit | None,
    crawl: SiteCrawl | None,
    demand_snapshot: DemandSnapshot | None,
    scored: list[tuple[DetectorHit, float]],
    source_mix: dict,
    action_path_mix: dict,
    domain_rollups: list[dict],
    skip_if_current: bool,
) -> dict:
    await acquire_project_lock(session, project_id)
    current = await _latest_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if skip_if_current and _snapshot_is_current(
        current, audit=audit, crawl=crawl, demand_snapshot=demand_snapshot
    ):
        assert current is not None  # noqa: S101 - narrows for the type checker; not a runtime check
        return project_snapshot(current)
    live_rows = list(
        (
            await session.scalars(
                select(Opportunity).where(
                    Opportunity.project_id == project_id,
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.superseded_at.is_(None),
                )
            )
        ).all()
    )
    live_by_target = {(row.rule_id, row.target_key): row for row in live_rows}
    successor_ids: dict[uuid.UUID, uuid.UUID] = {}
    new_rows: list[Opportunity] = []
    for hit, score in scored:
        rule = OPPORTUNITY_RULES_BY_ID[hit.rule_id]
        live = live_by_target.get((hit.rule_id, hit.target_key))
        new_id = uuid.uuid4()
        new_rows.append(
            Opportunity(
                id=new_id,
                workspace_id=workspace_id,
                project_id=project_id,
                rule_id=rule.rule_id,
                opportunity_type=rule.opportunity_type,
                severity=rule.severity,
                priority_score=score,
                title=rule.title,
                remediation=rule.remediation,
                target_key=hit.target_key,
                target_prompt_id=hit.target_prompt_id,
                target_url=hit.target_url,
                target_theme=hit.target_theme,
                evidence=hit.evidence,
                source_analysis_ids=list(hit.source_analysis_ids),
                source_issue_ids=list(hit.source_issue_ids),
                source_metric_ids=list(hit.source_metric_ids),
                source_traffic_ids=None,
                analyzer_version=ANALYZER_VERSION,
                rule_version=RULE_VERSION,
                formula_version=FORMULA_VERSION,
                status=live.status if live is not None else STATUS_OPEN,
            )
        )
        if live is not None:
            successor_ids[live.id] = new_id
    now = _utcnow()
    for live in live_rows:
        live.superseded_at = now
    await session.flush()
    session.add_all(new_rows)
    await session.flush()
    for live in live_rows:
        successor_id = successor_ids.get(live.id)
        if successor_id is not None:
            live.superseded_by_id = successor_id
    snapshot = build_snapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        audit=audit,
        crawl=crawl,
        demand_snapshot=demand_snapshot,
        new_rows=new_rows,
        scored=scored,
        source_mix=source_mix,
        action_path_mix=action_path_mix,
        domain_rollups=domain_rollups,
    )
    session.add(snapshot)
    await session.commit()
    return project_snapshot(snapshot)


async def recompute(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    site_crawl_id: uuid.UUID | None = None,
    skip_if_current: bool = False,
) -> dict:
    """Recompute the project's opportunities and return the new snapshot.

    A missing audit/crawl source is NOT an error. If a prior snapshot exists,
    it is returned unchanged (no lock, no new snapshot row) so an in-flight
    crawl/audit never empties the live set mid-run; only when nothing has
    ever been computed does this write an explicit empty snapshot. When a
    source IS resolved, recomputes on the same project serialize on the
    shared advisory lock; the second one recomputes on the latest state.
    """
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    audit = await _resolve_source(
        session,
        Audit,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=audit_id,
        ready_statuses=_DASHBOARD_READY_STATUSES,
        not_found_detail=_AUDIT_NOT_FOUND,
    )
    crawl = await _resolve_source(
        session,
        SiteCrawl,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=site_crawl_id,
        ready_statuses=_EVIDENCE_CRAWL_STATUSES,
        not_found_detail=_CRAWL_NOT_FOUND,
    )

    (
        audit,
        demand_snapshot,
        hits,
        source_mix,
        action_path_mix,
        domain_rollups,
    ) = await _collect_recompute_hits(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit=audit,
        crawl=crawl,
        explicit_audit=audit_id is not None,
    )

    if audit is None and crawl is None and demand_snapshot is None:
        unchanged = await _latest_snapshot(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if unchanged is not None:
            return project_snapshot(unchanged)

    scored = _score_hits(hits)
    return await _write_recompute(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit=audit,
        crawl=crawl,
        demand_snapshot=demand_snapshot,
        scored=scored,
        source_mix=source_mix,
        action_path_mix=action_path_mix,
        domain_rollups=domain_rollups,
        skip_if_current=skip_if_current,
    )
