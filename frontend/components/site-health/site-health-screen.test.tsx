import { http, HttpResponse } from 'msw';
import { describe, expect, it } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { COMPLETE_CLASSIFICATION_PROJECTION } from '@/test/site-health-fixtures';
import type { SiteHealthDashboard } from '@/lib/api/types';
import {
  CRAWL,
  PROJECT,
  crawl,
  entitlement,
  inventoryRow,
  mockRoutes,
  overview,
  project,
  renderScreen,
  setSearch,
} from './site-health-screen.test-support';

describe('SiteHealthScreen — Website tab deep links', () => {
  it('preserves Architecture from the URL on initial load', async () => {
    setSearch('tab=architecture');
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
    setSearch('tab=unknown');
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

describe('SiteHealthScreen — canonical single-screen flow (regression)', () => {
  it('walks discover → stop → new crawl → finish without resurrecting selection', async () => {
    const user = userEvent.setup();
    let createBody: unknown = null;
    const NEW_CRAWL = '99999999-9999-4999-8999-999999999999';
    const URL_ID = '66666666-6666-4666-8666-666666666666';
    const summary = {
      web_fundamentals_score: 80,
      web_fundamentals_coverage: 1,
      web_fundamentals_state: 'measured',
      aeo_readiness_score: 62,
      aeo_measurement_coverage: 0.8,
      aeo_measurement_state: 'measured',
      search_eligibility: 'eligible',
      selected_count: 1,
      analyzed_count: 1,
      issue_count: 3,
      scoring_version: 's1',
      ...COMPLETE_CLASSIFICATION_PROJECTION,
      classified_page_count: 1,
      classification_expected_page_count: 1,
      scored_page_kind_set: ['homepage'],
      scored_page_count_by_kind: { homepage: 1 },
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
