import { z } from 'zod';

import { phaseRunSchema, siteCrawlSchema, siteScoreSummarySchema } from './crawl';
import { responseObject, uuid } from './core';
import { monitoredQuotaSchema } from './inventory';
import { findingClassSchema, issueDimensionSchema, issueSeveritySchema } from './issues';
import { rootErrorSchema } from './pages';
import { cursorPageSchema } from './pagination';

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

export const changeStateSchema = z.enum(['available', 'unavailable', 'non_comparable']);
export const changeClassSchema = z.enum([
  'improvement',
  'neutral-change',
  'potential-regression',
  'critical-regression',
]);
export const changeSummarySchema = responseObject({
  state: changeStateSchema,
  reason_code: z.string().nullable(),
  snapshot_id: uuid().nullable(),
  crawl_a_id: uuid().nullable(),
  crawl_b_id: uuid().nullable(),
  complete_pair: z.boolean(),
  analyzer_version: z.string(),
  page_analyzer_version: z.string(),
  extractor_version: z.string(),
  source_analysis_ids: z.array(uuid()),
  coverage: z.record(z.string(), z.unknown()),
  summary: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  created_at: z.string().nullable(),
});
export const changeObservationSchema = responseObject({
  id: uuid(),
  site_url_id: uuid(),
  normalized_url: z.string(),
  field: z.string(),
  change_class: changeClassSchema,
  before_value: z.unknown().nullable(),
  after_value: z.unknown().nullable(),
  source_analysis_a_id: uuid().nullable(),
  source_analysis_b_id: uuid().nullable(),
  source_artifact_a_id: uuid().nullable(),
  source_artifact_b_id: uuid().nullable(),
  source_evaluation_a_id: uuid().nullable(),
  source_evaluation_b_id: uuid().nullable(),
  expected: z.boolean(),
  implementation_event_id: uuid().nullable(),
  created_at: z.string(),
});
export const changesPageSchema = changeSummarySchema.extend({
  items: z.array(changeObservationSchema),
  next_cursor: z.string().nullable(),
});

// One failed check on a page, named the way the rule catalog names it. A raw
// rule id (`aeo.answer_first`) never reaches the screen.
export const readinessFailingCheckSchema = responseObject({
  rule_id: z.string(),
  title: z.string(),
});

// Evidence is one row per FAILING PAGE listing that page's failed checks —
// never one row per evaluation, which repeated the same URL once per rule.
export const readinessEvidencePageSchema = responseObject({
  site_url_id: uuid(),
  normalized_url: z.string(),
  failed_checks: z.array(readinessFailingCheckSchema),
});

// One mapped rule rolled up, carrying the catalog title and the fix.
export const readinessCheckSchema = responseObject({
  rule_id: z.string(),
  title: z.string(),
  remediation: z.string(),
  pass_count: z.number().int(),
  fail_count: z.number().int(),
  not_applicable_count: z.number().int(),
  failing_page_count: z.number().int(),
});

export const readinessDimensionSchema = responseObject({
  key: z.enum([
    'answerability',
    'structure',
    'evidence',
    'machine-readability',
    'authority',
    'freshness',
    'crawlability',
  ]),
  label: z.string(),
  description: z.string(),
  rule_ids: z.array(z.string()),
  pass_count: z.number().int(),
  fail_count: z.number().int(),
  not_applicable_count: z.number().int(),
  error_count: z.number().int(),
  observed_evaluation_count: z.number().int(),
  expected_evaluation_count: z.number().int(),
  coverage: z.number().nullable(),
  // Human-scale quantities: pages a check applied to, and pages that failed at
  // least one. Always render `evidence_pages.length` against these, never as a
  // total of its own.
  checked_page_count: z.number().int(),
  failing_page_count: z.number().int(),
  checks: z.array(readinessCheckSchema),
  evidence_pages: z.array(readinessEvidencePageSchema),
  evidence_truncated: z.boolean(),
});

export const aeoReadinessSchema = responseObject({
  state: z.enum(['available', 'incomplete', 'unavailable']),
  crawl_id: uuid().nullable(),
  taxonomy_version: z.string(),
  analyzer_version: z.string(),
  source_analysis_ids: z.array(uuid()),
  analysis_count: z.number().int(),
  observed_evaluation_count: z.number().int(),
  expected_evaluation_count: z.number().int(),
  coverage: z.number().nullable(),
  dimensions: z.array(readinessDimensionSchema),
  limitations: z.array(z.string()),
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
