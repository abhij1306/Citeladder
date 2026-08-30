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
  observed_evidence: z.record(z.string(), z.unknown()),
  expected_capability: z.string(),
  remediation: z.string(),
  content_addressable: z.boolean(),
});

// Evidence is one row per FAILING PAGE listing that page's failed checks —
// never one row per evaluation, which repeated the same URL once per rule.
export const readinessEvidencePageSchema = responseObject({
  site_url_id: uuid(),
  source_analysis_id: uuid(),
  normalized_url: z.string(),
  failed_checks: z.array(readinessFailingCheckSchema),
});

// One mapped rule rolled up, carrying the catalog title and the fix.
export const readinessCheckSchema = responseObject({
  rule_id: z.string(),
  title: z.string(),
  remediation: z.string(),
  satisfied_count: z.number().int(),
  partial_count: z.number().int(),
  missing_count: z.number().int(),
  unknown_count: z.number().int(),
  unavailable_count: z.number().int(),
  conflicting_count: z.number().int(),
  not_applicable_count: z.number().int(),
  error_count: z.number().int(),
  failing_page_count: z.number().int(),
  checkpoint_family: z.string(),
  readiness_weight: z.number(),
  content_addressable: z.boolean(),
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
  dimension_applicability: z.enum(['applicable', 'not_applicable', 'unresolved']),
  dimension_measurement_state: z.enum(['measured', 'limited_evidence', 'not_measured', 'excluded']),
  score: z.number().nullable(),
  reason: z.string(),
  checkpoint_ids: z.array(z.string()),
  determinate_checkpoint_ids: z.array(z.string()),
  checkpoint_families: z.array(z.string()),
  earned_points: z.number(),
  determinate_points: z.number(),
  expected_points: z.number(),
  satisfied_count: z.number().int(),
  partial_count: z.number().int(),
  missing_count: z.number().int(),
  unknown_count: z.number().int(),
  unavailable_count: z.number().int(),
  conflicting_count: z.number().int(),
  not_applicable_count: z.number().int(),
  error_count: z.number().int(),
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
  state: z.enum(['measured', 'limited_evidence', 'not_measured', 'excluded']),
  crawl_id: uuid().nullable(),
  score: z.number().nullable(),
  coverage: z.number().nullable(),
  profile_version: z.string(),
  schema_contract_version: z.string(),
  scoring_version: z.string(),
  presentation_version: z.string(),
  analyzer_version: z.string(),
  source_analysis_ids: z.array(uuid()),
  analysis_count: z.number().int(),
  affected_page_count: z.number().int(),
  dimensions: z.array(readinessDimensionSchema),
  limitations: z.array(z.string()),
});

const measurementStateSchema = z.enum(['measured', 'limited_evidence', 'not_measured', 'excluded']);
const dimensionApplicabilitySchema = z.enum(['applicable', 'not_applicable', 'unresolved']);
const searchEligibilitySchema = z.enum(['eligible', 'blocked', 'unknown', 'excluded']);
const acquisitionEligibilityCheckpointSchema = responseObject({
  checkpoint_id: z.literal('acquisition.public_representation'),
  outcome: z.string(),
  reason: z.string(),
  source_task_id: uuid().nullable(),
  source_attempt_id: uuid().nullable(),
  source_artifact_id: uuid().nullable(),
});
const indexEligibilityCheckpointSchema = responseObject({
  checkpoint_id: z.literal('search.indexability'),
  outcome: z.string(),
  reason: z.string(),
  source_analysis_id: uuid().nullable(),
  source_evaluation_id: uuid().nullable(),
});
const searchPolicyEligibilityCheckpointSchema = responseObject({
  checkpoint_id: z.enum(['search.crawler_access', 'search.snippet_access']),
  outcome: z.string(),
  reason: z.string(),
  source_analysis_id: uuid().nullable(),
  source_evaluation_id: uuid().nullable(),
});
const overviewDimensionSchema = responseObject({
  key: z.string(),
  dimension_applicability: dimensionApplicabilitySchema,
  dimension_measurement_state: measurementStateSchema,
  score: z.number().nullable(),
  coverage: z.number().nullable(),
  earned_points: z.number(),
  determinate_points: z.number(),
  expected_points: z.number(),
  determinate_checkpoint_ids: z.array(z.string()),
  checkpoint_families: z.array(z.string()),
  reason: z.string(),
});
const overviewIssueSchema = responseObject({
  rule_id: z.string(),
  finding_class: z.string(),
  severity: z.string(),
  category: z.string(),
  description: z.string(),
  remediation: z.string(),
  affected_pages: z.number().int(),
  eligibility_blocker: z.boolean(),
  impact_band: z.number().int(),
});

