# Site Health API request/response DTOs (Slice 6).
#
# Every response model mirrors the checked-in strict frontend zod schema in
# ``frontend/lib/api/schemas.ts`` field-for-field so the two contracts can never
# drift (the frontend parses each payload with ``.strict()`` — an extra or
# missing key fails loud). The API layer builds these DTOs from persisted rows
# only (the service owns the projection rules); nothing here re-scores, fetches,
# or fabricates a metric. Count-bearing fields the backend redacts for a Free
# workspace are ``None`` (never a number), never leaking a full-site total.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.site_health.phase import SiteHealthPhase

# Presentation-status literals (superset of the persisted page-analysis states,
# adding the mockup-facing `not_selected` / `error` / `blocked` / `cancelled`).
PageAnalysisStatus = Literal[
    "not_selected",
    "pending",
    "running",
    "completed",
    "partially_completed",
    "failed",
    "error",
    "blocked",
    "cancelled",
]
AccessMode = Literal["sample", "full", "unresolved"]
IssueSeverity = Literal["critical", "high", "medium", "low", "info"]
FindingClass = Literal["defect", "advisory", "diagnostic"]
IssueDimension = Literal["technical", "aeo"]
SiteUrlSource = Literal["root", "link", "sitemap", "redirect"]
SelectionSource = Literal["user", "free_sample", "bootstrap"]
MeasurementState = Literal["measured", "limited_evidence", "not_measured", "excluded"]
ClassificationState = Literal["complete", "partial", "not_measured"]
DimensionApplicability = Literal["applicable", "not_applicable"]
SearchEligibility = Literal["eligible", "blocked", "unknown", "excluded"]


class _Model(BaseModel):
    # Reject unknown keys on the way IN (request bodies) as loudly as the
    # frontend rejects them on the way OUT.
    model_config = ConfigDict(extra="forbid")


# =========================================================================
# Requests
# =========================================================================
class CreateCrawlRequest(_Model):
    project_id: uuid.UUID
    include_globs: list[str] | None = None
    exclude_globs: list[str] | None = None
    seed: str | None = None
    input_mode: Literal["auto", "exact_urls", "discovery_seeds"] | None = None
    requested_page_limit: int | None = Field(default=None, ge=1)
    discovery_count: int | None = Field(default=None, ge=1)
    seed_urls: list[str] | None = None
    page_kinds: list[str] | None = None


class UrlPreviewRequest(_Model):
    project_id: uuid.UUID
    content: str | list[str] | dict
    input_format: Literal["text", "csv", "json"] = "text"
    include_globs: list[str] | None = None
    exclude_globs: list[str] | None = None


class UrlPreviewRow(_Model):
    row: int
    input: str
    accepted: bool
    canonical_url: str | None
    reason_code: str | None
    value_kind: str
    priority: int


class UrlPreviewResponse(_Model):
    items: list[UrlPreviewRow]
    truncated: bool
    counts: dict[str, int]
    policy_version: str


class ReplaceMonitoredRequest(_Model):
    site_url_ids: list[uuid.UUID]
    expected_selection_version: int


class BulkSelectMonitoredRequest(_Model):
    """Server-resolved bulk selection of monitored URLs.

    ``first_n`` selects the first ``count`` admitted URLs of ``crawl_id`` in
    the inventory's ``(normalized_url, id)`` order (``count`` required);
    ``all`` selects every admitted URL; ``none`` clears the selection.
    ``query`` applies the same substring filter as the inventory listing, so
    "select first N" matches exactly what a filtered inventory shows.
    """

    mode: Literal["first_n", "all", "none"]
    crawl_id: uuid.UUID
    count: int | None = None
    query: str | None = None
    expected_selection_version: int


