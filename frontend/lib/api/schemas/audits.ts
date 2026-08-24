import { z } from 'zod';
import { benchmarkModeSchema } from './project';
import { logicalEngineSchema, transportProviderSchema } from './providers';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
  measurement_mode: z.enum(['pulse', 'benchmark']).default('benchmark'),
  audit_scope: z.enum(['brand', 'commerce']).default('brand'),
  model_provenance: z.array(modelProvenanceSchema).default([]),
  repetitions: z.number().int(),
  random_seed: z.string(),
  requested_count: z.number().int(),
  completed_count: z.number().int(),
  failed_count: z.number().int(),
  error_message: z.string(),
  engine_snapshots: z.array(auditEngineSnapshotSchema),
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

// Queue/execution row status (B5 task statuses). This must list EVERY status
// the queue can persist, not just the ones a run usually ends on: the response
// is strictly validated, so a single row in a missing status fails the whole
// executions list. `capacity_wait` (parked on a full provider pool) and
// `pending_reservation` (funded task awaiting its ledger reservation) are both
// transient, both common mid-run, and both were absent — which is why a live
// run's executions table errored out and then loaded fine once it terminalized.
export const executionStatusSchema = z.enum([
  'pending_reservation',
  'queued',
  'leased',
  'running',
  'succeeded',
  'retry_wait',
  'capacity_wait',
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
  // Execution surface: the provenance triple is SINGULAR (one execution = one
  // exact model), projected from the frozen task snapshots only.
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
