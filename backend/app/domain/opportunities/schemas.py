# Opportunities API request/response DTOs.
#
# Every response model mirrors the checked-in strict frontend zod schema in
# ``frontend/lib/api/schemas.ts`` field-for-field so the two contracts can
# never drift (the frontend parses each payload with ``.strict()`` — an extra
# or missing key fails loud). The service builds these from persisted rows
# only; nothing here re-scores, fetches, or fabricates a metric.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.config.opportunities import (
    IMPLEMENTATION_EXPECTED_CHECKS_MAX,
    OPPORTUNITY_STATUSES,
)


class _Model(BaseModel):
    # Reject unknown keys on the way IN (request bodies) as loudly as the
    # frontend rejects them on the way OUT.
    model_config = ConfigDict(extra="forbid")


# =========================================================================
# Requests
# =========================================================================
class OpportunityStatusPatch(_Model):
    """PATCH body — ``status`` is the ONLY mutable field on an Opportunity."""

    status: str

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in OPPORTUNITY_STATUSES:
            raise ValueError(f"unknown opportunity status: {value!r}")
        return value


class OpportunityOrderUpdate(_Model):
    ordered_opportunity_ids: list[uuid.UUID]
    expected_version: int = Field(ge=0)


class OpportunityOrderResponse(_Model):
    version: int
    ordered_opportunity_ids: list[uuid.UUID]


class RecomputeRequest(_Model):
    """Optional recompute scope — omit both for the latest dashboard sources."""

    audit_id: uuid.UUID | None = None
    site_crawl_id: uuid.UUID | None = None


class SiteRuleExpectedCheck(_Model):
    kind: Literal["site_rule"]
    target_site_url_id: uuid.UUID | None = None
    rule_id: str = Field(min_length=1, max_length=64)
    expected_outcome: Literal["pass", "fail"]


class PageFactExpectedCheck(_Model):
    kind: Literal["page_fact"]
    target_site_url_id: uuid.UUID | None = None
    fact_key: str = Field(min_length=1, max_length=128)
    expected_value: Any


class MetricExpectedCheck(_Model):
    kind: Literal["visibility_metric", "traffic_metric"]
    metric: str = Field(min_length=1, max_length=128)
    direction: Literal["increase", "decrease", "equal"]
    expected_value: float
    tolerance: float = Field(default=0, ge=0)


ExpectedCheck = Annotated[
    SiteRuleExpectedCheck | PageFactExpectedCheck | MetricExpectedCheck,
    Field(discriminator="kind"),
]


class ImplementationEventCreate(_Model):
    opportunity_id: uuid.UUID
    target_site_url_ids: list[uuid.UUID] = Field(default_factory=list, max_length=64)
    generation_id: uuid.UUID | None = None
    declared_implemented_at: AwareDatetime
    expected_checks: list[ExpectedCheck] = Field(
        default_factory=list, max_length=IMPLEMENTATION_EXPECTED_CHECKS_MAX
    )


class VerificationEventView(_Model):
    id: uuid.UUID
    observation_kind: Literal["observed", "verified", "contradicted"]
    observed_at: datetime
    crawl_id: uuid.UUID | None
    audit_id: uuid.UUID | None
    source_analysis_ids: list[uuid.UUID]
    source_rule_evaluation_ids: list[uuid.UUID]
    source_metric_ids: list[uuid.UUID]
    result: dict[str, Any]
    verifier_version: str
    limitations: list[str]
    created_at: datetime


class ImplementationEventView(_Model):
    id: uuid.UUID
    project_id: uuid.UUID
    opportunity_id: uuid.UUID
    opportunity_snapshot_id: uuid.UUID
    target_site_url_ids: list[uuid.UUID]
    generation_id: uuid.UUID | None
    declared_implemented_at: datetime
    expected_checks: list[dict[str, Any]]
    state: Literal["declared", "observed", "verified", "contradicted"]
    limitations: list[str]
    verification_events: list[VerificationEventView]
    created_at: datetime


class ImplementationEventsPage(_Model):
    items: list[ImplementationEventView]
    next_cursor: str | None = None


