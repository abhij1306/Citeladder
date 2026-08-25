import { z } from 'zod';
import { auditStatusSchema } from './audits';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Products (agentic commerce) — catalog + visibility projections
// ---------------------------------------------------------------------------

export const productVariantSchema = responseObject({
  name: z.string(),
  sku: z.string(),
  price: z.number().nullable(),
});

// Computed data-quality badge: present/total against the backend config
// matrix (never persisted — computed on read).
export const productCompletenessSchema = responseObject({
  score: z.number(),
  present: z.number().int(),
  total: z.number().int(),
  missing: z.array(z.string()),
});

// Catalog provenance vocabulary (backend `Product.origin`): `manual` rows are
// entered by hand, `imported` rows arrived via CSV/JSON import, and `synced`
// rows are owned by a feed connection (e.g. Shopify). Feed-bound provenance
// fields are null on unbound manual/imported rows.
export const productOriginSchema = z.enum(['manual', 'imported', 'synced']);

export const productSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  sku: z.string(),
  name: z.string(),
  aliases: z.array(z.string()),
  variants: z.array(productVariantSchema),
  price: z.number().nullable(),
  currency: z.string(),
  url: z.string(),
  attributes: z.record(z.string(), z.unknown()),
  origin: productOriginSchema,
  // Feed binding (nullable): the connection that owns the row, the
  // provider's item reference, and the last sync run that observed it.
  connection_id: uuid().nullable(),
  external_item_ref: z.string().nullable(),
  last_seen_sync_run_id: uuid().nullable(),
  completeness: productCompletenessSchema,
  created_at: z.string(),
  updated_at: z.string(),
});

// D1 import feedback: the bulk-import response carries the refreshed catalog
// plus a per-row outcome summary (backend `ProductImportResponse`). `updated`
// is reserved (v1 imports are insert-only, so it is always 0).
export const productImportRowErrorSchema = responseObject({
  row: z.number().int(),
  field: z.string(),
  message: z.string(),
});

export const productImportSummarySchema = responseObject({
  created: z.number().int().nonnegative(),
  updated: z.number().int().nonnegative(),
  skipped: z.number().int().nonnegative(),
  errors: z.array(productImportRowErrorSchema),
});

export const productImportResponseSchema = responseObject({
  items: z.array(productSchema),
  summary: productImportSummarySchema,
});

// D4 delete guard: read-only frozen-audit usage check for one product
// (backend `ProductAuditReferences`).
export const productAuditReferencesSchema = responseObject({
  product_id: uuid(),
  referenced: z.boolean(),
  audit_count: z.number().int().nonnegative(),
});

// Buyer-destination classification vocabulary (backend `MERCHANT_KINDS`).
export const buyerDestinationKindSchema = z.enum([
  'marketplace',
  'retailer',
  'brand_site',
  'other',
]);

// Persisted buyer-destination aggregate for one visibility entry: the total
// destination count, per-kind tallies, and per-domain rows (sanitized —
// domain + display name only, never a raw URL).
export const buyerDestinationMixSchema = responseObject({
  total: z.number().int().nonnegative(),
  by_kind: z
    .object({
      merchant_kind: buyerDestinationKindSchema,
      count: z.number().int().nonnegative(),
    })
    .array(),
  by_domain: z
    .object({
      merchant_domain: z.string(),
      merchant_name: z.string(),
      merchant_kind: buyerDestinationKindSchema,
      count: z.number().int().nonnegative(),
    })
    .array(),
});

// Price-relation tallies (backend `price_relation` vocabulary). Strict
// partial: v2 rows count every key, v1 rows count only `match`/`mismatch`,
// and `{}` is valid (a v1 entry with nothing verifiable). Direction is NEVER
// inferred for v1 data — the UI renders `Direction unavailable` there.
export const priceRelationCountsSchema = responseObject({
  match: z.number().int().nonnegative().optional(),
  higher: z.number().int().nonnegative().optional(),
  lower: z.number().int().nonnegative().optional(),
  mismatch: z.number().int().nonnegative().optional(),
});

// Attribute-dimension mention frequency: `{group: {dimension: count}}`.
export const attributeDimensionFrequencySchema = z.record(
  z.string(),
  z.record(z.string(), z.number().int().nonnegative()),
);

// Fields the analyzer-v2 projection adds to every visibility entry (own and
// competitor): row-level analyzer version (mixed-version audits label each
// row with its ACTUAL persisted version), win rate, price relation, and the
// attribute/destination aggregates. Rates stay null when the
// backend could not compute them (never a fabricated 0).
const productVisibilityEntryV2Fields = {
  product_analyzer_version: z.string(),
  win_rate: z.number().nullable(),
  price_mismatch_rate: z.number().nullable(),
  price_relation_counts: priceRelationCountsSchema,
  attribute_dimension_frequency: attributeDimensionFrequencySchema,
  buyer_destination_mix: buyerDestinationMixSchema,
  prompt_coverage: z.number().nullable(),
  frozen_prompt_context: z.array(
    responseObject({
      prompt_index: z.number().int(),
      text: z.string(),
      theme: z.string(),
      intent: z.string(),
    }),
  ),
  conversation_themes: z.array(z.string()),
} as const;

export const productVisibilityEntrySchema = responseObject({
  // Nullable: the aggregate survives the catalog row's delete (SET NULL).
  product_id: uuid().nullable(),
  sku: z.string(),
  name: z.string(),
  category: z.string(),
  mention_count: z.number().int(),
  sov_share: z.number(),
  avg_rank: z.number().nullable(),
  rank_distribution: z.record(z.string(), z.number().int()),
  price_mention_count: z.number().int(),
  // null = no verifiable price mentions (never a fabricated 0).
  price_accuracy_rate: z.number().nullable(),
  visibility_rate: z.number(),
  top_three_rate: z.number(),
  engine_coverage: z.number().int().nonnegative(),
  visibility_delta: z.number().nullable(),
  ...productVisibilityEntryV2Fields,
});

