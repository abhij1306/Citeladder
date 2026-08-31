"""Persistable Web Fundamentals projection built from stored evaluations."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.site_health.rules import rule_for
from app.core.config.site_health_contracts import (
    RULE_OUTCOME_MISSING,
    RULE_OUTCOME_NOT_APPLICABLE,
    RULE_OUTCOME_SATISFIED,
)
from app.core.config.site_health_measurement import (
    MEASUREMENT_STATE_LIMITED,
    MEASUREMENT_STATE_MEASURED,
    MEASUREMENT_STATE_NOT_MEASURED,
    WEB_FUNDAMENTALS_AREAS,
)
from app.models.site_health.analysis import SiteRuleEvaluation


def _area_state(rows: list[SiteRuleEvaluation]) -> tuple[str, float | None]:
    applicable = [row for row in rows if row.outcome != RULE_OUTCOME_NOT_APPLICABLE]
    determinate = [
        row
        for row in applicable
        if row.outcome in (RULE_OUTCOME_SATISFIED, RULE_OUTCOME_MISSING)
    ]
    expected = len(applicable)
    coverage = round(len(determinate) / expected, 4) if expected else None
    if expected == 0:
        return MEASUREMENT_STATE_NOT_MEASURED, coverage
    if len(determinate) == expected:
        return MEASUREMENT_STATE_MEASURED, coverage
    return MEASUREMENT_STATE_LIMITED, coverage


def _findings(rows: list[SiteRuleEvaluation]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for row in rows:
        if row.outcome != RULE_OUTCOME_MISSING:
            continue
        rule = rule_for(row.rule_id)
        finding = grouped.setdefault(
            row.rule_id,
            {
                "rule_id": row.rule_id,
                "title": rule.display_label if rule else row.rule_id,
                "remediation": rule.remediation if rule else "",
                "affected_pages": 0,
                "source_evaluation_ids": [],
            },
        )
        finding["affected_pages"] += 1
        finding["source_evaluation_ids"].append(str(row.id))
    return list(grouped.values())[:5]


def _area_row(area: str, rows: list[SiteRuleEvaluation]) -> dict:
    state, coverage = _area_state(rows)
    return {
        "key": area,
        "state": state,
        "coverage": coverage,
        "passed_count": sum(row.outcome == RULE_OUTCOME_SATISFIED for row in rows),
        "missing_count": sum(row.outcome == RULE_OUTCOME_MISSING for row in rows),
        "unknown_count": sum(row.outcome == "unknown" for row in rows),
        "unavailable_count": sum(row.outcome == "unavailable" for row in rows),
        "unavailable_checks": [],
        "top_findings": _findings(rows),
    }


def _overall_state(areas: list[dict]) -> str:
    measured = [row for row in areas if row["state"] != MEASUREMENT_STATE_NOT_MEASURED]
    if not measured:
        return MEASUREMENT_STATE_NOT_MEASURED
    if all(row["state"] == MEASUREMENT_STATE_MEASURED for row in measured):
        return MEASUREMENT_STATE_MEASURED
    return MEASUREMENT_STATE_LIMITED


async def web_fundamentals_projection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    analysis_ids: list[uuid.UUID],
    artifact_ids: list[uuid.UUID],
) -> dict:
    """Build the HTTP-evidence projection without acquisition or repair."""
    evaluations = (
        list(
            await session.scalars(
                select(SiteRuleEvaluation)
                .where(
                    SiteRuleEvaluation.workspace_id == workspace_id,
                    SiteRuleEvaluation.analysis_id.in_(analysis_ids),
                )
                .order_by(SiteRuleEvaluation.id)
            )
        )
        if analysis_ids
        else []
    )
    by_area: dict[str, list[SiteRuleEvaluation]] = {
        area: [] for area in WEB_FUNDAMENTALS_AREAS
    }
    for evaluation in evaluations:
        rule = rule_for(evaluation.rule_id)
        if rule is not None and rule.web_fundamentals_area in by_area:
            by_area[rule.web_fundamentals_area].append(evaluation)
    areas = [_area_row(area, by_area[area]) for area in WEB_FUNDAMENTALS_AREAS]
    has_http_evidence = any(by_area.values())
    return {
        "state": (
            _overall_state(areas)
            if has_http_evidence
            else MEASUREMENT_STATE_NOT_MEASURED
        ),
        "areas": areas,
        "field_data": {
            "state": "unavailable",
            "reason": "provider_not_configured",
            "lcp": None,
            "inp": None,
            "cls": None,
        },
        "source_analysis_ids": [str(value) for value in analysis_ids],
        "source_artifact_ids": [str(value) for value in artifact_ids],
        "source_evaluation_ids": [
            str(row.id) for rows in by_area.values() for row in rows
        ],
        "limitations": [],
    }
