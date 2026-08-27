import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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

// Frozen on the row at enqueue: Website context was either projected in or
// unavailable because no usable crawl evidence existed.
export const groundingStatusSchema = z.enum(['included', 'unavailable', 'conflicting']);

export const contentOutputTypeSchema = z.enum(['website_page']);

// The skill catalog is served by `GET /content/skills`, so the set of valid
// ids is the backend's to decide — mirroring it as a frontend enum here would
// reject any newly added skill on a persisted row. Ids are bounded by the
// `skill_id` column width.
export const contentSkillSchema = z.string().min(1).max(64);

export const contentSkillChannelSchema = z.enum(['web', 'social', 'video', 'community', 'email']);

// One reusable output format. `structure`/`tone`/`length_hint` describe the
// craft constraints the backend applies, shown to the user so the picker can
// explain a skill without restating any directive text client-side.
export const contentSkillViewSchema = responseObject({
  id: contentSkillSchema,
  label: z.string(),
  channel: contentSkillChannelSchema,
  description: z.string(),
  structure: z.array(z.string()).default([]),
  tone: z.string(),
  length_hint: z.string(),
});

export const contentSkillCatalogSchema = responseObject({
  version: z.string(),
  default_skill_id: contentSkillSchema,
  skills: z.array(contentSkillViewSchema),
});

// Public summary of the frozen generation context: counts and URLs only,
// never the rendered blocks themselves.
export const contentContextSummarySchema = responseObject({
  version: z.string(),
  crawl_page_count: z.number().int().nonnegative(),
  crawl_urls: z.array(z.string()).default([]),
  crawl_completed_at: z.string().nullable(),
  brand_fields: z.array(z.string()).default([]),
  search_connected: z.boolean(),
  omissions: z.array(z.record(z.string(), z.unknown())).default([]),
});

// Pre-flight answer for the composer indicator: what would ground a draft
// right now. An absent crawl or unconnected Search Console is a neutral
// absence, not a fault — the UI renders it as such.
export const contentContextPreviewSchema = responseObject({
  crawl_available: z.boolean(),
  crawl_page_count: z.number().int().nonnegative(),
  crawl_completed_at: z.string().nullable(),
  brand_fields: z.array(z.string()).default([]),
  search_connected: z.boolean(),
});

// Fixed vocabulary for why a draft was rejected.
export const contentFeedbackReasonSchema = z.enum([
  'too_generic',
  'wrong_tone',
  'missed_topic',
  'incorrect_facts',
  'other',
]);

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
  grounding_status: groundingStatusSchema,
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
  skill_version: z.string(),
  feedback: z.enum(['accepted', 'rejected']).nullable(),
  // Empty on an acceptance or an older row; otherwise a known reason.
  feedback_reason: z.union([contentFeedbackReasonSchema, z.literal('')]).default(''),
  feedback_at: z.string().nullable(),
  grounding_status: groundingStatusSchema,
  requested_model: z.string(),
  returned_model: z.string().nullable(),
  provider: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  completed_at: z.string().nullable(),
  error_code: z.string(),
  prompt_preview: z.string(),
  prompt: z.string(),
  grounding_summary: contentContextSummarySchema,
  finish_reason: z.string().nullable(),
  output_truncated: z.boolean(),
  output_text: z.string().nullable(),
  usage: z.record(z.string(), z.unknown()).nullable(),
  latency_ms: z.number().int().nullable(),
  error_detail: z.string(),
  generator_version: z.string(),
});