class RerunPageResponse(_Model):
    """Identity/status returned by the per-page rerun (202) so the frontend can

    poll the FRESH rerun. When ``created_new_crawl`` is ``True`` the rerun runs
    in a NEW crawl (the source crawl was terminal) and the client should poll
    ``crawl_id`` (not the crawl it came from). ``analysis_status`` is the fresh
    crawl's analysis sub-state at enqueue time (``pending`` for a new crawl) so
    polling starts from a known non-terminal baseline.
    """

    crawl_id: uuid.UUID
    site_url_id: uuid.UUID
    task_id: uuid.UUID
    created_new_crawl: bool
    analysis_status: str


# =========================================================================
# Entitlement
# =========================================================================
class SiteHealthEntitlementResponse(_Model):
    """Neutral Site Health entitlement view (no commercial vocabulary).

    Sourced from the account's ``ResolvedEntitlement`` plus the workspace
    runtime projection; ``unresolved`` always carries a zero monitored limit,
    the neutral sample limit, no disclosure, and empty grant IDs.
    """

    workspace_id: uuid.UUID
    access_mode: AccessMode
    sample_url_limit: int
    monitored_url_limit: int
    count_disclosure: bool
    resolver_status: Literal["resolved", "entitlement_unresolved"]
    registry_revision: str
    entitlement_lifecycle_version: int
    valid_until: datetime | None
    contributing_grant_ids: list[uuid.UUID]
    advanced_controls_enabled: bool


# =========================================================================
# Crawl
# =========================================================================
class ScoreSummaryByType(_Model):
    """One page type's rollup inside ``score_summary.by_page_kind`` (v2 P1)."""

    analyzed_count: int
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    aeo_measurement_reason: str


class ScoreSummary(_Model):
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    search_eligibility: SearchEligibility
    selected_count: int
    analyzed_count: int
    issue_count: int
    scoring_version: str
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
    # Per-page-type breakdown (only types with >= 1 analyzed URL appear).
    by_page_kind: dict[str, ScoreSummaryByType] = {}


class CrawlFailureSummary(_Model):
    # Why a crawl failed (SH-2/SH-5 — B1): stable machine ``code`` + human
    # ``message`` + the terminal HTTP status / attempt count when present.
    # Projected from the root discover task's terminal fetch attempts — the
    # same shape that rides the ``crawl.failed`` event payload.
    code: str
    message: str
    attempts: int | None
    status_code: int | None
    target_url: str


class CrawlActivity(_Model):
    state: Literal["working", "waiting", "stalled", "terminal"]
    reason: Literal[
        "active_work",
        "host_gate",
        "retry_backoff",
        "expired_lease",
        "terminal",
    ]
    queue_depth: int
    next_available_at: str | None


class CrawlCounters(_Model):
    discovered: int | None
    selected: int
    queued: int
    running: int
    analyzed: int
    errors: int
    blocked: int
    failure_breakdown: dict[
        Literal["robots_denied", "http_4xx", "http_5xx", "timeout"], int
    ]
    activity: CrawlActivity
    by_page_kind: dict[str, int] = {}


class CrawlResponse(_Model):
    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID
    profile_id: uuid.UUID
    status: str
    discovery_status: str
    analysis_status: str
    root_url: str
    sample_mode: bool
    seed: str
    inventory_complete: bool
    # Why a PARTIALLY_COMPLETED crawl is partial: URLs that could not be
    # fetched during discovery, analyses that fell short, or both. Empty on
    # every other status. Unreachable links are routine on a real site and are
    # NOT an analysis failure, so the two can never share one message.
    partial_reason: Literal[
        "",
        "discovery_incomplete",
        "analysis_incomplete",
        "discovery_and_analysis_incomplete",
    ] = ""
    visible_url_count: int
    analyzed_count: int
    failed_count: int
    discovery_requested_count: int
    analysis_requested_count: int
    counters: CrawlCounters
    # Redactable count fields (Free → None, never a number).
    discovered_count: int | None = None
    total_url_count: int | None = None
    has_more_site_urls: bool | None = None
    score_summary: ScoreSummary | None = None
    # B1: present only on a failed crawl whose root fetch failed; ``None`` on
    # healthy/partial crawls and on list projections (N+1 avoidance).
    failure_summary: CrawlFailureSummary | None = None
    # v2 P2: bounded site-level facts (robots AI stance / llms.txt / sitemap
    # files); no discovered totals inside, so it is never redacted.
    site_facts: dict | None = None
    extractor_version: str
    analyzer_version: str
    rule_version: str
    scoring_version: str
    error_message: str
    created_at: str
    updated_at: str
    started_at: str | None
    completed_at: str | None


