import { z } from 'zod';

const uuid = z.string().uuid();
export const commerceTargetSchema = z
  .object({ kind: z.enum(['category', 'product']), id: uuid })
  .strict();
export const commerceCategorySchema = z
  .object({
    id: uuid,
    name: z.string(),
    role: z.enum(['hub', 'leaf', 'unknown']),
    canonical_url: z.string(),
    product_count: z.number().int(),
    source_analysis_id: uuid.nullable(),
    projector_version: z.string(),
  })
  .strict();
export const commerceProductSchema = z
  .object({
    id: uuid,
    canonical_url: z.string(),
    name: z.string(),
    description: z.string(),
    brand: z.string(),
    price: z.number().nullable(),
    currency: z.string(),
    sku: z.string(),
    gtin: z.string(),
    mpn: z.string(),
    observed_external_id: z.string(),
    variants: z.array(z.unknown()),
    attributes: z.record(z.string(), z.unknown()),
    field_sources: z.record(z.string(), z.unknown()),
    lifecycle_state: z.enum(['active', 'archived']),
    category_ids: z.array(uuid),
    created_at: z.string(),
    updated_at: z.string(),
  })
  .strict();
export const commerceCatalogSchema = z
  .object({
    products: z.array(commerceProductSchema),
    categories: z.array(commerceCategorySchema),
    projection_tasks: z.record(z.string(), z.number().int()),
  })
  .strict();
export const catalogImportSchema = z
  .object({
    import_id: uuid,
    created: z.number().int(),
    updated: z.number().int(),
    unchanged: z.number().int(),
    rejected: z.number().int(),
    row_outcomes: z.array(
      z
        .object({
          row_number: z.number().int(),
          status: z.enum(['created', 'updated', 'unchanged', 'rejected']),
          product_id: uuid.nullable(),
          error_code: z.string(),
          detail: z.string(),
        })
        .strict(),
    ),
  })
  .strict();
export const competitorCandidateSchema = z
  .object({
    id: uuid,
    target_kind: z.enum(['category', 'product']),
    target_id: uuid,
    canonical_url: z.string(),
    product_name: z.string(),
    brand_name: z.string(),
    evidence: z.record(z.string(), z.unknown()),
    source_kind: z.string(),
    state: z.enum(['pending', 'approved', 'rejected', 'excluded']),
    decision_at: z.string().nullable(),
  })
  .strict();
export const competitorDiscoverySchema = z.object({ task_ids: z.array(uuid) }).strict();
export const buyerPromptSchema = z
  .object({
    id: uuid,
    target: commerceTargetSchema,
    text: z.string(),
    enabled: z.boolean(),
    approved_at: z.string().nullable(),
  })
  .strict();
export const shelfSnapshotSchema = z
  .object({
    id: uuid,
    audit_id: uuid,
    target_kind: z.enum(['category', 'product']),
    target_id: uuid,
    product_visibility: z.number(),
    share_of_shelf: z.number().nullable(),
    average_shelf_position: z.number().nullable(),
    first_position_win_rate: z.number().nullable(),
    successful_execution_count: z.number().int(),
    recognized_slot_count: z.number().int(),
    ranked_execution_count: z.number().int(),
    formula_version: z.string(),
    created_at: z.string(),
  })
  .strict();
export const recommendationObservationSchema = z
  .object({
    id: uuid,
    audit_id: uuid,
    target_kind: z.enum(['category', 'product']),
    target_id: uuid,
    product_id: uuid.nullable(),
    competitor_candidate_id: uuid.nullable(),
    observed_product: z.string(),
    observed_brand: z.string(),
    classification: z.string(),
    observed_title: z.string(),
    observed_price: z.number().nullable(),
    observed_currency: z.string(),
    merchant_url: z.string(),
    merchant_domain: z.string(),
    surface_kind: z.enum(['recommendation', 'shopping_result']),
    rank: z.number().int().nullable(),
    order_observable: z.boolean(),
    match_confidence: z.number(),
    artifact_id: uuid,
  })
  .strict();
export const shelfSchema = z
  .object({
    snapshots: z.array(shelfSnapshotSchema),
    observations: z.array(recommendationObservationSchema),
  })
  .strict();

export type CommerceTarget = z.infer<typeof commerceTargetSchema>;
export type CommerceCatalog = z.infer<typeof commerceCatalogSchema>;
export type CommerceProduct = z.infer<typeof commerceProductSchema>;
export type CommerceProductEdit = Partial<
  Pick<
    CommerceProduct,
    | 'canonical_url'
    | 'name'
    | 'description'
    | 'brand'
    | 'price'
    | 'currency'
    | 'sku'
    | 'gtin'
    | 'mpn'
    | 'variants'
    | 'attributes'
    | 'category_ids'
    | 'lifecycle_state'
  >
>;
export type CatalogImport = z.infer<typeof catalogImportSchema>;
export type CompetitorCandidate = z.infer<typeof competitorCandidateSchema>;
export type BuyerPrompt = z.infer<typeof buyerPromptSchema>;
export type Shelf = z.infer<typeof shelfSchema>;
