import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

export const commerceComparisonProductSchema = responseObject({
  id: uuid(),
  name: z.string(),
  sku: z.string(),
  competitor_name: z.string(),
  price: z.number().nullable(),
  currency: z.string(),
  attributes: z.record(z.string(), z.unknown()),
  visibility_rate: z.number(),
  average_rank: z.number().nullable(),
  win_rate: z.number().nullable(),
});

export const commerceAttributeGapSchema = responseObject({
  field: z.string(),
  own_value: z.unknown().nullable(),
  competitor_value: z.unknown(),
});

export const commerceComparisonItemSchema = responseObject({
  own_product: commerceComparisonProductSchema,
  competitor_product: commerceComparisonProductSchema,
  match_confidence: z.number(),
  match_reasons: z.array(z.string()),
  attribute_gaps: z.array(commerceAttributeGapSchema),
});

export const commerceComparisonSchema = responseObject({
  id: uuid(),
  project_id: uuid(),
  audit_id: uuid(),
  matcher_version: z.string(),
  comparison_version: z.string(),
  source_metric_ids: z.array(uuid()),
  source_artifact_ids: z.array(uuid()),
  items: z.array(commerceComparisonItemSchema),
  created_at: z.string(),
});
