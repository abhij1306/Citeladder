/**
 * Contract-drift guard (A5, ERR-5).
 *
 * Diffs the backend OpenAPI response-model field sets against the zod
 * schemas' declared keys, so the tolerant-on-unknown policy (`responseObject`
 * in `schemas.ts`) can never become silent divergence:
 *
 *   - **FAIL on missing declared fields** — a zod schema declares a REQUIRED
 *     field the backend response model no longer has. That is drift the UI
 *     needs: `strictValidate` would throw on the real response at runtime.
 *   - **WARN on additive-only diffs** — the backend model carries fields the
 *     zod schema does not declare. The UI keeps working (unknown keys are
 *     stripped), but `schemas.ts` should be updated promptly.
 *
 * The OpenAPI document is obtained DETERMINISTICALLY (no live server needed):
 *   1. `CITELADDER_OPENAPI_JSON` — path to a schema export (CI override);
 *   2. generated offline from the checked-in backend code via the backend
 *      virtualenv (`backend/.venv`) — importing the FastAPI app needs no
 *      server, database, or network;
 *   3. fetched from the live backend at `CITELADDER_BACKEND_ORIGIN`
 *      (default `http://localhost:8000`) as a last resort.
 *
 * Wired into `pnpm test` via `contract-drift.test.ts`; runnable standalone as
 * `pnpm check:contract`. (The guard lives in `lib/api` — not `scripts/` —
 * because it must import the zod contracts, and the repo's `scripts/*.mjs`
 * guards are plain-node programs that never import app TypeScript.)
 */
import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { z } from 'zod';

import {
  CONTRACT_BACKEND_ORIGIN,
  CONTRACT_CODEGEN_TIMEOUT_MS,
  CONTRACT_LIVE_FETCH_TIMEOUT_MS,
} from '@/lib/config/operational';
import * as schemas from './schemas';

/**
 * The lookup behind `declaredKeysFor`: every response schema, all of which now
 * live in `schemas.ts` — the connection-test result moved there with the v8
 * provider contracts, so there is no longer a domain-owned exception.
 */
const CONTRACT_SCHEMAS: Record<string, unknown> = { ...schemas };

// ---------------------------------------------------------------------------
// zod schema → OpenAPI component mapping
// ---------------------------------------------------------------------------

/**
 * The response contracts the UI consumes, mapped to their OpenAPI component.
 * Covers the top-level response objects AND the item shapes of list/page
 * wrappers (the wrappers themselves add no new field sets). A mapped entry
 * that cannot be resolved on either side fails the guard — when a response
 * contract is added or renamed, update this table in the same change.
 */
