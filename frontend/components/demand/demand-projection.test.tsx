import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

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

describe('DemandProjection', () => {
  it.each(['overview', 'search'] as const)(
    'renders persisted coverage and search signals in the %s panel',
    async (panel) => {
      render(
        <QueryClientProvider client={new QueryClient()}>
          <DemandProjection panel={panel} />
        </QueryClientProvider>,
      );

      expect(await screen.findByText('Prioritized signals')).toBeInTheDocument();
      expect(screen.getByText('observed')).toBeInTheDocument();
      expect(screen.getByText('unavailable')).toBeInTheDocument();
      expect(
        screen.getByText('partial · 4 of 10 pages joined · 40% · excluded pages 2'),
      ).toBeInTheDocument();
      expect(screen.queryByText(/join rate 0\.4/)).not.toBeInTheDocument();
      expect(screen.getByText('school fees')).toBeInTheDocument();
    },
  );
});
