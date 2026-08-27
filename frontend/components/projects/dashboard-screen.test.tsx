import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const { project, downloadExecutiveReport, queryResult } = vi.hoisted(() => ({
  project: {
    id: '00000000-0000-4000-8000-000000000001',
    workspace_id: '00000000-0000-4000-8000-000000000002',
    name: 'Acme',
    brand_name: 'Acme',
    website_url: 'https://acme.com',
    brand: { aliases: [], logo_url: null },
    competitors: [],
  },
  downloadExecutiveReport: vi.fn().mockResolvedValue(new Blob(['pdf'])),
  queryResult: {
    data: undefined as unknown,
    error: null as unknown,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  },
}));

const commandCenter = {
  project,
  facts: {
    industry: 'Software',
    description: 'Analytics for growth teams',
    positioning: 'Evidence-first analytics',
    products_services: ['Analytics'],
    target_audience: 'Growth leaders',
    competitors: [],
  },
  loop: {
    connected: {
      state: 'observed',
      observed_at: '2026-07-27T00:00:00Z',
      freshness: 'current',
      coverage: ['gsc'],
      limitations: [],
    },
    analyzed: {
      state: 'partial',
      observed_at: '2026-07-27T00:00:00Z',
      freshness: 'current',
      coverage: ['site_health'],
      limitations: ['Search Demand has not refreshed yet.'],
    },
    acted: {
      state: 'not_run',
      observed_at: null,
      freshness: 'unknown',
      coverage: [],
      limitations: ['No current-cycle implementation.'],
    },
    tracked: {
      state: 'observed',
      observed_at: '2026-07-28T00:00:00Z',
      freshness: 'current',
      coverage: ['chatgpt', 'gemini'],
      limitations: [],
    },
  },
  next_action: {
    kind: 'monitor',
    title: 'Monitor — no required action',
    href: '/visibility?tab=trends',
    opportunity_id: null,
  },
  track: {
    citation_share: { value: 32.5, delta: 2.1 },
    engine_coverage: 2,
    observed_at: '2026-07-28T00:00:00Z',
    limitations: [],
  },
  measurement: {
    audit_id: '00000000-0000-4000-8000-000000000003',
    completed_at: '2026-07-28T00:00:00Z',
    benchmark_mode: 'consumer_like',
    logical_engines: ['chatgpt', 'gemini'],
    comparable_audit_id: '00000000-0000-4000-8000-000000000004',
  },
  state: {
    visibility: { value: 72.5, delta: 4.2 },
    share_of_voice: { value: 48.1, delta: 3.1 },
    brand_rank: { value: 2, delta: -1 },
  },
  movements: [
    { label: 'visibility', direction: 'positive', current: 72.5, previous: 68.3, delta: 4.2 },
  ],
  actions: [],
  action_order_version: 0,
  resolved_actions: {
    since_audit_id: '00000000-0000-4000-8000-000000000004',
    count: 2,
    titles: ['Fixed citations', 'Expanded evidence'],
  },
  report_available: true,
  stale: false,
};

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }));

