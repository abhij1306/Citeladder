import { expect, test } from '@playwright/test';

/**
 * Content screen stubbed e2e (Task 5).
 *
 * All backend calls are stubbed at the network layer (mirrors
 * `providers.spec.ts`) so the spec runs without a live backend. Covers: the
 * live "Content" nav link, the enqueue → poll → sanitised-Markdown-output
 * happy path, and the cancel flow. The real-stack integration (worker + mock
 * provider + disposable DB) lives in `content-integration.spec.ts`.
 */
const WORKSPACE_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT_ID = '22222222-2222-4222-8222-222222222222';
const GEN_ID = '33333333-3333-4333-8333-333333333333';

const user = {
  id: '44444444-4444-4444-8444-444444444444',
  email: 'content@example.com',
  role: 'owner',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const project = {
  id: PROJECT_ID,
  workspace_id: WORKSPACE_ID,
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
};

function generation(overrides: Record<string, unknown> = {}) {
  return {
    id: GEN_ID,
    project_id: PROJECT_ID,
    status: 'queued',
    output_type: 'website_page',
    skill_id: 'article',
    opportunity_id: null,
    skill_version: 'content-v1',
    feedback: null,
    feedback_at: null,
    grounding_status: 'included',
    requested_model: 'mistral-small-latest',
    returned_model: null,
    provider: 'mistral',
    created_at: '2026-07-15T00:00:00Z',
    updated_at: '2026-07-15T00:00:00Z',
    completed_at: null,
    error_code: '',
    prompt_preview: 'Write an about page',
    prompt: 'Write an about page for Acme.',
    grounding_summary: {
      version: 'grounding-envelope-v1',
      allowed_fact_count: 2,
      source_ref_count: 3,
      crawl_fragment_count: 1,
      prohibited_claim_classes: ['pricing'],
      omissions: [],
      budget: {},
    },
    finish_reason: null,
    output_truncated: false,
    output_text: null,
    usage: null,
    latency_ms: null,
    error_detail: '',
    generator_version: 'content-v1',
    ...overrides,
  };
}

const succeeded = generation({
  status: 'succeeded',
  returned_model: 'mistral-small-2506',
  finish_reason: 'stop',
  output_text: '# About Acme\n\nWe make excellent things.',
  usage: { total_tokens: 30 },
  latency_ms: 420,
  completed_at: '2026-07-15T00:01:00Z',
});

test('content nav link is live and the enqueue → output flow renders sanitised markdown', async ({
  page,
}) => {
  let enqueued = false;
  let detailCalls = 0;

  // 404 catch-all FIRST (reverse registration order means the specific stubs
  // below still win) — keeps unstubbed downstream queries from 401-ing a live
  // backend and tripping the session guard's any-401 → /login redirect.
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'e2e fixture: endpoint not stubbed' }),
    }),
  );

  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: { user } }));
  await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [project] }));
  await page.route('**/api/v1/content/generations?*', (route) =>
    route.fulfill({ json: enqueued ? [succeeded] : [] }),
  );
  await page.route('**/api/v1/content/generations', (route) => {
    if (route.request().method() === 'POST') {
      enqueued = true;
      return route.fulfill({ status: 201, json: generation() });
    }
    return route.fulfill({ json: enqueued ? [succeeded] : [] });
  });
  await page.route(`**/api/v1/content/generations/${GEN_ID}`, (route) => {
    detailCalls += 1;
    return route.fulfill({ json: detailCalls < 2 ? generation() : succeeded });
  });

  await page.goto('/visibility');
  const navLink = page.getByRole('link', { name: 'Content', exact: true });
  await expect(navLink).toBeVisible();
  await navLink.click();
  await expect(page).toHaveURL(/\/content$/);

  const promptBox = page.getByRole('textbox', { name: /describe the website content/i });
  await expect(
    page.getByText('Uses confirmed facts and crawl evidence when available'),
  ).toBeVisible();
  await promptBox.fill('Write an about page for Acme.');
  await page.getByRole('button', { name: 'Generate' }).click();

  // The queued state may resolve before the browser paints; assert the durable result.
  await expect(page.getByRole('heading', { name: 'About Acme' })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/returned model: mistral-small-2506/i)).toBeVisible();
  await expect(page.getByText(/Grounding: 2 confirmed facts · 1 crawl fragments/i)).toBeVisible();
});

test('cancel during generation returns the screen to a non-generating state', async ({ page }) => {
  let cancelled = false;

  // 404 catch-all FIRST (reverse registration order means the specific stubs
  // below still win) — keeps unstubbed downstream queries from 401-ing a live
  // backend and tripping the session guard's any-401 → /login redirect.
  await page.route('**/api/v1/**', (route) =>
    route.fulfill({
      status: 404,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'e2e fixture: endpoint not stubbed' }),
    }),
  );

  await page.route('**/api/v1/auth/me', (route) => route.fulfill({ json: { user } }));
  await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [project] }));
  await page.route('**/api/v1/content/generations?*', (route) => route.fulfill({ json: [] }));
  await page.route('**/api/v1/content/generations', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({ status: 201, json: generation() });
    }
    return route.fulfill({ json: [] });
  });
  await page.route(`**/api/v1/content/generations/${GEN_ID}`, (route) =>
    route.fulfill({
      json: cancelled ? generation({ status: 'cancelled', error_code: 'cancelled' }) : generation(),
    }),
  );
  await page.route(`**/api/v1/content/generations/${GEN_ID}/cancel`, (route) => {
    cancelled = true;
    return route.fulfill({
      json: generation({ status: 'cancelled', error_code: 'cancelled' }),
    });
  });

  await page.goto('/content');
  await page
    .getByRole('textbox', { name: /describe the website content/i })
    .fill('Write an about page.');
  await page.getByRole('button', { name: 'Generate' }).click();

  await expect(page.getByRole('status', { name: /generating content/i })).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();
  await expect(page.getByRole('status', { name: /generating content/i })).not.toBeVisible({
    timeout: 10_000,
  });
  // Composer is editable again.
  await expect(page.getByRole('textbox', { name: /describe the website content/i })).toBeEnabled();
});
