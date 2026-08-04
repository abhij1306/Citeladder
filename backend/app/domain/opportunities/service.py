# Opportunities recompute service + workspace-scoped projections.
#
# ``recompute`` is a pure projection pass (invariant 7): it reads the latest
# dashboard-ready audit (or an explicit one) and the latest terminal Site
# Health crawl, runs the pure detectors (``analysis/opportunities``), scores
# each hit with the config-owned formula, and atomically supersedes the prior
# live set + writes an immutable ``OpportunitySnapshot`` in ONE transaction
# serialized per project by the shared advisory lock (``prompts/locks.py``,
# invariant 2). Supersede-not-mutate (invariant 3): a fresh hit for a live
# ``(rule_id, target_key)`` inserts a NEW row (new id, status carried
# forward) and closes the old one; a live row with no fresh hit is closed
# with no successor; evidence/score/provenance on prior rows is never
# touched. The human ``status`` is the only mutable field.
#
# Every lookup is filtered by the resolved workspace, so a foreign / missing
# id is a 404 (invariant 5). Read projections are priority-sorted and
# keyset-paginated via the shared cursor helpers (invariant 2).
from __future__ import annotations

import json
import re
import statistics
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import (
    AnalysisEvidence,
    CommerceEvidence,
    DetectorHit,
    ProductEntryEvidence,
    PromptSnapshotEvidence,
    SiteEvidence,
    SiteIssueEvidence,
    SiteUrlEvidence,
    VisibilityEvidence,
    detect_brand_absent_high_value_prompt,
    detect_competitor_product_dominates,
    detect_owned_page_not_cited,
    detect_price_mention_mismatch,
    detect_product_not_mentioned,
    detect_site_issue_opportunities,
)
from app.analysis.opportunities.scoring import priority_score
from app.analysis.product_service import build_product_scoring_config
from app.core.config import settings
from app.core.config.analytics import (
    ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
    analytics_settings,
)
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    CODE_OPPORTUNITY_SUPERSEDED,
    FORMULA_VERSION,
    GUIDANCE_ENABLED_ENVIRONMENTS,
    GUIDANCE_GENERATOR_VERSION,
    GUIDANCE_HISTORY_DEFAULT_LIMIT,
    GUIDANCE_HISTORY_MAX_LIMIT,
    GUIDANCE_IDEMPOTENCY_KEY_MAX_LEN,
    GUIDANCE_MAX_EVIDENCE_KEYS,
    GUIDANCE_MAX_EVIDENCE_LIST_ITEMS,
    GUIDANCE_MAX_EVIDENCE_VALUE_CHARS,
    GUIDANCE_MAX_FINDINGS,
    GUIDANCE_MODEL,
    GUIDANCE_PROMPT_VERSION,
    GUIDANCE_PROVIDER,
    LIST_DEFAULT_LIMIT,
    LIST_MAX_LIMIT,
    MAX_EXPORT_ITEMS,
    MIN_PRIORITY_TO_SURFACE,
    OPPORTUNITY_ACTIVE_STATUSES,
    OPPORTUNITY_RULES_BY_ID,
    OPPORTUNITY_SEVERITIES,
    OPPORTUNITY_STATUSES,
    OPPORTUNITY_TYPES,
    RECOMPUTE_MAX_ANALYSES,
    RECOMPUTE_MAX_ISSUES,
    RECOMPUTE_MAX_PRODUCT_SNAPSHOTS,
    RULE_VERSION,
    STATUS_OPEN,
    validate_rule_id,
)
from app.core.config.site_health import (
    CRAWL_STATUS_CANCELLED,
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.task_queue import (
    TASK_STATUS_FAILED,
    TASK_STATUS_LEASED,
    TASK_STATUS_QUEUED,
    TASK_STATUS_RETRY_WAIT,
    TASK_STATUS_RUNNING,
)
from app.domain.products.visibility import select_current_snapshots
from app.domain.prompts.locks import acquire_project_lock
from app.domain.site_health.normalization import (
    decode_keyset_cursor,
    encode_keyset_cursor,
)
from app.models.analysis import (
    Citation,
    CompetitorMention,
    MetricSnapshot,
    ResponseAnalysis,
)
from app.models.analytics import AnalyticsTask
from app.models.audit import Audit, AuditPromptSnapshot
from app.models.brand import OwnedDomain
from app.models.opportunity import (
    Opportunity,
    OpportunityGuidance,
    OpportunityOrder,
    OpportunitySnapshot,
    OpportunityStatusEvent,
)
from app.models.product import ProductMetricSnapshot
from app.models.project import Project
from app.models.site_health import SiteCrawl, SiteIssue, SiteUrl

__all__ = [
    "OpportunityNotFoundError",
    "OpportunityValidationError",
    "OpportunitySupersededError",
    "OpportunityGuidanceUnavailableError",
    "OpportunityGuidanceIdempotencyConflictError",
    "OpportunityOrderConflictError",
    "InvalidCursorError",
    "recompute",
    "list_opportunities",
    "get_opportunity",
    "update_status",
    "update_order",
    "get_summary",
    "load_export_rows",
    "create_guidance",
    "get_latest_guidance",
    "list_guidance_history",
    "get_grouped_history",
    "enqueue_opportunity_refresh",
]


async def enqueue_opportunity_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    trigger_kind: str,
    trigger_id: uuid.UUID,
) -> None:
    """Transactionally enqueue one versioned automatic projection refresh."""
    idempotency_key = (
        f"opportunity:{trigger_kind}:{trigger_id}:"
        f"{ANALYZER_VERSION}:{RULE_VERSION}:{FORMULA_VERSION}"
    )
    await session.execute(
        pg_insert(AnalyticsTask)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            task_kind=ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
            payload={"trigger_kind": trigger_kind, "trigger_id": str(trigger_id)},
            idempotency_key=idempotency_key,
            status=TASK_STATUS_QUEUED,
            max_attempts=analytics_settings.task_max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )


# Dashboard-ready audit statuses (mirrors ``_DASHBOARD_STATUSES`` in
# ``domain/analysis/service.py``; the constants themselves are config-owned).
_DASHBOARD_READY_STATUSES = (AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED)
# A crawl whose issue rows are usable evidence (terminal, with analysis).
#
# CANCELLED belongs here: a cancelled run still fully analyzed every page that
# finished before the stop, and ``cancel_crawl`` rolls exactly those pages into
# the same canonical snapshot a clean terminalization writes. Excluding it meant
# the cancel-path recompute resolved no crawl and wrote an EMPTY snapshot over
# real findings — the dashboard showed partial scores while Opportunities sat
# blank. The issue rows are immutable evidence; how the run ended does not make
# the pages that did complete any less true.
_EVIDENCE_CRAWL_STATUSES = (
    CRAWL_STATUS_COMPLETED,
    CRAWL_STATUS_PARTIALLY_COMPLETED,
    CRAWL_STATUS_CANCELLED,
)

_PROJECT_NOT_FOUND = "Project not found"
_OPPORTUNITY_NOT_FOUND = "Opportunity not found"
_AUDIT_NOT_FOUND = "Audit not found"
_CRAWL_NOT_FOUND = "Crawl not found"
_LIST_SCOPE = "opportunities"


class OpportunityNotFoundError(Exception):
    """A workspace-scoped resource was missing / foreign (maps to 404)."""


class OpportunityValidationError(Exception):
    """An unknown filter/status token was supplied (maps to 422)."""


class OpportunitySupersededError(Exception):
    """A mutation targeted a superseded row (maps to 409, coded)."""

    code = CODE_OPPORTUNITY_SUPERSEDED


class OpportunityOrderConflictError(Exception):
    """The shared queue changed after the caller read its version."""


class OpportunityGuidanceUnavailableError(Exception):
    """Guidance is intentionally unavailable outside the dev eligibility gate."""


class OpportunityGuidanceIdempotencyConflictError(Exception):
    """An idempotency key was replayed for a changed frozen input."""


class InvalidCursorError(Exception):
    """A cursor was tampered with or replayed cross-scope (maps to 400)."""


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return LIST_DEFAULT_LIMIT
    return max(1, min(int(limit), LIST_MAX_LIMIT))


# =========================================================================
# Source resolution (audit + crawl)
# =========================================================================
async def _require_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    exists = await session.scalar(
        select(Project.id).where(
            Project.id == project_id, Project.workspace_id == workspace_id
        )
    )
    if exists is None:
        raise OpportunityNotFoundError(_PROJECT_NOT_FOUND)


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


# =========================================================================
# Evidence loading (bounded, deterministic truncation order)
# =========================================================================
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
        for citation in citations:
            if citation.is_owned:
                owned_counts[citation.analysis_id] = (
                    owned_counts.get(citation.analysis_id, 0) + 1
                )
            if citation.matched_competitor:
                competitor_names.setdefault(citation.analysis_id, set()).add(
                    citation.matched_competitor
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
        for mention in mentions:
            if mention.competitor_name:
                competitor_names.setdefault(mention.analysis_id, set()).add(
                    mention.competitor_name
                )

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
    return SiteEvidence(
        crawl_id=crawl.id,
        issues=tuple(
            SiteIssueEvidence(
                issue_id=issue.id,
                rule_id=issue.rule_id,
                severity=issue.severity or "",
                category=issue.category or "",
                site_url_id=issue.site_url_id,
                evidence=issue.evidence or {},
            )
            for issue in issues
        ),
        urls=tuple(
            SiteUrlEvidence(site_url_id=url.id, normalized_url=url.normalized_url)
            for url in urls
        ),
    )


async def _load_commerce_evidence(
    session: AsyncSession, *, workspace_id: uuid.UUID, audit: Audit
) -> CommerceEvidence:
    """Frozen catalog identity + persisted product snapshots for one audit.

    Entry identity (name/sku/competitor) reads the audit's FROZEN catalog
    (``Audit.configuration``, invariant 9) so a later catalog edit or delete
    never rewrites what the audit measured; the metrics read the persisted
    ``ProductMetricSnapshot`` rows (one per frozen entry, zero-filled when
    unmentioned — invariant 7). An audit with no frozen catalog short-circuits
    to empty evidence without a query.
    """
    config = build_product_scoring_config(audit.configuration or {})
    if not config.products and not config.competitor_products:
        return CommerceEvidence(audit_id=audit.id, entries=())
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot)
                .where(
                    ProductMetricSnapshot.audit_id == audit.id,
                    ProductMetricSnapshot.workspace_id == workspace_id,
                )
                # Newest-first so the cap truncates the OLDEST rows: an
                # ascending order with more snapshots than the cap dropped the
                # current ones and projected stale metrics.
                # ``select_current_snapshots`` is order-independent (it selects
                # by analyzer/rule version, not position), so this only changes
                # which rows survive the limit, never which one wins per entry.
                .order_by(
                    ProductMetricSnapshot.created_at.desc(),
                    ProductMetricSnapshot.id.desc(),
                )
                .limit(RECOMPUTE_MAX_PRODUCT_SNAPSHOTS)
            )
        ).all()
    )
    by_entry = select_current_snapshots(snapshots)

    def _entry(
        *,
        entry_id: str,
        kind: str,
        name: str,
        sku: str,
        competitor_name: str,
    ) -> ProductEntryEvidence:
        snapshot = by_entry.get(entry_id)
        return ProductEntryEvidence(
            entry_id=entry_id,
            kind=kind,
            name=name,
            sku=sku,
            competitor_name=competitor_name,
            mention_count=snapshot.mention_count if snapshot is not None else 0,
            sov_share=float(snapshot.sov_share) if snapshot is not None else 0.0,
            price_mismatch_rate=(
                float(snapshot.price_mismatch_rate)
                if snapshot is not None and snapshot.price_mismatch_rate is not None
                else None
            ),
            snapshot_id=snapshot.id if snapshot is not None else None,
            source_analysis_ids=(
                tuple(sorted(str(sid) for sid in (snapshot.source_analysis_ids or [])))
                if snapshot is not None
                else ()
            ),
        )

    entries = [
        _entry(
            entry_id=entry.id,
            kind="product",
            name=entry.name,
            sku=entry.sku,
            competitor_name="",
        )
        for entry in config.products
    ] + [
        _entry(
            entry_id=entry.id,
            kind="competitor_product",
            name=entry.name,
            sku="",
            competitor_name=entry.competitor,
        )
        for entry in config.competitor_products
    ]
    return CommerceEvidence(audit_id=audit.id, entries=tuple(entries))


