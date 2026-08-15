import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Site Health — entitlement, crawl + substates, inventory, monitored set,
// pages, issues, scores, events, and coded errors.
//
// Contract source: docs plan `/.plans/v1-site-health.md` (§API contract,
// §Persistence lifecycle states) + subplan `site-health-crawler.md`. Every
// object is `.strict()` so an unexpected key (e.g. a leaked full-site total on
// a Free projection, invariant: no Free count side channels) fails loud. All
// count-bearing fields the backend redacts for Free are `null`/absent, never a
// number — the frontend never invents a total.
// ---------------------------------------------------------------------------

// Capability access mode: a zero-allowance account gets a server-selected
// `sample`; an account with a monitored allowance gets `full` discovery plus
// user selection of a persistent monitored set. `unresolved` is the explicit
// fail-closed state. This is a NEUTRAL capability, not a plan name — there is
// deliberately no `plan_key` here to branch on.
export const siteHealthAccessModeSchema = z.enum(['sample', 'full', 'unresolved']);

// `GET /entitlements` — the workspace's neutral Site Health runtime
// projection. `monitored_url_limit` is the ONLY authority for the selection
// quota (never hard-code 50); `count_disclosure` gates every discovered-count
// disclosure. `resolver_status` is the fail-closed signal: anything other than
// `resolved` must enable no crawl or selection action.
export const siteHealthEntitlementSchema = responseObject({
  workspace_id: uuid(),
  access_mode: siteHealthAccessModeSchema,
  sample_url_limit: z.number().int(),
  monitored_url_limit: z.number().int(),
  count_disclosure: z.boolean(),
  resolver_status: z.enum(['resolved', 'entitlement_unresolved']),
  registry_revision: z.string(),
  entitlement_lifecycle_version: z.number().int(),
  valid_until: z.string().nullable(),
  contributing_grant_ids: z.array(uuid()),
  advanced_controls_enabled: z.boolean(),
});

// Independent crawl lifecycle sub-states (plan §Persistence lifecycle states).
export const crawlOverallStatusSchema = z.enum([
  'draft',
  'validating',
  'queued',
  'running',
  'paused',
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
]);
export const crawlDiscoveryStatusSchema = z.enum([
  'pending',
  'running',
  'stopped',
  'completed',
  'sample_completed',
  'failed',
  'cancelled',
]);
export const crawlAnalysisStatusSchema = z.enum([
  'pending',
  'running',
  'stopped',
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
]);
// Queue-neutral task status shared with the audit queue contract.
export const siteCrawlTaskStatusSchema = z.enum([
  'queued',
  'leased',
  'running',
  'succeeded',
  'retry_wait',
  'failed',
  'cancelled',
]);

// How a discovered URL was first observed (immutable provenance).
export const siteUrlSourceSchema = z.enum(['root', 'link', 'sitemap', 'redirect']);

// Per-URL analysis presentation state. `error`/`blocked` are explicit states
// (never a fabricated zero score); `not_selected` covers unanalysed rows.
export const pageAnalysisStatusSchema = z.enum([
  'not_selected',
  'pending',
  'running',
  'completed',
  'partially_completed',
  'failed',
  // Presentation-only terminal states. `blocked` = the latest analyze task
  // ended under a config-owned policy denial (robots/SSRF); `error` = any other
  // terminal-unsuccessful analysis. `failed` stays an internal persistence
  // state (the API never surfaces it as page copy).
  'error',
  'blocked',
  'cancelled',
]);

// Page-type classification vocabulary (site-health v2 P1). The deterministic
// backend classifier stamps every page analysis with one of these types; the
// page/inventory/detail DTOs project it as `page_kind`.
export const pageKindSchema = z.enum([
  'homepage',
  'article',
  'product',
  'category',
  'pricing',
  'docs',
  'faq',
  'about_contact',
  'service',
  'local',
  'guide',
  'comparison',
  'case_study_review',
  'trust_policy',
  'other',
]);

