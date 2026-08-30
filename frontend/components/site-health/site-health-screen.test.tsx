import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { ProjectProvider } from '@/lib/project/project-context';
import { SiteHealthScreen } from './site-health-screen';
import type { SiteHealthDashboard } from '@/lib/api/types';

let search = '';
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => '/site',
  useSearchParams: () => new URLSearchParams(search),
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
    partial_reason: '',
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
      failure_breakdown: { robots_denied: 0, http_4xx: 0, http_5xx: 0, timeout: 0 },
      activity: { state: 'terminal', reason: 'terminal', queue_depth: 0, next_available_at: null },
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
    technical_integrity_score: null,
    technical_integrity_coverage: null,
    technical_integrity_state: 'not_measured',
    aeo_readiness_score: null,
    aeo_measurement_coverage: null,
    aeo_measurement_state: 'not_measured',
    main_content_indexable: null,
    last_audited: null,
    page_kind: null,
  };
}

function overview(crawlId = CRAWL) {
  return {
    project_id: PROJECT,
    crawl_id: crawlId,
    snapshot_id: '77777777-7777-4777-8777-777777777777',
    search_eligibility: 'eligible',
    eligibility_totals: { eligible: 1, blocked: 0, unknown: 0, excluded: 0 },
    eligibility_reasons: [],
    technical_integrity_score: 80,
    technical_integrity_coverage: 1,
    technical_integrity_state: 'measured',
    aeo_readiness_score: 62,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    crawl_coverage: {
      state: 'complete',
      evidence: { observed: 1, expected: 1 },
      denominator_kind: 'selected_intended_public_urls',
    },
    audited_page_count: 1,
    selected_page_count: 1,
    status_counts: { audited: 1, blocked: 0, error: 0, pending: 0 },
    aeo_dimensions: [],
    top_issues: [],
    web_fundamentals: { state: 'not_measured', field_data_available: false },
    trend: { state: 'not_measured', reason: 'no_comparable_snapshot' },
    change_summary: { state: 'not_measured', reason: 'no_comparable_snapshot' },
    limitations: [],
  };
}

/**
 * `phase` is a SERVER field now (backend/app/domain/site_health/phase.py), so
 * each test states the phase it is exercising instead of arranging a crawl
 * shape and hoping the client re-derives the one it meant. Phase RESOLUTION is
 * covered by tests/unit/test_site_health_phase.py; these are rendering tests.
 */