# =========================================================================
# Recompute (supersede-not-mutate write path, one transaction)
# =========================================================================
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

    hits: list[DetectorHit] = []
    if audit is not None:
        visibility, metric_snapshot = await _load_visibility_evidence(
            session, workspace_id=workspace_id, audit=audit
        )
        if metric_snapshot is None and audit_id is None:
            # Not dashboard-ready (mirrors ``_load_snapshot``): the default
            # resolution requires the audit's aggregate snapshot.
            audit = None
        else:
            visibility_hits = detect_brand_absent_high_value_prompt(
                visibility
            ) + detect_owned_page_not_cited(visibility)
            if metric_snapshot is not None:
                metric_ids = (str(metric_snapshot.id),)
                visibility_hits = [
                    replace(hit, source_metric_ids=metric_ids)
                    for hit in visibility_hits
                ]
            hits.extend(visibility_hits)
            # Commerce-derived rules: same audit, persisted product slice.
            commerce = await _load_commerce_evidence(
                session, workspace_id=workspace_id, audit=audit
            )
            hits.extend(detect_product_not_mentioned(commerce))
            hits.extend(detect_competitor_product_dominates(commerce))
            hits.extend(detect_price_mention_mismatch(commerce))
    if crawl is not None:
        site = await _load_site_evidence(
            session, workspace_id=workspace_id, crawl=crawl
        )
        hits.extend(detect_site_issue_opportunities(site))

    if audit is None and crawl is None:
        unchanged = await _latest_snapshot(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if unchanged is not None:
            return _project_snapshot(unchanged)
        # Never computed and nothing to compute from: fall through and write
        # the explicit empty snapshot, so the screen can tell "no evidence yet"
        # from "not computed yet". There is no live set to protect here.

    # Score + apply the write-time floor; dedupe on the live-target identity
    # (first hit wins — detector output is already deterministically ordered).
    scored: list[tuple[DetectorHit, float]] = []
    seen_targets: set[tuple[str, str]] = set()
    for hit in hits:
        rule = OPPORTUNITY_RULES_BY_ID[hit.rule_id]
        score = priority_score(
            severity=rule.severity,
            value_factor=hit.value_factor,
            gap_factor=hit.gap_factor,
        )
        if score < MIN_PRIORITY_TO_SURFACE:
            continue
        target = (hit.rule_id, hit.target_key)
        if target in seen_targets:
            continue
        seen_targets.add(target)
        scored.append((hit, score))
    scored.sort(key=lambda item: (item[0].rule_id, item[0].target_key))

    # Write path: ONE transaction, serialized per project.
    await acquire_project_lock(session, project_id)
    current = await _latest_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if (
        skip_if_current
        and current is not None
        and current.audit_id == (audit.id if audit is not None else None)
        and current.site_crawl_id == (crawl.id if crawl is not None else None)
        and current.analyzer_version == ANALYZER_VERSION
        and current.rule_version == RULE_VERSION
        and current.formula_version == FORMULA_VERSION
    ):
        return _project_snapshot(current)
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

    now = _utcnow()
    successor_ids: dict[uuid.UUID, uuid.UUID] = {}  # live row id -> new row id
    new_rows: list[Opportunity] = []
    for hit, score in scored:
        # The scoring pass above already resolved the catalog entry (an
        # unknown rule_id raised there), so this lookup is guaranteed.
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
                # D5: carry the human workflow status forward on supersede.
                status=live.status if live is not None else STATUS_OPEN,
            )
        )
        if live is not None:
            successor_ids[live.id] = new_id
    # Three ordered phases inside the ONE transaction:
    # 1. Close every prior live row (link later) so the partial unique index
    #    releases the (project, rule, target) keys.
    # 2. Insert the successors (their ids now exist for the self-FK).
    # 3. Link predecessors to their successors.
    for live in live_rows:
        live.superseded_at = now
    await session.flush()
    session.add_all(new_rows)
    await session.flush()
    for live in live_rows:
        # Distinct name from the `new_id` built above: that one is always a UUID,
        # this lookup is optional, and reusing the name made the binding
        # `UUID | None` for both.
        successor_id = successor_ids.get(live.id)
        if successor_id is not None:
            live.superseded_by_id = successor_id

    snapshot = _build_snapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        audit=audit,
        crawl=crawl,
        new_rows=new_rows,
        scored=scored,
    )
    session.add(snapshot)
    await session.commit()
    return _project_snapshot(snapshot)


def _build_snapshot(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit: Audit | None,
    crawl: SiteCrawl | None,
    new_rows: list[Opportunity],
    scored: list[tuple[DetectorHit, float]],
) -> OpportunitySnapshot:
    """Aggregate the immutable per-run snapshot over the NEW live set."""
    counts_by_type = {name: 0 for name in sorted(OPPORTUNITY_TYPES)}
    counts_by_severity = {name: 0 for name in sorted(OPPORTUNITY_SEVERITIES)}
    counts_by_status = {name: 0 for name in sorted(OPPORTUNITY_STATUSES)}
    for row in new_rows:
        # Rows are written from the config vocabularies, so every key exists.
        counts_by_type[row.opportunity_type] += 1
        counts_by_severity[row.severity] += 1
        counts_by_status[row.status] += 1
    scores = sorted(score for _hit, score in scored)
    median = round(statistics.median(scores), 1) if scores else None
    source_analysis_ids = sorted(
        {sid for hit, _score in scored for sid in hit.source_analysis_ids}
    )
    source_issue_ids = sorted(
        {sid for hit, _score in scored for sid in hit.source_issue_ids}
    )
    return OpportunitySnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=uuid.uuid4(),
        audit_id=audit.id if audit is not None else None,
        site_crawl_id=crawl.id if crawl is not None else None,
        counts_by_type=counts_by_type,
        counts_by_severity=counts_by_severity,
        counts_by_status=counts_by_status,
        total_count=len(new_rows),
        median_priority=median,
        analyzer_version=ANALYZER_VERSION,
        rule_version=RULE_VERSION,
        formula_version=FORMULA_VERSION,
        source_analysis_ids=source_analysis_ids,
        source_issue_ids=source_issue_ids,
    )


