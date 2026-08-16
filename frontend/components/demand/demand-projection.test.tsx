import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { TooltipProvider } from '@/components/ui/tooltip';

import { DemandProjection } from './demand-projection';

vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({
    activeProject: { id: '11111111-1111-4111-8111-111111111111' },
    isLoading: false,
  }),
}));

const snapshot = {
  id: '22222222-2222-4222-8222-222222222222',
  project_id: '11111111-1111-4111-8111-111111111111',
  window_start: '2026-07-01',
  window_end: '2026-07-07',
  source_hash: 'hash',
  prior_snapshot_id: null,
  source_artifact_ids: ['artifact'],
  source_metric_row_ids: ['row'],
  coverage: {
    search: 'observed',
    traffic: 'unavailable',
    join: {
      state: 'partial',
      total_pages: 10,
      matched_pages: 4,
      join_rate: 0.4,
      excluded_pages: 2,
    },
  },
  summary: {
    signal_count: 2,
    detectors: {
      striking_distance: { state: 'available' },
      property_relative_ctr_gap: { state: 'unavailable' },
      query_trends: { state: 'insufficient_history' },
    },
  },
  comparison: null,
  formula_version: 'demand-priority-1',
  analyzer_version: 'demand-analyzer-1',
  created_at: '2026-07-08T00:00:00Z',
  signals: [
    {
      id: '33333333-3333-4333-8333-333333333333',
      snapshot_id: '22222222-2222-4222-8222-222222222222',
      signal_type: 'striking_distance',
      state: 'active',
      topic_cluster: 'ai marketing tools',
      page_url: 'https://example.com/ai-tools',
      evidence: { target_kind: 'query', target: 'ai marketing tools' },
      metrics: { impressions: 250, clicks: 12, ctr: 0.048, position: 7.2 },
      coverage: { search_demand: 'observed' },
      limitations: ['Privacy-filtered queries may be omitted.'],
      priority_score: 85,
      priority_inputs: {},
      created_at: '2026-07-08T00:00:00Z',
    },
    {
      id: '44444444-4444-4444-8444-444444444444',
      snapshot_id: '22222222-2222-4222-8222-222222222222',
      signal_type: 'high_impression_low_ctr',
      state: 'active',
      topic_cluster: 'school fees',
      page_url: 'https://example.com/fees',
      evidence: { target_kind: 'query', target: 'school fees' },
      metrics: { impressions: 100, clicks: 0, ctr: 0, position: 12.0 },
      coverage: { search_demand: 'observed' },
      limitations: ['Privacy-filtered queries may be omitted.'],
      priority_score: 50,
      priority_inputs: {},
      created_at: '2026-07-08T00:00:00Z',
    },
  ],
};

vi.mock('@/lib/api/demand', () => ({
  demandApi: {
    getLatest: vi.fn(async () => snapshot),
    // Recompute is a queued job: 202 + `queued`, never a finished snapshot.
    recompute: vi.fn(async () => ({
      task_id: '55555555-5555-4555-8555-555555555555',
      status: 'queued',
    })),
  },
}));

import { demandApi } from '@/lib/api/demand';

