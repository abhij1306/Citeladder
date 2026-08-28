import { z } from 'zod';
import { auditStatusSchema, modelProvenanceSchema } from './audits';
import { promptCohortSchema } from './project';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Visibility dashboard (selected-run projection)
// ---------------------------------------------------------------------------

// One per-engine comparison row for the selected run (B6 `EngineComparisonRow`).
export const visibilityEngineSchema = responseObject({
  logical_engine: z.string(),
  total_completed: z.number().int(),
  brand_mention_rate: z.number().nullable(),
  owned_citation_rate: z.number().nullable(),
  search_use_rate: z.number().nullable(),
  visibility_score: z.number().nullable(),
});

// One brand-vs-competitor rankings-table row (B6 `RankingRow`). `website_url`
// lets BrandLogo use its Logo.dev fallback when the cached `logo_url` is absent.
// `mention_rate` is the Visibility% and `share_of_voice` the SOV%; `sentiment`
// / `avg_position` are null until the roadmap computes them (decision B-2).
export const rankingRowSchema = responseObject({
  name: z.string(),
  is_brand: z.boolean(),
  logo_url: z.string().nullable().optional(),
  website_url: z.string().nullable().optional(),
  mention_rate: z.number().nullable(),
  citation_rate: z.number().nullable(),
  share_of_voice: z.number().nullable(),
  mention_count: z.number().int(),
  sentiment: z.string().nullable(),
  avg_position: z.number().nullable(),
});

// Selected-run dashboard projection (B6 `VisibilityResponse`). Computed
// server-side from the persisted MetricSnapshot for the selected audit
// (defaults to the latest completed audit). No cross-run trend in this payload
// — the Trends tab reads /visibility/trends for that.
export const visibilitySchema = responseObject({
  project_id: uuid(),
  audit_id: uuid(),
  audit_status: auditStatusSchema,
  analyzer_version: z.string(),
  scoring_rule_version: z.string(),
  cohort: promptCohortSchema.default('core'),
  coverage: z.record(z.string(), z.number()).default({}),
  total_completed: z.number().int(),
  total_failed: z.number().int(),
  visibility_score: z.number(),
  // Aggregate surface: never a forced singular model across engines.
  model_provenance: z.array(modelProvenanceSchema).default([]),
  rankings: z.array(rankingRowSchema),
  per_engine: z.array(visibilityEngineSchema),
  sentiment: z.string().nullable(),
  avg_position: z.number().nullable(),
  created_at: z.string(),
});

export const promptMetricItemSchema = responseObject({
  id: uuid(),
  audit_id: uuid(),
  prompt_id: uuid().nullable(),
  prompt_index: z.number().int(),
  prompt_text: z.string(),
  cohort: z.string(),
  composite_score: z.number(),
  previous_score: z.number().nullable(),
  immediate_delta: z.number().nullable(),
  rolling_four: z.array(z.number()),
  per_engine_scores: z.record(z.string(), z.number()),
  components: z.record(z.string(), z.number().nullable()),
  engine_agreement: z.number(),
  repetition_agreement: z.number(),
  evidence_coverage: z.number(),
  trend_confidence: z.number(),
  decline_confirmed: z.boolean(),
  analyzer_version: z.string(),
  scoring_rule_version: z.string(),
  created_at: z.string(),
});

export const observedCompetitorSchema = responseObject({
  id: uuid(),
  audit_id: uuid(),
  name: z.string(),
  domain: z.string(),
  qualification_reason: z.string(),
  prompt_count: z.number().int(),
  engine_count: z.number().int(),
  market_relevant: z.boolean(),
  analyzer_version: z.string(),
  source_analysis_ids: z.array(z.string()),
  source_artifact_ids: z.array(z.string()),
  status: z.string(),
  created_at: z.string(),
});