class CrawlListPage(_Model):
    items: list[CrawlResponse]
    next_cursor: str | None


# =========================================================================
# Inventory
# =========================================================================
class InventoryRow(_Model):
    site_url_id: uuid.UUID
    normalized_url: str
    display_url: str
    title: str | None
    content_type: str | None
    source: SiteUrlSource | None
    depth: int | None
    monitored: bool
    first_seen_at: str | None
    last_seen_at: str | None
    issue_count: int | None
    # Generic structural page kind; None until the URL has an analysis.
    page_kind: str | None
    # Same bounded role projection PageSummary carries. Inventory rows are
    # built by the same row builder, so without these the extra keys would fail
    # ``_Model`` validation for any packed analysis.
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    aeo_measurement_reason: str
    main_content_indexable: bool | None
    last_audited: str | None


class InventoryPage(_Model):
    items: list[InventoryRow]
    next_cursor: str | None


# =========================================================================
# Monitored set
# =========================================================================
class MonitoredQuota(_Model):
    used: int
    limit: int


class MonitoredUrl(_Model):
    site_url_id: uuid.UUID
    normalized_url: str
    display_url: str
    title: str | None
    active: bool
    selection_source: SelectionSource
    selected_at: str | None
    deselected_at: str | None


class MonitoredUrlsResponse(_Model):
    project_id: uuid.UUID
    selection_version: int
    monitored_urls: list[MonitoredUrl]
    quota: MonitoredQuota


# =========================================================================
# Pages
# =========================================================================
class PageSummary(_Model):
    site_url_id: uuid.UUID
    crawl_id: uuid.UUID
    normalized_url: str
    display_url: str
    title: str | None
    monitored: bool
    analysis_status: PageAnalysisStatus
    error_code: str
    issue_count: int | None
    # Generic structural page kind; None until the URL has an analysis.
    page_kind: str | None
    # Bounded role projection for list rows: the id, why it abstained, and the
    # corpus disposition. Full evidence/alternatives/conflicts stay on the
    # detail projection so a page of rows never carries kilobytes of evidence.
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    aeo_measurement_reason: str
    main_content_indexable: bool | None
    last_audited: str | None
    # Persisted internal-link projection (PR2). None means UNMEASURED — this
    # crawl wrote no metric row for the URL — never "nothing links here".
    inbound_count: int | None = None
    main_content_inbound_count: int | None = None
    depth_from_home: int | None = None


class RootError(_Model):
    # One REAL root-target network call the crawl lost (SH-4 — B3). These are
    # deliberately NOT page rows: a root failure never creates a ``SiteUrl``,
    # so there is no ``site_url_id`` and no PageDetail link — the Errors &
    # Blocked tab renders them as a distinct non-clickable block.
    method: str
    target: str
    outcome: str
    error_code: str
    status_code: int | None
    latency_ms: int | None


class PagesPage(_Model):
    items: list[PageSummary]
    next_cursor: str | None
    # B3: terminal root-target fetch failures, empty for any crawl whose root
    # fetch succeeded (including retried-then-succeeded). Never enters the
    # keyset pagination above.
    root_errors: list[RootError] = []


class PageFacts(_Model):
    title: str | None
    meta_description: str | None
    canonical_url: str | None
    robots_directives: list[str]
    h1_count: int
    heading_count: int
    image_count: int
    image_missing_alt_count: int
    word_count: int
    internal_link_count: int
    external_link_count: int
    structured_data_types: list[str]


