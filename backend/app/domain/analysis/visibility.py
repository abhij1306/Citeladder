"""Persisted selected-run visibility projections."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analysis.normalization import normalize_domain
from app.core.config.prompts import REQUESTABLE_PROMPT_COHORTS
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.analysis.projection_common import (
    _AUDIT_NOT_FOUND,
    aggregate_provenance,
    latest_dashboard_audit_id,
    load_snapshot,
)
from app.domain.analysis.schemas import (
    EngineComparisonRow,
    RankingRow,
    VisibilityResponse,
)
from app.domain.analysis.trend_folding import _brand_name
from app.domain.projects.logos import get_project_logo_urls
from app.domain.projects.service import get_project
from app.models.analysis import MetricSnapshot
from app.models.audit import Audit
from app.models.project import Project


async def get_visibility(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    cohort: str = "core",
) -> VisibilityResponse:
    """Serve the selected-run dashboard projection for a project.

    Defaults to the project's latest completed/partially-completed audit when
    ``audit_id`` is omitted. Computed server-side from the persisted snapshot;
    no provider call (invariant 7).
    """
    audit_id, audit = await _selected_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit_id=audit_id,
    )
    snapshot = await load_snapshot(
        session, workspace_id=workspace_id, audit_id=audit_id
    )
    metrics = _cohort_metrics(snapshot, cohort)
    logo_urls, logo_identity_ids, website_urls = await _project_logo_context(
        session, workspace_id=workspace_id, project_id=project_id
    )
    provenance_mode, model_provenance = aggregate_provenance(audit)
    return VisibilityResponse(
        project_id=project_id,
        audit_id=audit_id,
        audit_status=audit.status,
        analyzer_version=snapshot.analyzer_version,
        scoring_rule_version=snapshot.scoring_rule_version,
        cohort=cohort,
        coverage=dict(metrics.get("coverage") or {}),
        total_completed=int(metrics.get("total_completed") or 0),
        total_failed=max(
            0,
            int((metrics.get("coverage") or {}).get("requested") or 0)
            - int(metrics.get("total_completed") or 0),
        ),
        visibility_score=_selected_visibility_score(snapshot, metrics, cohort),
        measurement_mode=provenance_mode,
        model_provenance=model_provenance,
        rankings=_rankings(
            metrics,
            logo_urls=logo_urls,
            logo_identity_ids=logo_identity_ids,
            website_urls=website_urls,
        ),
        per_engine=_engine_rows(metrics),
        sentiment=metrics.get("sentiment"),
        avg_position=metrics.get("avg_position"),
        created_at=snapshot.created_at,
    )


async def _selected_audit(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
) -> tuple[uuid.UUID, Audit]:
    selected_id = audit_id or await latest_dashboard_audit_id(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if selected_id is None:
        raise AnalysisNotFoundError("No completed audit for project")
    audit = await session.scalar(
        select(Audit)
        .options(selectinload(Audit.engine_snapshots))
        .where(
            Audit.id == selected_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
        )
    )
    if audit is None:
        raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    return selected_id, audit


def _cohort_metrics(snapshot: MetricSnapshot, cohort: str) -> dict:
    if cohort not in REQUESTABLE_PROMPT_COHORTS:
        raise TrendQueryError(f"Unknown prompt cohort: {cohort!r}")
    stored_metrics = snapshot.metrics or {}
    return (
        stored_metrics
        if cohort == "core"
        else dict(stored_metrics.get("comparison") or {})
    )


def _selected_visibility_score(
    snapshot: MetricSnapshot, metrics: dict, cohort: str
) -> float:
    if cohort == "core":
        return snapshot.visibility_score
    return round(float(metrics.get("brand_mention_rate") or 0.0) * 100, 2)


async def _project_logo_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[
    dict[uuid.UUID, str],
    dict[tuple[bool, str], uuid.UUID],
    dict[tuple[bool, str], str],
]:
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    logo_urls = get_project_logo_urls(project)
    identity_ids: dict[tuple[bool, str], uuid.UUID] = {}
    if project.brand is not None:
        identity_ids[(True, project.brand.name)] = project.brand.id
    for competitor in project.competitors:
        identity_ids[(False, competitor.name)] = competitor.id
    return logo_urls, identity_ids, _project_website_urls(project)


def _project_website_urls(project: Project) -> dict[tuple[bool, str], str]:
    website_urls: dict[tuple[bool, str], str] = {}
    if project.brand is not None:
        brand_website = _normalized_logo_website_url(
            project.website_url
            or next((item.domain for item in project.owned_domains if item.domain), "")
        )
        if brand_website:
            website_urls[(True, project.brand.name)] = brand_website
    for competitor in project.competitors:
        competitor_website = _normalized_logo_website_url(
            next(
                (str(domain) for domain in competitor.domains or [] if str(domain)),
                "",
            )
        )
        if competitor_website:
            website_urls[(False, competitor.name)] = competitor_website
    return website_urls


def _rankings(
    metrics: dict,
    *,
    logo_urls: dict[uuid.UUID, str] | None = None,
    logo_identity_ids: dict[tuple[bool, str], uuid.UUID] | None = None,
    website_urls: dict[tuple[bool, str], str] | None = None,
) -> list[RankingRow]:
    """Build the brand-vs-competitor rankings table from the aggregate.

    Visibility % (mention rate) + SOV are populated; sentiment + average
    position are present but null (decision B-2).
    """
    sov = metrics.get("share_of_voice") or {}
    share = sov.get("share") or {}
    counts = sov.get("mention_counts") or {}
    brand_name = _brand_name(counts, metrics)
    competitor_mention = metrics.get("competitor_mention_rate") or {}
    competitor_citation = metrics.get("competitor_citation_rate") or {}

    rows = [
        _ranking_row(
            name=brand_name,
            is_brand=True,
            mention_rate=metrics.get("brand_mention_rate"),
            citation_rate=metrics.get("owned_citation_rate"),
            share=share,
            counts=counts,
            logo_urls=logo_urls or {},
            identity_ids=logo_identity_ids or {},
            website_urls=website_urls,
        ),
        *[
            _ranking_row(
                name=name,
                is_brand=False,
                mention_rate=competitor_mention.get(name),
                citation_rate=competitor_citation.get(name),
                share=share,
                counts=counts,
                logo_urls=logo_urls or {},
                identity_ids=logo_identity_ids or {},
                website_urls=website_urls,
            )
            for name in competitor_mention
        ],
    ]
    # Deterministic order: highest SOV first, then name for stable ties.
    rows.sort(key=lambda r: (-(r.share_of_voice or 0.0), r.name))
    return rows


def _ranking_row(
    *,
    name: str,
    is_brand: bool,
    mention_rate: object,
    citation_rate: object,
    share: dict,
    counts: dict,
    logo_urls: dict[uuid.UUID, str],
    identity_ids: dict[tuple[bool, str], uuid.UUID],
    website_urls: dict[tuple[bool, str], str] | None,
) -> RankingRow:
    return RankingRow(
        name=name,
        is_brand=is_brand,
        logo_url=_logo_url_for_name(name, is_brand, logo_urls, identity_ids),
        website_url=_website_url_for_name(name, is_brand, website_urls),
        mention_rate=mention_rate,
        citation_rate=citation_rate,
        share_of_voice=share.get(name),
        mention_count=int(counts.get(name, 0) or 0),
    )


def _logo_url_for_name(
    name: str,
    is_brand: bool,
    logo_urls: dict[uuid.UUID, str],
    identity_ids: dict[tuple[bool, str], uuid.UUID],
) -> str | None:
    identity_id = identity_ids.get((is_brand, name))
    return logo_urls.get(identity_id) if identity_id is not None else None


def _website_url_for_name(
    name: str,
    is_brand: bool,
    website_urls: dict[tuple[bool, str], str] | None,
) -> str | None:
    return website_urls.get((is_brand, name)) if website_urls is not None else None


def _normalized_logo_website_url(value: object) -> str | None:
    domain = normalize_domain(value)
    return f"https://{domain}" if domain else None


def _engine_rows(metrics: dict) -> list[EngineComparisonRow]:
    per_engine = metrics.get("per_engine") or {}
    rows: list[EngineComparisonRow] = []
    for engine, agg in sorted(per_engine.items()):
        rate = agg.get("brand_mention_rate")
        rows.append(
            EngineComparisonRow(
                logical_engine=engine,
                total_completed=int(agg.get("total_completed", 0) or 0),
                brand_mention_rate=rate,
                owned_citation_rate=agg.get("owned_citation_rate"),
                search_use_rate=agg.get("search_use_rate"),
                visibility_score=round(float(rate) * 100, 2)
                if rate is not None
                else None,
            )
        )
    return rows


# --- Cross-run Visibility trend projection helpers (pure, invariant 7) -----
#
# Every helper below reads only the already-persisted ``MetricSnapshot.metrics``
# dict (the same shape the single-run dashboard reads) and the owning ``Audit``
# timestamp/status. None of them re-score, re-extract, or call a provider.
