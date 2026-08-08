import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { ProjectProvider } from '@/lib/project/project-context';
import { SiteHealthScreen } from './site-health-screen';

// The analyzing/scored inventory modes render PagesTable (clickable rows) and
// the Site Intelligence workspace (panel state mirrored to the URL); stub
// next/navigation, which is unavailable in jsdom.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/site-health',
  useSearchParams: () => new URLSearchParams(),
}));

const WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';

const project = {
  id: PROJECT,
  workspace_id: WORKSPACE,
  name: 'Acme',
  brand_name: 'Acme',
  website_url: 'https://acme.com',
  industry: 'General',
  subindustry: '',
  primary_market: 'US',
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

const entitlement = {
  workspace_id: WORKSPACE,
  access_mode: 'full',
  sample_url_limit: 10,
  monitored_url_limit: 50,
  count_disclosure: true,
  resolver_status: 'resolved',
  registry_revision: 'registry-v8',
  entitlement_lifecycle_version: 1,
  valid_until: null,
  contributing_grant_ids: [],
  advanced_controls_enabled: false,
};

// Bounded site-facts blob the worker persists (`_crawl_setup` in
// backend/app/workers/site_health_worker.py); the backend always emits the key,
// so every MSW crawl payload must carry it or the strict schema rejects it.
const siteFacts = {
  robots: {
    fetched: true,
    url: 'https://acme.com/robots.txt',
    status_code: 200,
    ai_crawlers: {
      GPTBot: 'block',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
    sitemaps: ['https://acme.com/sitemap.xml'],
  },
  llms_txt: { fetched: true, url: 'https://acme.com/llms.txt', status_code: 200, present: true },
  sitemap: { fetched: false, files: [] },
};

function crawl(overrides: Record<string, unknown> = {}) {
  return {
    id: CRAWL,
    workspace_id: WORKSPACE,
    project_id: PROJECT,
    profile_id: '55555555-5555-4555-8555-555555555555',
    status: 'failed',
    discovery_status: 'completed',
    analysis_status: 'failed',
    root_url: 'https://acme.com/',
    sample_mode: false,
    seed: '1',
    inventory_complete: true,
    visible_url_count: 3,
    analyzed_count: 0,
    failed_count: 0,
    discovery_requested_count: 3,
    analysis_requested_count: 0,
    counters: {
      discovered: 3,
      selected: 0,
      queued: 0,
      running: 0,
      analyzed: 0,
      errors: 0,
      blocked: 0,
      by_page_kind: {},
    },
    discovered_count: 3,
    total_url_count: 3,
    has_more_site_urls: false,
    score_summary: null,
    failure_summary: null,
    site_facts: siteFacts,
    extractor_version: 'e1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
    error_message: '',
    created_at: '2026-07-16T00:00:00Z',
    updated_at: '2026-07-16T00:00:00Z',
    started_at: '2026-07-16T00:00:00Z',
    completed_at: '2026-07-16T00:05:00Z',
    ...overrides,
  };
}

function inventoryRow(id: string, url: string) {
  return {
    site_url_id: id,
    normalized_url: url,
    display_url: url,
    title: null,
    content_type: 'text/html',
    source: 'link',
    depth: 1,
    monitored: false,
    first_seen_at: null,
    last_seen_at: null,
    issue_count: null,
    technical_score: null,
    aeo_score: null,
    overall_score: null,
    last_audited: null,
    page_kind: null,
  };
}

function mockRoutes(crawlOverrides: Record<string, unknown> = {}) {
  mswServer.use(
    http.get('/api/v1/projects', () => HttpResponse.json([project])),
    http.post('/api/v1/projects/:id/logos/refresh', () => HttpResponse.json(project)),
    http.get('/api/v1/entitlements', () => HttpResponse.json(entitlement)),
    http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
      HttpResponse.json({
        project_id: PROJECT,
        crawl: crawl(crawlOverrides),
        score_summary: null,
        quota: { used: 3, limit: 50 },
        root_errors: [],
        phase_runs: { discovery: null, analysis: null },
      }),
    ),
    http.get(`/api/v1/projects/${PROJECT}/monitored-urls`, () =>
      HttpResponse.json({
        project_id: PROJECT,
        selection_version: 1,
        monitored_urls: [],
        quota: { used: 0, limit: 50 },
      }),
    ),
    http.get(`/api/v1/site-crawls/${CRAWL}/pages`, () =>
      HttpResponse.json({ items: [], next_cursor: null, root_errors: [] }),
    ),
    http.get(`/api/v1/site-crawls/${CRAWL}/inventory`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
    http.get(`/api/v1/site-crawls/${CRAWL}/events`, () => HttpResponse.text('', { status: 200 })),
  );
}

function renderScreen() {
  return renderWithProviders(
    <ProjectProvider>
      <SiteHealthScreen />
    </ProjectProvider>,
  );
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => {
  // ProjectProvider backfills a logo for fixtures without one. Keep the
  // production refresh behavior enabled and satisfy it with the shared MSW
  // pattern used by other project-screen tests.
  mswServer.use(http.post('/api/v1/projects/:id/logos/refresh', () => HttpResponse.json(project)));
});
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('SiteHealthScreen — loading failures', () => {
  it('shows an error instead of an endless skeleton when entitlement loading fails', async () => {
    mockRoutes();
    mswServer.use(
      http.get('/api/v1/entitlements', () =>
        HttpResponse.json({ detail: 'Access unavailable' }, { status: 403 }),
      ),
    );

    renderScreen();

    expect(await screen.findByText('Could not load Site Health. Please refresh.')).toBeVisible();
  });

  it('shows a recoverable warning when entitlement resolution fails closed', async () => {
    mockRoutes();
    mswServer.use(
      http.get('/api/v1/entitlements', () =>
        HttpResponse.json({ ...entitlement, resolver_status: 'entitlement_unresolved' }),
      ),
    );

    renderScreen();

    expect(await screen.findByText(/Site Health access could not be resolved/)).toBeVisible();
  });
});

describe('SiteHealthScreen — terminal states on the canonical screen', () => {
  it('renders an explicit terminal notice (not the active-progress UI) for a failed crawl', async () => {
    mockRoutes({ status: 'failed', error_message: 'Robots.txt denied crawling.' });

    renderScreen();

    // B1: the terminal card renders reason + what-to-do guidance (one span).
    expect(
      await screen.findByText(/Robots\.txt denied crawling\. Re-crawl to try again\./),
    ).toBeInTheDocument();
    // The header offers the restart — the screen itself stays the dashboard.
    expect(screen.getByRole('button', { name: 'Start a new crawl' })).toBeInTheDocument();
    // No redundant Cancel control for an already-stopped crawl.
    expect(screen.queryByRole('button', { name: 'Cancel' })).not.toBeInTheDocument();
    // The score section stays mounted with placeholders (no screen swap).
    expect(screen.getByTestId('score-section')).toBeInTheDocument();
  });

  it('routes a failed crawl with a PRESENT-but-null-score summary to terminal (the SH-2 shape)', async () => {
    // The production shape behind SH-2: a fully-failed crawl persists an
    // EMPTY summary object (persist_empty=True) whose scores are all null —
    // `score_summary != null` alone misreads it as dashboard-worthy. The
    // phase resolution must probe the failure shape (nothing analyzed AND no
    // overall score) and land on the terminal card with the API-projected
    // failure reason instead.
    mockRoutes({
      status: 'failed',
      analysis_status: 'failed',
      analyzed_count: 0,
      score_summary: {
        overall_score: null,
        technical_score: null,
        aeo_score: null,
        selected_count: 0,
        analyzed_count: 0,
        issue_count: 0,
        scoring_version: 's1',
        by_page_kind: {},
      },
      failure_summary: {
        code: 'http_5xx',
        message: 'The site returned HTTP 500 after 3 attempts',
        attempts: 3,
        status_code: 500,
        target_url: 'https://acme.com/',
      },
      error_message: 'The site returned HTTP 500 after 3 attempts',
    });

    renderScreen();

    // Terminal card with the failure-summary reason + code-aware guidance —
    // NOT an empty dashboard.
    expect(
      await screen.findByText(
        /The site returned HTTP 500 after 3 attempts\. The site is having server trouble/,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start a new crawl' })).toBeInTheDocument();
  });

  it('renders the root-failure block on the Errors & Blocked tab for a failed crawl (B3)', async () => {
    // SH-4: a root-fetch failure leaves no page row, so the evidence rides
    // the pages response as `root_errors` and renders as a distinct
    // NON-clickable block above the (empty) table.
    const user = userEvent.setup();
    mockRoutes({
      status: 'failed',
      analysis_status: 'failed',
      analyzed_count: 0,
      error_message: 'The site returned HTTP 404 for the start URL',
    });
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/pages`, () =>
        HttpResponse.json({
          items: [],
          next_cursor: null,
          root_errors: [
            {
              method: 'GET',
              target: 'https://acme.com/',
              outcome: 'error',
              error_code: 'http_4xx',
              status_code: 404,
              latency_ms: 120,
            },
          ],
          phase_runs: { discovery: null, analysis: null },
        }),
      ),
    );

    renderScreen();

    // The failed terminal view keeps the tabbed page browser (B3 decision).
    await screen.findByText(/The site returned HTTP 404 for the start URL/);
    await user.click(screen.getByRole('button', { name: 'Errors & Blocked' }));
    const block = await screen.findByTestId('root-errors-block');
    expect(within(block).getByText('http_4xx')).toBeInTheDocument();
    expect(within(block).getByText('HTTP 404')).toBeInTheDocument();
    expect(within(block).getByText('https://acme.com/')).toBeInTheDocument();
    // Non-clickable: no page-detail link exists for a URL never admitted.
    expect(within(block).queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows generic terminal copy for a cancelled crawl with NOTHING discovered', async () => {
    mockRoutes({ status: 'cancelled', error_message: '', visible_url_count: 0 });

    renderScreen();

    expect(
      await screen.findByText('This crawl was cancelled before it produced results.'),
    ).toBeInTheDocument();
  });

  it('keeps the discovered inventory (selection mode) for a cancelled Starter crawl', async () => {
    // Cancelling discovery must NOT dead-end the discovered URLs: the
    // inventory persists server-side, so the inventory section switches to
    // selection mode with a cancellation notice instead of a terminal card.
    mockRoutes({ status: 'cancelled', error_message: '', visible_url_count: 3 });
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/inventory`, () =>
        HttpResponse.json({
          items: [inventoryRow('66666666-6666-4666-8666-666666666666', 'https://acme.com/pricing')],
          next_cursor: null,
        }),
      ),
    );

    renderScreen();

    expect(
      await screen.findByText(/Discovery cancelled — found pages are kept/),
    ).toBeInTheDocument();
    // The persisted inventory row itself is visible and selectable.
    expect(await screen.findByLabelText('Monitor https://acme.com/pricing')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Start analysis' })).toBeInTheDocument();
    expect(
      screen.queryByText('This crawl was cancelled before it produced results.'),
    ).not.toBeInTheDocument();
  });

  it('offers Cancel beside the inventory controls while a crawl is discovering', async () => {
    let hiddenPagesRequests = 0;
    mockRoutes({
      status: 'running',
      discovery_status: 'running',
      analysis_status: 'pending',
      score_summary: null,
    });
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/pages`, () => {
        hiddenPagesRequests += 1;
        return HttpResponse.json({ items: [], next_cursor: null, root_errors: [] });
      }),
    );

    renderScreen();

    // Wait for the screen to settle past the initial loading skeleton.
    await waitFor(() => expect(screen.queryByText(/Discovering pages/)).toBeInTheDocument());
    // Active controls live with the discovered-page table, not in the global
    // page header. Re-crawl only appears for a settled dashboard/terminal run.
    const cancel = screen.getByRole('button', { name: 'Cancel' });
    expect(screen.getByTestId('inventory-section')).toContainElement(cancel);
    expect(screen.queryByRole('button', { name: /Re-crawl now/ })).not.toBeInTheDocument();
    expect(hiddenPagesRequests).toBe(0);
  });

  it('keeps the dashboard + partial scores and labels the run Cancelled (with Re-crawl)', async () => {
    // Cancellation with partial data must keep the latest dashboard, partial
    // scores, and inventory visible, explicitly labelled Cancelled, and offer
    // Re-crawl — never blank the results.
    const summary = {
      overall_score: 71,
      technical_score: 80,
      aeo_score: 62,
      selected_count: 10,
      analyzed_count: 4,
      issue_count: 3,
      scoring_version: 's1',
      by_page_kind: {
        article: { analyzed_count: 4, technical_score: 80, aeo_score: 62, overall_score: 71 },
      },
    };
    mockRoutes();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          crawl: crawl({
            status: 'cancelled',
            discovery_status: 'cancelled',
            analysis_status: 'cancelled',
            score_summary: summary,
          }),
          score_summary: summary,
          quota: { used: 4, limit: 50 },
          root_errors: [],
          phase_runs: { discovery: null, analysis: null },
        }),
      ),
    );

    renderScreen();

    // Explicit, text-labelled Cancelled notice (not color-only) with Re-crawl copy.
    expect(
      await screen.findByText(/This run was cancelled — showing the pages analyzed so far/),
    ).toBeInTheDocument();
    // The dashboard score value stays visible (partial results kept).
    expect(await screen.findByText('71 / 100')).toBeInTheDocument();
    // The v2 P1 per-page-kind breakdown renders from the same projection
    // (scoped — the inventory page-kind <select> also lists type labels).
    const breakdown = screen.getByTestId('page-kind-scores');
    expect(breakdown).toBeInTheDocument();
    expect(within(breakdown).getByText('Article')).toBeInTheDocument();
    // The header offers Re-crawl for a terminal-with-data dashboard.
    expect(screen.getByRole('button', { name: /Re-crawl now/ })).toBeInTheDocument();
    // Not the bare terminal notice.
    expect(
      screen.queryByText('This crawl was cancelled before it produced results.'),
    ).not.toBeInTheDocument();
  });
});

describe('SiteHealthScreen — canonical single-screen flow (regression)', () => {
  it('walks discover → cancel → select → start analysis → finish without ever swapping the screen', async () => {
    // The reported bug: each lifecycle step replaced the whole panel (cancel
    // showed a URL-list screen, starting analysis bounced back to that list,
    // finishing jumped to a separate dashboard). This walks the exact
    // sequence against ONE mutable server state and asserts the canonical
    // layout container is the SAME DOM node at every step — data updates in
    // place, the screen never changes.
    const user = userEvent.setup();
    let createBody: unknown = null;
    const NEW_CRAWL = '99999999-9999-4999-8999-999999999999';
    const URL_ID = '66666666-6666-4666-8666-666666666666';
    const summary = {
      overall_score: 71,
      technical_score: 80,
      aeo_score: 62,
      selected_count: 1,
      analyzed_count: 1,
      issue_count: 3,
      scoring_version: 's1',
      by_page_kind: {},
    };

    // Mutable server state the handlers read on every request.
    let serverCrawl = crawl({
      status: 'running',
      discovery_status: 'running',
      analysis_status: 'pending',
      inventory_complete: false,
      score_summary: null,
      completed_at: null,
    });
    const monitored: Array<Record<string, unknown>> = [];

    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([project])),
      http.get('/api/v1/entitlements', () => HttpResponse.json(entitlement)),
      http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          crawl: serverCrawl,
          score_summary: serverCrawl.score_summary,
          quota: { used: monitored.length, limit: 50 },
          root_errors: [],
          phase_runs: { discovery: null, analysis: null },
        }),
      ),
      http.get(`/api/v1/projects/${PROJECT}/monitored-urls`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          selection_version: 1,
          monitored_urls: monitored,
          quota: { used: monitored.length, limit: 50 },
        }),
      ),
      http.put(`/api/v1/projects/${PROJECT}/monitored-urls`, async ({ request }) => {
        const body = (await request.json()) as { site_url_ids: string[] };
        monitored.length = 0;
        for (const id of body.site_url_ids) {
          monitored.push({
            site_url_id: id,
            normalized_url: 'https://acme.com/pricing',
            display_url: 'https://acme.com/pricing',
            title: null,
            active: true,
            selection_source: 'user',
            selected_at: '2026-07-16T00:00:00Z',
            deselected_at: null,
          });
        }
        return HttpResponse.json({
          project_id: PROJECT,
          selection_version: 2,
          monitored_urls: monitored,
          quota: { used: monitored.length, limit: 50 },
        });
      }),
      http.post(`/api/v1/site-crawls/${serverCrawl.id}/cancel`, () => {
        serverCrawl = crawl({
          status: 'cancelled',
          discovery_status: 'cancelled',
          analysis_status: 'cancelled',
          score_summary: null,
          completed_at: null,
        });
        return HttpResponse.json(serverCrawl);
      }),
      http.post('/api/v1/site-crawls', async ({ request }) => {
        // The shape a real recrawl has for most of its life: discovery re-runs
        // while the seeded monitored-set analysis is still 'pending' (the
        // worker's reconcile flips it later). Resolving THIS shape back to the
        // URL list is the exact reported bug.
        serverCrawl = crawl({
          id: NEW_CRAWL,
          status: 'running',
          discovery_status: 'running',
          analysis_status: 'pending',
          inventory_complete: false,
          score_summary: null,
          completed_at: null,
        });
        createBody = await request.json();
        return HttpResponse.json(serverCrawl);
      }),
      http.get('/api/v1/site-crawls/:id/pages', () =>
        HttpResponse.json({ items: [], next_cursor: null, root_errors: [] }),
      ),
      http.get('/api/v1/site-crawls/:id/inventory', () =>
        HttpResponse.json({
          items: [inventoryRow(URL_ID, 'https://acme.com/pricing')],
          next_cursor: null,
        }),
      ),
      http.get('/api/v1/site-crawls/:id/events', () => HttpResponse.text('', { status: 200 })),
    );

    const { queryClient } = renderScreen();

    // Step 1 — discovering: canonical layout with live discovery narration.
    await waitFor(() => expect(screen.queryByTestId('site-health-canonical')).toBeInTheDocument());
    const canonical = screen.getByTestId('site-health-canonical');
    expect(screen.getByText(/pages discovered so far/)).toBeInTheDocument();

    // Step 2 — cancel from the header. The SAME screen shifts to selection
    // mode (inventory persists), no navigation, no terminal dead-end.
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(
      await screen.findByText(/Discovery cancelled — found pages are kept/),
    ).toBeInTheDocument();
    expect(screen.getByTestId('site-health-canonical')).toBe(canonical);

    // Step 3 — stage + save a monitored page, then start the analysis.
    await user.click(await screen.findByLabelText('Monitor https://acme.com/pricing'));
    await user.click(screen.getByRole('button', { name: /Save selection/ }));
    const startAnalysis = screen.getByRole('button', { name: 'Start analysis' });
    await waitFor(() => expect(startAnalysis).toBeEnabled());
    await user.click(startAnalysis);

    // The direct action must send the typed default payload, not React's
    // click event (which would fail before the request reached this handler).
    await waitFor(() => expect(createBody).toEqual({ project_id: PROJECT }));

    // The screen moves FORWARD to the analysis view in place — it must never
    // bounce back to the selection list (the reported regression), even though
    // the fresh crawl reports discovery running + analysis still pending.
    expect(
      await screen.findByText(
        'Auditing selected pages while discovery re-scans the site in the background',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Monitor https://acme.com/pricing')).not.toBeInTheDocument();
    expect(screen.getByTestId('site-health-canonical')).toBe(canonical);

    // Step 4 — the run finishes server-side; the next poll/SSE invalidation
    // lands the scores IN PLACE on the same screen (no dashboard jump).
    serverCrawl = crawl({
      id: NEW_CRAWL,
      status: 'completed',
      discovery_status: 'completed',
      analysis_status: 'completed',
      score_summary: summary,
    });
    await queryClient.invalidateQueries();

    expect(await screen.findByText('71 / 100')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Re-crawl now/ })).toBeInTheDocument();
    expect(screen.getByTestId('site-health-canonical')).toBe(canonical);
    // The score section that showed placeholders during analysis is the same
    // mounted section now showing real data.
    expect(screen.getByTestId('score-section')).toBeInTheDocument();
  });
});