// One `score_summary.by_page_kind` bucket (site-health v2 P1): the analyzed
// count + mean Technical/AEO/overall scores across the analyzed pages of one
// page type. A mean is null when no analyzed page of the type produced that
// score — never a fabricated zero.
export const pageKindScoreSummarySchema = responseObject({
  analyzed_count: z.number().int(),
  technical_score: z.number().nullable(),
  aeo_score: z.number().nullable(),
  overall_score: z.number().nullable(),
});

// Crawl score/coverage summary (nullable scores until analysis produces them).
// `by_page_kind` breaks the means down per classified page type (empty until
// at least one analyzed page has been classified).
export const siteScoreSummarySchema = responseObject({
  overall_score: z.number().nullable(),
  technical_score: z.number().nullable(),
  aeo_score: z.number().nullable(),
  selected_count: z.number().int(),
  analyzed_count: z.number().int(),
  issue_count: z.number().int(),
  scoring_version: z.string(),
  by_page_kind: z.record(z.string(), pageKindScoreSummarySchema),
});

export const crawlCountersSchema = responseObject({
  discovered: z.number().int().nullable(),
  selected: z.number().int(),
  queued: z.number().int(),
  running: z.number().int(),
  analyzed: z.number().int(),
  errors: z.number().int(),
  blocked: z.number().int(),
  failure_breakdown: responseObject({
    robots_denied: z.number().int(),
    http_4xx: z.number().int(),
    http_5xx: z.number().int(),
    timeout: z.number().int(),
  }),
  activity: responseObject({
    state: z.enum(['working', 'waiting', 'stalled', 'terminal']),
    reason: z.enum(['active_work', 'host_gate', 'retry_backoff', 'expired_lease', 'terminal']),
    queue_depth: z.number().int(),
    next_available_at: z.string().nullable(),
  }),
  by_page_kind: z.record(z.string(), z.number().int()),
});

// Why a crawl failed (SH-2/SH-5 — B1): stable machine `code` + human
// `message` + the terminal HTTP status / attempt count when present. Projected
// from the root discover task's terminal fetch attempts; null on any crawl
// that did not fail (and on list projections — N+1 avoidance).
export const crawlFailureSummarySchema = responseObject({
  code: z.string(),
  message: z.string(),
  attempts: z.number().int().nullable(),
  status_code: z.number().int().nullable(),
  target_url: z.string(),
});