const discoveryProfileSchema = responseObject({
  description: z.string(),
  positioning: z.string(),
  products_services: z.array(z.string()),
  target_audience: z.string(),
  industry: z.string(),
  business_type: z.enum(['b2b', 'b2c', 'both']),
  price_tier: z.string(),
  field_confidence: z.record(z.string(), z.number()),
  // Resolved business context. `category` and `category_terms` are open
  // vocabulary and carry the specificity; the rest are closed facets that
  // decide which kinds of question get generated.
  category: z.string().default(''),
  category_options: z.array(z.string()).default([]),
  category_aliases: z.array(z.string()).default([]),
  category_terms: z.array(z.string()).default([]),
  jobs_to_be_done: z.array(z.string()).default([]),
  sector: z.string().default('Other'),
  business_model: z.string().default('d2c_product'),
  secondary_business_models: z.array(z.string()).default([]),
  market_scope: z.enum(['global', 'national', 'regional', 'local']).default('national'),
  buyer_register: z.string().default('research_comparative'),
  buyer_roles: z.array(z.string()).default([]),
  service_areas: z.array(z.string()).default([]),
  knowledge_strength: z.enum(['strong', 'weak', 'none']).default('none'),
});

const discoveryPromptSuggestionSchema = responseObject({
  topic_id: uuid(),
  text: z.string(),
  intent: z.enum(['discovery', 'comparison', 'purchase', 'service', 'local']),
  cohort: promptCohortSchema,
});

const discoveryTopicSchema = responseObject({
  topic_id: uuid(),
  name: z.string(),
  description: z.string(),
  // `source_refs` on the wire: the offering entries or fetched pages that
  // supported this topic. Renamed from `evidence_refs` alongside the backend.
  source_refs: z.array(z.string()),
});

const discoveryEvidenceSchema = responseObject({
  source_url: z.string(),
  capture_method: z.string(),
  confidence: z.number(),
  captured_at: z.string(),
  supports: z.array(z.string()),
  provider: z.string(),
  model: z.string(),
  method: z.string(),
});

export const brandDiscoverySchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid().nullable(),
  status: z.enum(['queued', 'running', 'failed', 'ready', 'completing', 'project_created']),
  progress: responseObject({
    phase: z.enum([
      'opening_website',
      'understanding_business',
      'finding_competitors',
      'preparing_review',
      'complete',
    ]),
    completed_steps: z.number().int().nonnegative(),
    total_steps: z.number().int().positive(),
    pages_read: z.number().int().nonnegative(),
    competitors_found: z.number().int().nonnegative(),
    prompts_prepared: z.number().int().nonnegative(),
  }),
  input_data: z.record(z.string(), z.unknown()),
  profile: discoveryProfileSchema,
  domains: z.array(z.string()),
  competitors: z.array(
    responseObject({
      name: z.string(),
      aliases: z.array(z.string()),
      domains: z.array(z.string()),
      qualification: responseObject({
        product_substitutability: z.number(),
        customer_use_case_overlap: z.number(),
        geographic_relevance: z.number(),
        question_visibility: z.number(),
      }).nullable(),
      reasoning: z.string(),
      evidence_urls: z.array(z.string()),
      confidence: z.number(),
    }),
  ),
  topics: z.array(discoveryTopicSchema),
  prompt_suggestions: z.array(discoveryPromptSuggestionSchema),
  evidence: z.array(discoveryEvidenceSchema),
  warnings: z.array(z.string()),
  gaps: z.array(z.string()),
  error_code: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const brandDiscoveryCatalogSchema = responseObject({
  business_types: z.array(z.enum(['b2b', 'b2c', 'both'])),
  price_tiers: z.array(z.string()),
  required_fields: z.array(z.string()),
  optional_fields: z.array(z.string()),
  capture_methods: z.array(z.string()),
  maximum_competitors: z.number().int().positive(),
  industries: z.array(z.string()),
  subindustries: z.record(z.string(), z.array(z.string())),
  prompt_cohorts: z.array(z.string()),
});

// Completion is accepted as a job, not returned as a finished project: the
// portfolio takes minutes to generate and the client gives up on a request
// after 30s. `project_id` is null until the worker lands it, so callers poll
// the discovery and read the id from `project_created`.
export const brandDiscoveryCompleteSchema = responseObject({
  discovery_id: uuid(),
  status: z.enum(['completing', 'project_created', 'failed']),
  project_id: uuid().nullable(),
  crawl_id: uuid().nullable(),
  activation_state: z.enum(['queued']),
  page_limit: z.number().int().positive().nullable(),
  warnings: z.array(z.string()),
});
