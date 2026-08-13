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
export const websiteContextStatusSchema = z.enum(['included', 'unavailable']);

export const contentOutputTypeSchema = z.enum(['website_page']);
export const contentSkillSchema = z.enum(['youtube', 'reddit', 'blog', 'article']);

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
  selection_policy_version: z.string().default(''),
  omissions: z.array(z.record(z.string(), z.unknown())).default([]),
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
  skill_version: z.string(),
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
  website_context_summary: websiteContextSummarySchema.nullable(),
  finish_reason: z.string().nullable(),
  output_truncated: z.boolean(),
  output_text: z.string().nullable(),
  usage: z.record(z.string(), z.unknown()).nullable(),
  latency_ms: z.number().int().nullable(),
  error_detail: z.string(),
  generator_version: z.string(),
});
