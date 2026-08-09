/**
 * zod data contracts (F2) — the frontend's single source of truth for the
 * shape of every backend response it consumes.
 *
 * Contract invariants (docs/frontend-architecture.md §6/§7):
 *   - **Every `id` and `*_id` field is `z.uuid()`.** No numeric ids.
 *   - **No `user_id` anywhere** — the contract is workspace-scoped.
 *   - Provider secrets are **never** present on the wire (BYOK, invariant 6).
 *   - `sentiment` / `avg_position` are nullable (not computed yet; roadmap).
 *   - Validation **fails loud** via `strictValidate` on every DECLARED field —
 *     a missing required field or a wrong type is a bug to fix in the schema
 *     (backend is source of truth), never to swallow. UNKNOWN keys are
 *     stripped (see `responseObject`), so an additive backend field can never
 *     break the UI (ERR-5).
 */
import { z } from 'zod';

/**
 * Response-object contract (drift policy §6): strict on every DECLARED field
 * — a missing required field or a wrong type still fails loud via
 * `strictValidate` — and tolerant of UNKNOWN keys: zod's default `.strip()`
 * drops additive backend fields from the parsed output, so an additive
 * backend deploy can never take a screen down (ERR-5; previously
 * `z.strictObject` rejected any response carrying an undeclared key).
 *
 * Drift no longer breaks the UI, but it is still tracked: the contract-drift
 * guard (`lib/api/contract-drift.ts`, wired into `pnpm test` and runnable as
 * `pnpm check:contract`) FAILS when a declared field disappears from the
 * backend response model and WARNS on additive-only diffs so this file is
 * updated promptly. Request payloads stay strict — they are built from typed
 * TypeScript DTOs at the call site, never parsed with a tolerant schema.
 */
const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);

/** UUID id helper — all ids and foreign keys use this. */
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Auth / workspace
// ---------------------------------------------------------------------------

// Backend `SessionUser.role` is the ACCOUNT-level `User.role` (free-form
// string, defaults to `"user"` — see backend/app/models/user.py). It is a
// different axis from the per-workspace MEMBERSHIP role (`owner`/`member`,
// carried on `workspaceSchema.role` below) and must not be conflated with it
// via a restrictive enum — doing so previously rejected every real register/
// login response (`role: "user"` is not `owner|admin|member|viewer`).
export const sessionUserSchema = responseObject({
  id: uuid(),
  email: z.email(),
  role: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});

// register/login/me all return the authenticated user wrapped as
// `{ user: SessionUser }` (backend `AuthResponse`); the JWT rides the HttpOnly
// cookie, never the body. Fail loud on any extra key.
export const authResponseSchema = responseObject({ user: sessionUserSchema });

// OAuth start scaffold (Phase B backend): a configured provider answers
// `{ authorize_url, state, session_nonce }`; unconfigured providers answer
// 503 before this schema is ever parsed. `session_nonce` is additive — older
// backends omit it, so it parses with a default.
export const oauthStartResponseSchema = responseObject({
  authorize_url: z.string().min(1),
  state: z.string().min(1),
  session_nonce: z.string().default(''),
});

// Backend `WorkspaceResponse` is `{ id, name, role, created_at, updated_at }` —
// no slug; the caller's membership `role` is carried instead.
export const workspaceSchema = responseObject({
  id: uuid(),
  name: z.string(),
  role: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

// Cross-route onboarding tour state belongs to the caller's workspace
// membership, never a project or user id.
export const productTourStatusSchema = z.enum([
  'not_started',
  'in_progress',
  'completed',
  'skipped',
]);

export const productTourSchema = responseObject({
  workspace_id: uuid(),
  version: z.string(),
  status: productTourStatusSchema,
  step_id: z.string().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Brand / project / prompts
// ---------------------------------------------------------------------------

export const competitorSchema = responseObject({
  id: uuid(),
  name: z.string(),
  aliases: z.array(z.string()),
  domains: z.array(z.string()),
  logo_url: z.string().nullable().optional(),
});

// Intent enum. The B3 backend `normalize_intent` casefolds a free-text intent
// and normalizes any empty/unknown value to `''` ("unspecified"), so `''` is a
// valid on-the-wire value and must be accepted here (contract, not UI sugar).
export const promptIntentSchema = z.enum([
  '',
  'discovery',
  'comparison',
  'purchase',
  'service',
  'local',
]);

// Prompt library lifecycle. Measurement still requires an explicit audit run
// or schedule; generated prompts do not need a second approval state.
export const promptStatusSchema = z.enum(['active', 'archived']);
export const promptCohortSchema = z.enum([
  'market_visibility',
  'brand_relevant',
  'brand_diagnostic',
  'core',
  'comparison',
]);

// Backend `PromptResponse.theme` is a non-null string (empty when unset), so
// the wire value is always a string — never null.
export const promptSchema = responseObject({
  id: uuid(),
  prompt_set_id: uuid(),
  topic_id: uuid().nullable().optional(),
  text: z.string(),
  theme: z.string(),
  intent: promptIntentSchema,
  cohort: promptCohortSchema,
  branded: z.boolean(),
  enabled: z.boolean(),
  status: promptStatusSchema,
  origin: z.enum(['manual', 'imported', 'generated']),
  // Provenance for AI-generated prompts (model identity, run id, hashes) —
  // never contains credentials. Null for manual/imported prompts.
  generation_evidence: z.record(z.string(), z.unknown()).nullable().optional(),
  created_at: z.string().optional(),
  updated_at: z.string().optional(),
});

// A topical category grouping prompts within a project (first-class resource;
// counts are per-status projections for the topics rail).
export const topicSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  name: z.string(),
  description: z.string(),
  origin: z.enum(['manual', 'generated']),
  active_count: z.number().int(),
  proposed_count: z.number().int(),
  created_at: z.string(),
  updated_at: z.string(),
});

// `POST /prompt-sets/{id}/generate` result: inserted suggestions, the topics
// they landed in (with refreshed counts), and how many duplicates the DB
// conflict-safe dedupe dropped.
export const promptGenerateResponseSchema = responseObject({
  generated: z.array(promptSchema),
  topics: z.array(topicSchema),
  dropped_duplicates: z.number().int(),
});

export const brandProfileSourceSchema = z.enum(['manual', 'web_evidence', 'ai_suggested']);

const brandProfileFieldSourcesSchema = responseObject({
  description: brandProfileSourceSchema.nullable(),
  positioning: brandProfileSourceSchema.nullable(),
  products_services: brandProfileSourceSchema.nullable(),
  target_audience: brandProfileSourceSchema.nullable(),
});

const brandProfileSourceArtifactsSchema = responseObject({
  description: uuid().nullable(),
  positioning: uuid().nullable(),
  products_services: uuid().nullable(),
  target_audience: uuid().nullable(),
});

export const brandProfileDraftSchema = responseObject({
  description: z.string(),
  positioning: z.string(),
  products_services: z.array(z.string()),
  target_audience: z.string(),
});

export const brandProfileSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid(),
  brand_id: uuid(),
  ...brandProfileDraftSchema.shape,
  sources: brandProfileFieldSourcesSchema,
  source_artifact_ids: brandProfileSourceArtifactsSchema,
  created_at: z.string(),
  updated_at: z.string(),
});

export const promptSetSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  name: z.string(),
  // B3 PromptSetResponse carries a description and a denormalized prompt_count.
  description: z.string().optional(),
  prompt_count: z.number().int().optional(),
  prompts: z.array(promptSchema),
  created_at: z.string(),
  updated_at: z.string(),
});

export const benchmarkModeSchema = z.enum([
  'consumer_like',
  'controlled_localized',
  'forced_grounded',
]);

export const projectSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  name: z.string(),
  brand_name: z.string(),
  website_url: z.string(),
  industry: z.string(),
  subindustry: z.string(),
  primary_market: z.string(),
  country_code: z.string(),
  language_code: z.string(),
  benchmark_mode: benchmarkModeSchema,
  default_repetitions: z.number().int(),
  brand: responseObject({
    aliases: z.array(z.string()),
    logo_url: z.string().nullable().optional(),
  }),
  owned_domains: z.array(z.string()),
  unintended_domains: z.array(z.string()),
  competitors: z.array(competitorSchema),
  prompt_sets: z.array(promptSetSchema),
  created_at: z.string(),
  updated_at: z.string(),
});

// ---------------------------------------------------------------------------
// Providers (BYOK) — secret never present
// ---------------------------------------------------------------------------

// The complete BYOK transport surface exposed by the provider catalog.
export const transportProviderSchema = z.enum(['openai', 'anthropic', 'google']);
export const logicalEngineSchema = z.enum(['chatgpt', 'gemini', 'claude']);

// A configured route on a connection: which logical engine this transport
// serves and the concrete transport model to call.
export const providerRouteSchema = responseObject({
  id: uuid(),
  logical_engine: logicalEngineSchema,
  transport_provider: transportProviderSchema,
  transport_model: z.string(),
  is_default: z.boolean(),
  // Backend defaults to true.
  active: z.boolean().optional(),
});

// Strict: an unexpected key (e.g. a leaked `api_key`/`secret`) is a contract
// violation and must fail loud — the secret is never present on the wire.
export const providerConnectionSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  // Optional so the pre-B4 minimal shape (used in the schema test) still
  // validates; the live B4 DTO always sends these.
  label: z.string().nullable().optional(),
  transport_provider: transportProviderSchema,
  base_url: z.string().nullable(),
  active: z.boolean(),
  // Presence flag only — the key value itself is NEVER on the wire.
  api_key_set: z.boolean().optional(),
  last_tested_at: z.string().nullable().optional(),
  // Backend defaults to '' (untested); accept any short status string.
  last_test_status: z.string().optional(),
  routes: z.array(providerRouteSchema).optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

const providerCatalogRouteSchema = responseObject({
  measurement_mode: z.enum(['pulse', 'benchmark']),
  transport_provider: transportProviderSchema,
  transport_model: z.string(),
  retrieval_enabled: z.boolean(),
  reasoning_effort: z.string(),
});

const providerCatalogEngineSchema = responseObject({
  logical_engine: logicalEngineSchema,
  routes: z.array(providerCatalogRouteSchema),
});

export const providerCatalogSchema = responseObject({
  transports: z.array(transportProviderSchema),
  engines: z.array(providerCatalogEngineSchema),
});

// `POST /provider-connections/{id}/test`. Lives here with every other response
// contract rather than beside the caller, and locks `status` to the two values
// the backend actually emits so a probe outcome cannot be a free string.
export const connectionTestResultSchema = responseObject({
  connection_id: uuid(),
  status: z.enum(['ok', 'failed']),
  error_code: z.string().default(''),
  detail: z.string().default(''),
  latency_ms: z.number().nullable().default(null),
  logical_engine: z.string().default(''),
  transport_provider: z.string().default(''),
  transport_model: z.string().default(''),
  tested_at: z.string(),
});

// ---------------------------------------------------------------------------
// Audits (runs) + executions + evidence
// ---------------------------------------------------------------------------

export const auditStatusSchema = z.enum([
  'draft',
  'validating',
  'queued',
  'running',
  'analyzing',
  'reporting',
  'completed',
  'partially_completed',
  'failed',
  'cancelled',
]);

// The engine provenance a run froze at launch (B5 `AuditEngineSnapshotResponse`).
export const auditEngineSnapshotSchema = responseObject({
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
});

// Frozen shopping-surface identity (B5 `AuditShoppingSurfaceSnapshotResponse`;
// empty list while the shopping-surface gate is off).
export const auditShoppingSurfaceSnapshotSchema = responseObject({
  shopping_surface: z.string(),
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
});

/**
 * Canonical measurement mode. This is an axis INDEPENDENT of `benchmark_mode`
 * (prompt framing): it selects the frozen route/output policy. `''` means the
 * run predates the frozen policy block — render it as unknown, never as a
 * default mode.
 */
export const measurementModeSchema = z.enum(['pulse', 'benchmark', '']);

