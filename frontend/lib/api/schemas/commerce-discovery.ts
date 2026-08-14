import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Commerce discovery + competitor intelligence. These responses are durable
// candidate / comparison evidence; the browser never performs acquisition or
// matching itself.
// ---------------------------------------------------------------------------
export const commerceCandidateKindSchema = z.enum(['own', 'competitor']);
export const commerceDiscoveryInputKindSchema = z.enum(['upload', 'url']);
export const commerceCandidateInputSchema = z.object({
  candidate_kind: commerceCandidateKindSchema.optional(),
  competitor_id: uuid().nullable().optional(),
  name: z.string().min(1),
  sku: z.string().optional(),
  aliases: z.array(z.string()).optional(),
  variants: z.array(z.record(z.string(), z.unknown())).optional(),
  price: z.number().nullable().optional(),
  currency: z.string().optional(),
  url: z.string().optional(),
  attributes: z.record(z.string(), z.unknown()).optional(),
  availability: z.string().optional(),
  extraction_confidence: z.number().min(0).max(1).optional(),
});
export const commercePreviewRowErrorSchema = responseObject({
  row: z.number().int().positive(),
  field: z.string(),
  message: z.string(),
});
export const commerceDiscoveryPreviewSchema = responseObject({
  accepted: z.array(commerceCandidateInputSchema),
  duplicates: z.array(z.number().int().positive()),
  errors: z.array(commercePreviewRowErrorSchema),
  truncated: z.boolean(),
});
export const commerceMatchDecisionSchema = responseObject({
  target_id: uuid().nullable(),
  target_kind: z.enum(['product', 'competitor_product']),
  confidence: z.number(),
  reasons: z.array(z.string()),
  review_required: z.boolean(),
});
export const commerceCandidateSchema = responseObject({
  id: uuid(),
  run_id: uuid(),
  task_id: uuid(),
  artifact_id: uuid(),
  candidate_kind: commerceCandidateKindSchema,
  competitor_id: uuid().nullable(),
  identity: z.record(z.string(), z.unknown()),
  extraction_confidence: z.number(),
  created_at: z.string(),
  matches: z.array(commerceMatchDecisionSchema),
});
export const commerceDiscoveryRunSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  input_kind: commerceDiscoveryInputKindSchema,
  status: z.string(),
  configuration: z.record(z.string(), z.unknown()),
  discovery_version: z.string(),
  created_at: z.string(),
  completed_at: z.string().nullable(),
  candidates: z.array(commerceCandidateSchema),
});
export const commerceCandidateAcceptSchema = responseObject({
  review_id: uuid(),
  candidate_id: uuid(),
  status: z.enum(['accepted', 'rejected']),
  product_id: uuid().nullable(),
  competitor_product_id: uuid().nullable(),
  match_reason: z.string(),
  match_confidence: z.number(),
});
export const competitorComparisonSnapshotSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  competitor_id: uuid().nullable(),
  source_catalog_ids: z.record(z.string(), z.array(uuid())),
  source_artifact_ids: z.array(uuid()),
  matcher_version: z.string(),
  comparison_version: z.string(),
  comparison: z.record(z.string(), z.unknown()),
  truncated: z.boolean(),
  created_at: z.string(),
});
