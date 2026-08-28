"""Persisted Opportunity snapshot read projection."""

from __future__ import annotations

from app.analysis.opportunities.source_mix import empty_source_projection
from app.models.opportunity import OpportunitySnapshot


def project_snapshot(snapshot: OpportunitySnapshot) -> dict:
    """Project one immutable snapshot without recomputing any metric."""
    return {
        "id": snapshot.id,
        "run_id": snapshot.run_id,
        "audit_id": snapshot.audit_id,
        "site_crawl_id": snapshot.site_crawl_id,
        "demand_snapshot_id": snapshot.demand_snapshot_id,
        "demand_source_revision": snapshot.demand_source_revision,
        "coverage": snapshot.coverage or {},
        "limitations": list(snapshot.limitations or []),
        "source_mix": snapshot.source_mix or empty_source_projection(),
        "action_path_mix": snapshot.action_path_mix or empty_source_projection(),
        "domain_rollups": list(snapshot.domain_rollups or []),
        "counts_by_type": snapshot.counts_by_type or {},
        "counts_by_severity": snapshot.counts_by_severity or {},
        "counts_by_status": snapshot.counts_by_status or {},
        "total_count": snapshot.total_count,
        "median_priority": snapshot.median_priority,
        "analyzer_version": snapshot.analyzer_version,
        "rule_version": snapshot.rule_version,
        "formula_version": snapshot.formula_version,
        "created_at": snapshot.created_at.isoformat(),
    }