/**
 * One measured route on an AGGREGATE surface. Aggregates carry a LIST of these
 * in stable catalog order and must never be collapsed into a single model:
 * `retrieval_enabled: null` means the audit predates the frozen policy, not
 * "retrieval off".
 */
export const modelProvenanceSchema = responseObject({
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
  retrieval_enabled: z.boolean().nullable(),
});

// A run/audit projection (B5 `AuditResponse`). `random_seed` is a decimal
// STRING (64-bit seed), `error_message` a non-null string ('' when unset), and
// the engine provenance is carried but the provider key never is (invariant 6).
export const auditSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid(),
  status: auditStatusSchema,
  benchmark_mode: z.string(),
  // Aggregate surface: the frozen mode column plus every measured route.
  measurement_mode: measurementModeSchema.default(''),
  model_provenance: z.array(modelProvenanceSchema).default([]),
  repetitions: z.number().int(),
  random_seed: z.string(),
  requested_count: z.number().int(),
  completed_count: z.number().int(),
  failed_count: z.number().int(),
  error_message: z.string(),
  engine_snapshots: z.array(auditEngineSnapshotSchema),
  shopping_surface_snapshots: z.array(auditShoppingSurfaceSnapshotSchema).default([]),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
});

export const auditScheduleCadenceSchema = z.enum([
  'one_time',
  'every_n_minutes',
  'hourly',
  'daily',
  'weekly',
]);

export const auditScheduleSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid(),
  prompt_set_id: uuid(),
  cadence: auditScheduleCadenceSchema,
  interval_minutes: z.number().int().nullable(),
  timezone: z.string(),
  engines: z.array(logicalEngineSchema),
  repetitions: z.number().int().nullable(),
  benchmark_mode: benchmarkModeSchema.nullable(),
  measurement_mode: z.enum(['pulse', 'benchmark']),
  enabled: z.boolean(),
  next_run_at: z.string().nullable(),
  last_run_at: z.string().nullable(),
  failure_count: z.number().int(),
  last_error: z.string(),
  last_failure_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const auditEngineEstimateSchema = responseObject({
  logical_engine: logicalEngineSchema,
  transport_provider: transportProviderSchema,
  transport_model: z.string(),
  retrieval_enabled: z.boolean(),
  prompt_count: z.number().int(),
  repetition_count: z.number().int(),
  execution_count: z.number().int(),
  maximum_attempt_count: z.number().int(),
  estimated_input_tokens: z.number().int(),
  estimated_output_tokens: z.number().int(),
  estimated_search_calls: z.number().int().nullable(),
  estimated_token_cost_microusd: z.number().int().nullable(),
  estimated_search_cost_microusd: z.number().int().nullable(),
  estimated_total_cost_microusd: z.number().int().nullable(),
  cost_status: z.enum(['complete', 'partial', 'unknown']),
  pricing_version: z.string(),
});

export const auditEstimateSchema = responseObject({
  measurement_mode: measurementModeSchema,
  retrieval_enabled: z.boolean(),
  prompt_count: z.number().int(),
  engine_count: z.number().int(),
  repetition_count: z.number().int(),
  execution_count: z.number().int(),
  maximum_attempt_count: z.number().int(),
  maximum_wall_clock_seconds: z.number().int(),
  cost_status: z.enum(['complete', 'partial', 'unknown']),
  estimated_total_cost_microusd: z.number().int().nullable(),
  engines: z.array(auditEngineEstimateSchema),
});

// Deterministic citation classification (B6 `_classification`, invariant 4):
// owned / unintended (owned-but-unwanted) / competitor / third-party.
export const citationClassificationSchema = z.enum([
  'owned',
  'unintended',
  'competitor',
  'third_party',
]);

// One classified source citation on the evidence card (B6 `CitationEvidence`).
export const citationSchema = responseObject({
  ordinal: z.number().int(),
  url: z.string(),
  title: z.string(),
  domain: z.string(),
  classification: citationClassificationSchema,
  is_owned: z.boolean(),
  is_unintended: z.boolean(),
  matched_competitor: z.string().nullable(),
});

// Queue/execution row status (B5 task statuses).
export const executionStatusSchema = z.enum([
  'queued',
  'leased',
  'running',
  'succeeded',
  'retry_wait',
  'failed',
  'cancelled',
]);

// One execution/queue row in the run's executions table (B5 `AuditTaskResponse`).
// `answer_text` / `error_detail` default to '' (never null); the classified
// citation evidence lives on the single-execution evidence endpoint below.
export const executionSchema = responseObject({
  id: uuid(),
  audit_id: uuid(),
  prompt_index: z.number().int(),
  repetition: z.number().int(),
  randomized_position: z.number().int(),
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
  // Frozen shopping-surface identity per task (B5; additive — older backends
  // omit it, so it parses with a default like `shopping_surface_snapshots`).
  shopping_surface: z.string().default(''),
  // Execution surface: the provenance triple is SINGULAR (one execution = one
  // exact model), projected from the frozen task snapshots only.
  measurement_mode: measurementModeSchema.default(''),
  retrieval_enabled: z.boolean().nullable().default(null),
  status: executionStatusSchema,
  attempt_count: z.number().int(),
  max_attempts: z.number().int(),
  prompt_text: z.string(),
  answer_text: z.string(),
  search_used: z.boolean(),
  error_code: z.string(),
  error_detail: z.string(),
  latency_ms: z.number().nullable(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
});

// One execution's persisted analysis + evidence (B6 `ExecutionEvidenceResponse`,
// `GET /executions/{id}`). `id`/`task_id` are the EXECUTION (AuditTask) id — the
// same id space as the executions list — so the evidence page keys off the row
// id. `analysis_id` is the internal ResponseAnalysis id (traceability only).
// `sentiment` / `avg_position` are present but null until the roadmap (B-2).
export const executionEvidenceSchema = responseObject({
  id: uuid(),
  analysis_id: uuid(),
  audit_id: uuid(),
  task_id: uuid(),
  artifact_id: uuid().nullable(),
  analyzer_version: z.string(),
  scoring_rule_version: z.string(),
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
  // Execution-level surface: singular model, frozen snapshots only.
  measurement_mode: measurementModeSchema.default(''),
  retrieval_enabled: z.boolean().nullable().default(null),
  prompt_index: z.number().int(),
  repetition: z.number().int(),
  prompt_class: z.string(),
  brand_mentioned: z.boolean(),
  brand_first_offset: z.number().int().nullable(),
  owned_domain_cited: z.boolean(),
  owned_citation_count: z.number().int(),
  unintended_domain_cited: z.boolean(),
  citation_count: z.number().int(),
  search_used: z.boolean(),
  search_query_count: z.number().int(),
  sentiment: z.string().nullable(),
  avg_position: z.number().nullable(),
  score: z.record(z.string(), z.unknown()).nullable(),
  citations: z.array(citationSchema),
  competitors_mentioned: z.array(z.string()),
  created_at: z.string(),
});

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
  measurement_mode: measurementModeSchema.default(''),
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
});

