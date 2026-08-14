import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { ProjectProvider, useProjectContext } from '@/lib/project/project-context';
import { opportunitySummaryPollingInterval } from './opportunity-summary-polling';
import { OpportunitiesScreen } from './opportunities-screen';

const WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT = '11111111-1111-4111-8111-111111111111';
const OPP_A = '22222222-2222-4222-8222-222222222222';
const OPP_B = '33333333-3333-4333-8333-333333333333';
const RUN = '44444444-4444-4444-8444-444444444444';

it('stops summary polling after an uncached request error', () => {
  expect(opportunitySummaryPollingInterval({ status: 'error' })).toBe(false);
});

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

function opportunity(overrides: Record<string, unknown> = {}) {
  return {
    id: OPP_A,
    project_id: PROJECT,
    rule_id: 'brand_absent_high_value_prompt',
    opportunity_type: 'visibility',
    severity: 'high',
    priority_score: 120,
    title: 'Brand absent from high-value prompt',
    target_key: `prompt:${OPP_A}`,
    target_prompt_id: OPP_A,
    target_url: null,
    target_theme: 'crm',
    target_label: 'best crm for small teams',
    status: 'open',
    system_rank: 1,
    display_rank: 1,
    order_source: 'system',
    priority_factors: {
      severity: 'high',
      system_score: 120,
      formula_version: 'opp-formula-1',
    },
    evidence_summary: { count: 1, kinds: ['analysis'] },
    created_at: '2026-07-24T00:00:00Z',
    updated_at: '2026-07-24T00:00:00Z',
    ...overrides,
  };
}

const siteRow = opportunity({
  id: OPP_B,
  rule_id: 'thin_content',
  opportunity_type: 'site',
  severity: 'low',
  priority_score: 10,
  title: 'Thin content on an owned page',
  target_key: 'url:https://acme.com/blog',
  target_prompt_id: null,
  target_url: 'https://acme.com/blog',
  target_theme: null,
  target_label: 'https://acme.com/blog',
});

const summary = {
  activation_state: 'ready',
  computed: true,
  run_id: RUN,
  audit_id: RUN,
  site_crawl_id: RUN,
  demand_snapshot_id: null,
  demand_source_revision: null,
  counts_by_type: { site: 1, topic: 0, traffic: 0, visibility: 1 },
  counts_by_severity: { critical: 0, high: 1, info: 0, low: 1, medium: 0 },
  counts_by_status: { dismissed: 0, in_progress: 0, open: 2, resolved: 0 },
  total_count: 2,
  median_priority: 65,
  analyzer_version: 'opp-analyzer-1',
  rule_version: 'opp-rules-1',
  formula_version: 'opp-formula-1',
  computed_at: '2026-07-24T00:00:00Z',
  evidence_updated_at: '2026-07-23T00:00:00Z',
  stale: false,
};

const recomputeResponse = {
  id: RUN,
  run_id: RUN,
  audit_id: RUN,
  site_crawl_id: RUN,
  demand_snapshot_id: null,
  demand_source_revision: null,
  counts_by_type: summary.counts_by_type,
  counts_by_severity: summary.counts_by_severity,
  counts_by_status: summary.counts_by_status,
  total_count: 2,
  median_priority: 65,
  analyzer_version: 'opp-analyzer-1',
  rule_version: 'opp-rules-1',
  formula_version: 'opp-formula-1',
  created_at: '2026-07-24T00:00:00Z',
};