export const CONTRACT_SCHEMA_MAP = {
  // Auth / workspace / shell
  authResponseSchema: 'AuthResponse',
  registrationResponseSchema: 'RegistrationResponse',
  sessionUserSchema: 'SessionUser',
  workspaceSchema: 'WorkspaceResponse',
  productTourSchema: 'ProductTourResponse',
  oauthStartResponseSchema: 'OAuthStartResponse',
  // Projects / brand
  projectSchema: 'ProjectResponse',
  competitorSchema: 'CompetitorResponse',
  commandCenterSchema: 'CommandCenterResponse',
  brandProfileSchema: 'BrandProfileResponse',
  // Prompts / topics
  promptSchema: 'PromptResponse',
  promptSetSchema: 'PromptSetResponse',
  promptGenerateResponseSchema: 'PromptGenerateResponse',
  topicSchema: 'TopicResponse',
  // Providers
  providerConnectionSchema: 'ProviderConnectionResponse',
  connectionTestResultSchema: 'ProviderConnectionTestResponse',
  providerCatalogSchema: 'ProviderCatalogResponse',
  auditSchema: 'AuditResponse',
  executionSchema: 'AuditTaskResponse',
  executionEvidenceSchema: 'ExecutionEvidenceResponse',
  visibilitySchema: 'VisibilityResponse',
  visibilityTrendPointSchema: 'VisibilityTrendPoint',
  visibilityEvidenceResponseSchema: 'VisibilityEvidenceResponse',
  // Content
  contentGenerationListItemSchema: 'ContentGenerationListItem',
  contentGenerationDetailSchema: 'ContentGenerationDetail',
  // AI Referrals / traffic
  aiReferralsSchema: 'AiReferralsResponse',
  trafficDashboardSchema: 'TrafficDashboardResponse',
  trafficPagesPageSchema: 'TrafficPagesPage',
  trafficQueriesPageSchema: 'TrafficQueriesPage',
  // Integrations
  integrationConnectionSchema: 'IntegrationConnectionResponse',
  integrationSyncRunSchema: 'IntegrationSyncRunResponse',
  integrationSyncEnqueueSchema: 'IntegrationSyncEnqueueResponse',
  integrationTestResultSchema: 'IntegrationTestResponse',
  integrationPropertySchema: 'IntegrationPropertyResponse',
  integrationPropertyMappingSchema: 'IntegrationPropertyMappingResponse',
  // Billing (v8 commercial surface)
  billingCatalogSchema: 'BillingCatalogResponse',
  billingEntitlementSchema: 'BillingEntitlementResponse',
  billingUsageSchema: 'BillingUsageResponse',
  activationSchema: 'ActivationResponse',
  subscriptionChangeSchema: 'SubscriptionChangeResponse',
  resolvedQuoteSchema: 'ResolvedQuoteResponse',
  moneySchema: 'MoneyResponse',
  catalogPlanSchema: 'CatalogPlanResponse',
  catalogAddonSchema: 'CatalogAddonResponse',
  catalogTopupSchema: 'CatalogTopupResponse',
  catalogProviderSchema: 'CatalogProviderResponse',
  capabilityValueSchema: 'CapabilityValueResponse',
  grantProvenanceSchema: 'GrantProvenanceResponse',
  resolvedCapabilitySchema: 'ResolvedCapabilityResponse',
  subscriptionSummarySchema: 'SubscriptionSummaryResponse',
  usageItemSchema: 'UsageItemResponse',
  usageGrantBalanceSchema: 'UsageGrantBalanceResponse',
  // Authenticated provider projection (distinct from the public catalog)
  providerConnectionStatesSchema: 'ProviderConnectionStatesResponse',
  providerConnectionStateEntrySchema: 'ProviderConnectionStateResponse',
  providerProbeSchema: 'ProviderProbeResponse',
  // Opportunities
  opportunitySchema: 'OpportunityItem',
  opportunityDetailSchema: 'OpportunityDetail',
  opportunitiesPageSchema: 'OpportunitiesPage',
  opportunitySummarySchema: 'OpportunitySummary',
  recomputeResponseSchema: 'RecomputeResponse',
  // Site health
  siteCrawlSchema: 'CrawlResponse',
  siteCrawlListPageSchema: 'CrawlListPage',
  siteHealthDashboardSchema: 'DashboardResponse',
  siteHealthEntitlementSchema: 'SiteHealthEntitlementResponse',
  phaseMutationResponseSchema: 'PhaseMutationResponse',
  monitoredUrlsResponseSchema: 'MonitoredUrlsResponse',
  inventoryPageSchema: 'InventoryPage',
  pagesPageSchema: 'PagesPage',
  pageDetailSchema: 'PageDetail',
  siteIssuesPageSchema: 'SiteIssuesPage',
  siteIssueDetailSchema: 'SiteIssueDetail',
  issueHistoryPageSchema: 'IssueHistoryPage',
  rerunPageResponseSchema: 'RerunPageResponse',
} as const;

export type ContractSchemaName = keyof typeof CONTRACT_SCHEMA_MAP;

// ---------------------------------------------------------------------------
// Declared-key extraction (zod runtime introspection)
// ---------------------------------------------------------------------------

export type DeclaredKeys = {
  /** Every declared top-level key. */
  declared: string[];
  /** Declared keys that are REQUIRED inputs (no default, not optional). */
  required: string[];
};

/* oxlint-disable typescript/no-explicit-any */

/** Unwrap array/default/optional/nullable/readonly/pipe wrappers to the object. */
function unwrapToObject(schema: unknown): z.ZodObject | null {
  let current: any = schema;
  for (let depth = 0; depth < 8; depth += 1) {
    if (current instanceof z.ZodObject) return current;
    const def = current?._zod?.def;
    if (!def) return null;
    if (
      current instanceof z.ZodDefault ||
      current instanceof z.ZodOptional ||
      current instanceof z.ZodNullable ||
      current instanceof z.ZodReadonly
    ) {
      current = def.innerType;
      continue;
    }
    if (current instanceof z.ZodArray) {
      current = def.element;
      continue;
    }
    if (current instanceof z.ZodPipe) {
      current = def.out;
      continue;
    }
    return null;
  }
  return null;
}

/** True when the field tolerates an ABSENT key (`.optional()` / `.default()`). */
function toleratesAbsent(field: unknown): boolean {
  let current: any = field;
  for (let depth = 0; depth < 4; depth += 1) {
    if (current instanceof z.ZodOptional || current instanceof z.ZodDefault) return true;
    const def = current?._zod?.def;
    if (!def) return false;
    if (current instanceof z.ZodReadonly || current instanceof z.ZodNullable) {
      current = def.innerType;
      continue;
    }
    return false;
  }
  return false;
}