// Selected-audit product dashboard projection (persisted rows only). Identity
// (sku/name/competitor_name) comes from the audit's frozen configuration.
export const productVisibilitySchema = responseObject({
  project_id: uuid(),
  audit_id: uuid(),
  audit_status: auditStatusSchema,
  product_analyzer_version: z.string(),
  product_scoring_rule_version: z.string(),
  total_mentions: z.number().int(),
  total_analyses: z.number().int(),
  summary: responseObject({
    products_tracked: z.number().int().nonnegative(),
    products_visible: z.number().int().nonnegative(),
    visibility_rate: z.number(),
    top_three_rate: z.number(),
    average_rank: z.number().nullable(),
  }),
  products: z.array(productVisibilityEntrySchema),
  citation_comparison: responseObject({
    status: z.enum(['available', 'no_citations']),
    limitation: z.string(),
    categories: z.array(
      responseObject({
        category: z.string(),
        response_count: z.number().int().nonnegative(),
        brand_response_count: z.number().int().nonnegative(),
        uploaded_products: z.array(z.string()),
        uploaded_commerce_citation_count: z.number().int().nonnegative(),
        competitor_citation_count: z.number().int().nonnegative(),
        third_party_citation_count: z.number().int().nonnegative(),
        competitor_mentions: z.array(
          responseObject({
            competitor_name: z.string(),
            response_count: z.number().int().nonnegative(),
            distinct_prompts: z.number().int().nonnegative(),
            distinct_engines: z.number().int().nonnegative(),
            analysis_ids: z.array(uuid()),
            artifact_ids: z.array(uuid()),
          }),
        ),
        cited_sources: z.array(
          responseObject({
            domain: z.string(),
            title: z.string(),
            representative_url: z.string(),
            classification: z.string(),
            matched_competitor: z.string().nullable(),
            citation_count: z.number().int().nonnegative(),
            distinct_prompts: z.number().int().nonnegative(),
            distinct_engines: z.number().int().nonnegative(),
            citation_ids: z.array(uuid()),
            analysis_ids: z.array(uuid()),
            artifact_ids: z.array(uuid()),
          }),
        ),
      }),
    ),
  }),
  created_at: z.string(),
});

export const productVisibilityTrendPointSchema = responseObject({
  audit_id: uuid(),
  observed_at: z.string(),
  visibility_rate: z.number(),
  top_three_rate: z.number(),
  average_rank: z.number().nullable(),
});

export const productVisibilityTrendResponseSchema = responseObject({
  project_id: uuid(),
  product_id: uuid(),
  sku: z.string(),
  name: z.string(),
  points: z.array(productVisibilityTrendPointSchema),
});

// Evidence kind vocabulary (backend projection): one stable `evidence_id`
// per persisted row (ProductMention.id / MerchantMention.id / a
// config-namespaced UUIDv5 for attribute mentions), so React keys never fall
// back to an array index.
export const productEvidenceKindSchema = z.enum([
  'product_mention',
  'attribute_mention',
  'buyer_destination',
]);

// Item-level price relation (backend `price_relation` persisted string).
// `mismatch` is NOT storable item-level (it only exists as the v1 aggregate
// fallback for unverifiable direction), so it is not in this enum.
export const priceRelationSchema = z.enum(['match', 'higher', 'lower']);

// Generalized evidence row: one pinned key set for every kind, with the
// kind-specific field groups present on every row and null for the other
// kinds (the backend emits exactly this shape).
export const productEvidenceItemSchema = responseObject({
  evidence_id: uuid(),
  analysis_id: uuid(),
  evidence_kind: productEvidenceKindSchema,
  audit_id: uuid(),
  // Execution id — opens the in-run evidence drawer via `?execution=[taskId]`.
  task_id: uuid(),
  artifact_id: uuid().nullable(),
  logical_engine: z.string(),
  transport_model: z.string(),
  // Frozen prompt text (AuditPromptSnapshot) — survives prompt edits.
  prompt_text: z.string(),
  prompt_index: z.number().int(),
  repetition: z.number().int(),
  product_analyzer_version: z.string(),
  matched_name: z.string(),
  matched_sku: z.string(),
  created_at: z.string(),
  // Product-mention fields (null for the other kinds).
  first_offset: z.number().int().nullable(),
  rank_position: z.number().int().nullable(),
  price_value: z.number().nullable(),
  // null = not verifiable (no catalog price / currency mismatch).
  price_matches_catalog: z.boolean().nullable(),
  price_relation: priceRelationSchema.nullable(),
  price_text: z.string(),
  price_currency: z.string(),
  // Attribute-mention fields (null for the other kinds).
  attribute_dimension: z.string().nullable(),
  attribute_group: z.string().nullable(),
  attribute_text: z.string().nullable(),
  attribute_offset: z.number().int().nullable(),
  // Buyer-destination fields (null for the other kinds; the URL arrives
  // already sanitized by the backend).
  merchant_name: z.string().nullable(),
  merchant_domain: z.string().nullable(),
  merchant_kind: buyerDestinationKindSchema.nullable(),
  destination_url: z.string().nullable(),
});

export const productEvidenceResponseSchema = responseObject({
  items: z.array(productEvidenceItemSchema),
  truncated: z.boolean(),
});