const discoveryPromptSuggestionSchema = responseObject({
  text: z.string(),
  theme: z.string().default(''),
  intent: z.enum(['discovery', 'comparison', 'purchase', 'service', 'local']),
  cohort: z.enum(['market_visibility', 'brand_relevant']),
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
  status: z.enum(['queued', 'running', 'failed', 'ready', 'project_created']),
  progress: responseObject({
    phase: z.enum([
      'opening_website',
      'understanding_business',
      'finding_competitors',
      'building_questions',
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
  topics: z.array(z.string()),
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

export const brandDiscoveryCompleteSchema = responseObject({
  project_id: uuid(),
  crawl_id: uuid().nullable(),
  activation_state: z.enum(['queued']),
  page_limit: z.number().int().positive().nullable(),
  warnings: z.array(z.string()),
});

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
export const industryRoleManifestSchema = responseObject({
  catalog_version: z.string(),
  pack_id: z.string(),
  pack_version: z.string(),
  pack_content_hash: z.string(),
  classifier_version: z.string(),
});

// Pack-governed industry role for one page. Role IDs are pack-defined strings
// (`education.admissions_overview`), never a fixed frontend enum: a new pack
// must not require a frontend release, and an unrecognized ID must render as
// its raw ID rather than as an invented label.
export const industryRoleSchema = responseObject({
  role_id: z.string().nullable(),
  score: z.number().nullable(),
  winner_margin: z.number().nullable(),
  confidence_band: z.string(),
  secondary_role_ids: z.array(z.string()),
  // Non-null only for an EXECUTED abstention (the classifier ran and declined).
  abstention_reason: z.string().nullable(),
  temporal_state: z.string(),
  corpus_disposition: z.string(),
  evidence: z.array(z.record(z.string(), z.unknown())),
  alternatives: z.array(z.record(z.string(), z.unknown())),
  conflicts: z.array(z.record(z.string(), z.unknown())),
  manifest: industryRoleManifestSchema,
});

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
  industry_role_id: z.string().nullable().optional(),
  role_abstention_reason: z.string().nullable().optional(),
  industry_role_confidence: z.string().optional(),
  corpus_disposition: z.string().optional(),
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
  dimension: issueDimensionSchema,
  category: z.string(),
  severity: issueSeveritySchema,
  title: z.string(),
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
  title: z.string(),
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
  industry_role: industryRoleSchema.nullable().optional(),
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
  title: z.string(),
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
  quota: monitoredQuotaSchema,
  // B3: same root-failure projection as the pages response — the failed
  // crawl's dashboard renders the failure block without a second fetch.
  root_errors: z.array(rootErrorSchema),
  phase_runs: responseObject({
    discovery: phaseRunSchema.nullable(),
    analysis: phaseRunSchema.nullable(),
  }),
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

// ---------------------------------------------------------------------------
// Cross-run Visibility trend history (projection over persisted snapshots)
// ---------------------------------------------------------------------------

// Both Share-of-Voice definitions for one trend point (B backend
// `VisibilityTrendSov`). `response` is the response-level SOV (brand
// response-presence share vs competitors); `mention` is the mention-level SOV
// derived from the persisted `share_of_voice.mention_counts`. Both are
// deterministic reprojections of persisted metrics (invariant 7) and are
// nullable when the source metric is absent.
export const visibilityTrendSovSchema = responseObject({
  response: z.number().nullable(),
  mention: z.number().nullable(),
});

// One brand-vs-competitor ranking-history row within a trend point (backend
// `VisibilityTrendRankingRow`). Field-for-field identical to `rankingRowSchema`
// — aliased so the two contracts can't drift apart silently.
export const visibilityTrendRankingRowSchema = rankingRowSchema;

// One point in the cross-run Visibility trend (backend `VisibilityTrendPoint`).
// A raw per-run point carries a set `audit_id`; a week/month bucket folds many
// snapshots (`audit_id` is null) and carries the full provenance list. Version
// metadata lists every distinct analyzer/scoring version the point folds, with
// `spans_version_boundary` set when a bucket mixes versions. `sentiment` /
// `avg_position` stay null (decision B-2 / invariant 9).
export const visibilityTrendPointSchema = responseObject({
  audit_id: uuid().nullable(),
  completed_at: z.string(),
  logical_engine: z.string().nullable(),
  visibility_score: z.number().nullable(),
  brand_mention_rate: z.number().nullable(),
  owned_citation_rate: z.number().nullable(),
  sov: visibilityTrendSovSchema,
  rankings: z.array(visibilityTrendRankingRowSchema),
  sentiment: z.string().nullable(),
  avg_position: z.number().nullable(),
  // Measurement identity partition (invariant 7): a point folds only inside
  // one (measurement_mode, transport_model, retrieval_enabled) identity, so
  // the client must never recombine points across these. `transport_model` is
  // null when the point spans several models — see `model_provenance`.
  measurement_mode: measurementModeSchema.default(''),
  transport_model: z.string().nullable().default(null),
  retrieval_enabled: z.boolean().nullable().default(null),
  model_provenance: z.array(modelProvenanceSchema).default([]),
  // Provenance (invariant 4): every source snapshot this point folds.
  source_snapshot_ids: z.array(uuid()),
  // Distinct versions across the folded snapshots (invariant 4).
  analyzer_versions: z.array(z.string()),
  scoring_rule_versions: z.array(z.string()),
  spans_version_boundary: z.boolean(),
});

// The trends endpoint returns a chronological list of points (never wrapped).
export const visibilityTrendListSchema = z.array(visibilityTrendPointSchema);

// ---------------------------------------------------------------------------
// Execution-evidence projection (Mentions & Citations + Query Fanout tabs)
// `GET /projects/{id}/visibility/evidence`. A pure read projection over already
// persisted mention/citation/task/artifact rows — nothing is inferred or
// backfilled at read time (invariant 7).
// ---------------------------------------------------------------------------

// Three-state query-fanout availability for one execution (backend
// `VisibilityFanoutState`): `queries_available` (≥1 stored event has non-blank
// query text), `count_only` (search used / count positive but no query text —
// e.g. a legacy count-only row), `no_search` (neither signal present).
export const visibilityFanoutStateSchema = z.enum(['queries_available', 'count_only', 'no_search']);

// One normalized stored search event (backend `VisibilityEvidenceSearchEvent`).
// Empty query strings are preserved verbatim (a count-only event); query text
// is never invented.
export const visibilityEvidenceSearchEventSchema = responseObject({
  sequence: z.number().int(),
  query: z.string(),
  call_id: z.string(),
  call_sequence: z.number().int(),
  query_sequence: z.number().int(),
});

// One persisted brand/competitor mention row (backend
// `VisibilityMentionEvidence`). Projected directly from `BrandMention` /
// `CompetitorMention`; never inferred from answer text at read time.
export const visibilityMentionEvidenceSchema = responseObject({
  kind: z.enum(['brand', 'competitor']),
  name: z.string(),
  first_offset: z.number().int().nullable(),
  artifact_id: uuid().nullable(),
  analyzer_version: z.string(),
});

// One execution's persisted mention/citation + query-fanout evidence (backend
// `VisibilityExecutionEvidence`). `prompt_id` is nullable so a deleted source
// prompt stays readable via its frozen `prompt_text`; `completed_at` is
// nullable for an incomplete/legacy row.
export const visibilityExecutionEvidenceSchema = responseObject({
  audit_id: uuid(),
  task_id: uuid(),
  analysis_id: uuid(),
  artifact_id: uuid().nullable(),
  prompt_snapshot_id: uuid(),
  prompt_id: uuid().nullable(),
  prompt_index: z.number().int(),
  prompt_text: z.string(),
  repetition: z.number().int(),
  completed_at: z.string().nullable(),
  logical_engine: z.string(),
  transport_provider: z.string(),
  transport_model: z.string(),
  // Execution-level surface (singular model).
  measurement_mode: measurementModeSchema.default(''),
  retrieval_enabled: z.boolean().nullable().default(null),
  search_used: z.boolean(),
  search_query_count: z.number().int(),
  query_text_available: z.boolean(),
  state: visibilityFanoutStateSchema,
  search_events: z.array(visibilityEvidenceSearchEventSchema),
  event_source: z.enum(['raw_artifact', 'audit_task', 'none']),
  mentions: z.array(visibilityMentionEvidenceSchema),
  citations: z.array(citationSchema),
});

// The shared evidence dataset for the two evidence tabs (backend
// `VisibilityEvidenceResponse`). `items` is newest-first; `truncated` is set
// when more than `limit` matches exist (no offset/cursor/total).
export const visibilityEvidenceResponseSchema = responseObject({
  items: z.array(visibilityExecutionEvidenceSchema),
  truncated: z.boolean(),
});

// ---------------------------------------------------------------------------
// Content generation
// ---------------------------------------------------------------------------

// Generic queue-row lifecycle (backend `task_queue.TASK_STATUS_*`): the
// content row IS the queue row (AuditTask pattern), so the wire statuses are
// the queue statuses. `leased`/`running`/`retry_wait` are all "in flight"
// from the UI's perspective; terminal = succeeded | failed | cancelled.
export const contentGenerationStatusSchema = z.enum([
  'queued',
  'leased',
  'running',
  'succeeded',
  'retry_wait',
  'failed',
  'cancelled',
]);

// Frozen on the row at enqueue: whether Website context was projected in,
// unavailable (no usable crawl evidence), or turned off by the user.
export const websiteContextStatusSchema = z.enum(['included', 'unavailable', 'disabled']);

export const contentOutputTypeSchema = z.enum(['website_page']);
export const contentSkillSchema = z.enum([
  'youtube',
  'reddit',
  'blog',
  'article',
  'faq_visible',
  'faq_jsonld',
  'answer_first',
  'page_refresh',
  'comparison',
  'guide',
  'education_admissions',
  'education_program',
  'commerce_category',
  'commerce_pdp',
  'commerce_policy',
  'internal_links',
]);

// Provenance for the frozen Website-context snapshot (backend
// `WebsiteContextSummary`) — which crawl, how fresh, which sources. Never
// page bodies, never the key.
export const websiteContextSummarySchema = responseObject({
  crawl_id: uuid(),
  crawl_completed_at: z.string().nullable(),
  extractor_version: z.string(),
  analyzer_version: z.string(),
  page_count: z.number().int(),
  char_count: z.number().int(),
  site_url_ids: z.array(uuid()),
  artifact_ids: z.array(uuid()),
  content_hashes: z.array(z.string()),
});

// Bounded history-list projection (backend `ContentGenerationListItem`) —
// never `output_text`, never the full prompt. Model provenance is explicit
// (`requested_model` vs `returned_model`); there is no generic `model` field.
export const contentGenerationListItemSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  status: contentGenerationStatusSchema,
  output_type: contentOutputTypeSchema,
  skill_id: contentSkillSchema,
  opportunity_id: uuid().nullable(),
  brief_id: uuid().nullable(),
  context_package_id: uuid().nullable(),
  website_context_status: websiteContextStatusSchema,
  requested_model: z.string(),
  returned_model: z.string().nullable(),
  provider: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
  error_code: z.string(),
  prompt_preview: z.string(),
});

// Full projection of one generation (backend `ContentGenerationDetail`).
// Superset of the list item; never the provider API key (invariant 6).
export const contentGenerationDetailSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  status: contentGenerationStatusSchema,
  output_type: contentOutputTypeSchema,
  skill_id: contentSkillSchema,
  opportunity_id: uuid().nullable(),
  brief_id: uuid().nullable(),
  context_package_id: uuid().nullable(),
  skill_version: z.string(),
  evidence_context: z.record(z.string(), z.unknown()).nullable(),
  feedback: z.enum(['accepted', 'rejected']).nullable(),
  feedback_at: z.string().nullable(),
  website_context_status: websiteContextStatusSchema,
  requested_model: z.string(),
  returned_model: z.string().nullable(),
  provider: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
  error_code: z.string(),
  prompt_preview: z.string(),
  prompt: z.string(),
  website_context_enabled: z.boolean(),
  website_context_summary: websiteContextSummarySchema.nullable(),
  finish_reason: z.string().nullable(),
  output_truncated: z.boolean(),
  output_text: z.string().nullable(),
  usage: z.record(z.string(), z.unknown()).nullable(),
  latency_ms: z.number().int().nullable(),
  error_detail: z.string(),
  generator_version: z.string(),
  validator_snapshot: z.record(z.string(), z.unknown()).nullable(),
});

const jsonRecordSchema = z.record(z.string(), z.unknown());

export const contentStrategySchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  project_id: uuid(),
  site_snapshot_id: uuid(),
  demand_snapshot_id: uuid().nullable(),
  source_hash: z.string(),
  industry_pack_id: z.string(),
  industry_pack_version: z.string(),
  inventory_summary: jsonRecordSchema,
  coverage: jsonRecordSchema,
  priorities: z.array(jsonRecordSchema),
  program: z.array(jsonRecordSchema),
  limitations: z.array(z.unknown()),
  source_versions: jsonRecordSchema,
  created_at: z.string(),
});

export const contentInventoryItemSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  site_snapshot_id: uuid(),
  site_analysis_id: uuid(),
  site_url_id: uuid(),
  canonical_url: z.string(),
  page_kind: z.string(),
  industry_role_id: z.string().nullable(),
  temporal_state: z.string(),
  purpose: jsonRecordSchema,
  coverage: jsonRecordSchema,
  evidence: jsonRecordSchema,
  source_versions: jsonRecordSchema,
  created_at: z.string(),
});

export const contentBriefSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  strategy_snapshot_id: uuid().nullable(),
  prior_brief_id: uuid().nullable(),
  version: z.number().int().positive(),
  identity_hash: z.string(),
  kind: z.string(),
  title: z.string(),
  target: jsonRecordSchema,
  requirements: jsonRecordSchema,
  allowed_facts: z.array(jsonRecordSchema),
  prohibited_claims: z.array(jsonRecordSchema),
  source_refs: z.array(jsonRecordSchema),
  verification_criteria: z.array(jsonRecordSchema),
  industry_pack_id: z.string(),
  industry_pack_version: z.string(),
  brief_builder_version: z.string(),
  evidence_hash: z.string(),
  created_at: z.string(),
});

export const taskContextPackageSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  brief_id: uuid(),
  task_type: z.string(),
  manifest: jsonRecordSchema,
  rendered_context: jsonRecordSchema,
  omissions: z.array(jsonRecordSchema),
  selection_policy_version: z.string(),
  manifest_hash: z.string(),
  char_count: z.number().int().nonnegative(),
  created_at: z.string(),
});

export const contentValidationCheckSchema = responseObject({
  check_id: z.string(),
  passed: z.boolean(),
  blocking: z.boolean(),
  message: z.string(),
  evidence: z.array(z.unknown()),
});

export const contentValidationSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  content_generation_id: uuid(),
  status: z.enum(['passed', 'blocked']),
  blocking: z.boolean(),
  checks: z.array(contentValidationCheckSchema),
  validator_version: z.string(),
  brief_evidence_hash: z.string(),
  context_manifest_hash: z.string(),
  created_at: z.string(),
});

export const contentRevisionSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  content_generation_id: uuid(),
  state: z.enum(['draft', 'edited', 'saved', 'published_claimed', 'discarded']),
  visible_content: z.string(),
  structured_data: jsonRecordSchema.nullable(),
  content_hash: z.string(),
  validation_snapshot: jsonRecordSchema,
  publication_target_url: z.string(),
  publication_claimed_at: z.string().nullable(),
  saved_at: z.string().nullable(),
  created_by_user_id: uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

export const contentVerificationSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  revision_id: uuid(),
  site_snapshot_id: uuid(),
  demand_snapshot_id: uuid().nullable(),
  status: z.enum(['observed', 'partial', 'absent', 'materially_different']),
  requirements: z.array(jsonRecordSchema),
  comparison: jsonRecordSchema,
  coverage: jsonRecordSchema,
  verifier_version: z.string(),
  created_at: z.string(),
});

// ---------------------------------------------------------------------------
// Integrations (GSC / GA4 / Bing), Traffic, and LLM Analytics
//
// Contract source: `docs/integrations-traffic-analytics.md`
// (§2 contracts C2–C4, §5 F1–F3) + specs `docs/roadmap/integrations.md`,
// `docs/roadmap/traffic.md`, `docs/roadmap/llm-analytics.md`. Every object is
// `.strict()` so an unexpected key fails loud (drift policy §6). No token field
// ever appears on a connection DTO — a leaked `access_token` / `refresh_token`
// is a contract violation that must throw (invariant 6).
// ---------------------------------------------------------------------------

// Logical integration providers (the surfaces a workspace connects).
export const integrationProviderSchema = z.enum(['gsc', 'ga4', 'bing']);

// Grant lifecycle (`IntegrationOAuthGrant.status`). `pending_revocation` is
// disconnect-requested with the remote revoke not yet confirmed (encrypted
// tokens deliberately retained); `revoked` is fully torn down.
export const integrationGrantStatusSchema = z.enum([
  'connected',
  'needs_reauth',
  'pending_revocation',
  'revoked',
  'error',
]);

