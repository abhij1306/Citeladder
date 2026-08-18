"""Persisted Opportunity row projections and deterministic presentation."""

from __future__ import annotations

import json

from app.domain.opportunities.common import _iso
from app.models.opportunity import Opportunity, OpportunityOrder


def _humanize_theme(theme: str) -> str:
    words = " ".join(theme.replace("_", " ").replace("-", " ").split()).strip()
    if not words:
        return ""
    return f"{words[:1].upper()}{words[1:]} theme"


def _target_label(row: Opportunity) -> str | None:
    """Return the user-facing label from persisted frozen evidence only."""
    evidence = row.evidence or {}
    prompt_text = str(evidence.get("prompt_text") or "").strip()
    product_name = str(evidence.get("product_name") or "").strip()
    theme_label = _humanize_theme(row.target_theme or "")
    return row.target_url or prompt_text or theme_label or product_name or None


def _stable_key(row: Opportunity) -> str:
    return json.dumps(
        [row.rule_id, row.target_key], ensure_ascii=False, separators=(",", ":")
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


def project_item(
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


def ordered_items(
    rows: list[Opportunity], order: OpportunityOrder | None
) -> list[dict]:
    system_rank = {row.id: index for index, row in enumerate(rows, start=1)}
    if order is None or not order.ordered_keys:
        return [
            project_item(row, system_rank=index, display_rank=index)
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
        project_item(
            row,
            system_rank=system_rank[row.id],
            display_rank=index,
            order_source="manual" if _stable_key(row) in manual_rank else "system",
        )
        for index, row in enumerate(ordered, start=1)
    ]


def project_detail(row: Opportunity) -> dict:
    return {
        **project_item(row),
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


def project_export_row(row: Opportunity) -> dict:
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
