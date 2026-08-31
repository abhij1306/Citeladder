import { http, HttpResponse } from 'msw';
import { describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import {
  AUDIT_LATEST,
  AUDIT_OLDER,
  PROJECT_ID,
  makeAudit,
  makeEvidenceResponse,
  makeProject,
  makeTrendPoint,
  makeVisibility,
  renderVisibilityPage,
  setupVisibilityPageTests,
  useBaseVisibilityHandlers,
} from '@/test/fixtures/visibility';
import { mswServer } from '@/test/msw-server';

let pushStateSpy: ReturnType<typeof vi.spyOn>;
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn(), back: vi.fn(), forward: vi.fn() }),
  usePathname: () => '/visibility',
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

setupVisibilityPageTests(() => {
  pushStateSpy = vi.spyOn(window.history, 'pushState');
  window.history.replaceState(null, '', '/visibility');
  pushStateSpy.mockClear();
});

function setVisibilitySearch(search: string) {
  window.history.replaceState(null, '', `/visibility${search ? `?${search}` : ''}`);
}

describe('VisibilityPage — tablist', () => {
  it('renders exactly the three retained tabs and no retired Overview tab', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    const tablist = await screen.findByRole('tablist', { name: 'Visibility views' });
    const tabs = within(tablist).getAllByRole('tab');
    expect(tabs.map((t) => t.textContent)).toEqual(['Trends', 'Mentions', 'Search queries']);
    expect(within(tablist).queryByRole('tab', { name: 'Overview' })).toBeNull();
    // The forbidden tab labels are absent.
    expect(within(tablist).queryByRole('tab', { name: 'Sources' })).toBeNull();
    expect(within(tablist).queryByRole('tab', { name: 'Topics' })).toBeNull();
    expect(within(tablist).queryByRole('tab', { name: 'Sentiment' })).toBeNull();
  });

  it('opens on Trends by default and renders exactly one active panel', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    const trendsTab = await screen.findByRole('tab', { name: 'Trends' });
    expect(trendsTab).toHaveAttribute('aria-selected', 'true');
    // Exactly one panel is rendered.
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
    expect(await screen.findByTestId('trend-chart-visibility_score')).toBeVisible();
  });

  it('falls back to Trends for an invalid ?tab= value', async () => {
    setVisibilitySearch('tab=sources');
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    expect(await screen.findByRole('tab', { name: 'Trends' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('reads the active tab from ?tab= on load (refresh/deeplink)', async () => {
    setVisibilitySearch('tab=trends');
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () =>
        HttpResponse.json([
          makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67),
          makeTrendPoint(AUDIT_OLDER, '2026-07-10T00:00:00Z', 55),
        ]),
      ),
    ]);
    renderVisibilityPage();

    expect(await screen.findByRole('tab', { name: 'Trends' })).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  it('pushes shallow tab history so browser Back can restore the prior view', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () => HttpResponse.json([])),
    ]);
    const user = userEvent.setup();
    renderVisibilityPage();

    await screen.findByRole('tab', { name: 'Trends' });
    await user.click(screen.getByRole('tab', { name: 'Mentions' }));

    await waitFor(() =>
      expect(pushStateSpy).toHaveBeenCalledWith(
        null,
        '',
        expect.stringContaining('tab=mentions-citations'),
      ),
    );
  });

  it('supports keyboard Arrow/Home/End navigation with focus transfer', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () => HttpResponse.json([])),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/evidence`, () =>
        HttpResponse.json(makeEvidenceResponse()),
      ),
    ]);
    const user = userEvent.setup();
    renderVisibilityPage();

    const trendsTab = await screen.findByRole('tab', { name: 'Trends' });
    trendsTab.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Mentions' })).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{End}');
    expect(screen.getByRole('tab', { name: 'Search queries' })).toHaveAttribute(
      'aria-selected',
      'true',
    );

    // Wraps forward from the last tab back to the first.
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true');

    await user.keyboard('{Home}');
    expect(screen.getByRole('tab', { name: 'Trends' })).toHaveAttribute('aria-selected', 'true');
  });

  it('exposes a horizontally scrollable tablist for narrow viewports', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    const tablist = await screen.findByRole('tablist', { name: 'Visibility views' });
    expect(tablist.className).toContain('overflow-x-auto');
    expect(tablist.className).toContain('flex-nowrap');
  });
});

describe('VisibilityPage — retained capabilities in Trends', () => {
  it('renders the score and per-engine comparison from data', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    expect(await screen.findByRole('heading', { name: 'By model' })).toBeInTheDocument();
    expect(screen.getByText('Gemini')).toBeInTheDocument();
    expect(screen.getByText('Claude')).toBeInTheDocument();
  });

  it('renders latest and start-of-range ranking history', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    renderVisibilityPage();

    const rankings = (await screen.findByRole('heading', { name: 'Rankings (Latest)' })).closest(
      'section',
    )!;
    const bodyRows = within(rankings).getAllByRole('row').slice(1);
    expect(within(bodyRows[0]).getByText('Acme')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Rankings (Start of Range)' })).toBeVisible();
  });

  it('changes the query when a different run is selected', async () => {
    const seen: (string | null)[] = [];
    let releaseOlder: (() => void) | undefined;
    useBaseVisibilityHandlers([
      http.get('/api/v1/audits', () =>
        HttpResponse.json([
          makeAudit(AUDIT_LATEST, '2026-07-15T00:00:00Z'),
          makeAudit(AUDIT_OLDER, '2026-07-10T00:00:00Z'),
        ]),
      ),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, async ({ request }) => {
        const auditId = new URL(request.url).searchParams.get('audit_id');
        seen.push(auditId);
        if (auditId === AUDIT_OLDER) {
          await new Promise<void>((resolve) => {
            releaseOlder = resolve;
          });
        }
        return HttpResponse.json(
          makeVisibility(auditId ?? AUDIT_LATEST, auditId === AUDIT_OLDER ? 42 : 67),
        );
      }),
    ]);
    // makeAudit sets status completed; override the base audits handler above.
    mswServer.use(
      http.get('/api/v1/audits', () =>
        HttpResponse.json([
          makeAudit(AUDIT_LATEST, '2026-07-15T00:00:00Z'),
          makeAudit(AUDIT_OLDER, '2026-07-10T00:00:00Z'),
        ]),
      ),
    );
    const user = userEvent.setup();
    renderVisibilityPage();

    await screen.findByRole('heading', { name: 'By model' });
    expect(seen[0]).toBe(AUDIT_LATEST);

    await user.click(screen.getByRole('button', { name: 'Select run' }));
    const olderLabel = new Date('2026-07-10T00:00:00Z').toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
    await user.click(await screen.findByRole('menuitemradio', { name: olderLabel }));

    await waitFor(() => expect(releaseOlder).toBeTypeOf('function'));
    releaseOlder?.();
    await waitFor(() => expect(seen).toContain(AUDIT_OLDER));

    await user.click(screen.getByRole('button', { name: 'Select run' }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'Latest' }));
    expect(screen.getByRole('button', { name: 'Select run' })).toHaveTextContent('Latest');
  });

  it('narrows the per-engine comparison when an engine filter is applied', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    const user = userEvent.setup();
    renderVisibilityPage();

    await screen.findByRole('heading', { name: 'By model' });
    const comparisonOf = () =>
      screen.getByRole('heading', { name: 'By model' }).closest('section')!;
    expect(within(comparisonOf()).getByText('Claude')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Filter by model' }));
    await user.click(await screen.findByRole('menuitemradio', { name: 'Gemini' }));

    await waitFor(() =>
      expect(within(comparisonOf()).queryByText('Claude')).not.toBeInTheDocument(),
    );
    expect(within(comparisonOf()).getByText('Gemini')).toBeInTheDocument();
  });

  it('shows the empty state when the project has no completed runs', async () => {
    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([makeProject()])),
      http.get('/api/v1/audits', () => HttpResponse.json([])),
    );
    renderVisibilityPage();

    expect(await screen.findByText('No completed runs yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /launch your first audit/i })).toBeInTheDocument();
    // No tablist is rendered in the empty state.
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('shows the in-progress banner when the only run is still active', async () => {
    mswServer.use(
      http.get('/api/v1/projects', () => HttpResponse.json([makeProject()])),
      http.get('/api/v1/audits', () =>
        HttpResponse.json([
          {
            ...makeAudit(AUDIT_LATEST, '2026-07-15T00:00:00Z'),
            status: 'running',
            completed_at: null,
          },
        ]),
      ),
    );
    renderVisibilityPage();

    // The banner names the run's progress and links to its live detail page.
    expect(await screen.findByText(/a run is in progress/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /watch live progress/i })).toHaveAttribute(
      'href',
      `/runs/${AUDIT_LATEST}`,
    );
    // The empty state acknowledges the active run instead of urging a launch.
    expect(
      screen.getByText('An audit is running — results appear here when it finishes.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /launch your first audit/i })).toBeNull();
  });

  it('shows the in-progress banner above the dashboard when a completed run exists', async () => {
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
    ]);
    // Override the base audits handler: one completed run + one still running.
    mswServer.use(
      http.get('/api/v1/audits', () =>
        HttpResponse.json([
          makeAudit(AUDIT_LATEST, '2026-07-15T00:00:00Z'),
          {
            ...makeAudit(AUDIT_OLDER, '2026-07-18T00:00:00Z'),
            status: 'running',
            completed_at: null,
          },
        ]),
      ),
    );
    renderVisibilityPage();

    // The completed run's dashboard renders as usual…
    expect(await screen.findByRole('heading', { name: 'By model' })).toBeVisible();
    // …with the active-run banner on top, linking to the running audit.
    expect(screen.getByText(/a run is in progress/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /watch live progress/i })).toHaveAttribute(
      'href',
      `/runs/${AUDIT_OLDER}`,
    );
  });
});

describe('VisibilityPage — per-tab query enablement + cache reuse', () => {
  it('fetches trend and selected-run projections together only on Trends', async () => {
    let visibilityCalls = 0;
    let trendCalls = 0;
    let evidenceCalls = 0;
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () => {
        visibilityCalls += 1;
        return HttpResponse.json(makeVisibility(AUDIT_LATEST, 67));
      }),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () => {
        trendCalls += 1;
        return HttpResponse.json([makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67)]);
      }),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/evidence`, () => {
        evidenceCalls += 1;
        return HttpResponse.json(makeEvidenceResponse());
      }),
    ]);
    renderVisibilityPage();

    await screen.findByRole('heading', { name: 'By model' });
    expect(visibilityCalls).toBe(1);
    expect(trendCalls).toBe(1);
    expect(evidenceCalls).toBe(0);
  });

  it('reuses one evidence request across the two evidence tabs', async () => {
    let evidenceCalls = 0;
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility`, () =>
        HttpResponse.json(makeVisibility(AUDIT_LATEST, 67)),
      ),
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/evidence`, () => {
        evidenceCalls += 1;
        return HttpResponse.json(makeEvidenceResponse());
      }),
    ]);
    const user = userEvent.setup();
    renderVisibilityPage();

    await screen.findByRole('tab', { name: 'Trends' });
    await user.click(screen.getByRole('tab', { name: 'Mentions' }));
    expect(
      await screen.findByText('Best affordable clothing stores in Australia?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Search queries' }));
    // The Query Fanout panel renders from the same cached response.
    expect(
      await screen.findByText('affordable family clothing Australia 2026'),
    ).toBeInTheDocument();

    // One shared evidence request only — no duplicate fetch on tab switch.
    await waitFor(() => expect(evidenceCalls).toBe(1));
  });
});

