/**
 * React Query key namespaces (F2).
 *
 * All ids are string UUIDs (workspace-scoped contract). One namespace per API
 * domain owner, each defined in its own module under `query-keys/`:
 *   - core.ts          — auth, workspaces, projects, prompts, providers, content
 *   - runs.ts          — runs (audits + executions), visibility
 *   - site-health.ts   — site health (crawls, inventory, monitored, issues)
 *   - integrations.ts  — integrations (connections, sync runs)
 *   - traffic.ts       — traffic (dashboard, pages, queries)
 *   - analytics.ts     — LLM analytics (headline, referrals, themes)
 *   - products.ts      — products (agentic commerce catalog + visibility)
 *   - opportunities.ts — opportunities (catalog, detail, summary)
 *   - commerce.ts      — commerce (catalog feed health)
 *   - attribution.ts   — attribution (snapshot + recompute)
 *
 * This facade re-assembles them under the historical `queryKeys` shape so the
 * 20+ existing importers keep the single `@/lib/api/query-keys` entry point.
 */
import { analyticsKeys } from './query-keys/analytics';
import { agentKeys } from './query-keys/agent';
import { attributionKeys } from './query-keys/attribution';
import { billingKeys } from './query-keys/billing';
import { commerceKeys } from './query-keys/commerce';
import {
  authKeys,
  contentKeys,
  projectKeys,
  promptKeys,
  providerKeys,
  topicKeys,
  workspaceKeys,
} from './query-keys/core';
import { integrationKeys } from './query-keys/integrations';
import { opportunityKeys } from './query-keys/opportunities';
import { productKeys } from './query-keys/products';
import { runKeys, visibilityKeys } from './query-keys/runs';
import { siteHealthKeys } from './query-keys/site-health';
import { trafficKeys } from './query-keys/traffic';

export const queryKeys = {
  agent: agentKeys,
  auth: authKeys,
  billing: billingKeys,
  workspaces: workspaceKeys,
  projects: projectKeys,
  prompts: promptKeys,
  topics: topicKeys,
  providers: providerKeys,
  runs: runKeys,
  visibility: visibilityKeys,
  siteHealth: siteHealthKeys,
  content: contentKeys,
  integrations: integrationKeys,
  traffic: trafficKeys,
  analytics: analyticsKeys,
  products: productKeys,
  opportunities: opportunityKeys,
  commerce: commerceKeys,
  attribution: attributionKeys,
} as const;
