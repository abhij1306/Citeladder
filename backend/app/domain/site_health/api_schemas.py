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

from app.core.config.site_health import site_health_settings

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
IssueDimension = Literal["technical", "aeo"]
SiteUrlSource = Literal["root", "link", "sitemap", "redirect"]
SelectionSource = Literal["user", "free_sample", "bootstrap"]


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


class StartDiscoveryRequest(_Model):
    additional_url_count: int = Field(ge=1)


class StartAnalysisRequest(_Model):
    requested_url_count: int = Field(ge=1)
    site_url_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=site_health_settings.max_analysis_urls,
    )
    expected_selection_version: int = Field(ge=0)


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
    technical_score: float | None
    aeo_score: float | None
    overall_score: float | None


class ScoreSummary(_Model):
    overall_score: float | None
    technical_score: float | None
    aeo_score: float | None
    selected_count: int
    analyzed_count: int
    issue_count: int
    scoring_version: str
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


class CrawlCounters(_Model):
    discovered: int | None
    selected: int
    queued: int
    running: int
    analyzed: int
    errors: int
    blocked: int
    by_page_kind: dict[str, int] = {}


class PhaseRunResponse(_Model):
    id: uuid.UUID
    phase: Literal["discovery", "analysis"]
    status: Literal["running", "stopped", "completed", "failed"]
    requested_count: int
    processed_count: int
    created_at: str
    stopped_at: str | None
    completed_at: str | None


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


class PhaseMutationResponse(_Model):
    crawl: CrawlResponse
    phase_run: PhaseRunResponse | None
    created_new_crawl: bool
    selection_version: int | None
    scheduled_count: int


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
    industry_role_id: str | None = None
    role_abstention_reason: str | None = None
    industry_role_confidence: str = ""
    corpus_disposition: str = ""
    technical_score: float | None
    aeo_score: float | None
    overall_score: float | None
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
    industry_role_id: str | None = None
    role_abstention_reason: str | None = None
    industry_role_confidence: str = ""
    corpus_disposition: str = ""
    technical_score: float | None
    aeo_score: float | None
    overall_score: float | None
    last_audited: str | None


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
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    title: str
    remediation: str
    affected_url_count: int
    analyzer_version: str
    rule_version: str
    created_at: str


RuleOutcome = Literal["pass", "fail", "not_applicable", "error"]


class RuleEvaluation(_Model):
    id: uuid.UUID
    rule_id: str
    title: str
    dimension: IssueDimension
    category: str
    severity: IssueSeverity
    outcome: RuleOutcome
    weight: float
    evidence: dict[str, object]
    analyzer_version: str
    rule_version: str
    created_at: str


class LinkReference(_Model):
    id: uuid.UUID
    kind: str
    target_url: str
    is_internal: bool
    rel: str
    anchor_text: str
    target_artifact_id: uuid.UUID | None


class IndustryRoleManifest(_Model):
    """The exact frozen pack identity an understanding was produced under."""

    catalog_version: str = ""
    pack_id: str = ""
    pack_version: str = ""
    pack_content_hash: str = ""
    classifier_version: str = ""


class IndustryRole(_Model):
    """Pack-governed role projection, rendered from persisted state only.

    ``role_id is None`` together with a non-null ``abstention_reason`` is an
    EXECUTED abstention: the classifier ran on this page and declined to
    commit. The whole object is null (see ``PageDetail.industry_role``) when the
    pack classifier never ran. Those are different facts and the UI must be
    able to tell them apart.
    """

    role_id: str | None = None
    score: float | None = None
    winner_margin: float | None = None
    confidence_band: str = ""
    secondary_role_ids: list[str] = []
    abstention_reason: str | None = None
    temporal_state: str = ""
    corpus_disposition: str = ""
    evidence: list[dict] = []
    alternatives: list[dict] = []
    conflicts: list[dict] = []
    manifest: IndustryRoleManifest = IndustryRoleManifest()


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
    # Pack-governed industry role. None when the pack classifier never ran
    # (unpacked project, or an analysis written before the pack was frozen).
    industry_role: IndustryRole | None = None
    technical_score: float | None
    aeo_score: float | None
    overall_score: float | None
    issue_count: int | None
    last_audited: str | None
    facts: PageFacts
    delivery: DeliveryFacts
    issues: list[SiteIssue]
    evaluations: list[RuleEvaluation]
    link_references: list[LinkReference]
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
    title: str
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
    title: str
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
    title: str
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
    quota: MonitoredQuota
    # B3: same root-failure projection as the pages response, so the failed
    # crawl's dashboard can render the failure block without a second fetch.
    root_errors: list[RootError] = []
    phase_runs: dict[Literal["discovery", "analysis"], PhaseRunResponse | None] = {}


class SiteHealthError(_Model):
    code: str
    message: str
    limit: int | None = None
    currently_used: int | None = None
    expected_selection_version: int | None = None
    current_selection_version: int | None = Field(default=None)


# =========================================================================
# Site Intelligence (S2/S3 projection)
# =========================================================================
# Every model below renders the projection FROZEN onto the snapshot at crawl
# finalization. Nullable numbers are load-bearing: ``None`` means "not
# measurable", which is a different fact from ``0.0`` ("measured, and it is
# zero"). A DTO that coerced one into the other would turn an incomplete crawl
# into a failing site.
CoverageState = Literal[
    "answered_strong",
    "answered_weak",
    "missing",
    "conflicting",
    "unsupported",
    "historical_only",
    "unavailable_evidence",
    "not_applicable",
]


class QuestionCoverageItem(_Model):
    question_id: str
    label: str
    state: CoverageState
    journey_stage_id: str
    reason: str
    satisfied_predicate_ids: list[str] = []
    missing_predicate_ids: list[str] = []
    answering_role_ids: list[str] = []