describe('DemandProjection', () => {
  beforeEach(() => {
    vi.mocked(demandApi.getLatest).mockResolvedValue(snapshot);
  });

  // Mirrors the route: `app/(app)/demand/page.tsx` owns the TooltipProvider,
  // as every other tooltip-using page in the app does.
  function renderProjection() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <DemandProjection />
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it('renders one Search Demand view with KPI summary cards, diagnostic insights, and no raw priority score', async () => {
    renderProjection();

    expect(await screen.findByText('2 demand signals observed')).toBeInTheDocument();

    // KPI summary cards
    expect(screen.getByText('Latent Search Demand')).toBeInTheDocument();
    expect(screen.getByText('350')).toBeInTheDocument(); // 250 + 100
    expect(screen.getByText('Positions 4–15 quick wins')).toBeInTheDocument();

    // Detector pills
    expect(screen.getAllByText(/Striking distance/i).length).toBeGreaterThan(0);
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getAllByText(/CTR gap/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Unavailable').length).toBeGreaterThan(0);
    expect(screen.getByText('Query trends')).toBeInTheDocument();
    expect(screen.getByText('Needs 28d history')).toBeInTheDocument();

    // Query cards & diagnostic insights
    expect(screen.getByText('ai marketing tools')).toBeInTheDocument();
    expect(screen.getByText('Within reach of the top results')).toBeInTheDocument();
    expect(screen.getByText('school fees')).toBeInTheDocument();
    expect(screen.getByText('Underperforming expected CTR')).toBeInTheDocument();

    // Tabular metrics
    expect(screen.getByText('250')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getByText('4.8%')).toBeInTheDocument();
    expect(screen.getByText('7.2')).toBeInTheDocument();

    // The internal priority score is never rendered. Asserted against the
    // metric list specifically — a bare `queryByText('85')` would pass or fail
    // on any unrelated number that happens to format the same way.
    const metricValues = screen.getAllByRole('definition').map((node) => node.textContent?.trim());
    expect(metricValues).not.toContain('85');
    expect(metricValues).not.toContain('50');
    expect(screen.queryByText(/Demand overview/i)).not.toBeInTheDocument();
  });

  it('quotes no CTR comparison when the cohort benchmark was not observed', async () => {
    // `school fees` carries ctr but no `cohort_median_ctr` — the insight must
    // describe the gap without inventing a benchmark to compare against.
    renderProjection();

    expect(await screen.findByText('Underperforming expected CTR')).toBeInTheDocument();
    expect(screen.getByText(/Impressions are not converting into clicks/i)).toBeInTheDocument();
    expect(screen.queryByText(/median for this position band/i)).not.toBeInTheDocument();
  });

  it('keeps a signal’s priority rank stable when a filter hides the signals above it', async () => {
    renderProjection();

    expect(await screen.findByText('ai marketing tools')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();

    // `school fees` is the second-priority signal; filtering to CTR gaps must
    // not relabel it as the top-priority one.
    fireEvent.click(screen.getByRole('button', { name: /^CTR Gaps/i }));

    expect(screen.getByText('school fees')).toBeInTheDocument();
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.queryByText('#1')).not.toBeInTheDocument();
  });

  it('allows filtering by signal type filter chips and searching by query text', async () => {
    renderProjection();

    expect(await screen.findByText('ai marketing tools')).toBeInTheDocument();
    expect(screen.getByText('school fees')).toBeInTheDocument();

    // Click Striking Distance filter chip (using aria-pressed)
    const strikingChip = screen.getByRole('button', {
      name: /^Striking Distance/i,
      pressed: false,
    });
    fireEvent.click(strikingChip);

    expect(screen.getByText('ai marketing tools')).toBeInTheDocument();
    expect(screen.queryByText('school fees')).not.toBeInTheDocument();

    // Click All Signals chip
    const allChip = screen.getByRole('button', { name: /^All Signals/i });
    fireEvent.click(allChip);
    expect(screen.getByText('school fees')).toBeInTheDocument();

    // Search query
    const searchInput = screen.getByPlaceholderText('Filter queries or URLs...');
    fireEvent.change(searchInput, { target: { value: 'fees' } });

    expect(screen.queryByText('ai marketing tools')).not.toBeInTheDocument();
    expect(screen.getByText('school fees')).toBeInTheDocument();
  });

  it('announces the initial load while the skeleton remains decorative', () => {
    vi.mocked(demandApi.getLatest).mockImplementation(
      () =>
        new Promise(() => {
          // Intentionally pending so the loading state stays rendered.
        }),
    );
    renderProjection();

    expect(screen.getByRole('status')).toHaveTextContent('Loading search demand');
  });

  it('distinguishes unavailable Search Console evidence', async () => {
    vi.mocked(demandApi.getLatest).mockResolvedValue({
      ...snapshot,
      coverage: { ...snapshot.coverage, search: 'unavailable' },
    });
    renderProjection();

    expect(await screen.findByText(/Search Console evidence is unavailable/)).toBeInTheDocument();
    expect(screen.queryByText('school fees')).not.toBeInTheDocument();
  });

  it('states that observed Search Console data had no qualifying gaps', async () => {
    vi.mocked(demandApi.getLatest).mockResolvedValue({ ...snapshot, signals: [] });
    renderProjection();

    expect(await screen.findByText(/no qualifying search gaps observed/i)).toBeInTheDocument();
  });

  it('opens the evidence drawer with provenance and candidate breakdown when inspect is clicked', async () => {
    renderProjection();

    expect(await screen.findByText('ai marketing tools')).toBeInTheDocument();

    // Click the first Inspect Evidence button
    const inspectButtons = screen.getAllByRole('button', { name: /Inspect Evidence/i });
    fireEvent.click(inspectButtons[0]);

    // Drawer should display title, observed performance, and audit trail
    expect(await screen.findByText('Demand Signal Evidence')).toBeInTheDocument();
    expect(screen.getByText('Observed GSC Performance')).toBeInTheDocument();
    expect(screen.getByText('Audit Trail & Provenance')).toBeInTheDocument();
  });

  it('reports that recompute was queued rather than implying a finished rebuild', async () => {
    renderProjection();

    expect(await screen.findByText('2 demand signals observed')).toBeInTheDocument();

    const fetchesBeforeRecompute = vi.mocked(demandApi.getLatest).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: /Recompute Signals/i }));

    await waitFor(() => {
      expect(demandApi.recompute).toHaveBeenCalledWith('11111111-1111-4111-8111-111111111111', {
        window_start: '2026-07-01',
        window_end: '2026-07-07',
      });
    });

    // The worker has not run yet, so the UI must say the job is queued and
    // must NOT silently refetch the identical snapshot as if it had rebuilt.
    expect(await screen.findByText(/Recompute queued/i)).toBeInTheDocument();
    expect(vi.mocked(demandApi.getLatest).mock.calls.length).toBe(fetchesBeforeRecompute);
  });

  it('surfaces a recompute failure instead of returning silently to idle', async () => {
    vi.mocked(demandApi.recompute).mockRejectedValueOnce(new Error('boom'));
    renderProjection();

    expect(await screen.findByText('2 demand signals observed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Recompute Signals/i }));

    expect(await screen.findByRole('button', { name: /Try again/i })).toBeInTheDocument();
  });
});