// Why a sync run was enqueued (`IntegrationSyncRun.sync_kind`).
export const integrationSyncKindSchema = z.enum(['scheduled', 'on_demand', 'backfill']);

// `IntegrationSyncRun` IS a queue row (same shared queue-row contract as
// `AuditTask` / `SiteCrawlTask` / `ContentGeneration`), so the wire statuses
// are the queue statuses — the same vocabulary as
// `siteCrawlTaskStatusSchema` / `contentGenerationStatusSchema`.
export const integrationSyncRunStatusSchema = z.enum([
  'queued',
  'leased',
  'running',
  'retry_wait',
  'succeeded',
  'failed',
  'cancelled',
]);

// `GET /integrations` row: a connection joined to its grant's status +
// granted scopes. Tokens live encrypted on the grant and are NEVER serialized
// (invariant 6) — any `*_token` key on the wire fails strict validation.
export const integrationConnectionSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  grant_id: uuid(),
  provider: integrationProviderSchema,
  label: z.string(),
  account_ref: z.string(),
  grant_status: integrationGrantStatusSchema,
  granted_scopes: z.array(z.string()),
  last_synced_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});

// The list endpoint returns a bare array of connections (never wrapped).
export const integrationConnectionListSchema = z.array(integrationConnectionSchema);

// `POST /integrations/{id}/test` — cheap authenticated probe result (status +
// error_code, never the token). `error_code` is '' on success.
export const integrationTestResultSchema = responseObject({
  connection_id: uuid(),
  status: z.string(),
  error_code: z.string(),
  detail: z.string(),
  tested_at: z.string(),
});

// Sync-run history/detail projection (status, window, row counts — invariant
// 7: a read-only projection of the queue row). `row_count` is the number of
// imported rows; `error_code` / `error_detail` are '' when there is no error.
export const integrationSyncRunSchema = responseObject({
  id: uuid(),
  connection_id: uuid(),
  sync_kind: integrationSyncKindSchema,
  status: integrationSyncRunStatusSchema,
  window_start: z.string(),
  window_end: z.string(),
  row_count: z.number().int(),
  resync_seq: z.number().int(),
  error_code: z.string(),
  error_detail: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
});

// `GET /integrations/{id}/syncs` — bare array of run projections.
export const integrationSyncRunListSchema = z.array(integrationSyncRunSchema);

// `GET /integrations/{id}/properties` — the provider properties this grant can
// read, for the property picker. Discovery output, not stored state:
// `property_ref` is the canonical ref posted back to create a mapping
// (a GSC siteUrl, a bare GA4 numeric id); `label` is display-only.
export const integrationPropertySchema = responseObject({
  property_ref: z.string(),
  label: z.string(),
});

export const integrationPropertyListSchema = z.array(integrationPropertySchema);

// `GET|POST /integrations/{id}/mappings` — the property→project bridge that
// tells a sync WHICH property to pull and which project owns the rows.
export const integrationPropertyMappingSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  connection_id: uuid(),
  provider: integrationProviderSchema,
  property_ref: z.string(),
  project_id: uuid(),
  status: z.enum(['active', 'disabled']),
  created_at: z.string(),
  updated_at: z.string(),
});

export const integrationPropertyMappingListSchema = z.array(integrationPropertyMappingSchema);

// 202 enqueue identity (C3) — one per queued run. The frontend polls
// `GET /integrations/{connection_id}/syncs/{sync_run_id}` until terminal.
export const integrationSyncEnqueueSchema = responseObject({
  sync_run_id: uuid(),
  connection_id: uuid(),
  status: integrationSyncRunStatusSchema,
});

// `POST /projects/{id}/traffic/sync` fans out to every active mapped GSC/GA4
// connection of the project, so the 202 carries one C3 enqueue object per
// queued run — a bare array ("{sync_run_id, connection_id, status} per run").
export const trafficSyncEnqueueResponseSchema = z.array(integrationSyncEnqueueSchema);

// ---------------------------------------------------------------------------
// Traffic (projection over persisted TrafficSnapshot / stat rows — no
// read-time recomputation and no provider calls anywhere, invariant 7)
// ---------------------------------------------------------------------------

// Snapshot bucket granularity shared by the Traffic and LLM Analytics
// projections (`TrafficSnapshot` / `AnalyticsSnapshot.granularity`).
export const snapshotGranularitySchema = z.enum(['day', 'week', 'month']);

// One dated point of a metric series. A `null` value is an UNAVAILABLE bucket
// and renders as a chart gap — never coerced to a misleading zero.
export const metricSeriesPointSchema = responseObject({
  date: z.string(),
  value: z.number().nullable(),
});

export const metricSeriesSchema = z.array(metricSeriesPointSchema);

// Window totals. `ctr` / `position` are null when undefined (zero
// impressions); `sessions` / `conversions` are null when no GA4 connection
// feeds the window — the frontend never invents a number.
export const trafficTotalsSchema = responseObject({
  impressions: z.number().int(),
  clicks: z.number().int(),
  ctr: z.number().nullable(),
  position: z.number().nullable(),
  sessions: z.number().int().nullable(),
  conversions: z.number().int().nullable(),
});

// `GET /projects/{id}/traffic` — headline projection for the persisted
// snapshot matching (window, granularity). An absent snapshot yields an empty
// payload (empty series, zeroed/null totals), never a recomputation.
export const trafficDashboardSchema = responseObject({
  project_id: uuid(),
  window_start: z.string(),
  window_end: z.string(),
  granularity: snapshotGranularitySchema,
  totals: trafficTotalsSchema,
  series: responseObject({
    impressions: metricSeriesSchema,
    clicks: metricSeriesSchema,
    ctr: metricSeriesSchema,
    position: metricSeriesSchema,
    sessions: metricSeriesSchema,
    conversions: metricSeriesSchema,
  }),
  formula_version: z.string(),
  normalization_version: z.string(),
});

// One persisted per-page stat row (`TrafficPageStat`). `site_url_id` is the
// optional join to the crawled SiteUrl (SET NULL — unmatched pages are still
// valid measured pages). Metrics carry the same nullability as the totals.
export const trafficPageRowSchema = responseObject({
  canonical_url: z.string(),
  site_url_id: uuid().nullable(),
  impressions: z.number().int(),
  clicks: z.number().int(),
  ctr: z.number().nullable(),
  position: z.number().nullable(),
  sessions: z.number().int().nullable(),
  conversions: z.number().int().nullable(),
});

// One persisted per-query stat row (`TrafficQueryStat`; the key is the
// normalized query string — NFKC/casefold/whitespace at projection time).
export const trafficQueryRowSchema = responseObject({
  normalized_query: z.string(),
  impressions: z.number().int(),
  clicks: z.number().int(),
  ctr: z.number().nullable(),
  position: z.number().nullable(),
});

// Keyset envelopes (C4) — the site-health cursor-page convention.
export const trafficPagesPageSchema = cursorPageSchema(trafficPageRowSchema);
export const trafficQueriesPageSchema = cursorPageSchema(trafficQueryRowSchema);

// ---------------------------------------------------------------------------
// LLM Analytics (projection over ReferralClassification + MetricSnapshot —
// deterministic only, no LLM in any metric, invariant 9)
// ---------------------------------------------------------------------------

// AI-referral source vocabulary (config-owned rule table on the backend).
export const aiSourceSchema = z.enum([
  'chatgpt',
  'gemini',
  'claude',
  'perplexity',
  'copilot',
  'google_ai_overview',
  'other',
]);

// Deterministic confidence bucket + which signal fired the matched rule
// (fixed referrer → utm → user_agent priority).
export const referralConfidenceSchema = z.enum(['exact', 'heuristic']);
export const referralMatchSignalSchema = z.enum(['referrer', 'utm', 'user_agent']);

// Visibility ↔ referral correlation summary. Below the minimum aligned-sample
// size the backend reports `insufficient_data` with a NULL coefficient —
// never a fabricated number (invariant 9). The UI renders `—` for that state.
export const analyticsCorrelationSchema = responseObject({
  state: z.enum(['ok', 'insufficient_data']),
  coefficient: z.number().nullable(),
  sample_size: z.number().int(),
});

// Per-`ai_source` referral breakdown row.
export const analyticsSourceBreakdownRowSchema = responseObject({
  ai_source: aiSourceSchema,
  sessions: z.number().int(),
  share: z.number().nullable(),
});

// Per-engine visibility series (folded from persisted MetricSnapshot rows;
// `logical_engine` is the audited engine vocabulary, invariant 10).
export const analyticsEngineVisibilitySchema = responseObject({
  logical_engine: z.string(),
  series: metricSeriesSchema,
});

// `GET /projects/{id}/llm-analytics` — headline AEO Insights projection:
// referral volume/share series, per-source breakdown, per-engine visibility
// series, and the correlation summary. Empty history → empty payload.
export const llmAnalyticsSchema = responseObject({
  project_id: uuid(),
  window_start: z.string(),
  window_end: z.string(),
  granularity: snapshotGranularitySchema,
  referral_volume: metricSeriesSchema,
  referral_share: metricSeriesSchema,
  sources: z.array(analyticsSourceBreakdownRowSchema),
  engine_visibility: z.array(analyticsEngineVisibilitySchema),
  correlation: analyticsCorrelationSchema,
  analyzer_version: z.string(),
  formula_version: z.string(),
});

// One classified referral drill-down row (ReferralClassification joined to
// its ReferralEvent). URLs/UA are sanitized before persistence on the
// backend; `logical_engine` is null when the source has no audited-engine
// mapping, and `match_signal` is null when no rule fired (non-AI referral).
export const analyticsReferralRowSchema = responseObject({
  id: uuid(),
  occurred_at: z.string(),
  landing_url: z.string(),
  referrer_host: z.string().nullable(),
  is_ai_referral: z.boolean(),
  ai_source: aiSourceSchema,
  logical_engine: z.string().nullable(),
  confidence: referralConfidenceSchema,
  match_signal: referralMatchSignalSchema.nullable(),
});

// Keyset envelope (C4) for the referrals drill-down.
export const analyticsReferralsPageSchema = cursorPageSchema(analyticsReferralRowSchema);

// One theme-level visibility rollup row (grouped by the frozen
// theme/intent of the audited prompts). Rates/score are null when the
// underlying metric is absent (no fabricated numbers).
export const llmAnalyticsThemeRowSchema = responseObject({
  theme: z.string(),
  intent: promptIntentSchema,
  total_completed: z.number().int(),
  brand_mention_rate: z.number().nullable(),
  visibility_score: z.number().nullable(),
  share_of_voice: z.number().nullable(),
});

// `GET /projects/{id}/llm-analytics/themes` — bare array of rollup rows.
export const llmAnalyticsThemeListSchema = z.array(llmAnalyticsThemeRowSchema);

// ---------------------------------------------------------------------------
// Products (agentic commerce) — catalog + visibility projections
// ---------------------------------------------------------------------------

export const productVariantSchema = responseObject({
  name: z.string(),
  sku: z.string(),
  price: z.number().nullable(),
});

// Computed data-quality badge: present/total against the backend config
// matrix (never persisted — computed on read).
export const productCompletenessSchema = responseObject({
  score: z.number(),
  present: z.number().int(),
  total: z.number().int(),
  missing: z.array(z.string()),
});

// Catalog provenance vocabulary (backend `Product.origin`): `manual` rows are
// entered by hand, `imported` rows arrived via CSV/JSON import, and `synced`
// rows are owned by a feed connection (e.g. Shopify). Feed-bound provenance
// fields are null on unbound manual/imported rows.
export const productOriginSchema = z.enum(['manual', 'imported', 'synced']);

