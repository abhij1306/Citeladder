import { z } from 'zod';
import { promptIntentSchema } from './project';
import { cursorPageSchema } from './site-health';
import { metricSeriesSchema, snapshotGranularitySchema } from './traffic';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