class OpportunityGuidanceItem(_Model):
    id: uuid.UUID
    opportunity_id: uuid.UUID
    input_hash: str
    findings: list[str]
    recommendations: list[str]
    source_analysis_ids: list[uuid.UUID]
    source_issue_ids: list[uuid.UUID]
    source_metric_ids: list[uuid.UUID]
    analyzer_version: str
    rule_version: str
    formula_version: str
    generator_version: str
    prompt_version: str
    provider: str
    model: str
    created_at: str


class OpportunityGuidanceHistory(_Model):
    items: list[OpportunityGuidanceItem]


class OpportunityHistoryEvent(_Model):
    id: uuid.UUID
    status: str
    seen_at: str


class OpportunityHistoryGroup(_Model):
    rule_id: str
    target_key: str
    title: str
    current_state: str
    transition: str
    occurrence_count: int
    first_seen: str
    last_seen: str
    timeline: list[OpportunityHistoryEvent]


class OpportunityHistoryResponse(_Model):
    items: list[OpportunityHistoryGroup]
    since_previous: dict[str, int]


# =========================================================================
# Responses
# =========================================================================
class OpportunityItem(_Model):
    """One live opportunity row as rendered by the priority-sorted catalog."""

    id: uuid.UUID
    project_id: uuid.UUID
    rule_id: str
    opportunity_type: str
    severity: str
    priority_score: float
    title: str
    target_key: str
    target_prompt_id: uuid.UUID | None
    target_url: str | None
    target_theme: str | None
    # Backend-owned target presentation (url / frozen prompt text / humanized
    # theme / frozen product name); null when nothing user-facing exists.
    target_label: str | None
    status: str
    system_rank: int = 0
    display_rank: int = 0
    order_source: Literal["system", "manual"] = "system"
    priority_factors: dict[str, str | float] = Field(default_factory=dict)
    evidence_summary: dict[str, int | list[str]] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class OpportunityDetail(OpportunityItem):
    """Full evidence bundle + provenance for one opportunity."""

    remediation: str
    evidence: dict
    source_analysis_ids: list[str]
    source_issue_ids: list[str]
    source_metric_ids: list[str]
    source_traffic_ids: list[str]
    analyzer_version: str
    rule_version: str
    formula_version: str
    content_handoff: dict[str, Any]
    linked_generations: list[dict[str, Any]]
    superseded_by_id: uuid.UUID | None
    superseded_at: str | None


class OpportunitiesPage(_Model):
    items: list[OpportunityItem]
    next_cursor: str | None


class OpportunitySummary(_Model):
    """Latest recompute snapshot projection (``computed=false`` when none)."""

    computed: bool
    run_id: uuid.UUID | None
    audit_id: uuid.UUID | None
    site_crawl_id: uuid.UUID | None
    demand_snapshot_id: uuid.UUID | None
    demand_source_revision: str | None
    coverage: dict[str, Any]
    limitations: list[str]
    source_mix: dict[str, Any]
    action_path_mix: dict[str, Any]
    domain_rollups: list[dict[str, Any]]
    counts_by_type: dict[str, int]
    counts_by_severity: dict[str, int]
    counts_by_status: dict[str, int]
    total_count: int
    median_priority: float | None
    analyzer_version: str
    rule_version: str
    formula_version: str
    computed_at: str | None
    # Read-time freshness (no persisted marker): newest usable audit/crawl
    # evidence timestamp, and whether it post-dates the latest snapshot.
    evidence_updated_at: str | None
    stale: bool
    activation_state: Literal[
        "waiting_for_evidence", "queued", "refreshing", "ready", "delayed"
    ]


class RecomputeResponse(_Model):
    """The immutable snapshot written by one recompute run."""

    id: uuid.UUID
    run_id: uuid.UUID
    audit_id: uuid.UUID | None
    site_crawl_id: uuid.UUID | None
    demand_snapshot_id: uuid.UUID | None
    demand_source_revision: str | None
    coverage: dict[str, Any]
    limitations: list[str]
    source_mix: dict[str, Any]
    action_path_mix: dict[str, Any]
    domain_rollups: list[dict[str, Any]]
    counts_by_type: dict[str, int]
    counts_by_severity: dict[str, int]
    counts_by_status: dict[str, int]
    total_count: int
    median_priority: float | None
    analyzer_version: str
    rule_version: str
    formula_version: str
    created_at: str