export const productSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  sku: z.string(),
  name: z.string(),
  aliases: z.array(z.string()),
  variants: z.array(productVariantSchema),
  price: z.number().nullable(),
  currency: z.string(),
  url: z.string(),
  attributes: z.record(z.string(), z.unknown()),
  origin: productOriginSchema,
  // Feed binding (nullable): the connection that owns the row, the
  // provider's item reference, and the last sync run that observed it.
  connection_id: uuid().nullable(),
  external_item_ref: z.string().nullable(),
  last_seen_sync_run_id: uuid().nullable(),
  completeness: productCompletenessSchema,
  created_at: z.string(),
  updated_at: z.string(),
});

export const competitorProductSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  competitor_id: uuid(),
  name: z.string(),
  aliases: z.array(z.string()),
  price: z.number().nullable(),
  currency: z.string(),
  url: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});

// D1 import feedback: the bulk-import response carries the refreshed catalog
// plus a per-row outcome summary (backend `ProductImportResponse`). `updated`
// is reserved (v1 imports are insert-only, so it is always 0).
export const productImportRowErrorSchema = responseObject({
  row: z.number().int(),
  field: z.string(),
  message: z.string(),
});

export const productImportSummarySchema = responseObject({
  created: z.number().int().nonnegative(),
  updated: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  errors: z.array(productImportRowErrorSchema),
});

export const productImportResponseSchema = responseObject({
  items: z.array(productSchema),
  summary: productImportSummarySchema,
});

// D4 delete guard: read-only frozen-audit usage check for one product
// (backend `ProductAuditReferences`).
export const productAuditReferencesSchema = responseObject({
  product_id: uuid(),
  referenced: z.boolean(),
  audit_count: z.number().int().nonnegative(),
});

// Buyer-destination classification vocabulary (backend `MERCHANT_KINDS`).
export const buyerDestinationKindSchema = z.enum([
  'marketplace',
  'retailer',
  'brand_site',
  'other',
]);

// Persisted buyer-destination aggregate for one visibility entry: the total
// destination count, per-kind tallies, and per-domain rows (sanitized —
// domain + display name only, never a raw URL).
export const buyerDestinationMixSchema = responseObject({
  total: z.number().int().nonnegative(),
  by_kind: z
    .object({
      merchant_kind: buyerDestinationKindSchema,
      count: z.number().int().nonnegative(),
    })
    .array(),
  by_domain: z
    .object({
      merchant_domain: z.string(),
      merchant_name: z.string(),
      merchant_kind: buyerDestinationKindSchema,
      count: z.number().int().nonnegative(),
    })
    .array(),
});

// Persisted competitor co-placement rows for one visibility entry (answer
// executions listing the entry beside a competitor product), with the
// backend's truncation flag preserved verbatim.
export const competitorCoPlacementSchema = responseObject({
  items: z
    .object({
      competitor_product_id: uuid().nullable(),
      competitor_name: z.string(),
      product_name: z.string(),
      count: z.number().int().nonnegative(),
    })
    .array(),
  truncated: z.boolean(),
});

// Price-relation tallies (backend `price_relation` vocabulary). Strict
// partial: v2 rows count every key, v1 rows count only `match`/`mismatch`,
// and `{}` is valid (a v1 entry with nothing verifiable). Direction is NEVER
// inferred for v1 data — the UI renders `Direction unavailable` there.
export const priceRelationCountsSchema = responseObject({
  match: z.number().int().nonnegative().optional(),
  higher: z.number().int().nonnegative().optional(),
  lower: z.number().int().nonnegative().optional(),
  mismatch: z.number().int().nonnegative().optional(),
});

// Attribute-dimension mention frequency: `{group: {dimension: count}}`.
export const attributeDimensionFrequencySchema = z.record(
  z.string(),
  z.record(z.string(), z.number().int().nonnegative()),
);

// Fields the analyzer-v2 projection adds to every visibility entry (own and
// competitor): row-level analyzer version (mixed-version audits label each
// row with its ACTUAL persisted version), win rate, price relation, and the
// attribute/destination/co-placement aggregates. Rates stay null when the
// backend could not compute them (never a fabricated 0).
const productVisibilityEntryV2Fields = {
  product_analyzer_version: z.string(),
  win_rate: z.number().nullable(),
  price_mismatch_rate: z.number().nullable(),
  price_relation_counts: priceRelationCountsSchema,
  attribute_dimension_frequency: attributeDimensionFrequencySchema,
  buyer_destination_mix: buyerDestinationMixSchema,
  competitor_co_placement: competitorCoPlacementSchema,
} as const;

export const productVisibilityEntrySchema = responseObject({
  // Nullable: the aggregate survives the catalog row's delete (SET NULL).
  product_id: uuid().nullable(),
  sku: z.string(),
  name: z.string(),
  mention_count: z.number().int(),
  sov_share: z.number(),
  avg_rank: z.number().nullable(),
  rank_distribution: z.record(z.string(), z.number().int()),
  price_mention_count: z.number().int(),
  // null = no verifiable price mentions (never a fabricated 0).
  price_accuracy_rate: z.number().nullable(),
  ...productVisibilityEntryV2Fields,
});

export const competitorProductVisibilityEntrySchema = responseObject({
  competitor_product_id: uuid().nullable(),
  competitor_name: z.string(),
  name: z.string(),
  mention_count: z.number().int(),
  sov_share: z.number(),
  avg_rank: z.number().nullable(),
  rank_distribution: z.record(z.string(), z.number().int()),
  price_mention_count: z.number().int(),
  price_accuracy_rate: z.number().nullable(),
  ...productVisibilityEntryV2Fields,
});

// Selected-audit product dashboard projection (persisted rows only). Identity
// (sku/name/competitor_name) comes from the audit's frozen configuration.
export const productVisibilitySchema = responseObject({
  project_id: uuid(),
  audit_id: uuid(),
  audit_status: auditStatusSchema,
  product_analyzer_version: z.string(),
  product_scoring_rule_version: z.string(),
  total_mentions: z.number().int(),
  total_analyses: z.number().int(),
  products: z.array(productVisibilityEntrySchema),
  competitor_products: z.array(competitorProductVisibilityEntrySchema),
  // Distinct persisted analysis surfaces for the audit: the measurement
  // surface is `''` (UI label "Answer-engine APIs"); configured surface
  // ids follow verbatim. There is deliberately no "All surfaces" option.
  available_surfaces: z.array(z.string()),
  created_at: z.string(),
});

// Evidence kind vocabulary (backend projection): one stable `evidence_id`
// per persisted row (ProductMention.id / MerchantMention.id / a
// config-namespaced UUIDv5 for attribute mentions), so React keys never fall
// back to an array index.
export const productEvidenceKindSchema = z.enum([
  'product_mention',
  'attribute_mention',
  'buyer_destination',
]);

// Item-level price relation (backend `price_relation` persisted string).
// `mismatch` is NOT storable item-level (it only exists as the v1 aggregate
// fallback for unverifiable direction), so it is not in this enum.
export const priceRelationSchema = z.enum(['match', 'higher', 'lower']);

// Generalized evidence row: one pinned key set for every kind, with the
// kind-specific field groups present on every row and null for the other
// kinds (the backend emits exactly this shape).
export const productEvidenceItemSchema = responseObject({
  evidence_id: uuid(),
  analysis_id: uuid(),
  evidence_kind: productEvidenceKindSchema,
  audit_id: uuid(),
  // Execution id — opens the in-run evidence drawer via `?execution=[taskId]`.
  task_id: uuid(),
  artifact_id: uuid().nullable(),
  logical_engine: z.string(),
  transport_model: z.string(),
  // Frozen prompt text (AuditPromptSnapshot) — survives prompt edits.
  prompt_text: z.string(),
  prompt_index: z.number().int(),
  repetition: z.number().int(),
  product_analyzer_version: z.string(),
  // Analysis surface this row was projected from ('' = measurement).
  shopping_surface: z.string(),
  matched_name: z.string(),
  matched_sku: z.string(),
  created_at: z.string(),
  // Product-mention fields (null for the other kinds).
  first_offset: z.number().int().nullable(),
  rank_position: z.number().int().nullable(),
  price_value: z.number().nullable(),
  // null = not verifiable (no catalog price / currency mismatch).
  price_matches_catalog: z.boolean().nullable(),
  price_relation: priceRelationSchema.nullable(),
  price_text: z.string(),
  price_currency: z.string(),
  // Attribute-mention fields (null for the other kinds).
  attribute_dimension: z.string().nullable(),
  attribute_group: z.string().nullable(),
  attribute_text: z.string().nullable(),
  attribute_offset: z.number().int().nullable(),
  // Buyer-destination fields (null for the other kinds; the URL arrives
  // already sanitized by the backend).
  merchant_name: z.string().nullable(),
  merchant_domain: z.string().nullable(),
  merchant_kind: buyerDestinationKindSchema.nullable(),
  destination_url: z.string().nullable(),
});

export const productEvidenceResponseSchema = responseObject({
  items: z.array(productEvidenceItemSchema),
  truncated: z.boolean(),
});

// ---------------------------------------------------------------------------
// Commerce catalog health (persisted feed/sync projection — projections only,
// invariant 7; no provider call on reads)
// ---------------------------------------------------------------------------

// Per-SKU feed health status (backend feed-issue projection vocabulary).
export const feedHealthStatusSchema = z.enum(['healthy', 'warning', 'error', 'unavailable']);

export const feedIssueSeveritySchema = z.enum(['info', 'warning', 'error']);

// One connection's current-or-latest sync summary (a read-only projection of
// the sync queue row — same status vocabulary as integrationSyncRunSchema).
export const commerceSyncSummarySchema = responseObject({
  sync_run_id: uuid(),
  connection_id: uuid(),
  status: integrationSyncRunStatusSchema,
  window_start: z.string(),
  window_end: z.string(),
  row_count: z.number().int(),
  // '' when there is no error (non-secret code only, never a payload).
  error_code: z.string(),
  completed_at: z.string().nullable(),
});

// A catalog feed connection (Shopify) with its grant status and latest sync.
export const commerceConnectionSummarySchema = responseObject({
  connection_id: uuid(),
  provider: z.literal('shopify'),
  label: z.string(),
  account_ref: z.string(),
  grant_status: integrationGrantStatusSchema,
  last_synced_at: z.string().nullable(),
  latest_sync: commerceSyncSummarySchema.nullable(),
});

// One SKU's feed-health row. `product_id` is null when the feed item no
// longer resolves to a catalog row; `rule_ids` are non-secret rule codes.
export const productFeedHealthSchema = responseObject({
  product_id: uuid().nullable(),
  connection_id: uuid(),
  external_item_ref: z.string(),
  sync_run_id: uuid(),
  status: feedHealthStatusSchema,
  highest_severity: feedIssueSeveritySchema.nullable(),
  issue_count: z.number().int().nonnegative(),
  rule_ids: z.array(z.string()),
  last_seen_in_feed: z.boolean(),
});