class QuestionCoverageBlock(_Model):
    # ``None`` when the pack declares no applicable question — never 0.0, which
    # would read as total failure.
    answered_ratio: float | None = None
    denominator: int = 0
    counts: dict[str, int] = {}
    questions: list[QuestionCoverageItem] = []


class JourneyStageBlock(_Model):
    stage_id: str
    label: str
    order: int
    role_coverage: float
    question_coverage: float | None = None
    present_role_ids: list[str] = []
    missing_role_ids: list[str] = []
    answered_question_ids: list[str] = []
    gap_question_ids: list[str] = []
    # Outcome -> ``unavailable`` until Demand Intelligence supplies events.
    outcomes: dict[str, str] = {}


class JourneyBlock(_Model):
    journey_id: str
    label: str
    stages: list[JourneyStageBlock] = []
    role_coverage: float = 0.0
    question_coverage: float | None = None
    version: str = ""


class DimensionComponentBlock(_Model):
    component_id: str
    label: str
    # ``None`` == the crawl could not observe this component at all.
    score: float | None = None


class DimensionBlock(_Model):
    dimension_id: str
    label: str
    score: float
    coverage: float
    components: list[DimensionComponentBlock] = []


class DimensionsBlock(_Model):
    # ``None`` only when no projection exists; a real projection always reports
    # over all six dimensions.
    composite_score: float | None = None
    composite_coverage: float | None = None
    dimensions: list[DimensionBlock] = []


class KnowledgeSummaryBlock(_Model):
    entity_count: int = 0
    assertion_count: int = 0
    relation_count: int = 0
    contradiction_count: int = 0
    pages_considered: int = 0
    pages_contributing: int = 0
    entity_type_ids: list[str] = []
    # Named reasons a fact could not be produced — report copy, not log noise.
    warnings: list[str] = []


class CorpusBlock(_Model):
    by_disposition: dict[str, int] = {}
    by_item_kind: dict[str, int] = {}
    discovered: int = 0
    analyzable: int = 0
    inventory_only: int = 0
    documents: int = 0


class IntelligenceCrawlRef(_Model):
    id: str
    status: str
    root_url: str
    created_at: str | None = None


class IntelligenceOverviewResponse(_Model):
    # ``False`` when the crawl has produced no snapshot yet. Distinct from
    # ``packed=False``, which means a snapshot exists and no pack applied.
    available: bool
    reason: str | None = None
    packed: bool = False
    manifest: dict[str, str] | None = None
    crawl: IntelligenceCrawlRef
    snapshot_id: str | None = None
    corpus: CorpusBlock = CorpusBlock()
    knowledge: KnowledgeSummaryBlock = KnowledgeSummaryBlock()
    coverage: QuestionCoverageBlock = QuestionCoverageBlock()
    journeys: list[JourneyBlock] = []
    dimensions: DimensionsBlock = DimensionsBlock()
    versions: dict[str, str] = {}


class EvidenceRef(_Model):
    source_kind: str
    source_id: str
    locator: dict[str, object] = {}


class KnowledgeManifest(_Model):
    pack_id: str
    pack_version: str
    extractor_version: str


class KnowledgeEntityItem(_Model):
    id: str
    entity_type_id: str
    identity_key: str
    canonical_name: str
    aliases: list[str] = []
    identifiers: dict[str, str] = {}
    review_state: str
    evidence_page_count: int = 0
    evidence_refs: list[EvidenceRef] = []
    manifest: KnowledgeManifest


class KnowledgeEntityPage(_Model):
    crawl_id: str
    total: int
    items: list[KnowledgeEntityItem] = []


class AssertionSubject(_Model):
    id: str
    entity_type_id: str
    canonical_name: str


class KnowledgeAssertionItem(_Model):
    id: str
    predicate_id: str
    value_type: str
    raw_value: str
    normalized_value: str
    numeric_value: float | None = None
    unit: str = ""
    currency: str = ""
    scope: dict[str, str] = {}
    temporal_state: str
    effective_from: str | None = None
    effective_to: str | None = None
    derivation_method: str = ""
    confidence: float | None = None
    review_state: str
    # Null means nothing disputes this claim — NOT that a dispute was resolved.
    contradiction_group_id: str | None = None
    evidence_refs: list[EvidenceRef] = []
    subject: AssertionSubject


class KnowledgeAssertionPage(_Model):
    crawl_id: str
    total: int
    items: list[KnowledgeAssertionItem] = []


class ContradictionGroup(_Model):
    contradiction_group_id: str
    predicate_id: str
    scope: dict[str, str] = {}
    subject: AssertionSubject
    resolution_state: str
    # ALL sides. A reader who sees one cannot tell what the dispute is.
    sides: list[KnowledgeAssertionItem] = []


class ContradictionPage(_Model):
    crawl_id: str
    total: int
    items: list[ContradictionGroup] = []


class RelationEndpoint(_Model):
    name: str
    entity_type_id: str


class KnowledgeRelationItem(_Model):
    id: str
    relation_type_id: str
    temporal_state: str
    source: RelationEndpoint
    target: RelationEndpoint
    evidence_refs: list[EvidenceRef] = []


class KnowledgeRelationPage(_Model):
    crawl_id: str
    total: int
    items: list[KnowledgeRelationItem] = []


class SchemaTypeSummary(_Model):
    type: str
    pages: int
    valid: int
    invalid: int


class SchemaInvalidPage(_Model):
    site_url_id: str
    url: str
    type: str
    missing: list[str] = []


class SchemaGraphResponse(_Model):
    crawl_id: str
    analyzed_pages: int
    pages_with_schema: int
    types: list[SchemaTypeSummary] = []
    invalid: list[SchemaInvalidPage] = []
