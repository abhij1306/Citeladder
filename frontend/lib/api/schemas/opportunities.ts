import { z } from 'zod';
import { cursorPageSchema } from './site-health';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Opportunities (deterministic priority catalog — backend owns the contract)
// ---------------------------------------------------------------------------

// Opportunity vocabulary (config-owned; per-subsystem severity enum — the
// site-health `issueSeveritySchema` is NOT reused, they evolve independently).
export const opportunityTypeSchema = z.enum(['visibility', 'commerce', 'site', 'traffic', 'topic']);
export const opportunitySeveritySchema = z.enum(['critical', 'high', 'medium', 'low', 'info']);
export const opportunityStatusSchema = z.enum(['open', 'in_progress', 'dismissed', 'resolved']);
export const implementationStateSchema = z.enum([
  'declared',
  'observed',
  'verified',
  'contradicted',
]);

// One live opportunity row in the priority-sorted catalog.
export const opportunitySchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  rule_id: z.string(),
  opportunity_type: opportunityTypeSchema,
  severity: opportunitySeveritySchema,
  priority_score: z.number(),
  title: z.string(),
  target_key: z.string(),
  target_prompt_id: uuid().nullable(),
  target_url: z.string().nullable(),
  target_theme: z.string().nullable(),
  // Backend-owned target presentation (url / frozen prompt text / humanized
  // theme / frozen product name); null when nothing user-facing exists.
  target_label: z.string().nullable(),
  status: opportunityStatusSchema,
  system_rank: z.number().int(),
  display_rank: z.number().int(),
  order_source: z.enum(['system', 'manual']),
  priority_factors: z.record(z.string(), z.union([z.string(), z.number()])),
  evidence_summary: responseObject({
    count: z.number().int(),
    kinds: z.array(z.string()),
  }),
  created_at: z.string(),
  updated_at: z.string(),
});

const commandCenterMetricSchema = responseObject({
  value: z.number().nullable(),
  delta: z.number().nullable(),
});

const evidenceStateSchema = responseObject({
  state: z.enum(['observed', 'partial', 'not_run', 'unavailable']),
  observed_at: z.string().nullable(),
  freshness: z.enum(['current', 'unknown']),
  coverage: z.array(z.string()),
  limitations: z.array(z.string()),
});

export const commandCenterSchema = responseObject({
  project: responseObject({
    id: uuid(),
    name: z.string(),
    brand_name: z.string(),
    website_url: z.string(),
  }),
  facts: responseObject({
    industry: z.string(),
    description: z.string(),
    positioning: z.string(),
    products_services: z.array(z.string()),
    target_audience: z.string(),
    competitors: z.array(
      responseObject({ id: uuid(), name: z.string(), domains: z.array(z.string()) }),
    ),
  }),
  loop: responseObject({
    connected: evidenceStateSchema,
    analyzed: evidenceStateSchema,
    acted: evidenceStateSchema,
    tracked: evidenceStateSchema,
  }),
  next_action: responseObject({
    kind: z.enum(['opportunity', 'connect', 'crawl', 'configure_prompts', 'audit', 'monitor']),
    title: z.string(),
    href: z.string(),
    opportunity_id: uuid().nullable(),
  }),
  track: responseObject({
    citation_share: commandCenterMetricSchema,
    engine_coverage: z.number().int(),
    observed_at: z.string().nullable(),
    limitations: z.array(z.string()),
  }),
  measurement: responseObject({
    audit_id: uuid(),
    completed_at: z.string(),
    measurement_mode: z.string(),
    benchmark_mode: z.string(),
    logical_engines: z.array(z.string()),
    comparable_audit_id: uuid().nullable(),
  }).nullable(),
  state: responseObject({
    visibility: commandCenterMetricSchema,
    share_of_voice: commandCenterMetricSchema,
    brand_rank: commandCenterMetricSchema,
  }),
  movements: z.array(
    responseObject({
      label: z.string(),
      direction: z.string(),
      current: z.number().nullable(),
      previous: z.number().nullable(),
      delta: z.number().nullable(),
    }),
  ),
  actions: z.array(opportunitySchema),
  action_order_version: z.number().int(),
  resolved_actions: responseObject({
    since_audit_id: uuid().nullable(),
    count: z.number().int(),
    titles: z.array(z.string()),
  }),
  report_available: z.boolean(),
  stale: z.boolean(),
});

export const opportunityOrderResponseSchema = responseObject({
  version: z.number().int(),
  ordered_opportunity_ids: z.array(uuid()),
});