// A crawl projection. `total_url_count` is null while full discovery runs and
// ALWAYS null for a Free sample crawl; `has_more_site_urls`/`discovered_count`
// are absent (optional) or null under Free redaction — never a leaked total.
export const siteCrawlSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid(),
  profile_id: uuid(),
  status: crawlOverallStatusSchema,
  discovery_status: crawlDiscoveryStatusSchema,
  analysis_status: crawlAnalysisStatusSchema,
  root_url: z.string(),
  sample_mode: z.boolean(),
  seed: z.string(),
  inventory_complete: z.boolean(),
  visible_url_count: z.number().int(),
  analyzed_count: z.number().int(),
  failed_count: z.number().int(),
  discovery_requested_count: z.number().int(),
  analysis_requested_count: z.number().int(),
  counters: crawlCountersSchema,
  // Redactable count fields (Free → null / absent, never a number).
  discovered_count: z.number().int().nullable().optional(),
  total_url_count: z.number().int().nullable(),
  has_more_site_urls: z.boolean().nullable().optional(),
  score_summary: siteScoreSummarySchema.nullable(),
  // B1: REQUIRED key (the backend response model always serializes it); null
  // on healthy/partial crawls and on list projections.
  failure_summary: crawlFailureSummarySchema.nullable(),
  // v2 P2: bounded site-level facts (robots AI-crawler stance, llms.txt,
  // sitemap files). Mirrors the backend's untyped `dict | None`, and is
  // REQUIRED because the response model always serializes the key — making
  // it optional would weaken the drift contract.
  site_facts: z.record(z.string(), z.unknown()).nullable(),
  extractor_version: z.string(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  scoring_version: z.string(),
  error_message: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const phaseRunSchema = responseObject({
  id: uuid(),
  phase: z.enum(['discovery', 'analysis']),
  status: z.enum(['running', 'stopped', 'completed', 'failed']),
  requested_count: z.number().int(),
  processed_count: z.number().int(),
  created_at: z.string(),
  stopped_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const phaseMutationResponseSchema = responseObject({
  crawl: siteCrawlSchema,
  phase_run: phaseRunSchema.nullable(),
  created_new_crawl: z.boolean(),
  selection_version: z.number().int().nullable(),
  scheduled_count: z.number().int(),
});

export const urlPreviewRowSchema = responseObject({
  row: z.number().int(),
  input: z.string(),
  accepted: z.boolean(),
  canonical_url: z.string().nullable(),
  reason_code: z.string().nullable(),
  value_kind: z.string(),
  priority: z.number().int(),
});
export const urlPreviewResponseSchema = responseObject({
  items: z.array(urlPreviewRowSchema),
  truncated: z.boolean(),
  counts: z.record(z.string(), z.number().int()),
  policy_version: z.string(),
});

// Opaque, filter-bound keyset cursor page envelope. `next_cursor` is null on
// the last page. There is no offset / page total field (invariant: no Free
// count side channel; stable cursors while discovery appends rows).
export const cursorPageSchema = <T extends z.ZodTypeAny>(item: T) =>
  responseObject({
    items: z.array(item),
    next_cursor: z.string().nullable(),
  });

// The exact frozen pack identity an understanding was produced under. Shown in
// the "why this role?" disclosure so a result is always attributable to one
// reviewed pack version rather than to "the classifier" in general.
// Nullable analysis-summary fields shared by inventory rows and analyzed-page
// summary rows (null until analysis completes for that URL). `page_kind`
// joins them: it is stamped by the analysis classifier, so an unanalyzed row
// has no classification yet (null — the UI renders `—`, never a guessed type).
const analysisSummaryFields = {
  issue_count: z.number().int().nullable(),
  technical_score: z.number().nullable(),
  aeo_score: z.number().nullable(),
  overall_score: z.number().nullable(),
  last_audited: z.string().nullable(),
  page_kind: pageKindSchema.nullable(),
  // Bounded industry-role fields on list rows. These are pack-defined IDs, not
  // a fixed enum, so they stay plain strings — the UI must never title-case an
  // unknown namespaced ID as though it were a reviewed label. Absent entirely
  // when the pack classifier never ran for the row.
};

// One lightweight inventory row. Ordering is URL-only. The analysis summary
// fields (`issue_count`, `technical_score`, `aeo_score`, `overall_score`,
// `last_audited`) are null until analysis completes for that URL.
export const inventoryRowSchema = responseObject({
  site_url_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  content_type: z.string().nullable(),
  source: siteUrlSourceSchema.nullable(),
  depth: z.number().int().nullable(),
  monitored: z.boolean(),
  first_seen_at: z.string().nullable(),
  last_seen_at: z.string().nullable(),
  ...analysisSummaryFields,
});

export const inventoryPageSchema = cursorPageSchema(inventoryRowSchema);
export const siteCrawlListPageSchema = cursorPageSchema(siteCrawlSchema);

// Workspace-wide monitored quota usage (counts every active monitored row).
export const monitoredQuotaSchema = responseObject({
  used: z.number().int(),
  limit: z.number().int(),
});

// One persistent monitored-set row.
export const monitoredUrlSchema = responseObject({
  site_url_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  active: z.boolean(),
  selection_source: z.enum(['user', 'free_sample', 'bootstrap']),
  selected_at: z.string().nullable(),
  deselected_at: z.string().nullable(),
});

// `GET /projects/{id}/monitored-urls` — persistent set + revision + quota.
export const monitoredUrlsResponseSchema = responseObject({
  project_id: uuid(),
  selection_version: z.number().int(),
  monitored_urls: z.array(monitoredUrlSchema),
  quota: monitoredQuotaSchema,
});

// Deterministic HTTP delivery facts. `field_cwv_available` is a literal false —
// the HTTP-first crawler never fabricates field Core Web Vitals (no LCP/CLS/INP).
export const deliveryFactsSchema = responseObject({
  field_cwv_available: z.literal(false),
  status_code: z.number().int().nullable(),
  ttfb_ms: z.number().nullable(),
  wire_bytes: z.number().int().nullable(),
  decoded_bytes: z.number().int().nullable(),
  html_bytes: z.number().int().nullable(),
  http_version: z.string().nullable(),
  compression: z.string().nullable(),
  cache_control: z.string().nullable(),
  blocking_resource_count: z.number().int().nullable(),
});

// Bounded normalized page facts (deterministic; extractor-versioned).
export const pageFactsSchema = responseObject({
  title: z.string().nullable(),
  meta_description: z.string().nullable(),
  canonical_url: z.string().nullable(),
  robots_directives: z.array(z.string()),
  h1_count: z.number().int(),
  heading_count: z.number().int(),
  image_count: z.number().int(),
  image_missing_alt_count: z.number().int(),
  word_count: z.number().int(),
  internal_link_count: z.number().int(),
  external_link_count: z.number().int(),
  structured_data_types: z.array(z.string()),
});

// Issue severity + dimension enums (config-owned rule catalog).
export const issueSeveritySchema = z.enum(['critical', 'high', 'medium', 'low', 'info']);
export const issueDimensionSchema = z.enum(['technical', 'aeo']);
export const findingClassSchema = z.enum(['defect', 'advisory']);

// A single affected-URL summary on an issue projection. `page_kind` is the
// affected page's classification; it is OPTIONAL — the v1 backend DTO has no
// such key, so the badge renders only when the projection carries it (same
// absent-or-null treatment as the Free-redacted count fields).
export const affectedUrlSchema = responseObject({
  site_url_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  page_kind: pageKindSchema.nullable().optional(),
});

// One issue catalog row (failure projection with remediation snapshot).
export const siteIssueSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  rule_id: z.string(),
  // Page TYPES this group affects. Pack-free page-kind ids, sorted.
  page_kinds: z.array(z.string()),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  title: z.string(),
  description: z.string(),
  remediation: z.string(),
  affected_url_count: z.number().int(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
});

// Grouped-issue catalog summary (occurrence + severity + affected-page counts).
// `severity_counts` keys are the severity vocabulary; `dimension_counts` keys
// are the rule dimensions (technical/aeo); values are occurrence counts.
export const issuesSummarySchema = responseObject({
  issue_count: z.number().int(),
  defect_issue_type_count: z.number().int(),
  advisory_issue_type_count: z.number().int(),
  occurrence_count: z.number().int(),
  severity_counts: z.record(z.string(), z.number().int()),
  dimension_counts: z.record(z.string(), z.number().int()),
  affected_url_count: z.number().int(),
  monitored_affected_url_count: z.number().int(),
});

// Full grouped-issue detail — remediation + evidence + keyset-paginated
// affected URLs. `id` is the stable canonical (representative) issue id for the
// rule group; `affected_url_count` is the full deduplicated total and
// `next_cursor` walks the affected-URL page.
export const siteIssueDetailSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  rule_id: z.string(),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  title: z.string(),
  description: z.string(),
  remediation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  affected_urls: z.array(affectedUrlSchema),
  affected_url_count: z.number().int(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
  next_cursor: z.string().nullable().optional(),
});

// Grouped-issue catalog page — cursor page + API-owned summary (mockup 710).
export const siteIssuesPageSchema = cursorPageSchema(siteIssueSchema).extend({
  summary: issuesSummarySchema,
});

// Analyzed-page summary row (`/pages` list). Scores/issue-count are null when
// analysis has not completed; `error_code` is '' when there is no error.
export const pageSummarySchema = responseObject({
  site_url_id: uuid(),
  crawl_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  monitored: z.boolean(),
  analysis_status: pageAnalysisStatusSchema,
  error_code: z.string(),
  ...analysisSummaryFields,
});

// One REAL root-target network call the crawl lost (SH-4 — B3). Deliberately
// NOT a page row: a root failure never creates a SiteUrl, so there is no
// `site_url_id` and no PageDetail link — the Errors & Blocked tab renders
// these as a distinct non-clickable block above the table.
export const rootErrorSchema = responseObject({
  method: z.string(),
  target: z.string(),
  outcome: z.string(),
  error_code: z.string(),
  status_code: z.number().int().nullable(),
  latency_ms: z.number().int().nullable(),
});

export const pagesPageSchema = cursorPageSchema(pageSummarySchema).extend({
  // REQUIRED (backend always serializes); empty unless the crawl's root fetch
  // failed terminally. Never enters the keyset pagination of `items`.
  root_errors: z.array(rootErrorSchema),
});

// One persisted rule evaluation on a page (all outcomes, current label).
const ruleEvaluationSchema = responseObject({
  id: uuid(),
  rule_id: z.string(),
  title: z.string(),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  outcome: z.enum(['pass', 'fail', 'not_applicable', 'error']),
  weight: z.number(),
  evidence: z.record(z.string(), z.unknown()),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
});

// One deduplicated link/asset reference discovered on a page.
const linkReferenceSchema = responseObject({
  id: uuid(),
  kind: z.string(),
  target_url: z.string(),
  is_internal: z.boolean(),
  rel: z.string(),
  anchor_text: z.string(),
  target_artifact_id: uuid().nullable(),
});

// Full analyzed-page detail (persisted facts/delivery/scores/issues/provenance).
export const pageDetailSchema = responseObject({
  site_url_id: uuid(),
  crawl_id: uuid(),
  normalized_url: z.string(),
  display_url: z.string(),
  title: z.string().nullable(),
  analysis_status: pageAnalysisStatusSchema,
  error_code: z.string(),
  field_cwv_available: z.literal(false),
  technical_score: z.number().nullable(),
  aeo_score: z.number().nullable(),
  overall_score: z.number().nullable(),
  issue_count: z.number().int().nullable(),
  last_audited: z.string().nullable(),
  page_kind: pageKindSchema.nullable(),
  // Bounded classifier evidence behind page_kind ("why this kind?"
  // disclosure); null until the URL has an analysis.
  page_kind_evidence: z.record(z.string(), z.unknown()).nullable(),
  // Pack-governed industry role. `null` = the pack classifier never ran.
  // A present object with `role_id: null` plus an `abstention_reason` is an
  // EXECUTED abstention — a different fact, rendered differently.
  facts: pageFactsSchema,
  delivery: deliveryFactsSchema,
  issues: z.array(siteIssueSchema),
  evaluations: z.array(ruleEvaluationSchema),
  link_references: z.array(linkReferenceSchema),
  artifact_id: uuid().nullable(),
  extractor_version: z.string(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  scoring_version: z.string(),
});

// Identity/status returned by the per-page rerun (202). "Re-audit this page"
// is normally invoked from a COMPLETED (terminal) source crawl; the backend
// mints a fresh single-page rerun crawl in that case (`created_new_crawl`),
// so the client must poll the returned `crawl_id`/`site_url_id` (the fresh
// run) rather than the terminal source crawl it was invoked from.
export const rerunPageResponseSchema = responseObject({
  crawl_id: uuid(),
  site_url_id: uuid(),
  task_id: uuid(),
  created_new_crawl: z.boolean(),
  analysis_status: pageAnalysisStatusSchema,
});

// One per-URL issue-history row — an issue occurrence from the selected crawl
// or a prior crawl in the project chronology (immutable failure projection).
export const issueHistoryRowSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  rule_id: z.string(),
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  finding_class: findingClassSchema,
  title: z.string(),
  description: z.string(),
  remediation: z.string(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  created_at: z.string(),
});

// Per-URL issue history page (crawl-bounded, newest-first, cursor-paginated).
export const issueHistoryPageSchema = cursorPageSchema(issueHistoryRowSchema);

// Append-only safe crawl event. Free payloads never carry total/frontier/
// overflow data; `event_type` is an open string (backend owns the catalogue).
export const siteCrawlEventSchema = responseObject({
  id: uuid(),
  crawl_id: uuid(),
  event_type: z.string(),
  message: z.string(),
  payload: z.record(z.string(), z.unknown()),
  created_at: z.string(),
});

// Latest / selected crawl dashboard projection (`/projects/{id}/site-health`).
export const siteHealthDashboardSchema = responseObject({
  project_id: uuid(),
  crawl: siteCrawlSchema.nullable(),
  score_summary: siteScoreSummarySchema.nullable(),
  // THE screen phase, resolved server-side. The client renders this; it does
  // not re-derive it from crawl statuses + entitlement + monitored counts.
  phase: z.enum(['empty', 'discovering', 'analyzing', 'dashboard', 'terminal']),
  // Null until the crawl terminalizes; content verification compares a
  // published revision against a later snapshot.
  snapshot_id: uuid().nullable(),
  quota: monitoredQuotaSchema,
  // B3: same root-failure projection as the pages response — the failed
  // crawl's dashboard renders the failure block without a second fetch.
  root_errors: z.array(rootErrorSchema),
  phase_runs: responseObject({
    discovery: phaseRunSchema.nullable(),
    analysis: phaseRunSchema.nullable(),
  }),
});

export const linkGraphStateSchema = z.enum(['available', 'incomplete', 'unavailable']);

export const linkGraphSnapshotSchema = responseObject({
  state: linkGraphStateSchema,
  snapshot_id: uuid().nullable(),
  crawl_id: uuid().nullable(),
  root_site_url_id: uuid().nullable().optional(),
  analyzer_version: z.string(),
  page_analyzer_version: z.string(),
  extractor_version: z.string(),
  source_analysis_ids: z.array(uuid()),
  coverage: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  summary: z.record(z.string(), z.unknown()),
  created_at: z.string().nullable(),
});

export const linkGraphNodeSchema = responseObject({
  id: uuid(),
  site_url_id: uuid(),
  source_analysis_id: uuid(),
  normalized_url: z.string(),
  title: z.string(),
  indexable: z.boolean(),
  pagerank: z.number(),
  click_depth: z.number().int().nullable(),
  followed_inbound_count: z.number().int(),
  followed_outbound_count: z.number().int(),
  near_orphan: z.boolean(),
  weak_authority: z.boolean(),
  over_linked: z.boolean(),
  hub: z.boolean(),
  suggested_source_ids: z.array(uuid()),
});

export const linkGraphEdgeSchema = responseObject({
  id: uuid(),
  source_site_url_id: uuid(),
  target_site_url_id: uuid().nullable(),
  target_url: z.string(),
  followed: z.boolean(),
  occurrence_count: z.number().int(),
  followed_occurrence_count: z.number().int(),
  nofollow_occurrence_count: z.number().int(),
  anchor_texts: z.array(z.string()),
});

const linkGraphPageBase = {
  state: linkGraphStateSchema,
  snapshot_id: uuid().nullable(),
  crawl_id: uuid().nullable(),
  next_cursor: z.string().nullable(),
  limitations: z.array(z.string()),
};

export const linkGraphNodesPageSchema = responseObject({
  ...linkGraphPageBase,
  items: z.array(linkGraphNodeSchema),
});

export const linkGraphEdgesPageSchema = responseObject({
  ...linkGraphPageBase,
  items: z.array(linkGraphEdgeSchema),
});

// Stable coded failures (plan §API contract). The frontend keys UX (upgrade
// prompt, quota feedback, stale-revision refetch, retry copy) off these codes.
export const siteHealthErrorCodeSchema = z.enum([
  'starter_required',
  'site_health_quota_exceeded',
  'stale_selection_version',
  'crawl_already_active',
  'site_health_discovery_limit_exceeded',
  'site_health_analysis_limit_exceeded',
  'site_health_phase_already_running',
  'site_health_phase_not_resumable',
  'ssrf_blocked',
  'robots_denied',
  'redirect_limit',
  'response_too_large',
  'unsupported_content_type',
  'timeout',
  'dns_resolution_failed',
  'http_4xx',
  'http_5xx',
]);

// Coded error body. Quota errors carry `limit`/`currently_used`; a stale
// selection carries the expected/current versions. Extra keys fail loud.
export const siteHealthErrorSchema = responseObject({
  code: siteHealthErrorCodeSchema,
  message: z.string(),
  limit: z.number().int().optional(),
  currently_used: z.number().int().optional(),
  expected_selection_version: z.number().int().optional(),
  current_selection_version: z.number().int().optional(),
});
