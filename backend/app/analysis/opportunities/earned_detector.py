"""Grouped earned-source Opportunity detector over a persisted source projection."""

from __future__ import annotations

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.opportunities import (
    ACTION_PATH_EARNED,
    OPPORTUNITY_RULES_BY_ID,
    RULE_EARNED_SOURCE_RECURS,
)
from app.core.config.source_patterns import (
    CONTENT_HANDOFF_TEMPLATE_VERSION,
    SOURCE_MIX_PROJECTION_VERSION,
    SOURCE_TAXONOMY_VERSION,
)


def detect_earned_source_opportunities(rollups: list[dict]) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_EARNED_SOURCE_RECURS]
    if not rule.enabled:
        return []
    return [_earned_hit(rule.rule_id, row) for row in rollups if row.get("actionable")]


def _earned_hit(rule_id: str, row: dict) -> DetectorHit:
    source_class = str(row["source_class"])
    domain = str(row["canonical_domain"])
    citations: list[dict] = list(row.get("representative_citations") or [])
    representative: dict = next(iter(citations), {})
    themes: list[str] = list(row.get("themes") or [])
    target_theme: str | None = next(iter(themes), None)
    content_handoff = {
        "pathway": ACTION_PATH_EARNED,
        "source_class": source_class,
        "canonical_domain": domain,
        "suggested_role": row.get("suggested_role"),
        "suggested_skill_id": row.get("suggested_skill_id"),
        "task_seed": f"Prepare a transparent, human-led contribution for {domain}.",
        "target_url": representative.get("url"),
        "target_theme": target_theme,
        "representative_citations": citations,
        "affected_prompt_indices": row.get("prompt_indices") or [],
        "affected_themes": themes,
        "observed_competitors": row.get("competitors") or [],
        "coverage": {
            "numerator": row.get("usage_numerator"),
            "denominator": row.get("usage_denominator"),
            "percentage": row.get("usage_percentage"),
        },
        "limitations": [
            "Observed on cited pages only; domain-wide brand presence was not "
            "assessed.",
            "Inclusion is a human decision and does not guarantee a later engine "
            "citation.",
        ],
        "truncated": bool(row.get("truncated") or row.get("projection_truncated")),
        "source_analysis_ids": row.get("analysis_ids") or [],
        "projection_version": SOURCE_MIX_PROJECTION_VERSION,
        "taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "handoff_template_version": CONTENT_HANDOFF_TEMPLATE_VERSION,
    }
    return DetectorHit(
        rule_id=rule_id,
        target_key=f"earned-source:{source_class}:{domain}",
        target_prompt_id=None,
        target_url=None,
        target_theme=target_theme,
        evidence={
            "content_handoff": content_handoff,
            "priority_factors": {
                "source_usage_factor": row["usage_factor"],
                "competitor_cooccurrence_factor": row["competitor_cooccurrence_factor"],
            },
        },
        source_analysis_ids=tuple(row.get("analysis_ids") or []),
        source_issue_ids=(),
        source_metric_ids=(),
        value_factor=float(row["usage_factor"]),
        gap_factor=float(row["competitor_cooccurrence_factor"]),
    )
