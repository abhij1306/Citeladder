import { z } from 'zod';
import { integrationGrantStatusSchema, integrationSyncRunStatusSchema } from './integrations';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

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