/* oxlint-enable typescript/no-explicit-any */

/**
 * Extract the declared top-level keys for one mapped zod schema, split into
 * all-declared and required-input. Returns null when the export is missing or
 * does not resolve to an object schema (a guard bug — reported as a failure).
 */
export function declaredKeysFor(name: ContractSchemaName): DeclaredKeys | null {
  const schema = CONTRACT_SCHEMAS[name];
  const object = unwrapToObject(schema);
  if (!object) return null;
  const shape = object.shape;
  const declared = Object.keys(shape);
  const required = declared.filter((key) => !toleratesAbsent(shape[key]));
  return { declared, required };
}

// ---------------------------------------------------------------------------
// OpenAPI component property extraction
// ---------------------------------------------------------------------------

type OpenApiSchemaObject = {
  type?: string;
  properties?: Record<string, unknown>;
  required?: string[];
  allOf?: OpenApiSchemaObject[];
  $ref?: string;
};

export type OpenApiSpec = {
  components?: { schemas?: Record<string, OpenApiSchemaObject> };
};

/** Top-level property names of one component, resolving `allOf`/`$ref` merges. */
export function componentProperties(spec: OpenApiSpec, componentName: string): Set<string> | null {
  const components = spec.components?.schemas ?? {};
  const root = components[componentName];
  if (!root) return null;
  const properties = new Set<string>();
  const visit = (node: OpenApiSchemaObject, seen: Set<string>) => {
    if (node.$ref) {
      const prefix = '#/components/schemas/';
      const targetName = node.$ref.startsWith(prefix) ? node.$ref.slice(prefix.length) : null;
      const target = targetName ? components[targetName] : null;
      if (target && targetName && !seen.has(targetName)) {
        seen.add(targetName);
        visit(target, seen);
      }
      return;
    }
    for (const key of Object.keys(node.properties ?? {})) properties.add(key);
    for (const branch of node.allOf ?? []) visit(branch, seen);
  };
  visit(root, new Set([componentName]));
  return properties;
}

// ---------------------------------------------------------------------------
// The diff
// ---------------------------------------------------------------------------

type ContractDrift = {
  schema: ContractSchemaName;
  component: string;
  /** Required declared keys absent from the backend model — FAIL. */
  missing: string[];
  /** Backend model keys the schema does not declare — WARN. */
  additive: string[];
};

export type ContractDiffResult = {
  drifts: ContractDrift[];
  /** Map entries that failed to resolve on the zod or the OpenAPI side. */
  unresolved: string[];
  warnings: string[];
  failures: string[];
};

function compareMachineKeys(left: string, right: string): number {
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

/** Diff every mapped schema against the spec. Pure — testable offline. */
export function diffContract(spec: OpenApiSpec): ContractDiffResult {
  const drifts: ContractDrift[] = [];
  const unresolved: string[] = [];
  for (const [name, component] of Object.entries(CONTRACT_SCHEMA_MAP) as [
    ContractSchemaName,
    string,
  ][]) {
    const keys = declaredKeysFor(name);
    if (!keys) {
      unresolved.push(`${name}: does not resolve to an object schema in lib/api/schemas.ts`);
      continue;
    }
    const properties = componentProperties(spec, component);
    if (!properties) {
      unresolved.push(`${name}: OpenAPI component '${component}' not found`);
      continue;
    }
    const declared = new Set(keys.declared);
    const missing = keys.required.filter((key) => !properties.has(key));
    const additive = [...properties].filter((key) => !declared.has(key)).sort(compareMachineKeys);
    if (missing.length > 0 || additive.length > 0) {
      drifts.push({ schema: name, component, missing, additive });
    }
  }
  const warnings: string[] = [];
  const failures = unresolved.map((entry) => `unresolved mapping — ${entry}`);
  for (const drift of drifts) {
    if (drift.additive.length > 0) {
      warnings.push(
        `${drift.schema} (${drift.component}): additive backend fields not declared: ${drift.additive.join(', ')}`,
      );
    }
    if (drift.missing.length > 0) {
      failures.push(
        `${drift.schema} (${drift.component}): declared fields missing from the backend model: ${drift.missing.join(', ')}`,
      );
    }
  }
  return { drifts, unresolved, warnings, failures };
}

// ---------------------------------------------------------------------------
// OpenAPI acquisition (deterministic: file → offline codegen → live fetch)
// ---------------------------------------------------------------------------

type OpenApiSource = 'env-file' | 'backend-codegen' | 'live-fetch';

export type AcquiredSpec = { spec: OpenApiSpec; source: OpenApiSource; detail: string };

const GENERATE_OPENAPI_PY =
  'import json; from app.main import app; print(json.dumps(app.openapi()))';

function frontendRoot(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), '../..');
}