// This file mocks useQuery wholesale to return the command-center fixture, so
// TopInsights would receive that shape instead of an opportunities page. It is
// a separate unit with its own tests (components/intelligence); stub it out
// rather than teaching this fixture two response shapes.
vi.mock('@/components/intelligence/top-insights', () => ({
  TopInsights: () => null,
}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => queryResult,
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
  useMutation: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock('@/lib/project/project-context', () => ({
  useActiveProject: () => project,
  useProjectContext: () => ({
    projects: [project],
    activeProject: project,
    activeProjectId: project.id,
    setActiveProjectId: vi.fn(),
    isLoading: false,
  }),
}));

vi.mock('@/lib/api/projects', () => ({
  projectsApi: { getCommandCenter: vi.fn(), downloadExecutiveReport },
}));

vi.mock('@/lib/api/opportunities', () => ({
  opportunitiesApi: { updateOrder: vi.fn() },
}));

import { DashboardScreen } from './dashboard-screen';

describe('DashboardScreen', () => {
  beforeEach(() => {
    queryResult.data = commandCenter;
    queryResult.error = null;
    queryResult.isLoading = false;
    queryResult.isError = false;
    queryResult.refetch.mockReset();
  });

  it('renders state, comparable movement, actions, and report proof', () => {
    render(<DashboardScreen />);

    expect(screen.getByRole('heading', { name: 'Acme' })).toBeInTheDocument();
    expect(screen.getByText('72.5')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Project state' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Movement' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Ranked actions' })).toBeInTheDocument();
    expect(screen.getByText(/2 action\(s\) resolved/i)).toBeInTheDocument();
    expect(screen.getByText('Evidence-first analytics')).toBeVisible();
    expect(screen.getByText('Growth leaders')).toBeVisible();
    expect(screen.getByText('Analytics')).toBeVisible();
    expect(screen.getByText('32.5%')).toHaveClass('text-3xl');
    expect(screen.getByText('Citation share')).toHaveClass('font-display', 'text-base');

    const facts = screen.getByRole('heading', { name: 'Company facts' });
    const nextAction = screen.getByText('Monitor — no required action');
    const state = screen.getByRole('heading', { name: 'Project state' });
    const movement = screen.getByRole('heading', { name: 'Movement' });
    expect(
      facts.compareDocumentPosition(nextAction) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      nextAction.compareDocumentPosition(state) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(state.compareDocumentPosition(movement) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('downloads the authenticated executive PDF', async () => {
    const user = userEvent.setup();
    const createObjectURL = vi.fn(() => 'blob:report');
    const revokeObjectURL = vi.fn();
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);

    render(<DashboardScreen />);
    await user.click(screen.getByRole('button', { name: /executive pdf/i }));

    expect(downloadExecutiveReport).toHaveBeenCalledWith(project.id);
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(click).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report');
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it('shows a recoverable error when report download fails', async () => {
    downloadExecutiveReport.mockRejectedValueOnce(new Error('download failed'));
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:report'), revokeObjectURL: vi.fn() });
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    const user = userEvent.setup();

    render(<DashboardScreen />);
    await user.click(screen.getByRole('button', { name: /executive pdf/i }));
    expect(await screen.findByText('The report could not be downloaded. Try again.')).toBeVisible();

    await user.click(screen.getByRole('button', { name: /executive pdf/i }));
    await waitFor(() =>
      expect(
        screen.queryByText('The report could not be downloaded. Try again.'),
      ).not.toBeInTheDocument(),
    );
    click.mockRestore();
    vi.unstubAllGlobals();
  });

  it('renders facts and a real next action before the first audit', () => {
    queryResult.data = {
      ...commandCenter,
      measurement: null,
      report_available: false,
      track: {
        citation_share: { value: null, delta: null },
        engine_coverage: 0,
        observed_at: null,
        limitations: ['No visibility audit has run yet.'],
      },
      loop: {
        ...commandCenter.loop,
        tracked: {
          state: 'not_run',
          observed_at: null,
          freshness: 'unknown',
          coverage: [],
          limitations: ['No visibility audit has run yet.'],
        },
      },
      next_action: {
        kind: 'audit',
        title: 'Run the first visibility audit',
        href: '/runs',
        opportunity_id: null,
      },
    };

    render(<DashboardScreen />);

    expect(screen.getByRole('heading', { name: 'Company facts' })).toBeVisible();
    // The Product loop strip was removed from Overview; loop evidence still
    // arrives on the projection but no longer has a station-tile surface.
    expect(screen.queryByRole('heading', { name: 'Product loop' })).not.toBeInTheDocument();
    expect(screen.getByText('Run the first visibility audit')).toBeVisible();
    expect(screen.getByText('Citation share')).toBeVisible();
    expect(screen.getAllByText('Not run').length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: /executive pdf/i })).not.toBeInTheDocument();
  });

  it('keeps observed zero distinct from an unavailable value', () => {
    queryResult.data = {
      ...commandCenter,
      track: {
        ...commandCenter.track,
        citation_share: { value: 0, delta: 0 },
      },
    };

    render(<DashboardScreen />);

    expect(screen.getByText('0%')).toBeVisible();
    expect(screen.queryByText('Not measured')).not.toBeInTheDocument();
  });
});