const detail = {
  ...opportunity(),
  remediation: 'Publish a comparison page.',
  evidence: {
    prompt_text: 'best crm for small teams',
    prompt_theme: 'crm',
    prompt_intent: 'purchase',
    engines: ['gemini'],
    repetitions: 1,
    owned_citation_count: 0,
    competitor_names: ['Globex'],
    audit_id: RUN,
  },
  source_analysis_ids: [RUN],
  source_issue_ids: [],
  source_metric_ids: [RUN],
  source_traffic_ids: [],
  analyzer_version: 'opp-analyzer-1',
  rule_version: 'opp-rules-1',
  formula_version: 'opp-formula-1',
  superseded_by_id: null,
  superseded_at: null,
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function renderScreen() {
  return renderWithProviders(
    <ProjectProvider>
      <OpportunitiesScreen />
    </ProjectProvider>,
  );
}

function mockBase() {
  const PROJECT_2 = '55555555-5555-4555-8555-555555555555';
  const project2 = { ...project, id: PROJECT_2, name: 'Beta', brand_name: 'Beta' };
  mswServer.use(
    http.get('/api/v1/projects', () => HttpResponse.json([project, project2])),
    http.post(`/api/v1/projects/${PROJECT}/logos/refresh`, () => HttpResponse.json({})),
    http.post(`/api/v1/projects/${PROJECT_2}/logos/refresh`, () => HttpResponse.json({})),
  );
}

describe('OpportunitiesScreen', () => {
  it('shows automatic preparation without a normal refresh action', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json({
          ...summary,
          activation_state: 'queued',
          computed: false,
          run_id: null,
          audit_id: null,
          site_crawl_id: null,
          demand_snapshot_id: null,
          demand_source_revision: null,
          counts_by_type: {},
          counts_by_severity: {},
          counts_by_status: {},
          total_count: 0,
          median_priority: null,
          computed_at: null,
        }),
      ),
    );

    renderScreen();

    expect(await screen.findByText('Preparing recommendations')).toBeInTheDocument();
    expect(screen.getByText(/automatically/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /recommendations again/i }),
    ).not.toBeInTheDocument();
  });

  it('renders the compact summary strip + prioritized recommendations when computed', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [opportunity(), siteRow], next_cursor: null }),
      ),
    );

    renderScreen();

    // Summary strip: compact recommendation queue.
    expect(await screen.findByText('Recommendation queue')).toBeInTheDocument();
    // The counts are in a mixed text+spans paragraph. Use the full
    // textContent via a custom matcher on the parent <p>.
    const countParagraph = screen.getByText((_content, element) => {
      const text = element?.textContent ?? '';
      return (
        element?.tagName === 'P' &&
        text.includes('2 open recommendations') &&
        text.includes('1 high impact') &&
        text.includes('0 in progress')
      );
    });
    expect(countParagraph).toBeInTheDocument();

    // Export has been collapsed into a dropdown trigger.
    expect(screen.getByRole('button', { name: /Export/ })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /recommendations again/i }),
    ).not.toBeInTheDocument();

    // Catalog rows: title, backend-owned target label, impact/area badges.
    await screen.findByText('Brand absent from high-value prompt');
    const catalog = screen.getByRole('table');
    expect(within(catalog).getByText('Brand absent from high-value prompt')).toBeInTheDocument();
    expect(within(catalog).getByText('Thin content on an owned page')).toBeInTheDocument();
    expect(within(catalog).getByText('https://acme.com/blog')).toBeInTheDocument();
    expect(within(catalog).getByText('best crm for small teams')).toBeInTheDocument();
    expect(within(catalog).getByText('HIGH')).toBeInTheDocument();
    expect(within(catalog).getByText('Visibility')).toBeInTheDocument();
    // No priority score exposed in the table.
    expect(screen.queryByText('120.0')).not.toBeInTheDocument();
  });

  it('renders the featured card with the API target label (C1)', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [opportunity(), siteRow], next_cursor: null }),
      ),
      http.get(`/api/v1/opportunities/${OPP_A}`, () => HttpResponse.json(detail)),
    );

    renderScreen();

    // The detail-backed featured card takes its "Applies to" line from the
    // API target_label (no client-side derivation). The card renders after a
    // three-fetch chain (projects -> list -> detail), so allow a longer wait.
    expect(await screen.findByText('Next best action', {}, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByText('Applies to best crm for small teams')).toBeInTheDocument();
  });

  it('shows the stale badge only when newer evidence exists (C4c)', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json({ ...summary, stale: true, evidence_updated_at: '2026-07-25T00:00:00Z' }),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [siteRow], next_cursor: null }),
      ),
    );

    renderScreen();

    expect(await screen.findByText(/Last computed/)).toBeInTheDocument();
    expect(screen.getByText('Newer evidence available')).toBeInTheDocument();
  });

  it('hides the stale badge when the snapshot is current (C4c)', async () => {
    mockBase();
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [siteRow], next_cursor: null }),
      ),
    );

    renderScreen();

    expect(await screen.findByText(/Last computed/)).toBeInTheDocument();
    expect(screen.queryByText('Newer evidence available')).not.toBeInTheDocument();
  });

  it('sends filter dropdown selections as server query params (never a client filter)', async () => {
    mockBase();
    const seen: URLSearchParams[] = [];
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, ({ request }) => {
        seen.push(new URL(request.url).searchParams);
        return HttpResponse.json({ items: [siteRow], next_cursor: null });
      }),
    );

    const user = userEvent.setup();
    renderScreen();
    await screen.findByText('Thin content on an owned page');

    // Open the Area dropdown and select "Site".
    await user.click(screen.getByRole('button', { name: /Area:/ }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'Site' }));
    await waitFor(() => expect(seen.some((params) => params.get('type') === 'site')).toBe(true));

    // Open the Status dropdown and select "Dismissed".
    await user.click(screen.getByRole('button', { name: /Status:/ }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'Dismissed' }));
    await waitFor(() =>
      expect(seen.some((params) => params.get('status') === 'dismissed')).toBe(true),
    );

    // Open the Impact dropdown and select "Low".
    await user.click(screen.getByRole('button', { name: /Impact:/ }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'Low' }));
    await waitFor(() => expect(seen.some((params) => params.get('severity') === 'low')).toBe(true));
  });

  it('offers retry only after recommendation preparation is delayed', async () => {
    mockBase();
    let summaryCalls = 0;
    let recomputeCalls = 0;
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () => {
        summaryCalls += 1;
        return HttpResponse.json({ ...summary, activation_state: 'delayed' });
      }),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [opportunity()], next_cursor: null }),
      ),
      http.post(`/api/v1/projects/${PROJECT}/opportunities/recompute`, () => {
        recomputeCalls += 1;
        return HttpResponse.json(recomputeResponse);
      }),
    );

    const user = userEvent.setup();
    renderScreen();
    await screen.findByText('Brand absent from high-value prompt');
    const before = summaryCalls;

    await user.click(screen.getByRole('button', { name: 'Try recommendations again' }));
    await waitFor(() => expect(recomputeCalls).toBe(1));
    await waitFor(() => expect(summaryCalls).toBeGreaterThan(before));
  });

  it('row status dropdown patches the status and refetches the list', async () => {
    mockBase();
    const patches: unknown[] = [];
    let listCalls = 0;
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () => {
        listCalls += 1;
        return HttpResponse.json({ items: [opportunity()], next_cursor: null });
      }),
      http.patch(`/api/v1/opportunities/${OPP_A}`, async ({ request }) => {
        patches.push(await request.json());
        return HttpResponse.json(opportunity({ status: 'dismissed' }));
      }),
    );

    const user = userEvent.setup();
    renderScreen();
    await screen.findByText('Brand absent from high-value prompt');
    const before = listCalls;

    await user.click(
      screen.getByRole('button', {
        name: 'Change status for Brand absent from high-value prompt',
      }),
    );
    await user.click(await screen.findByRole('menuitem', { name: 'Dismissed' }));

    await waitFor(() => expect(patches).toEqual([{ status: 'dismissed' }]));
    await waitFor(() => expect(listCalls).toBeGreaterThan(before));
  });

  it('Review opens the recommendation detail drawer with evidence + footer actions', async () => {
    mockBase();
    const patches: unknown[] = [];
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [opportunity()], next_cursor: null }),
      ),
      http.get(`/api/v1/opportunities/${OPP_A}`, () => HttpResponse.json(detail)),
      http.patch(`/api/v1/opportunities/${OPP_A}`, async ({ request }) => {
        patches.push(await request.json());
        return HttpResponse.json(opportunity({ status: 'in_progress' }));
      }),
    );

    const user = userEvent.setup();
    renderScreen();
    const rowTitle = await screen.findByText('Brand absent from high-value prompt');
    const row = rowTitle.closest('tr');
    expect(row).not.toBeNull();
    // Click the Review button on the row (not the status control).
    await user.click(within(row!).getByRole('button', { name: /Review/ }));

    // Drawer: prompt quote, competitor chip, remediation (what to do).
    expect(await screen.findByText('Opportunity detail')).toBeInTheDocument();
    const drawer = screen.getByRole('dialog', { name: 'Opportunity detail' });
    expect(within(drawer).getByText('“best crm for small teams”')).toBeInTheDocument();
    expect(within(drawer).getByText('Globex')).toBeInTheDocument();
    expect(within(drawer).getByText('Publish a comparison page.')).toBeInTheDocument();
    expect(within(drawer).queryByText('Tailored guidance')).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('button', { name: /Generate|Regenerate/ }),
    ).not.toBeInTheDocument();

    const runLink = within(drawer).getByRole('link', { name: 'View result' });
    expect(runLink).toHaveAttribute('href', `/runs/${RUN}`);
    const promptLink = within(drawer).getByRole('link', { name: 'Open prompt library' });
    expect(promptLink).toHaveAttribute('href', '/prompts');
    expect(
      within(drawer).queryByText(/metric snapshot|formula|analyzer|rule version/i),
    ).not.toBeInTheDocument();
    expect(
      within(drawer).queryByText(/opp-analyzer|opp-rules|opp-formula/),
    ).not.toBeInTheDocument();

    // Footer workflow: Mark in progress patches the row.
    await user.click(screen.getByRole('button', { name: 'Mark in progress' }));
    await waitFor(() => expect(patches).toEqual([{ status: 'in_progress' }]));

    // Close returns to the catalog.
    await user.click(screen.getByRole('button', { name: 'Close drawer' }));
    await waitFor(() => expect(screen.queryByText('Opportunity detail')).not.toBeInTheDocument());
  });

  it('renders the Site Health page deep-link for site-sourced rows (C2)', async () => {
    mockBase();
    const SITE_URL = '77777777-7777-4777-8777-777777777777';
    const siteDetail = {
      ...siteRow,
      remediation: 'Add substantive body content.',
      evidence: {
        issue_rule_id: 'technical.thin_content',
        crawl_id: RUN,
        site_url_id: SITE_URL,
        url: 'https://acme.com/blog',
      },
      source_analysis_ids: [],
      source_issue_ids: [RUN],
      source_metric_ids: [],
      source_traffic_ids: [],
      analyzer_version: 'opp-analyzer-1',
      rule_version: 'opp-rules-2',
      formula_version: 'opp-formula-1',
      superseded_by_id: null,
      superseded_at: null,
    };
    mswServer.use(
      http.get(`/api/v1/projects/${PROJECT}/opportunities/summary`, () =>
        HttpResponse.json(summary),
      ),
      http.get(`/api/v1/projects/${PROJECT}/opportunities`, () =>
        HttpResponse.json({ items: [siteRow], next_cursor: null }),
      ),
      http.get(`/api/v1/opportunities/${OPP_B}`, () => HttpResponse.json(siteDetail)),
    );

    const user = userEvent.setup();
    renderScreen();
    const rowTitle = await screen.findByText('Thin content on an owned page');
    const row = rowTitle.closest('tr');
    await user.click(within(row!).getByRole('button', { name: /Review/ }));

    const drawer = await screen.findByRole('dialog', { name: 'Opportunity detail' });
    const pageLink = within(drawer).getByRole('link', { name: 'View page' });
    expect(pageLink).toHaveAttribute('href', `/site-health/crawls/${RUN}/pages/${SITE_URL}`);
    // No visibility-run or prompt link for a site-sourced row.
    expect(within(drawer).queryByRole('link', { name: 'View result' })).not.toBeInTheDocument();
    expect(
      within(drawer).queryByRole('link', { name: 'Open prompt library' }),
    ).not.toBeInTheDocument();
    expect(
      within(drawer).queryByText(/site issue|snapshot|formula|analyzer/i),
    ).not.toBeInTheDocument();
  });

  it('clears prior project data and selections during project switch', async () => {
    const PROJECT_2 = '55555555-5555-4555-8555-555555555555';
    const OPP_BETA = '66666666-6666-4666-8666-666666666666';
    const project2 = { ...project, id: PROJECT_2, name: 'Beta', brand_name: 'Beta' };

    function SwitcherTest() {
      const { setActiveProjectId } = useProjectContext();
      return (
        <div>
          <button onClick={() => setActiveProjectId(PROJECT_2)}>Switch Project</button>
          <OpportunitiesScreen />
        </div>
      );
    }

    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([project, project2])),
      http.post(`/api/v1/projects/${PROJECT}/logos/refresh`, () => HttpResponse.json({})),
      http.post(`/api/v1/projects/${PROJECT_2}/logos/refresh`, () => HttpResponse.json({})),
      http.get(`/api/v1/opportunities/${OPP_BETA}`, () =>
        HttpResponse.json({
          ...detail,
          id: OPP_BETA,
          project_id: PROJECT_2,
          title: 'Beta recommendation',
        }),
      ),
      http.get('/api/v1/projects/:projectId/opportunities/summary', ({ params }) => {
        if (params.projectId === PROJECT_2) {
          return HttpResponse.json({ ...summary, counts_by_status: { open: 10 } });
        }
        return HttpResponse.json(summary);
      }),
      http.get('/api/v1/projects/:projectId/opportunities', ({ params }) => {
        if (params.projectId === PROJECT_2) {
          return HttpResponse.json({
            items: [
              opportunity({ id: OPP_BETA, project_id: PROJECT_2, title: 'Beta recommendation' }),
            ],
            next_cursor: null,
          });
        }
        return HttpResponse.json({ items: [opportunity()], next_cursor: null });
      }),
    );

    const user = userEvent.setup();
    renderWithProviders(
      <ProjectProvider>
        <SwitcherTest />
      </ProjectProvider>,
    );

    // Initial render shows Project 1 recommendation
    expect(await screen.findByText('Brand absent from high-value prompt')).toBeInTheDocument();

    // Click to switch active project to Project 2
    await user.click(screen.getByRole('button', { name: 'Switch Project' }));

    // Verify Project 2 recommendation loads and Project 1 recommendation is no longer present
    expect(
      await screen.findByText('Beta recommendation', {}, { timeout: 3000 }),
    ).toBeInTheDocument();
    expect(screen.queryByText('Brand absent from high-value prompt')).not.toBeInTheDocument();
  });
});
