"""PR2 Site Health measurement, Overview, and Content handoff DTOs."""

from __future__ import annotations

import uuid
from typing import Literal

from app.domain.site_health.api_schemas import _Model

MeasurementState = Literal["measured", "limited_evidence", "not_measured", "excluded"]
DimensionApplicability = Literal["applicable", "not_applicable", "unresolved"]


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
    title: str
    remediation: str
    satisfied_count: int
    partial_count: int
    missing_count: int
    unknown_count: int
    unavailable_count: int
    conflicting_count: int
    not_applicable_count: int
    error_count: int
    failing_page_count: int
    checkpoint_family: str
    readiness_weight: float
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
    unavailable_count: int
    conflicting_count: int
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


class SiteHealthOverviewResponse(_Model):
    project_id: uuid.UUID
    crawl_id: uuid.UUID
    snapshot_id: uuid.UUID
    search_eligibility: str
    eligibility_totals: dict[str, int]
    eligibility_reasons: list[dict]
    technical_integrity_score: float | None
    technical_integrity_coverage: float | None
    technical_integrity_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    crawl_coverage: dict
    audited_page_count: int
    selected_page_count: int
    status_counts: dict[str, int]
    aeo_dimensions: list[dict]
    top_issues: list[dict]
    web_fundamentals: dict
    trend: dict
    change_summary: dict
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
