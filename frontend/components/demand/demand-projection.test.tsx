import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

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
  summary: { signal_count: 1 },
  comparison: null,
  formula_version: 'demand-priority-1',
  analyzer_version: 'demand-analyzer-1',
  created_at: '2026-07-08T00:00:00Z',
  signals: [
    {
      id: '33333333-3333-4333-8333-333333333333',
      snapshot_id: '22222222-2222-4222-8222-222222222222',
      signal_type: 'high_impression_low_ctr',
      state: 'active',
      topic_cluster: 'school fees',
      page_url: '',
      evidence: {},
      metrics: { impressions: 100, clicks: 0 },
      coverage: { search_demand: 'observed' },
      limitations: ['Privacy-filtered queries may be omitted.'],
      priority_score: 50,
      priority_inputs: {},
      created_at: '2026-07-08T00:00:00Z',
    },
  ],
};

vi.mock('@/lib/api/demand', () => ({
  demandApi: { getLatest: vi.fn(async () => snapshot) },
}));

import { demandApi } from '@/lib/api/demand';

describe('DemandProjection', () => {
  beforeEach(() => {
    vi.mocked(demandApi.getLatest).mockResolvedValue(snapshot);
  });

  function renderProjection() {
    return render(
      <QueryClientProvider client={new QueryClient()}>
        <DemandProjection />
      </QueryClientProvider>,
    );
  }

  it('renders one Search Demand view with useful GSC metrics and no raw score', async () => {
    renderProjection();

    expect(await screen.findByText('1 search gap needs attention')).toBeInTheDocument();
    expect(screen.getByText('Query')).toBeInTheDocument();
    expect(screen.getByText('school fees')).toBeInTheDocument();
    expect(screen.getByText('100')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('0.0%')).toBeInTheDocument();
    expect(screen.getByText('Privacy-filtered queries may be omitted.')).toBeInTheDocument();
    expect(screen.queryByText('50')).not.toBeInTheDocument();
    expect(screen.queryByText(/Demand overview/i)).not.toBeInTheDocument();
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

    expect(
      await screen.findByText(/no query or page met the configured high-impression, low-click criteria/i),
    ).toBeInTheDocument();
  });
});