// `GET /projects/{id}/commerce/catalog-health`. Connections + products are
// arrays because catalog rows can be bound to different connection ids.
export const commerceCatalogHealthSchema = responseObject({
  project_id: uuid(),
  connections: z.array(commerceConnectionSummarySchema),
  products: z.array(productFeedHealthSchema),
  generated_at: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Commerce attribution (A1 GA4 platform-attributed vs A2 order referrer —
// cross-checks, NEVER summed; partitioned by ISO currency, never converted)
// ---------------------------------------------------------------------------

export const attributionMethodSchema = z.enum(['ga4_platform_attributed', 'order_referrer']);

export const attributionDataStateSchema = z.enum(['available', 'no_data', 'not_connected']);

// A1's GA4 source dimension only: `default_channel_group` is the reduced GA4
// item fallback. A2's `order_referrer` identity is carried by
// attributionMethodSchema, never by this field.
export const attributionSourceGranularitySchema = z.enum([
  'session_source_medium',
  'default_channel_group',
]);

// ISO-4217 alphabetic code (three characters, e.g. "USD").
const isoCurrencyCode = () => z.string().length(3);

// One method's metric set. A non-null revenue/AOV requires its ISO currency
// (the refine mirrors the backend producer contract); null metrics mean
// unavailable — never a fabricated zero.
export const attributionMetricSetSchema = z
  .object({
    currency: isoCurrencyCode().nullable(),
    revenue: z.number().nullable(),
    orders: z.number().int().nullable(),
    average_order_value: z.number().nullable(),
    sessions: z.number().int().nullable(),
    conversion_rate: z.number().nullable(),
  })
  .refine(
    (value) =>
      (value.revenue !== null || value.average_order_value !== null) && value.currency === null
        ? false
        : true,
    { message: 'revenue and average_order_value require a non-null currency' },
  );

// Per-`ai_source` deterministic row within one method/currency partition.
export const attributionSourceRowSchema = responseObject({
  ai_source: aiSourceSchema,
  currency: isoCurrencyCode(),
  metrics: attributionMetricSetSchema,
});

// Per-SKU row. `ai_source` is null and `source_label` carries the
// default-channel label when GA4 item granularity is reduced — those rows
// must never be relabelled as per-AI-source data.
export const attributionProductRowSchema = responseObject({
  product_id: uuid().nullable(),
  sku: z.string(),
  name: z.string(),
  ai_source: aiSourceSchema.nullable(),
  source_label: z.string(),
  currency: isoCurrencyCode(),
  revenue: z.number().nullable(),
  orders: z.number().int().nullable(),
});

// One method/currency partition. `source_granularity` is non-null on
// available A1 rows and null everywhere else; `currency` is non-null on
// every available row (an unavailable method reports no_data/not_connected
// with null metrics rather than a fabricated zero).
export const attributionMethodMetricsSchema = z
  .object({
    method: attributionMethodSchema,
    state: attributionDataStateSchema,
    source_granularity: attributionSourceGranularitySchema.nullable(),
    reduced_granularity: z.boolean(),
    currency: isoCurrencyCode().nullable(),
    coverage_rate: z.number().nullable(),
    totals: attributionMetricSetSchema,
    by_ai_source: z.array(attributionSourceRowSchema),
    by_product: z.array(attributionProductRowSchema),
  })
  .superRefine((value, ctx) => {
    if (
      value.method === 'ga4_platform_attributed' &&
      value.state === 'available' &&
      value.source_granularity === null
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'available A1 rows require a non-null source_granularity',
        path: ['source_granularity'],
      });
    }
    if (value.state === 'available' && value.currency === null) {
      ctx.addIssue({
        code: 'custom',
        message: 'available rows require a non-null currency',
        path: ['currency'],
      });
    }
  });

export const attributionDeltaStateSchema = z.enum([
  'comparable',
  'method_unavailable',
  'currency_unavailable',
]);

// Backend-projected A1 − A2 for one currency (may be negative; non-comparable
// rows carry null values). The browser NEVER computes this delta itself.
export const attributionDeltaSchema = responseObject({
  currency: isoCurrencyCode(),
  state: attributionDeltaStateSchema,
  revenue: z.number().nullable(),
  orders: z.number().int().nullable(),
  average_order_value: z.number().nullable(),
  conversion_rate: z.number().nullable(),
});

// Orders with no referrer evidence (no session join key exists — they stay
// unattributed). A null share is unavailable, never 0%.
export const unattributedMetricsSchema = responseObject({
  currency: isoCurrencyCode(),
  orders: z.number().int(),
  order_share: z.number().nullable(),
  revenue: z.number().nullable(),
});

// Layer B statistical allocation of unattributed orders — model output,
// excluded from every deterministic total/delta/trend. `ai_source` is a
// plain string (the allocation can carry an unassigned bucket outside the
// deterministic AI-source vocabulary).
export const statisticalAllocationRowSchema = responseObject({
  ai_source: z.string(),
  currency: isoCurrencyCode(),
  estimated_revenue: z.number().nullable(),
  estimated_orders: z.number().nullable(),
  estimated_share: z.number().nullable(),
});

export const attributionStatisticalSchema = z
  .object({
    state: z.enum(['not_offered', 'available', 'insufficient_data']),
    sample_size: z.number().int().nullable(),
    allocations: z.array(statisticalAllocationRowSchema),
  })
  .superRefine((value, ctx) => {
    if (value.state === 'not_offered' && value.allocations.length > 0) {
      ctx.addIssue({
        code: 'custom',
        message: 'not_offered statistical state requires empty allocations',
        path: ['allocations'],
      });
    }
    if (
      value.state === 'insufficient_data' &&
      value.allocations.some(
        (row) =>
          row.estimated_revenue !== null ||
          row.estimated_orders !== null ||
          row.estimated_share !== null,
      )
    ) {
      ctx.addIssue({
        code: 'custom',
        message: 'insufficient_data requires every estimate to be null',
        path: ['allocations'],
      });
    }
  });

export const attributionDeterministicSchema = responseObject({
  a1: z.array(attributionMethodMetricsSchema),
  a2: z.array(attributionMethodMetricsSchema),
  delta: z.array(attributionDeltaSchema),
  unattributed: z.array(unattributedMetricsSchema),
  coverage: responseObject({
    total_latest_orders: z.number().int(),
    orders_with_evidence: z.number().int(),
    linked_ai_orders: z.number().int(),
    unattributed_orders: z.number().int(),
    evidence_coverage_rate: z.number().nullable(),
    attributed_share: z.number().nullable(),
    window_start: z.string(),
    window_end: z.string(),
  }),
});

export const attributionMetricsSchema = responseObject({
  deterministic: attributionDeterministicSchema,
  statistical: attributionStatisticalSchema,
});

// `GET /projects/{id}/commerce/attribution` — the persisted snapshot
// projection (an absent snapshot yields the empty contract, not a 404).
export const attributionSnapshotSchema = responseObject({
  project_id: uuid(),
  window_start: z.string(),
  window_end: z.string(),
  granularity: snapshotGranularitySchema,
  metrics: attributionMetricsSchema,
  // Provenance: the persisted rows this snapshot was projected from.
  source_link_ids: z.array(uuid()),
  source_order_fact_ids: z.array(uuid()),
  source_metric_row_ids: z.array(uuid()),
  source_snapshot_ids: z.array(uuid()),
  formula_version: z.string(),
  analyzer_version: z.string(),
  created_at: z.string().nullable(),
});

// Attribution recompute task (queue-row vocabulary — same statuses as the
// integration sync run queue).
export const attributionTaskStatusSchema = z.enum([
  'queued',
  'leased',
  'running',
  'retry_wait',
  'succeeded',
  'failed',
  'cancelled',
]);

// `POST /projects/{id}/commerce/attribution/recompute` (202) and
// `GET /projects/{id}/commerce/attribution/recompute/{task_id}` responses.
export const attributionRecomputeSchema = responseObject({
  task_id: uuid(),
  project_id: uuid(),
  status: attributionTaskStatusSchema,
  // '' when there is no error (non-secret code only).
  error_code: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
});

// ---------------------------------------------------------------------------
// Opportunities (deterministic priority catalog — backend owns the contract)
// ---------------------------------------------------------------------------

// Opportunity vocabulary (config-owned; per-subsystem severity enum — the
// site-health `issueSeveritySchema` is NOT reused, they evolve independently).
export const opportunityTypeSchema = z.enum(['visibility', 'site', 'traffic', 'topic']);
export const opportunitySeveritySchema = z.enum(['critical', 'high', 'medium', 'low', 'info']);
export const opportunityStatusSchema = z.enum(['open', 'in_progress', 'dismissed', 'resolved']);

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

export const commandCenterSchema = responseObject({
  project: responseObject({
    id: uuid(),
    name: z.string(),
    brand_name: z.string(),
    website_url: z.string(),
  }),
  measurement: responseObject({
    audit_id: uuid(),
    completed_at: z.string(),
    measurement_mode: z.string(),
    benchmark_mode: z.string(),
    logical_engines: z.array(z.string()),
    comparable_audit_id: uuid().nullable(),
  }),
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

// ---------------------------------------------------------------------------
// Commerce discovery + competitor intelligence. These responses are durable
// candidate / comparison evidence; the browser never performs acquisition or
// matching itself.
// ---------------------------------------------------------------------------
export const commerceCandidateKindSchema = z.enum(['own', 'competitor']);
export const commerceDiscoveryInputKindSchema = z.enum(['upload', 'url']);
export const commerceCandidateInputSchema = z.object({
  candidate_kind: commerceCandidateKindSchema.optional(),
  competitor_id: uuid().nullable().optional(),
  name: z.string().min(1),
  sku: z.string().optional(),
  aliases: z.array(z.string()).optional(),
  variants: z.array(z.record(z.string(), z.unknown())).optional(),
  price: z.number().nullable().optional(),
  currency: z.string().optional(),
  url: z.string().optional(),
  attributes: z.record(z.string(), z.unknown()).optional(),
  availability: z.string().optional(),
  extraction_confidence: z.number().min(0).max(1).optional(),
});
export const commercePreviewRowErrorSchema = responseObject({
  row: z.number().int().positive(),
  field: z.string(),
  message: z.string(),
});
export const commerceDiscoveryPreviewSchema = responseObject({
  accepted: z.array(commerceCandidateInputSchema),
  duplicates: z.array(z.number().int().positive()),
  errors: z.array(commercePreviewRowErrorSchema),
  truncated: z.boolean(),
});
export const commerceMatchDecisionSchema = responseObject({
  target_id: uuid().nullable(),
  target_kind: z.enum(['product', 'competitor_product']),
  confidence: z.number(),
  reasons: z.array(z.string()),
  review_required: z.boolean(),
});
export const commerceCandidateSchema = responseObject({
  id: uuid(),
  run_id: uuid(),
  task_id: uuid(),
  artifact_id: uuid(),
  candidate_kind: commerceCandidateKindSchema,
  competitor_id: uuid().nullable(),
  identity: z.record(z.string(), z.unknown()),
  extraction_confidence: z.number(),
  created_at: z.string(),
  matches: z.array(commerceMatchDecisionSchema),
});
export const commerceDiscoveryRunSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  input_kind: commerceDiscoveryInputKindSchema,
  status: z.string(),
  configuration: z.record(z.string(), z.unknown()),
  discovery_version: z.string(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  candidates: z.array(commerceCandidateSchema),
});
export const commerceCandidateAcceptSchema = responseObject({
  review_id: uuid(),
  candidate_id: uuid(),
  status: z.enum(['accepted', 'rejected']),
  product_id: uuid().nullable(),
  competitor_product_id: uuid().nullable(),
  match_reason: z.string(),
  match_confidence: z.number(),
});
export const competitorComparisonSnapshotSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  competitor_id: uuid().nullable(),
  source_catalog_ids: z.record(z.string(), z.array(uuid())),
  source_artifact_ids: z.array(uuid()),
  matcher_version: z.string(),
  comparison_version: z.string(),
  comparison: z.record(z.string(), z.unknown()),
  truncated: z.boolean(),
  created_at: z.string(),
});

export const opportunityGuidanceItemSchema = responseObject({
  id: uuid(),
  opportunity_id: uuid(),
  input_hash: z.string(),
  findings: z.array(z.string()),
  recommendations: z.array(z.string()),
  source_analysis_ids: z.array(uuid()),
  source_issue_ids: z.array(uuid()),
  source_metric_ids: z.array(uuid()),
  analyzer_version: z.string(),
  rule_version: z.string(),
  formula_version: z.string(),
  generator_version: z.string(),
  prompt_version: z.string(),
  provider: z.string(),
  model: z.string(),
  created_at: z.string(),
});
export const opportunityGuidanceHistorySchema = responseObject({
  items: z.array(opportunityGuidanceItemSchema),
});

// ---------------------------------------------------------------------------
// Billing (provider ids, plan ids, secrets, and billing PII never cross wire)
// ---------------------------------------------------------------------------

