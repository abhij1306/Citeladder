import { z } from 'zod';
import { cursorPageSchema } from './site-health';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