describe('VisibilityPage — Trends tab', () => {
  it('renders the trend charts and sends granularity + date bounds', async () => {
    vi.stubEnv('NEXT_PUBLIC_LOGO_DEV_PUBLISHABLE', 'pk_test');
    setVisibilitySearch('tab=trends');
    const params: URL[] = [];
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, ({ request }) => {
        params.push(new URL(request.url));
        return HttpResponse.json([
          makeTrendPoint(AUDIT_OLDER, '2026-07-10T00:00:00Z', 55),
          makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67),
        ]);
      }),
    ]);
    renderVisibilityPage();

    expect(await screen.findByTestId('trend-chart-visibility_score')).toBeInTheDocument();
    expect(screen.getByTestId('trend-chart-sov')).toBeInTheDocument();
    const latestRankings = screen
      .getByRole('heading', { name: 'Rankings (Latest)' })
      .closest('section')!;
    expect(latestRankings.querySelector('img')?.getAttribute('src')).toContain(
      'img.logo.dev/acme.com',
    );
    expect(latestRankings.querySelector('.size-2')).toBeNull();
    // Default granularity=run and a bounded 90d `from` are sent.
    expect(params[0].searchParams.get('granularity')).toBe('run');
    expect(params[0].searchParams.get('from')).toBeTruthy();
  });

  it('renders the single-point info state', async () => {
    setVisibilitySearch('tab=trends');
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () =>
        HttpResponse.json([makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67)]),
      ),
    ]);
    renderVisibilityPage();

    expect(await screen.findByText(/only one completed run is in range/i)).toBeInTheDocument();
  });

  it('renders a null trend metric as a chart gap, never a zero', async () => {
    setVisibilitySearch('tab=trends');
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () =>
        HttpResponse.json([
          makeTrendPoint(AUDIT_OLDER, '2026-07-10T00:00:00Z', 55),
          makeTrendPoint('11111111-1111-4111-8111-1111111111ab', '2026-07-12T00:00:00Z', null),
          makeTrendPoint(AUDIT_LATEST, '2026-07-15T00:00:00Z', 67),
        ]),
      ),
    ]);
    renderVisibilityPage();

    const scoreChart = await screen.findByTestId('trend-chart-visibility_score');
    const svg = within(scoreChart).getByRole('img');
    expect(svg.getAttribute('aria-label')).toContain('unavailable and shown as gaps');
    // The null point draws no dot: only the two available points do.
    expect(scoreChart.querySelectorAll('circle.fill-accent')).toHaveLength(2);
  });

  it('renders the retryable error state', async () => {
    setVisibilitySearch('tab=trends');
    useBaseVisibilityHandlers([
      http.get(`/api/v1/projects/${PROJECT_ID}/visibility/trends`, () =>
        HttpResponse.json({ detail: 'boom' }, { status: 400 }),
      ),
    ]);
    renderVisibilityPage();

    expect(await screen.findByText(/could not load the visibility trend/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });
});
