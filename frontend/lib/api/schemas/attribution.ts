import { z } from 'zod';
import { aiSourceSchema } from './analytics';
import { snapshotGranularitySchema } from './traffic';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
