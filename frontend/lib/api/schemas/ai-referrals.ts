import { z } from 'zod';

import { metricSeriesSchema, snapshotGranularitySchema } from './traffic';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

export const aiSourceSchema = z.enum([
  'chatgpt',
  'gemini',
  'claude',
  'perplexity',
  'copilot',
  'google_ai_overview',
  'other',
]);

export const aiReferralSourceRowSchema = responseObject({
  ai_source: aiSourceSchema.exclude(['other']),
  sessions: z.number().int().nonnegative(),
  share: z.number().min(0).max(1).nullable(),
});

/** Persisted AI-referral measurements from the canonical GA4 source/medium report. */
export const aiReferralsSchema = responseObject({
  project_id: uuid(),
  window_start: z.string(),
  window_end: z.string(),
  granularity: snapshotGranularitySchema,
  referral_volume: metricSeriesSchema,
  referral_share: metricSeriesSchema,
  sources: z.array(aiReferralSourceRowSchema),
  analyzer_version: z.string(),
  formula_version: z.string(),
});