class DeliveryFacts(_Model):
    field_cwv_available: Literal[False] = False
    status_code: int | None
    ttfb_ms: float | None
    wire_bytes: int | None
    decoded_bytes: int | None
    html_bytes: int | None
    http_version: str | None
    compression: str | None
    cache_control: str | None
    blocking_resource_count: int | None


class SiteIssue(_Model):
    id: uuid.UUID
    crawl_id: uuid.UUID
    rule_id: str
    # The page TYPES this group affects, sorted. A group can legitimately span
    # several (a title rule applies everywhere) or exactly one (a Product/offers
    # rule only reaches product pages) — which is the distinction the issue list
    # exists to make visible.
    page_kinds: list[str] = []
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    finding_class: FindingClass
    title: str
    description: str
    remediation: str
    affected_url_count: int
    analyzer_version: str
    rule_version: str
    created_at: str


RuleOutcome = Literal[
    "satisfied",
    "partial",
    "missing",
    "unknown",
    "unavailable",
    "conflicting",
    "error",
    "not_applicable",
    "excluded",
]


class RuleEvaluation(_Model):
    id: uuid.UUID
    rule_id: str
    title: str
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    finding_class: FindingClass
    outcome: RuleOutcome
    display_applicability: bool
    score_applicability: bool
    expected_profile_membership: bool
    reason_code: str
    score_roles: list[str]
    checkpoint_family: str
    readiness_dimension: str
    readiness_weight: float
    weight: float
    evidence: dict[str, object]
    analyzer_version: str
    rule_version: str
    created_at: str


class LinkNeighbour(_Model):
    """One bounded top-N neighbour of a page in the crawl's link graph."""

    site_url_id: uuid.UUID | None = None
    url: str
    anchor_count: int
    main_content: bool
    nofollow: bool
    rel: list[str] = []


class InternalLinks(_Model):
    """A page's persisted internal-link metrics and bounded neighbours.

    ``depth_from_home`` is shortest-path over ALL followable internal links
    (navigation links are real clicks); ``main_content_inbound_count`` is the
    separate "genuinely linked, or only in the menu" signal, derived from the
    per-anchor DOM region — never from link frequency.
    """

    inbound_count: int
    outbound_count: int
    main_content_inbound_count: int
    main_content_outbound_count: int
    nofollow_inbound_count: int
    depth_from_home: int | None
    source_page_count: int
    top_inbound: list[LinkNeighbour]
    top_outbound: list[LinkNeighbour]
    formula_version: str


class PageDetail(_Model):
    site_url_id: uuid.UUID
    crawl_id: uuid.UUID
    normalized_url: str
    display_url: str
    title: str | None
    analysis_status: PageAnalysisStatus
    error_code: str
    field_cwv_available: Literal[False] = False
    # Generic structural page kind; None until the URL has an analysis.
    page_kind: str | None
    # Bounded classifier evidence behind ``page_kind`` (ranked signals,
    # confidence, schema suggestion) for the "why this kind?" disclosure;
    # None until the URL has an analysis.
    page_kind_evidence: dict | None = None
    # Observed page traits, independent of ``page_kind``: a product page with
    # an FAQ block carries both. Empty list once analyzed and nothing was
    # observed; None until the URL has an analysis.
    page_traits: list[str] | None = None
    # Pack-governed industry role. None when the pack classifier never ran
    # (unpacked project, or an analysis written before the pack was frozen).
    web_fundamentals_score: float | None
    web_fundamentals_coverage: float | None
    web_fundamentals_state: MeasurementState
    aeo_readiness_score: float | None
    aeo_measurement_coverage: float | None
    aeo_measurement_state: MeasurementState
    aeo_measurement_reason: str
    main_content_indexable: bool | None
    issue_count: int | None
    last_audited: str | None
    facts: PageFacts
    delivery: DeliveryFacts
    # None when this crawl persisted no link metric for the URL.
    internal_links: InternalLinks | None = None
    issues: list[SiteIssue]
    evaluations: list[RuleEvaluation]
    artifact_id: uuid.UUID | None
    extractor_version: str
    analyzer_version: str
    rule_version: str
    scoring_version: str