export const siteHealthOverviewSchema = responseObject({
  project_id: uuid(),
  crawl_id: uuid(),
  snapshot_id: uuid(),
  search_eligibility: searchEligibilitySchema,
  eligibility_totals: z.record(z.string(), z.number().int()),
  eligibility_reasons: z.array(
    responseObject({
      site_url_id: uuid(),
      state: searchEligibilitySchema,
      checkpoints: z.array(
        z.union([
          acquisitionEligibilityCheckpointSchema,
          indexEligibilityCheckpointSchema,
          searchPolicyEligibilityCheckpointSchema,
        ]),
      ),
    }),
  ),
  technical_integrity_score: z.number().nullable(),
  technical_integrity_coverage: z.number().nullable(),
  technical_integrity_state: measurementStateSchema,
  aeo_readiness_score: z.number().nullable(),
  aeo_measurement_coverage: z.number().nullable(),
  aeo_measurement_state: measurementStateSchema,
  crawl_coverage: responseObject({
    state: z.string(),
    evidence: z.record(z.string(), z.unknown()),
    denominator_kind: z.literal('selected_intended_public_urls'),
  }),
  audited_page_count: z.number().int(),
  selected_page_count: z.number().int(),
  status_counts: z.record(z.string(), z.number().int()),
  aeo_dimensions: z.array(overviewDimensionSchema),
  top_issues: z.array(overviewIssueSchema),
  web_fundamentals: responseObject({
    state: measurementStateSchema,
    areas: z.array(
      responseObject({
        key: z.enum(['accessibility', 'mobile', 'security', 'lab']),
        state: measurementStateSchema,
        coverage: z.number().nullable(),
        passed_count: z.number().int(),
        missing_count: z.number().int(),
        unknown_count: z.number().int(),
        unavailable_count: z.number().int(),
        unavailable_checks: z.array(z.string()),
        top_findings: z.array(
          responseObject({
            rule_id: z.string(),
            title: z.string(),
            remediation: z.string(),
            affected_pages: z.number().int(),
            source_evaluation_ids: z.array(uuid()),
          }),
        ),
      }),
    ),
    field_data: responseObject({
      state: z.literal('unavailable'),
      reason: z.string(),
      lcp: z.number().nullable(),
      inp: z.number().nullable(),
      cls: z.number().nullable(),
    }),
    source_analysis_ids: z.array(uuid()),
    source_artifact_ids: z.array(uuid()),
    source_evaluation_ids: z.array(uuid()),
    limitations: z.array(z.string()),
  }),
  trend: responseObject({ state: z.string(), reason: z.string() }),
  change_summary: responseObject({ state: z.string(), reason: z.string() }),
  limitations: z.array(z.string()),
});

export const siteHealthContentHandoffSchema = responseObject({
  project_id: uuid(),
  crawl_id: uuid(),
  site_url_id: uuid(),
  source_analysis_id: uuid(),
  dimension: z.string(),
  checkpoint_ids: z.array(z.string()),
  finding_class: z.string(),
  observed_evidence: z.array(z.record(z.string(), z.unknown())),
  expected_capability: z.array(z.string()),
  remediation: z.array(z.string()),
  page_kind: z.string(),
  page_traits: z.array(z.string()),
  normalized_url: z.string(),
  scoring_policy_version: z.literal('1'),
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
