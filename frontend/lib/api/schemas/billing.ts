import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.object(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Billing (provider ids, plan ids, secrets, and billing PII never cross wire)
// ---------------------------------------------------------------------------

// Plan keys are LOCKED to the four the backend publishes. A retired `free`/
// `paid` key must fail parsing rather than render as an unknown tier.
export const planCatalogKeySchema = z.enum(['tier_1', 'tier_2', 'tier_3', 'enterprise']);
export const credentialModeSchema = z.enum(['byok', 'funded']);
export const billingRegionSchema = z.enum(['india', 'international']);
export const catalogAvailabilitySchema = z.enum(['available', 'unavailable']);
export const grantSourceKindSchema = z.enum(['plan', 'addon', 'topup', 'trial', 'override']);
export const entitlementStatusSchema = z.enum(['resolved', 'entitlement_unresolved']);
export const capabilityTypeSchema = z.enum([
  'flag',
  'counter.occupancy',
  'counter.consumable',
  'counter.rate',
  'level',
]);
export const counterCapabilityTypeSchema = z.enum([
  'counter.occupancy',
  'counter.consumable',
  'counter.rate',
]);
/**
 * `limit_state` is the ONLY authority for what a null aggregate means: the
 * backend never uses null to mean both "unlimited" and "unresolved". The UI
 * must branch on this, never on nullability.
 */
export const limitStateSchema = z.enum(['finite', 'unlimited', 'unknown']);
export const activationKindSchema = z.enum(['base', 'addon', 'topup']);
export const activationStatusSchema = z.enum(['pending', 'activated', 'failed', 'abandoned']);

export const moneySchema = responseObject({
  currency: z.enum(['USD', 'INR']),
  amount_minor: z.number().int().nonnegative(),
});

/**
 * The server-resolved charge. `quote_id` is an opaque digest that proves the
 * displayed terms without exposing any provider identity — the frontend
 * compares its displayed price against `base_price` here and never computes a
 * total of its own.
 */
export const resolvedQuoteSchema = responseObject({
  quote_id: z.string(),
  catalog_revision: z.string(),
  catalog_key: z.string(),
  credential_mode: credentialModeSchema,
  country_code: z.string(),
  region: billingRegionSchema,
  base_price: moneySchema,
  credit_price: moneySchema.nullable(),
  tax: moneySchema,
  total_price: moneySchema,
  expires_at: z.string(),
});

export const capabilityValueSchema = responseObject({
  key: z.string(),
  capability_type: capabilityTypeSchema,
  value: z.union([z.boolean(), z.number(), z.string()]).nullable(),
  issuable: z.boolean(),
});

export const catalogProviderRouteSchema = responseObject({
  logical_engine: z.string(),
  measurement_mode: z.enum(['pulse', 'benchmark']).optional(),
  transport_provider: z.string(),
  model: z.string(),
});

/**
 * PUBLIC provider row — availability only, never workspace state. Grok,
 * Perplexity and Copilot appear here as `unavailable` with an empty `routes`
 * list; that absence of a route is what makes them non-connectable.
 */
export const catalogProviderSchema = responseObject({
  key: z.string(),
  label: z.string(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  adapter_shipped: z.boolean(),
  grant_key: z.string(),
  issuable: z.boolean(),
  routes: z.array(catalogProviderRouteSchema),
});

export const catalogPlanSchema = responseObject({
  key: planCatalogKeySchema,
  name: z.string(),
  description: z.string(),
  cadence: z.enum(['monthly', 'custom']),
  self_serve: z.boolean(),
  contact_only: z.boolean(),
  contact_url: z.string().nullable(),
  base_price: moneySchema.nullable(),
  // Null in this release: funded inputs are deliberately unset. Never coerce
  // to zero and never derive a funded total from it.
  credit_price: moneySchema.nullable(),
  funded_total_price: moneySchema.nullable(),
  checkout_available: z.boolean(),
  unavailable_reason: z.string().nullable(),
  capabilities: z.array(capabilityValueSchema),
  trial_availability: catalogAvailabilitySchema,
  trial_unavailable_reason: z.string().nullable(),
  trial_days: z.number().int().nullable(),
});

export const catalogAddonSchema = responseObject({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  cadence: z.literal('monthly'),
  unit_price: moneySchema.nullable(),
  quantity_min: z.number().int(),
  quantity_max: z.number().int(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  grant_key: z.string(),
  grant_value_per_unit: z.number().int(),
});

export const catalogTopupSchema = responseObject({
  key: z.string(),
  name: z.string(),
  description: z.string(),
  unit_price: moneySchema.nullable(),
  quantity_min: z.number().int(),
  quantity_max: z.number().int(),
  availability: catalogAvailabilitySchema,
  unavailable_reason: z.string().nullable(),
  grant_key: z.enum(['audit_credits', 'benchmark_credits', 'pulse_credits']),
  credits_per_unit: z.number().int().nullable(),
  expiry_days: z.number().int(),
});

export const billingCatalogSchema = responseObject({
  catalog_revision: z.string(),
  country_code: z.string().nullable(),
  region: billingRegionSchema,
  currency: z.enum(['USD', 'INR']),
  currency_minor_units: z.number().int(),
  plans: z.array(catalogPlanSchema),
  addons: z.array(catalogAddonSchema),
  topups: z.array(catalogTopupSchema),
  providers: z.array(catalogProviderSchema),
});

export const grantProvenanceSchema = responseObject({
  grant_id: uuid(),
  source_kind: grantSourceKindSchema,
  key: z.string(),
  value: z.number().int(),
  valid_from: z.string(),
  effective_valid_until: z.string().nullable(),
  revoked_at: z.string().nullable(),
  catalog_revision: z.string(),
});

export const resolvedCapabilitySchema = responseObject({
  key: z.string(),
  capability_type: capabilityTypeSchema,
  value: z.union([z.boolean(), z.number(), z.string()]).nullable(),
  contributing_grant_ids: z.array(uuid()),
  ordered_draw_grant_ids: z.array(uuid()),
});

export const subscriptionSummarySchema = responseObject({
  catalog_key: z.string(),
  status: z.string(),
  current_period_end: z.string().nullable(),
  cancel_at_period_end: z.boolean(),
});

export const trialGrantSummarySchema = responseObject({
  deadline: z.string(),
  days_remaining: z.number().int(),
  exhausted: z.boolean(),
});

/**
 * The resolved account entitlement. There is deliberately no
 * `funded_execution_allowed` flag — funded admission is an enforcement-time
 * decision, so the UI must never present one.
 */
export const billingEntitlementSchema = responseObject({
  billing_account_id: uuid(),
  status: entitlementStatusSchema,
  errors: z.array(z.string()),
  registry_revision: z.string(),
  entitlement_lifecycle_version: z.number().int(),
  resolved_at: z.string(),
  valid_until: z.string().nullable(),
  subscription: subscriptionSummarySchema.nullable(),
  trial_grant: trialGrantSummarySchema.nullable(),
  capabilities: z.array(resolvedCapabilitySchema),
  grants: z.array(grantProvenanceSchema),
});

export const usageGrantBalanceSchema = responseObject({
  grant_id: uuid(),
  source_kind: grantSourceKindSchema,
  allowance: z.number().int(),
  consumed: z.number().int(),
  reserved: z.number().int(),
  remaining: z.number().int(),
  effective_valid_until: z.string().nullable(),
});

export const usageItemSchema = responseObject({
  key: z.string(),
  capability_type: counterCapabilityTypeSchema,
  unit: z.string(),
  limit_state: limitStateSchema,
  allowance: z.number().int().nullable(),
  consumed: z.number().int().nullable(),
  reserved: z.number().int().nullable(),
  remaining: z.number().int().nullable(),
  window_started_at: z.string().nullable(),
  resets_at: z.string().nullable(),
  earliest_expiry: z.string().nullable(),
  grants: z.array(usageGrantBalanceSchema),
});

export const billingUsageSchema = responseObject({
  billing_account_id: uuid(),
  entitlement_lifecycle_version: z.number().int(),
  status: entitlementStatusSchema,
  items: z.array(usageItemSchema),
});

/** Every commercial POST answers with this. `quote` is always present. */
export const activationSchema = responseObject({
  activation_id: uuid(),
  kind: activationKindSchema,
  catalog_key: z.string(),
  quantity: z.number().int(),
  status: activationStatusSchema,
  quote: resolvedQuoteSchema,
  checkout_url: z.string().nullable(),
  expires_at: z.string(),
  failure_code: z.string().nullable(),
});

/**
 * Deactivation has its OWN vocabulary — deliberately not the activation state
 * machine. Parsing a DELETE through `activationSchema` would invent a
 * pending/failed lifecycle the backend never reports.
 */
export const subscriptionChangeSchema = responseObject({
  catalog_key: z.string(),
  status: z.enum(['cancellation_scheduled', 'already_scheduled']),
  effective_at: z.string(),
});

// --- Authenticated provider connection state -------------------------------
// Separate contract from the PUBLIC catalog above: availability is what we
// sell, connection state is what this workspace actually has.
export const providerConnectionStateSchema = z.enum([
  'connected',
  'missing',
  'failed',
  'unavailable',
]);

export const providerProbeSchema = responseObject({
  status: z.enum(['ok', 'failed']),
  safe_reason: z.string().nullable(),
  tested_at: z.string(),
  model: z.string().nullable(),
  latency_ms: z.number().int().nullable(),
});

export const providerConnectionStateEntrySchema = responseObject({
  key: z.string(),
  label: z.string(),
  state: providerConnectionStateSchema,
  safe_reason: z.string().nullable(),
  grant_key: z.string(),
  latest_probe: providerProbeSchema.nullable(),
});

export const providerConnectionStatesSchema = responseObject({
  workspace_id: uuid(),
  providers: z.array(providerConnectionStateEntrySchema),
});