# =========================================================================
# Issues (grouped) + detail + history
# =========================================================================
class AffectedUrl(_Model):
    site_url_id: uuid.UUID
    normalized_url: str
    display_url: str
    title: str | None
    # Classified page type of the affected analysis (v2 P1; None when the
    # URL has no classified analysis).
    page_kind: str | None = None


class IssuesSummary(_Model):
    issue_count: int
    defect_issue_type_count: int
    advisory_issue_type_count: int
    occurrence_count: int
    severity_counts: dict[str, int]
    dimension_counts: dict[str, int]
    affected_url_count: int
    monitored_affected_url_count: int


class SiteIssuesPage(_Model):
    items: list[SiteIssue]
    next_cursor: str | None
    summary: IssuesSummary


class SiteIssueDetail(_Model):
    id: uuid.UUID
    crawl_id: uuid.UUID
    rule_id: str
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    finding_class: FindingClass
    title: str
    description: str
    remediation: str
    evidence: dict[str, object]
    affected_urls: list[AffectedUrl]
    affected_url_count: int
    analyzer_version: str
    rule_version: str
    created_at: str
    next_cursor: str | None = None


class IssueHistoryRow(_Model):
    id: uuid.UUID
    crawl_id: uuid.UUID
    rule_id: str
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    finding_class: FindingClass
    title: str
    description: str
    remediation: str
    analyzer_version: str
    rule_version: str
    created_at: str


class IssueHistoryPage(_Model):
    items: list[IssueHistoryRow]
    next_cursor: str | None


class IssueHistoryTimelineRow(_Model):
    crawl_id: uuid.UUID
    observed_at: str | None
    outcome: RuleOutcome
    transition: Literal["new", "continuing", "resolved", "unchanged"]


class GroupedIssueHistoryRow(_Model):
    rule_id: str
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    finding_class: FindingClass
    title: str
    description: str
    remediation: str
    current_state: Literal["open", "resolved"]
    current_transition: Literal["new", "continuing", "resolved", "unchanged"]
    occurrence_count: int
    first_seen_at: str | None
    last_seen_at: str | None
    analyzer_version: str
    rule_version: str
    timeline: list[IssueHistoryTimelineRow]


class IssueHistorySincePreviousCrawl(_Model):
    has_previous_crawl: bool
    new: int
    continuing: int
    resolved: int


class GroupedIssueHistoryPage(_Model):
    items: list[GroupedIssueHistoryRow]
    next_cursor: str | None
    since_previous_crawl: IssueHistorySincePreviousCrawl


# =========================================================================
# Events + dashboard
# =========================================================================
class CrawlEvent(_Model):
    id: uuid.UUID
    crawl_id: uuid.UUID
    event_type: str
    message: str
    payload: dict[str, object]
    created_at: str


class DashboardResponse(_Model):
    project_id: uuid.UUID
    crawl: CrawlResponse | None
    score_summary: ScoreSummary | None
    # THE screen phase, resolved server-side from the crawl, the entitlement,
    # and the project's monitored set at one instant (app/domain/site_health/
    # phase.py). The client renders this; it does not re-derive it.
    phase: SiteHealthPhase
    # The crawl's immutable aggregate snapshot (one per crawl); null until the
    # crawl terminalizes. Content verification compares a published revision
    # against a later snapshot and reads this handle.
    snapshot_id: uuid.UUID | None = None
    quota: MonitoredQuota
    # B3: same root-failure projection as the pages response, so the failed
    # crawl's dashboard can render the failure block without a second fetch.
    root_errors: list[RootError] = []


class SiteHealthError(_Model):
    code: str
    message: str
    limit: int | None = None
    currently_used: int | None = None
    expected_selection_version: int | None = None
    current_selection_version: int | None = Field(default=None)