function mockRoutes(
  crawlOverrides: Record<string, unknown> = {},
  phase: SiteHealthDashboard['phase'] = 'dashboard',
) {
  mswServer.use(
    http.get('/api/v1/projects', () => HttpResponse.json([project])),
    http.post('/api/v1/projects/:id/logos/refresh', () => HttpResponse.json(project)),
    http.get('/api/v1/entitlements', () => HttpResponse.json(entitlement)),
    http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
      HttpResponse.json({
        project_id: PROJECT,
        crawl: crawl(crawlOverrides),
        score_summary: null,
        phase,
        snapshot_id: null,
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
    http.get(`/api/v1/projects/${PROJECT}/site-health/overview`, () =>
      HttpResponse.json(overview()),
    ),
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
  search = '';
  mswServer.use(http.post('/api/v1/projects/:id/logos/refresh', () => HttpResponse.json(project)));
});
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('SiteHealthScreen — Website tab deep links', () => {
  it('preserves Architecture from the URL on initial load', async () => {
    search = 'tab=architecture';
    mockRoutes();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/site-health/architecture`, () =>
        HttpResponse.json({
          state: 'unavailable',
          crawl_id: CRAWL,
          coverage_state: 'unknown',
          page_count: 0,
          page_kinds: [],
          nodes: [],
          internal_linking: {
            internal_link_count: 0,
            pages_with_incoming_count: 0,
            pages_with_incoming_percentage: null,
            orphan_page_count: null,
          },
          structure_depth: {
            measured_page_count: 0,
            unmeasured_page_count: 0,
            buckets: [],
          },
          architecture_formula_version: 'sh-architecture-1',
          limitations: ['Architecture is not available yet.'],
        }),
      ),
    );

    renderScreen();

    expect(await screen.findByRole('tab', { name: 'Architecture' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect(await screen.findByText('Architecture is not available yet.')).toBeVisible();
  });

  it('defaults to Overview after the crawl projection resolves', async () => {
    search = 'tab=unknown';
    mockRoutes();

    renderScreen();

    expect(await screen.findByRole('tab', { name: 'Overview' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});

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

describe('SiteHealthScreen — before the first crawl', () => {
  it('shows one Run new crawl placeholder instead of empty metrics', async () => {
    const user = userEvent.setup();
    let createBody: unknown = null;
    let monitoredRequests = 0;
    mockRoutes();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          crawl: null,
          score_summary: null,
          phase: 'empty',
          snapshot_id: null,
          quota: { used: 0, limit: 50 },
          root_errors: [],
          phase_runs: { discovery: null, analysis: null },
        }),
      ),
      http.get(`/api/v1/projects/${PROJECT}/monitored-urls`, () => {
        monitoredRequests += 1;
        return HttpResponse.json({
          project_id: PROJECT,
          selection_version: 1,
          monitored_urls: [],
          quota: { used: 0, limit: 50 },
        });
      }),
      http.post('/api/v1/site-crawls', async ({ request }) => {
        createBody = await request.json();
        return HttpResponse.json(
          crawl({
            status: 'queued',
            discovery_status: 'pending',
            analysis_status: 'pending',
            completed_at: null,
          }),
        );
      }),
    );

    renderScreen();

    expect(await screen.findByText('Run your first site crawl')).toBeVisible();
    expect(screen.queryByTestId('score-section')).not.toBeInTheDocument();
    const runButtons = screen.getAllByRole('button', { name: 'Run new crawl' });
    expect(runButtons).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Export' })).not.toBeInTheDocument();

    await waitFor(() => expect(monitoredRequests).toBe(1));
    await user.click(runButtons[0]);
    await waitFor(() => expect(createBody).toEqual({ project_id: PROJECT }));
    await waitFor(() => expect(monitoredRequests).toBeGreaterThanOrEqual(2));
  });
});

describe('SiteHealthScreen — terminal states on the canonical screen', () => {
  it('renders an explicit terminal notice (not the active-progress UI) for a failed crawl', async () => {
    mockRoutes({ status: 'failed', error_message: 'Robots.txt denied crawling.' }, 'terminal');

    renderScreen();

    expect(
      await screen.findByText(/Robots\.txt denied crawling\. Re-crawl to try again\./),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run new crawl' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Stop crawl' })).not.toBeInTheDocument();
    const scores = screen.getByTestId('score-section');
    expect(scores).toBeInTheDocument();
    expect(within(scores).getAllByText('Not measured').length).toBeGreaterThanOrEqual(3);
  });

  it('routes a failed crawl with a PRESENT-but-null-score summary to terminal (the SH-2 shape)', async () => {
    mockRoutes(
      {
        status: 'failed',
        analysis_status: 'failed',
        analyzed_count: 0,
        score_summary: {
          technical_integrity_score: null,
          technical_integrity_coverage: 0,
          technical_integrity_state: 'not_measured',
          aeo_readiness_score: null,
          aeo_measurement_coverage: 0,
          aeo_measurement_state: 'not_measured',
          search_eligibility: 'unknown',
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
      },
      'terminal',
    );

    renderScreen();

    expect(
      await screen.findByText(
        /The site returned HTTP 500 after 3 attempts\. The site is having server trouble/,
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
    expect(screen.queryByText('Across 0 of 0 pages')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run new crawl' })).toBeInTheDocument();
  });

  it('renders the root-failure block on the Errors & Blocked tab for a failed crawl (B3)', async () => {
    const user = userEvent.setup();
    mockRoutes(
      {
        status: 'failed',
        analysis_status: 'failed',
        analyzed_count: 0,
        error_message: 'The site returned HTTP 404 for the start URL',
      },
      'terminal',
    );
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

    await screen.findByText(/The site returned HTTP 404 for the start URL/);
    await user.click(screen.getByRole('tab', { name: 'Errors & Blocked' }));
    const block = await screen.findByTestId('root-errors-block');
    expect(within(block).getByText('http_4xx')).toBeInTheDocument();
    expect(within(block).getByText('HTTP 404')).toBeInTheDocument();
    expect(within(block).getByText('https://acme.com/')).toBeInTheDocument();
    expect(within(block).queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows generic terminal copy for a cancelled crawl with NOTHING discovered', async () => {
    mockRoutes({ status: 'cancelled', error_message: '', visible_url_count: 0 }, 'terminal');

    renderScreen();

    expect(
      await screen.findByText('This crawl was cancelled before it produced results.'),
    ).toBeInTheDocument();
  });

  it('does not resurrect the removed selection step after cancellation', async () => {
    mockRoutes({ status: 'cancelled', error_message: '', visible_url_count: 3 }, 'terminal');

    renderScreen();

    expect(
      await screen.findByText('This crawl was cancelled before it produced results.'),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Discovery finished/)).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Save selection/ })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Monitor https:\/\/acme\.com/)).not.toBeInTheDocument();
  });

  it('offers one Stop crawl action beside the Website tabs while discovering', async () => {
    let hiddenPagesRequests = 0;
    mockRoutes(
      {
        status: 'running',
        discovery_status: 'running',
        analysis_status: 'pending',
        score_summary: null,
      },
      'discovering',
    );
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/pages`, () => {
        hiddenPagesRequests += 1;
        return HttpResponse.json({ items: [], next_cursor: null, root_errors: [] });
      }),
    );

    renderScreen();

    await waitFor(() => expect(screen.queryByText(/Discovering pages/)).toBeInTheDocument());
    const stop = screen.getByRole('button', { name: 'Stop crawl' });
    const analysisTabs = screen.getByRole('tablist', { name: 'Website analysis' });
    expect(screen.getByTestId('inventory-section')).not.toContainElement(stop);
    expect(analysisTabs.parentElement).toContainElement(stop);
    expect(
      analysisTabs.compareDocumentPosition(stop) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Run new crawl' })).not.toBeInTheDocument();
    expect(hiddenPagesRequests).toBe(0);
  });

  it('reveals completed pages progressively in the first active audit view', async () => {
    const user = userEvent.setup();
    const requestedStatuses: Array<string | null> = [];
    mockRoutes(
      {
        status: 'running',
        discovery_status: 'running',
        analysis_status: 'running',
        inventory_complete: false,
        partial_reason: '',
        score_summary: null,
      },
      'analyzing',
    );
    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/pages`, ({ request }) => {
        requestedStatuses.push(new URL(request.url).searchParams.get('status'));
        return HttpResponse.json({ items: [], next_cursor: null, root_errors: [] });
      }),
    );

    renderScreen();

    expect(await screen.findByRole('tab', { name: 'Audited so far' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await waitFor(() => expect(requestedStatuses).toContain('completed'));

    await user.click(screen.getByRole('tab', { name: 'All Discovered' }));
    await waitFor(() => expect(requestedStatuses).toContain(null));
    expect(screen.getByRole('tab', { name: 'Monitored' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  it('defaults partial results to Overview and keeps the cancelled Pages view available', async () => {
    const user = userEvent.setup();
    const summary = {
      technical_integrity_score: 80,
      technical_integrity_coverage: 1,
      technical_integrity_state: 'measured',
      aeo_readiness_score: 62,
      aeo_measurement_coverage: 0.8,
      aeo_measurement_state: 'measured',
      search_eligibility: 'eligible',
      selected_count: 10,
      analyzed_count: 4,
      issue_count: 3,
      scoring_version: 's1',
      by_page_kind: {
        article: {
          analyzed_count: 4,
          technical_integrity_score: 80,
          technical_integrity_coverage: 1,
          technical_integrity_state: 'measured',
          aeo_readiness_score: 62,
          aeo_measurement_coverage: 0.8,
          aeo_measurement_state: 'measured',
        },
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
          phase: 'dashboard',
          snapshot_id: null,
          quota: { used: 4, limit: 50 },
          root_errors: [],
          phase_runs: { discovery: null, analysis: null },
        }),
      ),
    );

    renderScreen();

    expect(await screen.findByRole('tab', { name: 'Overview' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
    expect((await screen.findAllByText('80')).length).toBeGreaterThan(0);
    await user.click(screen.getByRole('tab', { name: 'Pages' }));
    expect(
      await screen.findByText(/This run was cancelled — showing the pages analyzed so far/),
    ).toBeInTheDocument();
    const breakdown = screen.getByTestId('page-kind-scores');
    expect(breakdown).toBeInTheDocument();
    expect(within(breakdown).getByText('Article')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Run new crawl' })).toBeInTheDocument();
    expect(
      screen.queryByText('This crawl was cancelled before it produced results.'),
    ).not.toBeInTheDocument();
  });
});

describe('SiteHealthScreen — canonical single-screen flow (regression)', () => {
  it('walks discover → stop → new crawl → finish without resurrecting selection', async () => {
    const user = userEvent.setup();
    let createBody: unknown = null;
    const NEW_CRAWL = '99999999-9999-4999-8999-999999999999';
    const URL_ID = '66666666-6666-4666-8666-666666666666';
    const summary = {
      technical_integrity_score: 80,
      technical_integrity_coverage: 1,
      technical_integrity_state: 'measured',
      aeo_readiness_score: 62,
      aeo_measurement_coverage: 0.8,
      aeo_measurement_state: 'measured',
      search_eligibility: 'eligible',
      selected_count: 1,
      analyzed_count: 1,
      issue_count: 3,
      scoring_version: 's1',
      by_page_kind: {},
    };

    let serverCrawl = crawl({
      status: 'running',
      discovery_status: 'running',
      analysis_status: 'pending',
      inventory_complete: false,
      partial_reason: '',
      score_summary: null,
      completed_at: null,
    });
    let serverPhase: SiteHealthDashboard['phase'] = 'discovering';
    const monitored: Array<Record<string, unknown>> = [
      {
        site_url_id: URL_ID,
        normalized_url: 'https://acme.com/pricing',
        display_url: 'https://acme.com/pricing',
        title: null,
        active: true,
        selection_source: 'bootstrap',
        selected_at: '2026-07-16T00:00:00Z',
        deselected_at: null,
      },
    ];

    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([project])),
      http.get('/api/v1/entitlements', () => HttpResponse.json(entitlement)),
      http.get(`/api/v1/projects/${PROJECT}/site-health`, () =>
        HttpResponse.json({
          project_id: PROJECT,
          crawl: serverCrawl,
          score_summary: serverCrawl.score_summary,
          phase: serverPhase,
          snapshot_id: null,
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
      http.post(`/api/v1/site-crawls/${serverCrawl.id}/cancel`, () => {
        serverCrawl = crawl({
          status: 'cancelled',
          discovery_status: 'cancelled',
          analysis_status: 'cancelled',
          score_summary: null,
          completed_at: null,
        });
        serverPhase = 'terminal';
        return HttpResponse.json(serverCrawl);
      }),
      http.post('/api/v1/site-crawls', async ({ request }) => {
        serverCrawl = crawl({
          id: NEW_CRAWL,
          status: 'running',
          discovery_status: 'running',
          analysis_status: 'pending',
          inventory_complete: false,
          partial_reason: '',
          score_summary: null,
          completed_at: null,
        });
        serverPhase = 'analyzing';
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
      http.get(`/api/v1/projects/${PROJECT}/site-health/overview`, () =>
        HttpResponse.json(overview(serverCrawl.id)),
      ),
    );

    const { queryClient } = renderScreen();

    await waitFor(() => expect(screen.queryByTestId('site-health-canonical')).toBeInTheDocument());
    const canonical = screen.getByTestId('site-health-canonical');
    expect(screen.getByText(/pages discovered so far/)).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Stop crawl' }));
    expect(
      await screen.findByText('This crawl was cancelled before it produced results.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Save selection/ })).not.toBeInTheDocument();
    expect(screen.getByTestId('site-health-canonical')).toBe(canonical);

    const recrawl = screen.getByRole('button', { name: 'Run new crawl' });
    await waitFor(() => expect(recrawl).toBeEnabled());
    await user.click(recrawl);

    await waitFor(() => expect(createBody).toMatchObject({ project_id: PROJECT }));

    expect(
      await screen.findByText(
        'Auditing monitored pages while discovery re-scans the site in the background',
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Monitor https://acme.com/pricing')).not.toBeInTheDocument();
    expect(screen.getByTestId('site-health-canonical')).toBe(canonical);

    serverCrawl = crawl({
      id: NEW_CRAWL,
      status: 'completed',
      discovery_status: 'completed',
      analysis_status: 'completed',
      score_summary: summary,
    });
    serverPhase = 'dashboard';
    await queryClient.invalidateQueries();

    expect((await screen.findAllByText('80')).length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Run new crawl' })).toBeInTheDocument();
    expect(screen.getByTestId('site-health-overview')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
  });
});
