"""Persisted PR2 AEO Readiness and typed Content handoff projections."""

from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.rules import rule_for
from app.core.config.site_health_contracts import (
    AEO_READINESS_DIMENSION_DESCRIPTIONS,
    AEO_READINESS_DIMENSION_LABELS,
    AEO_READINESS_DIMENSIONS,
    AEO_READINESS_MAX_EVALUATIONS,
    AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION,
    PAGE_ANALYSIS_STATUS_COMPLETED,
    RULE_FAILING_OUTCOMES,
    RULE_OUTCOME_CONFLICTING,
    RULE_OUTCOME_ERROR,
    RULE_OUTCOME_FAIL,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_PARTIAL,
    RULE_OUTCOME_PASS,
    RULE_OUTCOME_UNAVAILABLE,
    RULE_OUTCOME_UNKNOWN,
    SCORING_VERSION,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    READINESS_CHECKPOINTS,
    SCHEMA_CONTRACT_VERSION,
)
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    resolve_usable_crawl,
)
from app.domain.site_health.service.presentation import display_label_for
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import MonitoredSiteUrl, SiteUrl


def _unavailable(crawl_id: uuid.UUID | None = None) -> dict:
    return {
        "state": "not_measured",
        "crawl_id": crawl_id,
        "score": None,
        "coverage": None,
        "profile_version": PROFILE_VERSION,
        "schema_contract_version": SCHEMA_CONTRACT_VERSION,
        "scoring_version": SCORING_VERSION,
        "presentation_version": PRESENTATION_VERSION,
        "analyzer_version": "",
        "source_analysis_ids": [],
        "analysis_count": 0,
        "affected_page_count": 0,
        "dimensions": [],
        "limitations": ["AEO Readiness appears after persisted page analysis."],
    }


def _bounded_evaluations(
    evaluations: list[SiteRuleEvaluation],
) -> tuple[list[SiteRuleEvaluation], bool]:
    return (
        evaluations[:AEO_READINESS_MAX_EVALUATIONS],
        len(evaluations) > AEO_READINESS_MAX_EVALUATIONS,
    )


def _check_projection(rule_id: str, rows: list[SiteRuleEvaluation]) -> dict | None:
    checkpoint = READINESS_CHECKPOINTS.get(rule_id)
    if checkpoint is None:
        return None
    counts = Counter(row.outcome for row in rows)
    rule = rule_for(rule_id)
    return {
        "rule_id": rule_id,
        "title": display_label_for(rule_id),
        "remediation": rule.remediation if rule else "",
        "satisfied_count": counts[RULE_OUTCOME_PASS],
        "partial_count": counts[RULE_OUTCOME_PARTIAL],
        "missing_count": counts[RULE_OUTCOME_FAIL],
        "unknown_count": counts[RULE_OUTCOME_UNKNOWN],
        "unavailable_count": counts[RULE_OUTCOME_UNAVAILABLE],
        "conflicting_count": counts[RULE_OUTCOME_CONFLICTING],
        "not_applicable_count": counts[RULE_OUTCOME_NOT_APPLICABLE],
        "error_count": counts[RULE_OUTCOME_ERROR],
        "failing_page_count": len(_failing_analysis_ids(rows)),
        "checkpoint_family": checkpoint.family,
        "readiness_weight": checkpoint.weight,
        "content_addressable": checkpoint.content_addressable,
    }


def _rule_guidance(rule_id: str) -> tuple[str, str]:
    rule = rule_for(rule_id)
    if rule is None:
        return "", ""
    return rule.description, rule.remediation


