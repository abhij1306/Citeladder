import { z } from 'zod';

// ---------------------------------------------------------------------------
// strictValidate — fail loud on declared-field drift (drift policy §6)
// ---------------------------------------------------------------------------

/**
 * Validate `data` against `schema`, throwing a descriptive error tagged with
 * `context` on any mismatch of a DECLARED field. The backend is the source of
 * truth: a failure here means `schemas.ts` is out of sync and must be fixed —
 * never swallowed. Unknown keys are stripped by `responseObject` (tolerated
 * additive drift); the contract-drift guard (`lib/api/contract-drift.ts`)
 * keeps the two field sets from silently diverging.
 */
export function strictValidate<T>(schema: z.ZodType<T>, data: unknown, context: string): T {
  const result = schema.safeParse(data);
  if (!result.success) {
    throw new Error(`API validation failure in ${context}: ${result.error.message}`);
  }
  return result.data;
}