function backendPythonCandidates(root: string): string[] {
  return [
    resolve(root, '../backend/.venv/bin/python'),
    resolve(root, '../backend/.venv/Scripts/python.exe'),
  ];
}

/**
 * True when a missing OpenAPI source must FAIL rather than skip.
 *
 * `pnpm check:contract` runs the same vitest file as `pnpm test`, so the
 * documented "the wrapper skips, check:contract fails" split needs an explicit
 * signal — without one both paths skipped and the guard could silently never
 * run anywhere. Only `check:contract` sets `CITELADDER_CONTRACT_STRICT=1`.
 *
 * Deliberately NOT keyed on `CI`: the CI frontend job runs `pnpm test` without
 * a backend virtualenv, so treating `CI` as strict would fail the whole suite
 * on an unavailable spec rather than on real contract drift.
 */
export function contractGuardIsStrict(env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(env.CITELADDER_CONTRACT_STRICT);
}

export type AcquireOpenApiOptions = {
  env?: NodeJS.ProcessEnv;
  root?: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};

type AcquisitionAttempt = { acquired: AcquiredSpec | null; error?: string };

function fileSpecAttempt(exportPath: string | undefined): AcquisitionAttempt {
  if (!exportPath) return { acquired: null };
  try {
    return {
      acquired: {
        spec: JSON.parse(readFileSync(exportPath, 'utf8')) as OpenApiSpec,
        source: 'env-file',
        detail: exportPath,
      },
    };
  } catch (error) {
    return { acquired: null, error: `CITELADDER_OPENAPI_JSON (${exportPath}): ${String(error)}` };
  }
}

function codegenSpecAttempt(root: string, timeoutMs?: number): AcquisitionAttempt {
  const backendDir = resolve(root, '../backend');
  const python = backendPythonCandidates(root).find((candidate) => existsSync(candidate));
  if (!python || !existsSync(backendDir)) {
    return {
      acquired: null,
      error: `backend codegen: no backend virtualenv found next to ${root}`,
    };
  }
  try {
    const stdout = execFileSync(python, ['-c', GENERATE_OPENAPI_PY], {
      cwd: backendDir,
      timeout: timeoutMs ?? CONTRACT_CODEGEN_TIMEOUT_MS,
      maxBuffer: 64 * 1024 * 1024,
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return {
      acquired: {
        spec: JSON.parse(stdout.toString()) as OpenApiSpec,
        source: 'backend-codegen',
        detail: backendDir,
      },
    };
  } catch (error) {
    return { acquired: null, error: `backend codegen (${backendDir}): ${String(error)}` };
  }
}

async function liveSpecAttempt(
  origin: string,
  fetchImpl: typeof fetch,
): Promise<AcquisitionAttempt> {
  try {
    const response = await fetchImpl(`${origin}/openapi.json`, {
      signal: AbortSignal.timeout(CONTRACT_LIVE_FETCH_TIMEOUT_MS),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return {
      acquired: {
        spec: (await response.json()) as OpenApiSpec,
        source: 'live-fetch',
        detail: origin,
      },
    };
  } catch (error) {
    return { acquired: null, error: `live fetch (${origin}): ${String(error)}` };
  }
}

function recordAttempt(errors: string[], attempt: AcquisitionAttempt): AcquiredSpec | null {
  if (attempt.error) errors.push(attempt.error);
  return attempt.acquired;
}

/** Obtain the backend OpenAPI document from file, codegen, then live fetch. */
export async function acquireOpenApiSpec(
  options?: AcquireOpenApiOptions,
): Promise<{ acquired: AcquiredSpec | null; errors: string[] }> {
  const env = options?.env ?? process.env;
  const root = options?.root ?? frontendRoot();
  const errors: string[] = [];
  const fileSpec = recordAttempt(errors, fileSpecAttempt(env.CITELADDER_OPENAPI_JSON));
  if (fileSpec) return { acquired: fileSpec, errors };
  const codegenSpec = recordAttempt(errors, codegenSpecAttempt(root, options?.timeoutMs));
  if (codegenSpec) return { acquired: codegenSpec, errors };
  const origin = env.CITELADDER_BACKEND_ORIGIN ?? CONTRACT_BACKEND_ORIGIN;
  const liveSpec = recordAttempt(
    errors,
    await liveSpecAttempt(origin, options?.fetchImpl ?? fetch),
  );
  return { acquired: liveSpec, errors };
}
