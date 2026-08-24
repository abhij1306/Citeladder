import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
export const promptCohortSchema = z.enum(['core', 'brand_diagnostic', 'comparison', 'commerce']);

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
export const brandProfileReviewStateSchema = z.enum(['unreviewed', 'confirmed', 'edited']);

const brandProfileFieldProvenanceSchema = responseObject({
  origin: brandProfileSourceSchema,
  review_state: brandProfileReviewStateSchema,
  reviewed_by: uuid().nullable(),
  reviewed_at: z.string().nullable(),
});

const brandProfileFieldSourcesSchema = responseObject({
  description: brandProfileFieldProvenanceSchema.nullable(),
  positioning: brandProfileFieldProvenanceSchema.nullable(),
  products_services: brandProfileFieldProvenanceSchema.nullable(),
  target_audience: brandProfileFieldProvenanceSchema.nullable(),
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