# =========================================================================
# Read projections (priority-sorted, keyset-paginated, workspace-scoped)
# =========================================================================
def _validate_filters(
    *,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
) -> None:
    if opportunity_type is not None and opportunity_type not in OPPORTUNITY_TYPES:
        raise OpportunityValidationError(
            f"unknown opportunity type: {opportunity_type!r}"
        )
    if severity is not None and severity not in OPPORTUNITY_SEVERITIES:
        raise OpportunityValidationError(f"unknown opportunity severity: {severity!r}")
    if status is not None and status not in OPPORTUNITY_STATUSES:
        raise OpportunityValidationError(f"unknown opportunity status: {status!r}")
    if rule_id is not None:
        try:
            validate_rule_id(rule_id)
        except ValueError as exc:
            raise OpportunityValidationError(str(exc)) from exc


def _filter_clauses(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
    min_priority: float | None,
) -> list:
    clauses = [
        Opportunity.workspace_id == workspace_id,
        Opportunity.project_id == project_id,
        Opportunity.superseded_at.is_(None),
    ]
    if opportunity_type:
        clauses.append(Opportunity.opportunity_type == opportunity_type)
    if severity:
        clauses.append(Opportunity.severity == severity)
    if status:
        clauses.append(Opportunity.status == status)
    else:
        # Default view: the triage queue.
        clauses.append(Opportunity.status.in_(sorted(OPPORTUNITY_ACTIVE_STATUSES)))
    if rule_id:
        clauses.append(Opportunity.rule_id == rule_id)
    if min_priority is not None:
        clauses.append(Opportunity.priority_score >= min_priority)
    return clauses


def _cursor_filters(
    *,
    project_id: uuid.UUID,
    opportunity_type: str | None,
    severity: str | None,
    status: str | None,
    rule_id: str | None,
    min_priority: float | None,
) -> dict:
    return {
        "project_id": str(project_id),
        "type": opportunity_type or None,
        "severity": severity or None,
        "status": status or None,
        "rule_id": rule_id or None,
        "min_priority": min_priority,
    }