def _page_evidence(
    dimension: str,
    rows: list[SiteRuleEvaluation],
    analyses: dict[uuid.UUID, tuple[SitePageAnalysis, SiteUrl]],
) -> list[dict]:
    by_analysis: dict[uuid.UUID, list[SiteRuleEvaluation]] = {}
    for row in rows:
        if (
            row.rule_id in READINESS_CHECKPOINTS
            and row.readiness_dimension == dimension
            and row.outcome in RULE_FAILING_OUTCOMES
        ):
            by_analysis.setdefault(row.analysis_id, []).append(row)
    ordered = sorted(
        by_analysis.items(),
        key=lambda item: (
            -len(item[1]),
            analyses[item[0]][1].normalized_url,
            str(item[0]),
        ),
    )
    pages: list[dict] = []
    for analysis_id, failures in ordered[
        :AEO_READINESS_MAX_EVIDENCE_PAGES_PER_DIMENSION
    ]:
        analysis, site_url = analyses[analysis_id]
        failures.sort(key=lambda row: row.rule_id)
        failure_guidance = {
            row.rule_id: _rule_guidance(row.rule_id) for row in failures
        }
        pages.append(
            {
                "site_url_id": site_url.id,
                "source_analysis_id": analysis.id,
                "normalized_url": site_url.normalized_url,
                "failed_checks": [
                    {
                        "rule_id": row.rule_id,
                        "title": display_label_for(row.rule_id),
                        "observed_evidence": row.evidence or {},
                        "expected_capability": failure_guidance[row.rule_id][0],
                        "remediation": failure_guidance[row.rule_id][1],
                        "content_addressable": READINESS_CHECKPOINTS[
                            row.rule_id
                        ].content_addressable,
                    }
                    for row in failures
                ],
            }
        )
    return pages


def _failing_analysis_ids(rows: list[SiteRuleEvaluation]) -> set[uuid.UUID]:
    return {row.analysis_id for row in rows if row.outcome in RULE_FAILING_OUTCOMES}


def _outcome_page_count(
    rows: list[SiteRuleEvaluation], outcomes: frozenset[str]
) -> int:
    return len({row.analysis_id for row in rows if row.outcome in outcomes})


def _check_projections(
    rows: list[SiteRuleEvaluation], checkpoint_ids: list[str]
) -> list[dict]:
    return [
        projection
        for rule_id in checkpoint_ids
        if (
            projection := _check_projection(
                rule_id, [row for row in rows if row.rule_id == rule_id]
            )
        )
        is not None
    ]


def _dimension_projection(
    persisted: dict,
    rows: list[SiteRuleEvaluation],
    analyses: dict[uuid.UUID, tuple[SitePageAnalysis, SiteUrl]],
) -> dict:
    key = str(persisted.get("key") or "")
    dimension_rows = [row for row in rows if row.readiness_dimension == key]
    counts = Counter(row.outcome for row in dimension_rows)
    checkpoint_ids = sorted({row.rule_id for row in dimension_rows})
    evidence_pages = _page_evidence(key, dimension_rows, analyses)
    failing_page_count = len(_failing_analysis_ids(dimension_rows))
    return {
        "key": key,
        "label": AEO_READINESS_DIMENSION_LABELS[key],
        "description": AEO_READINESS_DIMENSION_DESCRIPTIONS[key],
        "dimension_applicability": persisted.get(
            "dimension_applicability", "unresolved"
        ),
        "dimension_measurement_state": persisted.get(
            "dimension_measurement_state", "not_measured"
        ),
        "score": persisted.get("score"),
        "reason": persisted.get("reason", ""),
        "checkpoint_ids": checkpoint_ids,
        "determinate_checkpoint_ids": persisted.get("determinate_checkpoint_ids", []),
        "checkpoint_families": persisted.get("checkpoint_families", []),
        "earned_points": persisted.get("earned_points", 0.0),
        "determinate_points": persisted.get("determinate_points", 0.0),
        "expected_points": persisted.get("expected_points", 0.0),
        "satisfied_count": counts[RULE_OUTCOME_PASS],
        "partial_count": counts[RULE_OUTCOME_PARTIAL],
        "missing_count": counts[RULE_OUTCOME_FAIL],
        "unknown_count": counts[RULE_OUTCOME_UNKNOWN],
        "unavailable_count": counts[RULE_OUTCOME_UNAVAILABLE],
        "conflicting_count": counts[RULE_OUTCOME_CONFLICTING],
        "not_applicable_count": counts[RULE_OUTCOME_NOT_APPLICABLE],
        "error_count": counts[RULE_OUTCOME_ERROR],
        "coverage": persisted.get("coverage"),
        "checked_page_count": _outcome_page_count(
            dimension_rows,
            frozenset({RULE_OUTCOME_PASS, RULE_OUTCOME_PARTIAL, RULE_OUTCOME_FAIL}),
        ),
        "failing_page_count": failing_page_count,
        "checks": _check_projections(dimension_rows, checkpoint_ids),
        "evidence_pages": evidence_pages,
        "evidence_truncated": failing_page_count > len(evidence_pages),
    }


