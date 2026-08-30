"""Immutable AEO Readiness read model and bounded Content handoff evidence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_PARTIAL,
    SCORING_VERSION,
)
from app.core.config.site_health_measurement import (
    PRESENTATION_VERSION,
    PROFILE_VERSION,
    SCHEMA_CONTRACT_VERSION,
)
from app.core.config.site_health_rules import SITE_HEALTH_RULES_BY_ID
from app.domain.site_health.aeo_readiness_projection import rule_guidance
from app.domain.site_health.service.common import (
    SiteHealthNotFoundError,
    resolve_usable_crawl,
)
from app.models.site_health.analysis import SitePageAnalysis, SiteRuleEvaluation
from app.models.site_health.snapshot import SiteHealthSnapshot
from app.models.site_health.urls import SiteUrl


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


async def get_aeo_readiness(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    crawl_id: uuid.UUID | None = None,
) -> dict:
    """Return only the immutable diagnostic frozen with the selected snapshot."""
    crawl = await resolve_usable_crawl(
        session, workspace_id=workspace_id, project_id=project_id, crawl_id=crawl_id
    )
    if crawl is None:
        return _unavailable()
    descriptor = await session.scalar(
        select(SiteHealthSnapshot.aeo_readiness_diagnostic).where(
            SiteHealthSnapshot.workspace_id == workspace_id,
            SiteHealthSnapshot.project_id == project_id,
            SiteHealthSnapshot.crawl_id == crawl.id,
        )
    )
    if isinstance(descriptor, dict) and descriptor:
        return descriptor
    return _unavailable(crawl.id)


def _allowed_content_checkpoints(dimension: str, checkpoint_ids: list[str]) -> set[str]:
    allowed = {
        checkpoint_id
        for checkpoint_id in checkpoint_ids
        if checkpoint_id in SITE_HEALTH_RULES_BY_ID
        and SITE_HEALTH_RULES_BY_ID[checkpoint_id].content_addressable
        and SITE_HEALTH_RULES_BY_ID[checkpoint_id].readiness_dimension == dimension
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
                    (RULE_OUTCOME_MISSING, RULE_OUTCOME_PARTIAL)
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
        "expected_capability": [rule_guidance(row.rule_id)[0] for row in evaluations],
        "remediation": [rule_guidance(row.rule_id)[1] for row in evaluations],
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
