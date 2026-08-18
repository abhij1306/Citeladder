from __future__ import annotations

import statistics
import uuid

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.opportunities import (
    ANALYZER_VERSION,
    FORMULA_VERSION,
    OPPORTUNITY_SEVERITIES,
    OPPORTUNITY_STATUSES,
    OPPORTUNITY_TYPES,
    RULE_VERSION,
)
from app.domain.opportunities.site_coverage import site_coverage
from app.models.audit import Audit
from app.models.demand import DemandSnapshot
from app.models.opportunity import Opportunity, OpportunitySnapshot
from app.models.site_health.crawl import SiteCrawl


def build_snapshot(
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit: Audit | None,
    crawl: SiteCrawl | None,
    demand_snapshot: DemandSnapshot | None,
    new_rows: list[Opportunity],
    scored: list[tuple[DetectorHit, float]],
) -> OpportunitySnapshot:
    """Aggregate one immutable recompute snapshot over the new live set."""
    counts_by_type = {name: 0 for name in sorted(OPPORTUNITY_TYPES)}
    counts_by_severity = {name: 0 for name in sorted(OPPORTUNITY_SEVERITIES)}
    counts_by_status = {name: 0 for name in sorted(OPPORTUNITY_STATUSES)}
    for row in new_rows:
        counts_by_type[row.opportunity_type] += 1
        counts_by_severity[row.severity] += 1
        counts_by_status[row.status] += 1
    scores = sorted(score for _hit, score in scored)
    coverage, limitations = site_coverage(crawl)
    return OpportunitySnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=uuid.uuid4(),
        audit_id=audit.id if audit is not None else None,
        site_crawl_id=crawl.id if crawl is not None else None,
        demand_snapshot_id=demand_snapshot.id if demand_snapshot is not None else None,
        demand_source_revision=(
            demand_snapshot.source_hash if demand_snapshot is not None else None
        ),
        coverage=coverage or None,
        limitations=limitations,
        counts_by_type=counts_by_type,
        counts_by_severity=counts_by_severity,
        counts_by_status=counts_by_status,
        total_count=len(new_rows),
        median_priority=round(statistics.median(scores), 1) if scores else None,
        analyzer_version=ANALYZER_VERSION,
        rule_version=RULE_VERSION,
        formula_version=FORMULA_VERSION,
        source_analysis_ids=_source_ids(scored, "source_analysis_ids"),
        source_issue_ids=_source_ids(scored, "source_issue_ids"),
    )


def _source_ids(scored: list[tuple[DetectorHit, float]], attribute: str) -> list[str]:
    return sorted({sid for hit, _score in scored for sid in getattr(hit, attribute)})
