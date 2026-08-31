"""PR2 Site Health measurement, Overview, and Content handoff DTOs."""

from __future__ import annotations

import uuid
from typing import Literal

from app.domain.site_health.api_schemas import (
    ClassificationState,
    DimensionApplicability,
    MeasurementState,
    SearchEligibility,
    _Model,
)


class ReadinessFailingCheckResponse(_Model):
    rule_id: str
    title: str
    observed_evidence: dict[str, object]
    expected_capability: str
    remediation: str
    content_addressable: bool


class ReadinessEvidencePageResponse(_Model):
    site_url_id: uuid.UUID
    source_analysis_id: uuid.UUID
    normalized_url: str
    failed_checks: list[ReadinessFailingCheckResponse]


class ReadinessCheckResponse(_Model):
    rule_id: str
    scope: Literal["page", "site", "cluster", "graph"]
    title: str
    remediation: str
    satisfied_count: int
    partial_count: int
    missing_count: int
    unknown_count: int
    not_applicable_count: int
    error_count: int
    failing_entity_count: int
    checkpoint_family: str
    content_addressable: bool


class ReadinessDimensionResponse(_Model):
    key: str
    label: str
    description: str
    dimension_applicability: DimensionApplicability
    dimension_measurement_state: MeasurementState
    score: float | None
    reason: str
    checkpoint_ids: list[str]
    determinate_checkpoint_ids: list[str]
    checkpoint_families: list[str]
    earned_points: float
    determinate_points: float
    expected_points: float
    satisfied_count: int
    partial_count: int
    missing_count: int
    unknown_count: int
    not_applicable_count: int
    error_count: int
    coverage: float | None
    checked_page_count: int
    failing_page_count: int
    checks: list[ReadinessCheckResponse]
    evidence_pages: list[ReadinessEvidencePageResponse]
    evidence_truncated: bool


class AeoReadinessResponse(_Model):
    state: MeasurementState
    crawl_id: uuid.UUID | None = None
    score: float | None
    coverage: float | None
    profile_version: str
    schema_contract_version: str
    scoring_version: str
    presentation_version: str
    analyzer_version: str
    source_analysis_ids: list[uuid.UUID]
    analysis_count: int
    affected_page_count: int
    dimensions: list[ReadinessDimensionResponse]
    limitations: list[str]


class AcquisitionEligibilityCheckpointResponse(_Model):
    checkpoint_id: Literal["acquisition.public_representation"]
    outcome: str
    reason: str
    source_task_id: uuid.UUID | None
    source_attempt_id: uuid.UUID | None
    source_artifact_id: uuid.UUID | None


class IndexEligibilityCheckpointResponse(_Model):
    checkpoint_id: Literal["search.indexability"]
    outcome: str
    reason: str
    source_analysis_id: uuid.UUID | None
    source_evaluation_id: uuid.UUID | None


class SearchPolicyEligibilityCheckpointResponse(_Model):
    checkpoint_id: Literal["search.crawler_access", "search.snippet_access"]
    outcome: str
    reason: str
    source_analysis_id: uuid.UUID | None
    source_evaluation_id: uuid.UUID | None


class EligibilityReasonResponse(_Model):
    site_url_id: uuid.UUID
    state: SearchEligibility
    checkpoints: list[
        AcquisitionEligibilityCheckpointResponse
        | IndexEligibilityCheckpointResponse
        | SearchPolicyEligibilityCheckpointResponse
    ]


class CrawlCoverageResponse(_Model):
    state: str
    evidence: dict[str, object]
    denominator_kind: Literal["selected_intended_public_urls"]


class OverviewDimensionResponse(_Model):
    key: str
    label: str
    description: str
    dimension_applicability: DimensionApplicability
    dimension_measurement_state: MeasurementState
    score: float | None
    coverage: float | None
    earned_points: float
    determinate_points: float
    expected_points: float
    determinate_checkpoint_ids: list[str]
    checkpoint_families: list[str]
    reason: str


class OverviewIssueResponse(_Model):
    rule_id: str
    finding_class: str
    severity: str
    category: str
    description: str
    remediation: str
    # Which site scores the rule feeds: `web_fundamentals` (presented as
    # Web Fundamentals) and/or `aeo_readiness`. Empty for a diagnostic rule.
    score_roles: list[str]
    affected_pages: int
    eligibility_blocker: bool
    impact_band: int
    impact_label: str


