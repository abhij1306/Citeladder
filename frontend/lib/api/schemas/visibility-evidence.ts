import { z } from 'zod';
import { citationSchema, measurementModeSchema } from './audits';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