async def _analysis_graph(
    session: AsyncSession,
    *,
    crawl_id: uuid.UUID,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> tuple[
    dict[uuid.UUID, tuple[SitePageAnalysis, SiteUrl]],
    list[SiteRuleEvaluation],
    bool,
]:
    analysis_rows = (
        await session.execute(
            select(SitePageAnalysis, SiteUrl)
            .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
            .join(
                MonitoredSiteUrl,
                (MonitoredSiteUrl.site_url_id == SitePageAnalysis.site_url_id)
                & (MonitoredSiteUrl.project_id == project_id)
                & (MonitoredSiteUrl.workspace_id == workspace_id),
            )
            .where(
                SitePageAnalysis.workspace_id == workspace_id,
                SitePageAnalysis.project_id == project_id,
                SitePageAnalysis.crawl_id == crawl_id,
                SitePageAnalysis.status == PAGE_ANALYSIS_STATUS_COMPLETED,
                SitePageAnalysis.is_current.is_(True),
                MonitoredSiteUrl.active.is_(True),
            )
        )
    ).all()
    analyses = {
        analysis.id: (analysis, site_url) for analysis, site_url in analysis_rows
    }
    evaluations = (
        list(
            await session.scalars(
                select(SiteRuleEvaluation)
                .where(
                    SiteRuleEvaluation.workspace_id == workspace_id,
                    SiteRuleEvaluation.analysis_id.in_(analyses),
                    SiteRuleEvaluation.readiness_dimension != "",
                    SiteRuleEvaluation.rule_id.in_(READINESS_CHECKPOINTS),
                )
                .order_by(SiteRuleEvaluation.analysis_id, SiteRuleEvaluation.rule_id)
                .limit(AEO_READINESS_MAX_EVALUATIONS + 1)
            )
        )
        if analyses
        else []
    )
    bounded, evaluations_truncated = _bounded_evaluations(evaluations)
    return analyses, bounded, evaluations_truncated


async def get_aeo_readiness(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    crawl = await resolve_usable_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    if crawl is None:
        return _unavailable()
    snapshot = await session.scalar(
        select(SiteHealthSnapshot).where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
            SiteHealthSnapshot.crawl_id == crawl.id,
        )
    )
    if snapshot is None:
        return _unavailable(crawl.id)
    analyses, evaluations, evaluations_truncated = await _analysis_graph(
        session,
        crawl_id=crawl.id,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    persisted_by_key = {
        str(item.get("key")): item for item in (snapshot.readiness_dimensions or [])
    }
    dimensions = [
        _dimension_projection(
            persisted_by_key.get(key, {"key": key}), evaluations, analyses
        )
        for key in AEO_READINESS_DIMENSIONS
    ]
    affected = _failing_analysis_ids(evaluations)
    limitations = []
    if snapshot.aeo_measurement_state != "measured":
        limitations.append(
            "PR2 measures a defensible initial checkpoint set; broader "
            "page-purpose coverage ships in PR3."
        )
    if snapshot.coverage_state != "complete":
        limitations.append(
            f"AEO Readiness describes {snapshot.analyzed_url_count} audited pages; "
            f"crawl coverage is {snapshot.coverage_state}."
        )
    if evaluations_truncated:
        limitations.append(
            "Readiness diagnostic counts and evidence are truncated at "
            f"{AEO_READINESS_MAX_EVALUATIONS} evaluations."
        )
    return {
        "state": snapshot.aeo_measurement_state,
        "crawl_id": crawl.id,
        "score": snapshot.aeo_readiness_score,
        "coverage": snapshot.aeo_measurement_coverage,
        "profile_version": snapshot.profile_version,
        "schema_contract_version": snapshot.schema_contract_version,
        "scoring_version": snapshot.scoring_version,
        "presentation_version": snapshot.presentation_version,
        "analyzer_version": snapshot.analyzer_version,
        "source_analysis_ids": snapshot.source_analysis_ids or [],
        "analysis_count": snapshot.analyzed_url_count,
        "affected_page_count": len(affected),
        "dimensions": dimensions,
        "limitations": limitations,
    }


def _allowed_content_checkpoints(dimension: str, checkpoint_ids: list[str]) -> set[str]:
    allowed = {
        checkpoint_id
        for checkpoint_id in checkpoint_ids
        if checkpoint_id in READINESS_CHECKPOINTS
        and READINESS_CHECKPOINTS[checkpoint_id].content_addressable
        and READINESS_CHECKPOINTS[checkpoint_id].dimension == dimension
    }
    if allowed and allowed == set(checkpoint_ids):
        return allowed
    raise SiteHealthNotFoundError("Content-addressable readiness gap not found")


async def _handoff_analysis(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    source_analysis_id: uuid.UUID,
) -> tuple[SitePageAnalysis, SiteUrl]:
    analysis_row = await session.execute(
        select(SitePageAnalysis, SiteUrl)
        .join(SiteUrl, SiteUrl.id == SitePageAnalysis.site_url_id)
        .where(
            SitePageAnalysis.id == source_analysis_id,
            SitePageAnalysis.workspace_id == workspace_id,
            SitePageAnalysis.project_id == project_id,
            SitePageAnalysis.crawl_id == crawl_id,
            SitePageAnalysis.site_url_id == site_url_id,
            SitePageAnalysis.is_current.is_(True),
        )
    )
    found = analysis_row.one_or_none()
    if found is None:
        raise SiteHealthNotFoundError("Site Health handoff evidence not found")
    analysis, site_url = found
    return analysis, site_url


async def _handoff_evaluations(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    source_analysis_id: uuid.UUID,
    dimension: str,
    allowed: set[str],
) -> list[SiteRuleEvaluation]:
    rows = list(
        await session.scalars(
            select(SiteRuleEvaluation)
            .where(
                SiteRuleEvaluation.workspace_id == workspace_id,
                SiteRuleEvaluation.analysis_id == source_analysis_id,
                SiteRuleEvaluation.readiness_dimension == dimension,
                SiteRuleEvaluation.rule_id.in_(allowed),
                SiteRuleEvaluation.outcome.in_(
                    (RULE_OUTCOME_FAIL, RULE_OUTCOME_PARTIAL)
                ),
            )
            .order_by(SiteRuleEvaluation.rule_id)
        )
    )
    if rows and {row.rule_id for row in rows} == allowed:
        return rows
    raise SiteHealthNotFoundError("Content-addressable readiness gap not found")


async def get_content_handoff(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID,
    site_url_id: uuid.UUID,
    source_analysis_id: uuid.UUID,
    dimension: str,
    checkpoint_ids: list[str],
) -> dict:
    analysis, site_url = await _handoff_analysis(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        crawl_id=crawl_id,
        site_url_id=site_url_id,
        source_analysis_id=source_analysis_id,
    )
    allowed = _allowed_content_checkpoints(dimension, checkpoint_ids)
    evaluations = await _handoff_evaluations(
        session,
        workspace_id=workspace_id,
        source_analysis_id=source_analysis_id,
        dimension=dimension,
        allowed=allowed,
    )
    return {
        "project_id": project_id,
        "crawl_id": crawl_id,
        "site_url_id": site_url_id,
        "source_analysis_id": source_analysis_id,
        "dimension": dimension,
        "checkpoint_ids": sorted(allowed),
        "finding_class": evaluations[0].finding_class,
        "observed_evidence": [row.evidence or {} for row in evaluations],
        "expected_capability": [_rule_guidance(row.rule_id)[0] for row in evaluations],
        "remediation": [_rule_guidance(row.rule_id)[1] for row in evaluations],
        "page_kind": analysis.page_kind,
        "page_traits": analysis.page_traits or [],
        "normalized_url": site_url.normalized_url,
        "scoring_policy_version": "1",
        "limitations": [
            "Crawl observations are untrusted evidence and remain subject to "
            "Content grounding and claim validation."
        ],
    }


__all__ = ["get_aeo_readiness", "get_content_handoff"]