// Plan keys are LOCKED to the four the backend publishes. A retired `free`/
// `paid` key must fail parsing rather than render as an unknown tier.
export const planCatalogKeySchema = z.enum(['tier_1', 'tier_2', 'tier_3', 'enterprise']);
export const credentialModeSchema = z.enum(['byok', 'funded']);
export const billingRegionSchema = z.enum(['india', 'international']);
export const catalogAvailabilitySchema = z.enum(['available', 'unavailable']);
export const grantSourceKindSchema = z.enum(['plan', 'addon', 'topup', 'trial', 'override']);
export const entitlementStatusSchema = z.enum(['resolved', 'entitlement_unresolved']);
export const capabilityTypeSchema = z.enum([
  'flag',
  'counter.occupancy',
  'counter.consumable',
  'counter.rate',
  'level',
]);
export const counterCapabilityTypeSchema = z.enum([
  'counter.occupancy',
  'counter.consumable',
  'counter.rate',
]);
/**
 * `limit_state` is the ONLY authority for what a null aggregate means: the
 * backend never uses null to mean both "unlimited" and "unresolved". The UI
 * must branch on this, never on nullability.
 */
export const limitStateSchema = z.enum(['finite', 'unlimited', 'unknown']);
export const activationKindSchema = z.enum(['base', 'addon', 'topup']);
export const activationStatusSchema = z.enum(['pending', 'activated', 'failed', 'abandoned']);

export const moneySchema = responseObject({
  currency: z.enum(['USD', 'INR']),
  amount_minor: z.number().int().nonnegative(),
});

/**
 * The server-resolved charge. `quote_id` is an opaque digest that proves the
 * displayed terms without exposing any provider identity — the frontend
 * compares its displayed price against `base_price` here and never computes a
 * total of its own.
 */
export const resolvedQuoteSchema = responseObject({
  quote_id: z.string(),
  catalog_revision: z.string(),
  catalog_key: z.string(),
  credential_mode: credentialModeSchema,
  country_code: z.string(),
  region: billingRegionSchema,
  base_price: moneySchema,
  credit_price: moneySchema.nullable(),
  tax: moneySchema,
  total_price: moneySchema,
  expires_at: z.string(),
});

export const capabilityValueSchema = responseObject({
  key: z.string(),
  capability_type: capabilityTypeSchema,
  value: z.union([z.boolean(), z.number(), z.string()]).nullable(),
  issuable: z.boolean(),
});

export const catalogProviderRouteSchema = responseObject({
  logical_engine: z.string(),
  measurement_mode: measurementModeSchema,
  transport_provider: z.string(),
  model: z.string(),
});

/**
 * PUBLIC provider row — availability only, never workspace state. Grok,
 * Perplexity and Copilot appear here as `unavailable` with an empty `routes`
 * list; that absence of a route is what makes them non-connectable.
 */