// Full evidence bundle + provenance for one opportunity. Superseded rows stay
// readable (only the status PATCH is live-only, coded 409).
export const opportunityDetailSchema = opportunitySchema.extend({
  remediation: z.string(),
  evidence: z.record(z.string(), z.unknown()),
  source_analysis_ids: z.array(z.string()),
  source_issue_ids: z.array(z.string()),
  source_metric_ids: z.array(z.string()),
  source_traffic_ids: z.array(z.string()),
  analyzer_version: z.string(),
  rule_version: z.string(),
  formula_version: z.string(),
  superseded_by_id: uuid().nullable(),
  superseded_at: z.string().nullable(),
});

export const opportunitiesPageSchema = cursorPageSchema(opportunitySchema);

// Latest recompute snapshot projection. `computed=false` (with empty counts +
// null ids) before the first recompute — a 200, never a 404.
export const opportunitySummarySchema = responseObject({
  activation_state: z.enum(['waiting_for_evidence', 'queued', 'refreshing', 'ready', 'delayed']),
  computed: z.boolean(),
  run_id: uuid().nullable(),
  audit_id: uuid().nullable(),
  site_crawl_id: uuid().nullable(),
  demand_snapshot_id: uuid().nullable(),
  demand_source_revision: z.string().nullable(),
  coverage: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  counts_by_type: z.record(z.string(), z.number().int()),
  counts_by_severity: z.record(z.string(), z.number().int()),
  counts_by_status: z.record(z.string(), z.number().int()),
  total_count: z.number().int(),
  median_priority: z.number().nullable(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  formula_version: z.string(),
  computed_at: z.string().nullable(),
  // Read-time freshness: newest usable audit/crawl evidence timestamp, and
  // whether it post-dates the latest snapshot (drives the stale badge).
  evidence_updated_at: z.string().nullable(),
  stale: z.boolean(),
});

// The immutable snapshot written by one recompute run (POST response).
export const recomputeResponseSchema = responseObject({
  id: uuid(),
  run_id: uuid(),
  audit_id: uuid().nullable(),
  site_crawl_id: uuid().nullable(),
  demand_snapshot_id: uuid().nullable(),
  demand_source_revision: z.string().nullable(),
  coverage: z.record(z.string(), z.unknown()),
  limitations: z.array(z.string()),
  counts_by_type: z.record(z.string(), z.number().int()),
  counts_by_severity: z.record(z.string(), z.number().int()),
  counts_by_status: z.record(z.string(), z.number().int()),
  total_count: z.number().int(),
  median_priority: z.number().nullable(),
  analyzer_version: z.string(),
  rule_version: z.string(),
  formula_version: z.string(),
  created_at: z.string(),
});

const siteRuleExpectedCheckSchema = responseObject({
  kind: z.literal('site_rule'),
  target_site_url_id: uuid().optional(),
  rule_id: z.string(),
  expected_outcome: z.enum(['pass', 'fail']),
});
const pageFactExpectedCheckSchema = responseObject({
  kind: z.literal('page_fact'),
  target_site_url_id: uuid().optional(),
  fact_key: z.string(),
  expected_value: z.unknown(),
});
const metricExpectedCheckSchema = responseObject({
  kind: z.enum(['visibility_metric', 'traffic_metric']),
  metric: z.string(),
  direction: z.enum(['increase', 'decrease', 'equal']),
  expected_value: z.number(),
  tolerance: z.number(),
});
const expectedCheckSchema = z.discriminatedUnion('kind', [
  siteRuleExpectedCheckSchema,
  pageFactExpectedCheckSchema,
  metricExpectedCheckSchema,
]);

export const implementationEventSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  opportunity_id: uuid(),
  opportunity_snapshot_id: uuid(),
  target_site_url_ids: z.array(uuid()),
  generation_id: uuid().nullable(),
  declared_implemented_at: z.string(),
  expected_checks: z.array(expectedCheckSchema),
  state: implementationStateSchema,
  limitations: z.array(z.string()),
  verification_events: z.array(
    responseObject({
      id: uuid(),
      observation_kind: z.enum(['observed', 'verified', 'contradicted']),
      observed_at: z.string(),
      crawl_id: uuid().nullable(),
      audit_id: uuid().nullable(),
      source_analysis_ids: z.array(uuid()),
      source_rule_evaluation_ids: z.array(uuid()),
      source_metric_ids: z.array(uuid()),
      verifier_version: z.string(),
      limitations: z.array(z.string()),
      created_at: z.string(),
    }),
  ),
  created_at: z.string(),
});

export const implementationEventsPageSchema = responseObject({
  items: z.array(implementationEventSchema),
  next_cursor: z.string().nullable(),
});
