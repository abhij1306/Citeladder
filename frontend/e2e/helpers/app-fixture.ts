import type { Page } from '@playwright/test';

/**
 * Authed-shell network fixture for e2e + visual specs.
 *
 * The app authenticates by cookie session: `SessionGuard` calls
 * `GET /api/v1/auth/me` and `ProjectProvider` calls `GET /api/v1/projects`,
 * so stubbing those two endpoints is the whole "logged in with one project"
 * arrangement — no token needs seeding. The ids are the canonical ones the
 * existing specs already use (shell.spec.ts, content.spec.ts, …).
 */
export const FIXTURE_USER = {
  id: '22222222-2222-4222-8222-222222222222',
  email: 'shell@example.com',
  role: 'owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as const;

export const FIXTURE_PROJECT = {
  id: '11111111-1111-4111-8111-111111111111',
  workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  name: 'Acme',
  brand_name: 'Acme',
  website_url: 'https://acme.example',
  industry: 'general',
  subindustry: '',
  primary_market: 'United States',
  country_code: 'US',
  language_code: 'en',
  benchmark_mode: 'consumer_like',
  default_repetitions: 3,
  brand: { aliases: [] },
  owned_domains: [],
  unintended_domains: [],
  competitors: [],
  prompt_sets: [],
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
} as const;

/**
 * Stub the two shell endpoints, plus a 404 catch-all for everything else
 * under `/api/v1/`. The catch-all is what makes screenshots deterministic:
 * 4xx never retries (lib/api/query-client.ts), so every unstubbed data query
 * settles into its empty/error state in ONE attempt instead of flapping
 * between skeleton and error across the two-retry window. It is also what
 * keeps an unstubbed downstream call (GettingStartedCard's audits query, the
 * shell EntitlementProvider's entitlements query) from falling through to a
 * live backend, 401-ing, and tripping the session guard's "any 401 → logout"
 * path — which is how a spec that only stubs auth/me + projects ends up
 * bounced to /login.
 *
 * Playwright matches routes in reverse registration order, so register the
 * catch-all FIRST and the specific stubs after it; the last-registered
 * matching route wins. `stubs` lets a spec layer its own endpoints on top.
 */
export async function stubAuthedShell(
  page: Page,
  stubs: ReadonlyArray<readonly [string | RegExp, unknown]> = [],
): Promise<void> {
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'e2e fixture: endpoint not stubbed' }),
    }),
  );
  for (const [pattern, body] of stubs) {
    await page.route(pattern, (route) => route.fulfill({ json: body }));
  }
  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: { user: FIXTURE_USER } }));
  await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [FIXTURE_PROJECT] }));
}

/**
 * Hide the Next.js dev overlay (`<nextjs-portal>`) — dev chrome, not product
 * UI. Its badge reflects build activity, so leaving it visible is a flake
 * source in baselines. Call AFTER navigation (addStyleTag needs a document).
 */
export async function hideDevChrome(page: Page): Promise<void> {
  await page.addStyleTag({ content: 'nextjs-portal { display: none !important; }' });
}