export const catalogProviderSchema = responseObject({
  key: z.string(),
  label: z.string(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  adapter_shipped: z.boolean(),
  grant_key: z.string(),
  issuable: z.boolean(),
  routes: z.array(catalogProviderRouteSchema),
});

export const catalogPlanSchema = responseObject({
  key: planCatalogKeySchema,
  name: z.string(),
  description: z.string(),
  cadence: z.enum(['monthly', 'custom']),
  self_serve: z.boolean(),
  contact_only: z.boolean(),
  contact_url: z.string().nullable(),
  base_price: moneySchema.nullable(),
  // Null in this release: funded inputs are deliberately unset. Never coerce
  // to zero and never derive a funded total from it.
  credit_price: moneySchema.nullable(),
  funded_total_price: moneySchema.nullable(),
  checkout_available: z.boolean(),
  unavailable_reason: z.string().nullable(),
  capabilities: z.array(capabilityValueSchema),
  trial_availability: catalogAvailabilitySchema,
  trial_unavailable_reason: z.string().nullable(),
  trial_days: z.number().int().nullable(),
});

export const catalogAddonSchema = responseObject({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  cadence: z.literal('monthly'),
  unit_price: moneySchema.nullable(),
  quantity_min: z.number().int(),
  quantity_max: z.number().int(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  grant_key: z.string(),
  grant_value_per_unit: z.number().int(),
});

export const catalogTopupSchema = responseObject({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  unit_price: moneySchema.nullable(),
  quantity_min: z.number().int(),
  quantity_max: z.number().int(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  grant_key: z.enum(['benchmark_credits', 'pulse_credits']),
  credits_per_unit: z.number().int().nullable(),
  expiry_days: z.number().int(),
});

export const billingCatalogSchema = responseObject({
  catalog_revision: z.string(),
  country_code: z.string().nullable(),
  region: billingRegionSchema,
  currency: z.enum(['USD', 'INR']),
  currency_minor_units: z.number().int(),
  plans: z.array(catalogPlanSchema),
  addons: z.array(catalogAddonSchema),
  topups: z.array(catalogTopupSchema),
  providers: z.array(catalogProviderSchema),
});

export const grantProvenanceSchema = responseObject({
  grant_id: uuid(),
  source_kind: grantSourceKindSchema,
  key: z.string(),
  value: z.number().int(),
  valid_from: z.string(),
  effective_valid_until: z.string().nullable(),
  revoked_at: z.string().nullable(),
  catalog_revision: z.string(),
});

export const resolvedCapabilitySchema = responseObject({
  key: z.string(),
  capability_type: capabilityTypeSchema,
  value: z.union([z.boolean(), z.number(), z.string()]).nullable(),
  contributing_grant_ids: z.array(uuid()),
  ordered_draw_grant_ids: z.array(uuid()),
});

export const subscriptionSummarySchema = responseObject({
  catalog_key: z.string(),
  status: z.string(),
  current_period_end: z.string().nullable(),
  cancel_at_period_end: z.boolean(),
});

export const trialGrantSummarySchema = responseObject({
  deadline: z.string(),
  days_remaining: z.number().int(),
  exhausted: z.boolean(),
});

/**
 * The resolved account entitlement. There is deliberately no
 * `funded_execution_allowed` flag — funded admission is an enforcement-time
 * decision, so the UI must never present one.
 */
export const billingEntitlementSchema = responseObject({
  billing_account_id: uuid(),
  status: entitlementStatusSchema,
  errors: z.array(z.string()),
  registry_revision: z.string(),
  entitlement_lifecycle_version: z.number().int(),
  resolved_at: z.string(),
  valid_until: z.string().nullable(),
  subscription: subscriptionSummarySchema.nullable(),
  trial_grant: trialGrantSummarySchema.nullable(),
  capabilities: z.array(resolvedCapabilitySchema),
  grants: z.array(grantProvenanceSchema),
});

export const usageGrantBalanceSchema = responseObject({
  grant_id: uuid(),
  source_kind: grantSourceKindSchema,
  allowance: z.number().int(),
  consumed: z.number().int(),
  reserved: z.number().int(),
  remaining: z.number().int(),
  effective_valid_until: z.string().nullable(),
});

export const usageItemSchema = responseObject({
  key: z.string(),
  capability_type: counterCapabilityTypeSchema,
  unit: z.string(),
  limit_state: limitStateSchema,
  allowance: z.number().int().nullable(),
  consumed: z.number().int().nullable(),
  reserved: z.number().int().nullable(),
  remaining: z.number().int().nullable(),
  window_started_at: z.string().nullable(),
  resets_at: z.string().nullable(),
  earliest_expiry: z.string().nullable(),
  grants: z.array(usageGrantBalanceSchema),
});

export const billingUsageSchema = responseObject({
  billing_account_id: uuid(),
  entitlement_lifecycle_version: z.number().int(),
  status: entitlementStatusSchema,
  items: z.array(usageItemSchema),
});

/** Every commercial POST answers with this. `quote` is always present. */
export const activationSchema = responseObject({
  activation_id: uuid(),
  kind: activationKindSchema,
  catalog_key: z.string(),
  quantity: z.number().int(),
  status: activationStatusSchema,
  quote: resolvedQuoteSchema,
  checkout_url: z.string().nullable(),
  expires_at: z.string(),
  failure_code: z.string().nullable(),
});

/**
 * Deactivation has its OWN vocabulary — deliberately not the activation state
 * machine. Parsing a DELETE through `activationSchema` would invent a
 * pending/failed lifecycle the backend never reports.
 */
export const subscriptionChangeSchema = responseObject({
  catalog_key: z.string(),
  status: z.enum(['cancellation_scheduled', 'already_scheduled']),
  effective_at: z.string(),
});

// --- Authenticated provider connection state -------------------------------
// Separate contract from the PUBLIC catalog above: availability is what we
// sell, connection state is what this workspace actually has.
export const providerConnectionStateSchema = z.enum([
  'connected',
  'missing',
  'failed',
  'unavailable',
]);

export const providerProbeSchema = responseObject({
  status: z.enum(['ok', 'failed']),
  safe_reason: z.string().nullable(),
  tested_at: z.string(),
  model: z.string().nullable(),
  latency_ms: z.number().int().nullable(),
});

export const providerConnectionStateEntrySchema = responseObject({
  key: z.string(),
  label: z.string(),
  state: providerConnectionStateSchema,
  safe_reason: z.string().nullable(),
  grant_key: z.string(),
  latest_probe: providerProbeSchema.nullable(),
});

export const providerConnectionStatesSchema = responseObject({
  workspace_id: uuid(),
  providers: z.array(providerConnectionStateEntrySchema),
});

// ---------------------------------------------------------------------------
// Audit events — the discriminated envelope shared by `GET /audits/{id}/events`
// and its SSE stream. On the wire SSE `event:` IS `event_type` and SSE `id:` IS
// the event UUID (the `Last-Event-ID` resume cursor).
//
// This is a DISCRIMINATED UNION, not a permissive envelope: an unknown
// `event_type` fails parsing rather than reaching a handler as a partial
// object. Payloads are invalidation signals only — never treat one as a row.
// ---------------------------------------------------------------------------

const eventEnvelope = <Type extends string, Payload extends z.ZodTypeAny>(
  eventType: Type,
  payload: Payload,
) =>
  responseObject({
    id: uuid(),
    audit_id: uuid(),
    occurred_at: z.string(),
    event_type: z.literal(eventType),
    payload,
  });

export const auditEventSchema = z.discriminatedUnion('event_type', [
  eventEnvelope(
    'audit.created',
    responseObject({
      requested_count: z.number().int(),
      engines: z.array(z.string()),
    }),
  ),
  eventEnvelope('audit.queued', responseObject({ task_count: z.number().int() })),
  eventEnvelope('audit.running', z.null()),
  eventEnvelope(
    'audit.status',
    responseObject({
      status: z.string(),
      completed: z.number().int().nullable().default(null),
      failed: z.number().int().nullable().default(null),
    }),
  ),
  eventEnvelope(
    'audit.cancelled',
    responseObject({
      status: z.string(),
      completed: z.number().int().nullable().default(null),
      failed: z.number().int().nullable().default(null),
    }),
  ),
  eventEnvelope(
    'audit.completed',
    responseObject({
      status: z.string(),
      completed: z.number().int(),
      failed: z.number().int(),
      visibility_score: z.number(),
    }),
  ),
  eventEnvelope('task.succeeded', responseObject({ task_id: uuid() })),
  eventEnvelope('task.failed', responseObject({ task_id: uuid(), error_code: z.string() })),
  eventEnvelope('task.retry', responseObject({ task_id: uuid(), error_code: z.string() })),
  eventEnvelope(
    'task.capacity_wait',
    responseObject({
      task_id: uuid(),
      code: z.string(),
      pool_kind: z.string(),
      available_at: z.string().default(''),
      retry_after_seconds: z.number().default(0),
    }),
  ),
]);

export const auditEventListSchema = z.array(auditEventSchema);

// ---------------------------------------------------------------------------
// Site Intelligence (S2/S3)
// ---------------------------------------------------------------------------
//
// Every nullable number below is load-bearing. `null` means NOT MEASURABLE and
// `0` means measured-and-zero; a UI that renders one as the other turns an
// incomplete crawl into a failing site. Components must branch on `null`, never
// coalesce it.

// Counts and ratios the backend computes are never negative and never above
// one. Declaring that here turns an impossible value into a loud validation
// failure instead of a UI that renders "-3 entities" or a 140% bar.
const count = () => z.number().int().min(0);
const unitInterval = () => z.number().min(0).max(1);

export const coverageStateSchema = z.enum([
  'answered_strong',
  'answered_weak',
  'missing',
  'conflicting',
  'unsupported',
  'historical_only',
  'unavailable_evidence',
  'not_applicable',
]);

export const questionCoverageItemSchema = responseObject({
  question_id: z.string(),
  label: z.string(),
  state: coverageStateSchema,
  journey_stage_id: z.string(),
  reason: z.string(),
  satisfied_predicate_ids: z.array(z.string()),
  missing_predicate_ids: z.array(z.string()),
  answering_role_ids: z.array(z.string()),
});

export const questionCoverageBlockSchema = responseObject({
  answered_ratio: unitInterval().nullable(),
  denominator: count(),
  counts: z.record(z.string(), count()),
  questions: z.array(questionCoverageItemSchema),
});

export const journeyStageBlockSchema = responseObject({
  stage_id: z.string(),
  label: z.string(),
  order: z.number().int(),
  role_coverage: unitInterval(),
  question_coverage: unitInterval().nullable(),
  present_role_ids: z.array(z.string()),
  missing_role_ids: z.array(z.string()),
  answered_question_ids: z.array(z.string()),
  gap_question_ids: z.array(z.string()),
  // Outcome id -> measurement state. `unavailable` until Demand Intelligence
  // supplies events; it is never a zero.
  outcomes: z.record(z.string(), z.string()),
});

export const journeyBlockSchema = responseObject({
  journey_id: z.string(),
  label: z.string(),
  stages: z.array(journeyStageBlockSchema),
  role_coverage: unitInterval(),
  question_coverage: unitInterval().nullable(),
  version: z.string(),
});

export const dimensionComponentSchema = responseObject({
  component_id: z.string(),
  label: z.string(),
  score: unitInterval().nullable(),
});

export const dimensionBlockSchema = responseObject({
  dimension_id: z.string(),
  label: z.string(),
  score: unitInterval(),
  coverage: unitInterval(),
  components: z.array(dimensionComponentSchema),
});

export const dimensionsBlockSchema = responseObject({
  composite_score: unitInterval().nullable(),
  composite_coverage: unitInterval().nullable(),
  dimensions: z.array(dimensionBlockSchema),
});

export const knowledgeSummaryBlockSchema = responseObject({
  entity_count: count(),
  assertion_count: count(),
  relation_count: count(),
  contradiction_count: count(),
  pages_considered: count(),
  pages_contributing: count(),
  entity_type_ids: z.array(z.string()),
  warnings: z.array(z.string()),
});

export const corpusBlockSchema = responseObject({
  by_disposition: z.record(z.string(), count()),
  by_item_kind: z.record(z.string(), count()),
  discovered: count(),
  analyzable: count(),
  inventory_only: count(),
  documents: count(),
});

const comparisonChangeSetSchema = responseObject({
  before_count: count(),
  after_count: count(),
  added_count: count(),
  removed_count: count(),
  changed_count: count(),
  changes: z.array(z.record(z.string(), z.unknown())),
  truncated: z.boolean(),
});

const comparisonBoundedChangesSchema = responseObject({
  changed_count: count(),
  changes: z.array(z.record(z.string(), z.unknown())),
  truncated: z.boolean(),
});

const actionResolutionTargetSchema = responseObject({
  site_url_id: z.string(),
  target_key: z.string(),
  source_rule_id: z.string(),
  prior_issue_id: z.string(),
  current_evaluation_id: z.string().nullable(),
  current_outcome: z.string(),
  observed_pass: z.boolean(),
});

const actionResolutionItemSchema = responseObject({
  opportunity_rule_id: z.string(),
  state: z.enum(['verified', 'partial', 'unresolved']),
  verified_targets: count(),
  target_count: count(),
  targets: z.array(actionResolutionTargetSchema),
  truncated: z.boolean(),
});

export const snapshotComparisonSchema = responseObject({
  version: z.string(),
  available: z.boolean(),
  reason: z.string().nullable(),
  prior_snapshot_id: z.string().nullable().optional(),
  prior_crawl_id: z.string().nullable().optional(),
  facts: comparisonChangeSetSchema.nullable().optional(),
  rules: comparisonChangeSetSchema.nullable().optional(),
  questions: comparisonBoundedChangesSchema.nullable().optional(),
  journeys: comparisonBoundedChangesSchema.nullable().optional(),
  dimensions: comparisonBoundedChangesSchema
    .extend({
      composite_score_delta: z.number().nullable(),
      composite_coverage_delta: z.number().nullable(),
    })
    .nullable()
    .optional(),
  coverage: responseObject({
    answered_ratio_delta: z.number().nullable(),
    denominator_before: count(),
    denominator_after: count(),
  })
    .nullable()
    .optional(),
  scores: responseObject({
    technical_delta: z.number().nullable(),
    aeo_delta: z.number().nullable(),
    overall_delta: z.number().nullable(),
    analyzed_url_delta: z.number().nullable(),
    issue_count_delta: z.number().nullable(),
  })
    .nullable()
    .optional(),
  action_resolutions: responseObject({
    total: count(),
    state_counts: responseObject({
      verified: count(),
      partial: count(),
      unresolved: count(),
    }),
    items: z.array(actionResolutionItemSchema),
    truncated: z.boolean(),
  })
    .nullable()
    .optional(),
});

export const intelligenceOverviewSchema = responseObject({
  // `available` false = no snapshot yet. Distinct from `packed` false, which
  // means a snapshot exists and no industry pack applied.
  available: z.boolean(),
  reason: z.string().nullable(),
  packed: z.boolean(),
  manifest: z.record(z.string(), z.string()).nullable(),
  crawl: responseObject({
    id: z.string(),
    status: z.string(),
    root_url: z.string(),
    created_at: z.string().nullable(),
  }),
  snapshot_id: z.string().nullable(),
  prior_snapshot_id: z.string().nullable(),
  comparison: snapshotComparisonSchema.nullable(),
  corpus: corpusBlockSchema,
  knowledge: knowledgeSummaryBlockSchema,
  coverage: questionCoverageBlockSchema,
  journeys: z.array(journeyBlockSchema),
  dimensions: dimensionsBlockSchema,
  versions: z.record(z.string(), z.string()),
});

export const evidenceRefSchema = responseObject({
  source_kind: z.string(),
  source_id: z.string(),
  locator: z.record(z.string(), z.unknown()),
});

const correctionTransitionItemSchema = responseObject({
  id: z.string(),
  sequence: count(),
  transition_type: z.enum(['created', 'withdrawn']),
  actor_user_id: z.string(),
  reason: z.string(),
  snapshot: z.record(z.string(), z.unknown()),
  created_at: z.string(),
});

export const correctionItemSchema = responseObject({
  id: z.string(),
  target_kind: z.enum(['entity', 'assertion', 'relation']),
  target_ref: z.record(z.string(), z.unknown()),
  target_field: z.string(),
  source_crawl_id: z.string(),
  source_target_id: z.string(),
  derived_value: z.record(z.string(), z.unknown()),
  corrected_value: z.record(z.string(), z.unknown()),
  value_type: z.string(),
  effective_scope: z.enum(['project', 'entity']),
  effective_scope_ref: z.record(z.string(), z.unknown()),
  effective_from: z.string().nullable(),
  effective_to: z.string().nullable(),
  author_user_id: z.string(),
  reason: z.string(),
  state: z.enum(['active', 'withdrawn']),
  withdrawn_at: z.string().nullable(),
  created_at: z.string(),
  transitions: z.array(correctionTransitionItemSchema),
});

const effectiveValueSchema = z.record(z.string(), z.unknown());

export const knowledgeEntityItemSchema = responseObject({
  id: z.string(),
  entity_type_id: z.string(),
  identity_key: z.string(),
  canonical_name: z.string(),
  aliases: z.array(z.string()),
  identifiers: z.record(z.string(), z.string()),
  review_state: z.string(),
  evidence_page_count: count(),
  evidence_refs: z.array(evidenceRefSchema),
  manifest: responseObject({
    pack_id: z.string(),
    pack_version: z.string(),
    extractor_version: z.string(),
  }),
  effective_value: effectiveValueSchema,
  correction: correctionItemSchema.nullable(),
});

export const knowledgeEntityPageSchema = responseObject({
  crawl_id: z.string(),
  total: count(),
  items: z.array(knowledgeEntityItemSchema),
});

export const assertionSubjectSchema = responseObject({
  id: z.string(),
  entity_type_id: z.string(),
  canonical_name: z.string(),
});

export const knowledgeAssertionItemSchema = responseObject({
  id: z.string(),
  predicate_id: z.string(),
  value_type: z.string(),
  raw_value: z.string(),
  normalized_value: z.string(),
  numeric_value: z.number().nullable(),
  unit: z.string(),
  currency: z.string(),
  scope: z.record(z.string(), z.string()),
  // false = a pack-required qualifier was never evidenced. Render such a claim
  // as unscoped; it must never read as fully qualified.
  scope_complete: z.boolean(),
  temporal_state: z.string(),
  effective_from: z.string().nullable(),
  effective_to: z.string().nullable(),
  derivation_method: z.string(),
  confidence: z.number().nullable(),
  review_state: z.string(),
  // null = nothing disputes this claim. NOT "a dispute was resolved".
  contradiction_group_id: z.string().nullable(),
  evidence_refs: z.array(evidenceRefSchema),
  subject: assertionSubjectSchema,
  effective_value: effectiveValueSchema,
  correction: correctionItemSchema.nullable(),
});

export const knowledgeAssertionPageSchema = responseObject({
  crawl_id: z.string(),
  total: count(),
  items: z.array(knowledgeAssertionItemSchema),
});

export const contradictionGroupSchema = responseObject({
  contradiction_group_id: z.string(),
  predicate_id: z.string(),
  scope: z.record(z.string(), z.string()),
  subject: assertionSubjectSchema,
  resolution_state: z.string(),
  correction: correctionItemSchema.nullable(),
  sides: z.array(knowledgeAssertionItemSchema),
});

export const contradictionPageSchema = responseObject({
  crawl_id: z.string(),
  total: count(),
  items: z.array(contradictionGroupSchema),
});

export const knowledgeRelationItemSchema = responseObject({
  id: z.string(),
  relation_type_id: z.string(),
  temporal_state: z.string(),
  source: responseObject({ name: z.string(), entity_type_id: z.string() }),
  target: responseObject({ name: z.string(), entity_type_id: z.string() }),
  evidence_refs: z.array(evidenceRefSchema),
  effective_value: effectiveValueSchema,
  correction: correctionItemSchema.nullable(),
});

export const knowledgeRelationPageSchema = responseObject({
  crawl_id: z.string(),
  total: count(),
  items: z.array(knowledgeRelationItemSchema),
});

export const schemaGraphResponseSchema = responseObject({
  crawl_id: z.string(),
  analyzed_pages: count(),
  pages_with_schema: count(),
  types: z.array(
    responseObject({
      type: z.string(),
      pages: count(),
      valid: count(),
      invalid: count(),
    }),
  ),
  invalid: z.array(
    responseObject({
      site_url_id: z.string(),
      url: z.string(),
      type: z.string(),
      missing: z.array(z.string()),
    }),
  ),
});

// ---------------------------------------------------------------------------
// strictValidate — fail loud on declared-field drift (drift policy §6)
// ---------------------------------------------------------------------------

/**
 * Validate `data` against `schema`, throwing a descriptive error tagged with
 * `context` on any mismatch of a DECLARED field. The backend is the source of
 * truth: a failure here means `schemas.ts` is out of sync and must be fixed —
 * never swallowed. Unknown keys are stripped by `responseObject` (tolerated
 * additive drift); the contract-drift guard (`lib/api/contract-drift.ts`)
 * keeps the two field sets from silently diverging.
 */
export function strictValidate<T>(schema: z.ZodType<T>, data: unknown, context: string): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new Error(`API validation failure in ${context}: ${result.error.message}`);
  }
  return result.data;
}
