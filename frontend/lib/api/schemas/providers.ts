import { z } from 'zod';

const responseObject = <Shape extends z.ZodRawShape>(shape: Shape) => z.strictObject(shape);
const uuid = () => z.uuid();

// ---------------------------------------------------------------------------
// Providers (BYOK) — secret never present
// ---------------------------------------------------------------------------

// The complete BYOK transport surface exposed by the provider catalog.
export const transportProviderSchema = z.enum(['openai', 'anthropic', 'google']);
export const logicalEngineSchema = z.enum(['chatgpt', 'gemini', 'claude']);

// A configured route on a connection: which logical engine this transport
// serves and the concrete transport model to call.
export const providerRouteSchema = responseObject({
  id: uuid(),
  logical_engine: logicalEngineSchema,
  transport_provider: transportProviderSchema,
  transport_model: z.string(),
  is_default: z.boolean(),
  // Backend defaults to true.
  active: z.boolean().optional(),
});

// Strict: an unexpected key (e.g. a leaked `api_key`/`secret`) is a contract
// violation and must fail loud — the secret is never present on the wire.
export const providerConnectionSchema = responseObject({
  id: uuid(),
  workspace_id: uuid(),
  // Optional so the pre-B4 minimal shape (used in the schema test) still
  // validates; the live B4 DTO always sends these.
  label: z.string().nullable().optional(),
  transport_provider: transportProviderSchema,
  base_url: z.string().nullable(),
  active: z.boolean(),
  // Presence flag only — the key value itself is NEVER on the wire.
  api_key_set: z.boolean().optional(),
  last_tested_at: z.string().nullable().optional(),
  // Backend defaults to '' (untested); accept any short status string.
  last_test_status: z.string().optional(),
  routes: z.array(providerRouteSchema).optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

const providerCatalogRouteSchema = responseObject({
  measurement_mode: z.enum(['pulse', 'benchmark']),
  transport_provider: transportProviderSchema,
  transport_model: z.string(),
  retrieval_enabled: z.boolean(),
  reasoning_effort: z.string(),
});

const providerCatalogEngineSchema = responseObject({
  logical_engine: logicalEngineSchema,
  routes: z.array(providerCatalogRouteSchema),
});

export const providerCatalogSchema = responseObject({
  transports: z.array(transportProviderSchema),
  engines: z.array(providerCatalogEngineSchema),
});

// `POST /provider-connections/{id}/test`. Lives here with every other response
// contract rather than beside the caller, and locks `status` to the two values
// the backend actually emits so a probe outcome cannot be a free string.
export const connectionTestResultSchema = responseObject({
  connection_id: uuid(),
  status: z.enum(['ok', 'failed']),
  error_code: z.string().default(''),
  detail: z.string().default(''),
  latency_ms: z.number().nullable().default(null),
  logical_engine: z.string().default(''),
  transport_provider: z.string().default(''),
  transport_model: z.string().default(''),
  tested_at: z.string(),
});