async def list_opportunities(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_id: str | None = None,
    min_priority: float | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict:
    """Live-row catalog page, ordered ``(priority_score DESC, id DESC)``."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    _validate_filters(
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
    )
    limit = _clamp_limit(limit)
    filters = _cursor_filters(
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    clauses = _filter_clauses(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    if cursor:
        try:
            score_raw, id_raw = decode_keyset_cursor(
                cursor, scope=_LIST_SCOPE, filters=filters
            )
            cursor_score = float(score_raw)
            cursor_id = uuid.UUID(id_raw)
        except ValueError as exc:  # CursorScopeError is a ValueError
            raise InvalidCursorError(str(exc)) from exc
        clauses.append(
            or_(
                Opportunity.priority_score < cursor_score,
                and_(
                    Opportunity.priority_score == cursor_score,
                    Opportunity.id < cursor_id,
                ),
            )
        )
    rows = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(*clauses)
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.desc())
                .limit(limit + 1)
            )
        ).all()
    )
    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = encode_keyset_cursor(
            scope=_LIST_SCOPE,
            filters=filters,
            sort_values=[last.priority_score, str(last.id)],
        )
    order = await _load_order(session, workspace_id=workspace_id, project_id=project_id)
    return {
        "items": _ordered_items(rows, order),
        "next_cursor": next_cursor,
    }


async def get_opportunity(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> dict:
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    return _project_detail(row)


async def update_status(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    status: str,
    changed_by_user_id: uuid.UUID,
) -> dict:
    """Mutate the human workflow status (the ONLY mutable field)."""
    _validate_status(status)
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    if row.superseded_at is not None:
        raise OpportunitySupersededError(
            "Opportunity was superseded by a newer recompute"
        )
    previous_status = row.status
    if previous_status != status:
        row.status = status
        session.add(
            OpportunityStatusEvent(
                workspace_id=workspace_id,
                project_id=row.project_id,
                opportunity_id=row.id,
                stable_key=_stable_key(row),
                previous_status=previous_status,
                next_status=status,
                changed_by_user_id=changed_by_user_id,
            )
        )
    await session.commit()
    return _project_item(row)


def _validate_status(status: str) -> None:
    if status not in OPPORTUNITY_STATUSES:
        raise OpportunityValidationError(f"unknown opportunity status: {status!r}")


async def _load_order(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> OpportunityOrder | None:
    return await session.scalar(
        select(OpportunityOrder).where(
            OpportunityOrder.workspace_id == workspace_id,
            OpportunityOrder.project_id == project_id,
        )
    )


async def _lock_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    locked_id = await session.scalar(
        select(Project.id)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if locked_id is None:
        raise OpportunityNotFoundError(_PROJECT_NOT_FOUND)


async def update_order(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    ordered_opportunity_ids: list[uuid.UUID],
    expected_version: int,
    updated_by_user_id: uuid.UUID,
) -> dict:
    """Persist one shared project order without mutating derived evidence."""
    # Lock the always-present parent so concurrent first writes serialize even
    # before an OpportunityOrder row exists.
    await _lock_project(session, workspace_id=workspace_id, project_id=project_id)
    if len(set(ordered_opportunity_ids)) != len(ordered_opportunity_ids):
        raise OpportunityValidationError("ordered opportunity ids must be unique")

    rows = list(
        (
            await session.scalars(
                select(Opportunity).where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.project_id == project_id,
                    Opportunity.id.in_(ordered_opportunity_ids),
                    Opportunity.superseded_at.is_(None),
                )
            )
        ).all()
    )
    by_id = {row.id: row for row in rows}
    if set(by_id) != set(ordered_opportunity_ids):
        raise OpportunityValidationError(
            "ordered opportunity ids must identify live project opportunities"
        )

    order = await session.scalar(
        select(OpportunityOrder)
        .where(
            OpportunityOrder.workspace_id == workspace_id,
            OpportunityOrder.project_id == project_id,
        )
        .with_for_update()
    )
    current_version = order.version if order is not None else 0
    if expected_version != current_version:
        raise OpportunityOrderConflictError(
            f"queue version changed from {expected_version} to {current_version}"
        )

    ordered_keys = [_stable_key(by_id[item_id]) for item_id in ordered_opportunity_ids]
    if order is None:
        order = OpportunityOrder(
            workspace_id=workspace_id,
            project_id=project_id,
            ordered_keys=ordered_keys,
            version=1,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(order)
    else:
        order.ordered_keys = ordered_keys
        order.version += 1
        order.updated_by_user_id = updated_by_user_id
    await session.commit()
    return {
        "version": order.version,
        "ordered_opportunity_ids": ordered_opportunity_ids,
    }


# =========================================================================
# Development-only immutable guidance (persisted opportunity evidence only)
# =========================================================================
def _guidance_enabled() -> bool:
    return str(settings.app_env or "").strip().lower() in GUIDANCE_ENABLED_ENVIRONMENTS


def _require_guidance_enabled() -> None:
    # Production eligibility fails closed. Production plan/tier entitlement is
    # intentionally not inferred here: this development-only feature cannot
    # accidentally become a trial/Tier-1 benefit before its billing policy is
    # wired in the entitlement owner.
    if not _guidance_enabled():
        raise OpportunityGuidanceUnavailableError(
            "Opportunity guidance is not available for this workspace"
        )


def _bounded_value(value: object, *, depth: int = 0) -> object:
    """Return a stable, JSON-safe, size-bounded evidence representation."""
    if depth >= 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key)[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]: _bounded_value(
                child, depth=depth + 1
            )
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))[
                :GUIDANCE_MAX_EVIDENCE_KEYS
            ]
        }
    if isinstance(value, (list, tuple)):
        return [
            _bounded_value(child, depth=depth + 1)
            for child in value[:GUIDANCE_MAX_EVIDENCE_LIST_ITEMS]
        ]
    if isinstance(value, str):
        return value[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:GUIDANCE_MAX_EVIDENCE_VALUE_CHARS]


def _guidance_input(row: Opportunity) -> dict:
    """Freeze only bounded, already persisted opportunity evidence."""
    return {
        "opportunity_id": str(row.id),
        "project_id": str(row.project_id),
        "rule_id": row.rule_id,
        "title": row.title or "",
        "severity": row.severity,
        "status": row.status,
        "target": {
            "key": row.target_key,
            "url": row.target_url,
            "theme": row.target_theme,
        },
        "evidence": _bounded_value(row.evidence or {}),
        "source_analysis_ids": sorted(
            str(value) for value in row.source_analysis_ids or []
        ),
        "source_issue_ids": sorted(str(value) for value in row.source_issue_ids or []),
        "source_metric_ids": sorted(
            str(value) for value in row.source_metric_ids or []
        ),
        "versions": {
            "analyzer": row.analyzer_version,
            "rule": row.rule_version,
            "formula": row.formula_version,
        },
    }


def _guidance_hash(snapshot: dict) -> str:
    encoded = json.dumps(
        snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return sha256(encoded.encode("utf-8")).hexdigest()


def _guidance_findings(row: Opportunity, snapshot: dict) -> list[str]:
    evidence = snapshot.get("evidence") or {}
    findings = [f"{row.title or row.rule_id} is currently {row.status}."]
    target = _target_label(row)
    if target:
        findings.append(f"Affected target: {target}.")
    expected = (
        evidence.get("expected_schema_types") if isinstance(evidence, dict) else None
    )
    if expected:
        findings.append(f"Expected schema: {expected}.")
    return findings[:GUIDANCE_MAX_FINDINGS]


async def _guidance_opportunity(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> Opportunity:
    row = await session.scalar(
        select(Opportunity).where(
            Opportunity.id == opportunity_id,
            Opportunity.workspace_id == workspace_id,
        )
    )
    if row is None:
        raise OpportunityNotFoundError(_OPPORTUNITY_NOT_FOUND)
    return row


async def create_guidance(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    idempotency_key: str,
) -> tuple[OpportunityGuidance, bool]:
    """Persist one deterministic guidance version or replay its exact key."""
    _require_guidance_enabled()
    key = idempotency_key.strip()
    if not key or len(key) > GUIDANCE_IDEMPOTENCY_KEY_MAX_LEN:
        raise OpportunityValidationError("a bounded Idempotency-Key is required")
    row = await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    snapshot = _guidance_input(row)
    input_hash = _guidance_hash(snapshot)
    existing = await session.scalar(
        select(OpportunityGuidance).where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
            OpportunityGuidance.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.input_hash == input_hash:
            return existing, False
        raise OpportunityGuidanceIdempotencyConflictError(
            "Idempotency-Key was already used for an earlier guidance input"
        )

    guidance = OpportunityGuidance(
        workspace_id=workspace_id,
        project_id=row.project_id,
        opportunity_id=row.id,
        idempotency_key=key,
        input_snapshot=snapshot,
        input_hash=input_hash,
        findings=_guidance_findings(row, snapshot),
        recommendations=[row.remediation or "Review the persisted evidence."],
        source_analysis_ids=list(row.source_analysis_ids or []),
        source_issue_ids=list(row.source_issue_ids or []),
        source_metric_ids=list(row.source_metric_ids or []),
        analyzer_version=row.analyzer_version,
        rule_version=row.rule_version,
        formula_version=row.formula_version,
        generator_version=GUIDANCE_GENERATOR_VERSION,
        prompt_version=GUIDANCE_PROMPT_VERSION,
        provider=GUIDANCE_PROVIDER,
        model=GUIDANCE_MODEL,
    )
    session.add(guidance)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        winner = await session.scalar(
            select(OpportunityGuidance).where(
                OpportunityGuidance.workspace_id == workspace_id,
                OpportunityGuidance.opportunity_id == opportunity_id,
                OpportunityGuidance.idempotency_key == key,
            )
        )
        if winner is not None and winner.input_hash == input_hash:
            return winner, False
        if winner is not None:
            raise OpportunityGuidanceIdempotencyConflictError(
                "Idempotency-Key was already used for an earlier guidance input"
            ) from None
        raise
    await session.refresh(guidance)
    return guidance, True


async def get_latest_guidance(
    session: AsyncSession, *, workspace_id: uuid.UUID, opportunity_id: uuid.UUID
) -> OpportunityGuidance | None:
    _require_guidance_enabled()
    await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    return await session.scalar(
        select(OpportunityGuidance)
        .where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
        )
        .order_by(OpportunityGuidance.created_at.desc(), OpportunityGuidance.id.desc())
        .limit(1)
    )


async def list_guidance_history(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    opportunity_id: uuid.UUID,
    limit: int | None = None,
) -> list[OpportunityGuidance]:
    _require_guidance_enabled()
    await _guidance_opportunity(
        session, workspace_id=workspace_id, opportunity_id=opportunity_id
    )
    capped = max(
        1, min(limit or GUIDANCE_HISTORY_DEFAULT_LIMIT, GUIDANCE_HISTORY_MAX_LIMIT)
    )
    rows = await session.scalars(
        select(OpportunityGuidance)
        .where(
            OpportunityGuidance.workspace_id == workspace_id,
            OpportunityGuidance.opportunity_id == opportunity_id,
        )
        .order_by(OpportunityGuidance.created_at.desc(), OpportunityGuidance.id.desc())
        .limit(capped)
    )
    return list(rows.all())


def _project_guidance(row: OpportunityGuidance) -> dict:
    return {
        "id": row.id,
        "opportunity_id": row.opportunity_id,
        "input_hash": row.input_hash,
        "findings": list(row.findings or []),
        "recommendations": list(row.recommendations or []),
        "source_analysis_ids": list(row.source_analysis_ids or []),
        "source_issue_ids": list(row.source_issue_ids or []),
        "source_metric_ids": list(row.source_metric_ids or []),
        "analyzer_version": row.analyzer_version,
        "rule_version": row.rule_version,
        "formula_version": row.formula_version,
        "generator_version": row.generator_version,
        "prompt_version": row.prompt_version,
        "provider": row.provider,
        "model": row.model,
        "created_at": _iso(row.created_at),
    }


def _active_opportunity_at(
    occurrences: list[Opportunity], timestamp: datetime | None
) -> Opportunity | None:
    if timestamp is None:
        return next(
            (row for row in reversed(occurrences) if row.superseded_at is None), None
        )
    return next(
        (
            row
            for row in reversed(occurrences)
            if row.created_at <= timestamp
            and (row.superseded_at is None or row.superseded_at > timestamp)
        ),
        None,
    )


def _history_transition(
    current: Opportunity | None, previous: Opportunity | None
) -> str:
    if current is not None and previous is not None:
        return "continuing"
    if current is not None:
        return "new"
    return "resolved"


def _project_history_group(
    *,
    rule_id: str,
    target_key: str,
    occurrences: list[Opportunity],
    latest_at: datetime | None,
    previous_at: datetime | None,
) -> tuple[dict, str, bool]:
    current = _active_opportunity_at(occurrences, latest_at)
    previous = _active_opportunity_at(occurrences, previous_at)
    transition = _history_transition(current, previous)
    return (
        {
            "rule_id": rule_id,
            "target_key": target_key,
            "title": occurrences[-1].title or "",
            "current_state": current.status if current is not None else "resolved",
            "transition": transition,
            "occurrence_count": len(occurrences),
            "first_seen": _iso(occurrences[0].created_at),
            "last_seen": _iso(occurrences[-1].created_at),
            "timeline": [
                {"id": row.id, "status": row.status, "seen_at": _iso(row.created_at)}
                for row in occurrences
            ],
        },
        transition,
        current is not None or previous is not None,
    )


async def get_grouped_history(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """Rule/target history compared with the two latest recompute snapshots."""
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    snapshots = list(
        (
            await session.scalars(
                select(OpportunitySnapshot)
                .where(
                    OpportunitySnapshot.workspace_id == workspace_id,
                    OpportunitySnapshot.project_id == project_id,
                )
                .order_by(
                    OpportunitySnapshot.created_at.desc(), OpportunitySnapshot.id.desc()
                )
                .limit(2)
            )
        ).all()
    )
    latest_snapshot = snapshots[0] if snapshots else None
    previous_snapshot = snapshots[1] if len(snapshots) > 1 else None
    rows = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(
                    Opportunity.workspace_id == workspace_id,
                    Opportunity.project_id == project_id,
                )
                .order_by(Opportunity.created_at.asc(), Opportunity.id.asc())
            )
        ).all()
    )
    groups: dict[tuple[str, str], list[Opportunity]] = {}
    for row in rows:
        groups.setdefault((row.rule_id, row.target_key), []).append(row)

    projected: list[dict] = []
    counts = {"new": 0, "continuing": 0, "resolved": 0}
    latest_at = latest_snapshot.created_at if latest_snapshot is not None else None
    previous_at = (
        previous_snapshot.created_at if previous_snapshot is not None else None
    )
    for (rule_id, target_key), occurrences in groups.items():
        group, transition, changed = _project_history_group(
            rule_id=rule_id,
            target_key=target_key,
            occurrences=occurrences,
            latest_at=latest_at,
            previous_at=previous_at,
        )
        if changed:
            counts[transition] += 1
        projected.append(group)
    projected.sort(
        key=lambda group: (group["last_seen"] or "", group["rule_id"]), reverse=True
    )
    return {"items": projected, "since_previous": counts}


async def _resolve_scored_audit(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Audit | None:
    """The latest dashboard-ready audit that also has its aggregate snapshot.

    Mirrors ``recompute``'s default-resolution condition exactly: an audit
    without its ``MetricSnapshot`` row is NOT dashboard-ready, and recompute
    discards it. Counting such an audit as evidence made ``stale`` true even
    immediately after a successful recompute — permanently, since no
    recompute could ever catch up to it.
    """
    audit = await _resolve_source(
        session,
        Audit,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=None,
        ready_statuses=_DASHBOARD_READY_STATUSES,
        not_found_detail=_AUDIT_NOT_FOUND,
    )
    if audit is None:
        return None
    has_snapshot = await session.scalar(
        select(MetricSnapshot.id).where(
            MetricSnapshot.audit_id == audit.id,
            MetricSnapshot.workspace_id == workspace_id,
        )
    )
    return audit if has_snapshot is not None else None


async def _latest_evidence_at(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> datetime | None:
    """Newest usable-evidence timestamp (latest dashboard-ready audit/crawl).

    Read-time only (C4c): compared against the latest snapshot's
    ``created_at`` to derive staleness — nothing is persisted, so a failed
    best-effort recompute hook manifests as exactly this drift.

    The audit condition MIRRORS ``recompute``'s (see ``_resolve_scored_audit``).
    """
    audit = await _resolve_scored_audit(
        session, workspace_id=workspace_id, project_id=project_id
    )
    crawl = await _resolve_source(
        session,
        SiteCrawl,
        workspace_id=workspace_id,
        project_id=project_id,
        source_id=None,
        ready_statuses=_EVIDENCE_CRAWL_STATUSES,
        not_found_detail=_CRAWL_NOT_FOUND,
    )
    stamps = [
        stamp
        for stamp in (
            (audit.completed_at or audit.created_at) if audit is not None else None,
            (crawl.completed_at or crawl.created_at) if crawl is not None else None,
        )
        if stamp is not None
    ]
    return max(stamps) if stamps else None


async def get_summary(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict:
    """Latest snapshot projection; ``computed=false`` when never recomputed.

    ``stale`` is read-time staleness (no persisted marker): the latest
    completed audit/crawl is newer than the latest opportunity snapshot.
    """
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    snapshot = await _latest_snapshot(
        session, workspace_id=workspace_id, project_id=project_id
    )
    evidence_at = await _latest_evidence_at(
        session, workspace_id=workspace_id, project_id=project_id
    )
    stale = (
        snapshot is not None
        and evidence_at is not None
        and evidence_at > snapshot.created_at
    )
    refresh_task = await session.scalar(
        select(AnalyticsTask)
        .where(
            AnalyticsTask.workspace_id == workspace_id,
            AnalyticsTask.project_id == project_id,
            AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_OPPORTUNITY_REFRESH,
        )
        .order_by(AnalyticsTask.created_at.desc(), AnalyticsTask.id.desc())
        .limit(1)
    )
    if evidence_at is None:
        activation_state = "waiting_for_evidence"
    elif snapshot is not None and not stale:
        activation_state = "ready"
    elif refresh_task is not None and refresh_task.status in {
        TASK_STATUS_LEASED,
        TASK_STATUS_RUNNING,
    }:
        activation_state = "refreshing"
    elif refresh_task is not None and refresh_task.status in {
        TASK_STATUS_RETRY_WAIT,
        TASK_STATUS_FAILED,
    }:
        activation_state = "delayed"
    elif refresh_task is not None and refresh_task.status == TASK_STATUS_QUEUED:
        activation_state = "queued"
    else:
        activation_state = "queued"
    if snapshot is None:
        return {
            "computed": False,
            "run_id": None,
            "audit_id": None,
            "site_crawl_id": None,
            "counts_by_type": {},
            "counts_by_severity": {},
            "counts_by_status": {},
            "total_count": 0,
            "median_priority": None,
            "analyzer_version": ANALYZER_VERSION,
            "rule_version": RULE_VERSION,
            "formula_version": FORMULA_VERSION,
            "computed_at": None,
            "evidence_updated_at": _iso(evidence_at),
            "stale": False,
            "activation_state": activation_state,
        }
    return {
        "computed": True,
        "run_id": snapshot.run_id,
        "audit_id": snapshot.audit_id,
        "site_crawl_id": snapshot.site_crawl_id,
        "counts_by_type": snapshot.counts_by_type or {},
        "counts_by_severity": snapshot.counts_by_severity or {},
        "counts_by_status": snapshot.counts_by_status or {},
        "total_count": snapshot.total_count,
        "median_priority": snapshot.median_priority,
        "analyzer_version": snapshot.analyzer_version,
        "rule_version": snapshot.rule_version,
        "formula_version": snapshot.formula_version,
        "computed_at": _iso(snapshot.created_at),
        "evidence_updated_at": _iso(evidence_at),
        "stale": stale,
        "activation_state": activation_state,
    }


async def load_export_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    opportunity_type: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    rule_id: str | None = None,
    min_priority: float | None = None,
) -> list[dict]:
    """The list projection, uncapped-sortable but bounded by MAX_EXPORT_ITEMS.

    Same filters as ``list_opportunities`` (including the default active-status
    view) so an export always matches what the catalog shows.
    """
    await _require_project(session, workspace_id=workspace_id, project_id=project_id)
    _validate_filters(
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
    )
    clauses = _filter_clauses(
        workspace_id=workspace_id,
        project_id=project_id,
        opportunity_type=opportunity_type,
        severity=severity,
        status=status,
        rule_id=rule_id,
        min_priority=min_priority,
    )
    rows = list(
        (
            await session.scalars(
                select(Opportunity)
                .where(*clauses)
                .order_by(Opportunity.priority_score.desc(), Opportunity.id.desc())
                .limit(MAX_EXPORT_ITEMS)
            )
        ).all()
    )
    return [_project_export_row(row) for row in rows]


# =========================================================================
# Row projections (model -> strict contract dicts)
# =========================================================================
def _humanize_theme(theme: str) -> str:
    """Humanized theme label (``crm-software`` -> ``Crm software theme``)."""
    words = re.sub(r"[-_]+", " ", theme).strip()
    if not words:
        return ""
    return f"{words[:1].upper()}{words[1:]} theme"


def _target_label(row: Opportunity) -> str | None:
    """Backend-owned target presentation (single owner — the client renders
    this verbatim and has no derivation helper of its own).

    Derived from PERSISTED fields only, mirroring ``_project_export_row``:
    the URL for site targets, then the frozen ``evidence.prompt_text`` (the
    audit prompt snapshot taken at detection time — it survives a later
    prompt deletion, unlike a join on ``target_prompt_id``), then the
    humanized theme, then the frozen ``evidence.product_name`` for
    commerce-derived targets. Never falls back to the deterministic
    ``target_key`` (not user-facing).
    """
    evidence = row.evidence or {}
    prompt_text = str(evidence.get("prompt_text") or "").strip()
    product_name = str(evidence.get("product_name") or "").strip()
    theme_label = _humanize_theme(row.target_theme or "")
    return row.target_url or prompt_text or theme_label or product_name or None


def _stable_key(row: Opportunity) -> str:
    # JSON tuple encoding is reversible and collision-safe when either persisted
    # identity component contains the separator used by older concatenated keys.
    return json.dumps(
        [row.rule_id, row.target_key],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _evidence_summary(row: Opportunity) -> dict:
    sources = {
        "analysis": list(row.source_analysis_ids or []),
        "issue": list(row.source_issue_ids or []),
        "metric": list(row.source_metric_ids or []),
        "traffic": list(row.source_traffic_ids or []),
    }
    kinds = [kind for kind, values in sources.items() if values]
    return {"count": sum(len(values) for values in sources.values()), "kinds": kinds}


def _project_item(
    row: Opportunity,
    *,
    system_rank: int = 0,
    display_rank: int = 0,
    order_source: str = "system",
) -> dict:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "rule_id": row.rule_id,
        "opportunity_type": row.opportunity_type,
        "severity": row.severity,
        "priority_score": row.priority_score,
        "title": row.title or "",
        "target_key": row.target_key,
        "target_prompt_id": row.target_prompt_id,
        "target_url": row.target_url,
        "target_theme": row.target_theme,
        "target_label": _target_label(row),
        "status": row.status,
        "system_rank": system_rank,
        "display_rank": display_rank,
        "order_source": order_source,
        "priority_factors": {
            "severity": row.severity,
            "system_score": row.priority_score,
            "formula_version": row.formula_version,
        },
        "evidence_summary": _evidence_summary(row),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def _ordered_items(
    rows: list[Opportunity], order: OpportunityOrder | None
) -> list[dict]:
    system_rank = {row.id: index for index, row in enumerate(rows, start=1)}
    if order is None or not order.ordered_keys:
        return [
            _project_item(row, system_rank=index, display_rank=index)
            for index, row in enumerate(rows, start=1)
        ]

    manual_rank = {key: index for index, key in enumerate(order.ordered_keys)}
    ordered = sorted(
        rows,
        key=lambda row: (
            manual_rank.get(_stable_key(row), len(manual_rank) + system_rank[row.id]),
            system_rank[row.id],
        ),
    )
    return [
        _project_item(
            row,
            system_rank=system_rank[row.id],
            display_rank=index,
            order_source="manual" if _stable_key(row) in manual_rank else "system",
        )
        for index, row in enumerate(ordered, start=1)
    ]


def _project_detail(row: Opportunity) -> dict:
    return {
        **_project_item(row),
        "remediation": row.remediation or "",
        "evidence": row.evidence or {},
        "source_analysis_ids": list(row.source_analysis_ids or []),
        "source_issue_ids": list(row.source_issue_ids or []),
        "source_metric_ids": list(row.source_metric_ids or []),
        "source_traffic_ids": list(row.source_traffic_ids or []),
        "analyzer_version": row.analyzer_version,
        "rule_version": row.rule_version,
        "formula_version": row.formula_version,
        "superseded_by_id": row.superseded_by_id,
        "superseded_at": _iso(row.superseded_at),
    }


def _project_export_row(row: Opportunity) -> dict:
    evidence = row.evidence or {}
    target = row.target_url or evidence.get("prompt_text") or row.target_key
    return {
        "id": str(row.id),
        "rule_id": row.rule_id,
        "opportunity_type": row.opportunity_type,
        "severity": row.severity,
        "priority_score": row.priority_score,
        "status": row.status,
        "title": row.title or "",
        "target": target,
        "remediation": row.remediation or "",
        "rule_version": row.rule_version,
        "formula_version": row.formula_version,
        "created_at": _iso(row.created_at),
    }


def _project_snapshot(snapshot: OpportunitySnapshot) -> dict:
    return {
        "id": snapshot.id,
        "run_id": snapshot.run_id,
        "audit_id": snapshot.audit_id,
        "site_crawl_id": snapshot.site_crawl_id,
        "counts_by_type": snapshot.counts_by_type or {},
        "counts_by_severity": snapshot.counts_by_severity or {},
        "counts_by_status": snapshot.counts_by_status or {},
        "total_count": snapshot.total_count,
        "median_priority": snapshot.median_priority,
        "analyzer_version": snapshot.analyzer_version,
        "rule_version": snapshot.rule_version,
        "formula_version": snapshot.formula_version,
        "created_at": _iso(snapshot.created_at),
    }