class WebFundamentalsFindingResponse(_Model):
    rule_id: str
    title: str
    remediation: str
    affected_pages: int
    source_evaluation_ids: list[uuid.UUID]


class WebFundamentalsAreaResponse(_Model):
    key: Literal["accessibility", "mobile", "security", "lab"]
    state: MeasurementState
    coverage: float | None
    passed_count: int
    missing_count: int
    unknown_count: int
    unavailable_count: int
    unavailable_checks: list[str]
    top_findings: list[WebFundamentalsFindingResponse]


class WebFundamentalsFieldDataResponse(_Model):
    state: Literal["unavailable"]
    reason: str
    lcp: float | None
    inp: float | None
    cls: float | None


class WebFundamentalsResponse(_Model):
    state: MeasurementState
    areas: list[WebFundamentalsAreaResponse]
    field_data: WebFundamentalsFieldDataResponse
    source_analysis_ids: list[uuid.UUID]
    source_artifact_ids: list[uuid.UUID]
    source_evaluation_ids: list[uuid.UUID]
    limitations: list[str]


class CohortCompositionResponse(_Model):
    added_page_kinds: list[str]
    removed_page_kinds: list[str]
    previous_page_count_by_kind: dict[str, int]
    current_page_count_by_kind: dict[str, int]


class OverviewTrendPointResponse(_Model):
    label: str
    value: float | None


class OverviewTrendResponse(_Model):
    state: Literal["unavailable", "measured"]
    reason: Literal[
        "no_comparable_snapshot",
        "comparable_snapshot",
        "cohort_composition_changed",
    ]
    metric: Literal["aeo_readiness_score"]
    series: list[OverviewTrendPointResponse]
    cohort_composition: CohortCompositionResponse


class OverviewChangeMetricResponse(_Model):
    key: Literal[
        "web_fundamentals_score",
        "web_fundamentals_coverage",
        "aeo_readiness_score",
        "aeo_measurement_coverage",
    ]
    label: str
    previous: float | None
    current: float | None
    delta: float | None
    direction: Literal["increased", "decreased", "unchanged", "unavailable"]


class OverviewChangeSummaryResponse(_Model):
    state: Literal["unavailable", "measured"]
    reason: Literal[
        "no_comparable_snapshot",
        "comparable_snapshot",
        "cohort_composition_changed",
    ]
    metrics: list[OverviewChangeMetricResponse]
    cohort_composition: CohortCompositionResponse


class SiteHealthOverviewResponse(_Model):
    project_id: uuid.UUID
    crawl_id: uuid.UUID
    snapshot_id: uuid.UUID
    search_eligibility: SearchEligibility
    eligibility_totals: dict[str, int]
    eligibility_reasons: list[EligibilityReasonResponse]
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    classified_page_count: int
    other_page_count: int
    classification_error_page_count: int
    classification_expected_page_count: int
    classification_coverage: float | None
    classification_state: ClassificationState
    classification_reason_groups: dict[str, int]
    classification_formula_version: str
    classification_source_analysis_ids: list[uuid.UUID]
    classification_source_artifact_ids: list[uuid.UUID]
    classification_source_task_ids: list[uuid.UUID]
    scored_page_kind_set: list[str]
    scored_page_count_by_kind: dict[str, int]
    crawl_coverage: CrawlCoverageResponse
    audited_page_count: int
    selected_page_count: int
    status_counts: dict[str, int]
    issue_count: int
    technical_defect_count: int
    technical_defect_affected_page_count: int
    aeo_readiness_gap_count: int
    aeo_readiness_gap_affected_page_count: int
    severity_counts: dict[str, int]
    category_counts: dict[str, int]
    measured_check_count: int
    expected_check_count: int
    aeo_dimensions: list[OverviewDimensionResponse]
    top_issues: list[OverviewIssueResponse]
    web_fundamentals: WebFundamentalsResponse
    trend: OverviewTrendResponse
    change_summary: OverviewChangeSummaryResponse
    limitations: list[str]


class SiteHealthContentHandoffResponse(_Model):
    project_id: uuid.UUID
    crawl_id: uuid.UUID
    site_url_id: uuid.UUID
    source_analysis_id: uuid.UUID
    dimension: str
    checkpoint_ids: list[str]
    finding_class: str
    observed_evidence: list[dict]
    expected_capability: list[str]
    remediation: list[str]
    page_kind: str
    page_traits: list[str]
    normalized_url: str
    scoring_policy_version: Literal["1"]
    limitations: list[str]
