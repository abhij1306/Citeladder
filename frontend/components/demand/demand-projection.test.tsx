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
  site_snapshot_id: null,
  prior_snapshot_id: null,
  source_artifact_ids: ['artifact'],
  source_metric_row_ids: ['row'],
  source_audit_ids: [],
  journey_version_ids: [],
  coverage: { search: 'observed', visibility: 'unavailable' },
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
      audience: '',
      intent: '',
      journey_stage: '',
      topic_cluster: 'school fees',
      page_url: '',
      evidence: {},
      metrics: { impressions: 100, clicks: 0 },
      coverage: { search_demand: 'observed' },
      limitations: ['Privacy-filtered queries may be omitted.'],
      priority_score: 50,
      priority_inputs: {},
      model_provenance: null,
      created_at: '2026-07-08T00:00:00Z',
    },
  ],
};

vi.mock('@/lib/api/demand', () => ({
  demandApi: {
    listSnapshots: vi.fn(async () => ({ items: [{ ...snapshot, signals: [] }] })),
    getSnapshot: vi.fn(async () => snapshot),
    getCapabilities: vi.fn(async () => ({ datasets: [] })),
  },
}));

function renderProjection(panel: 'overview' | 'search' | 'journeys' | 'prompts' | 'evidence') {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <DemandProjection panel={panel} />
    </QueryClientProvider>,
  );
}

describe('DemandProjection', () => {
  it('renders observed and unavailable coverage without coercing either to zero', async () => {
    renderProjection('overview');
    expect(await screen.findByText('Prioritized signals')).toBeInTheDocument();
    expect(screen.getByText('observed')).toBeInTheDocument();
    expect(screen.getByText('unavailable')).toBeInTheDocument();
    expect(screen.getByText('school fees')).toBeInTheDocument();
  });

  it('renders exact persisted provenance in the evidence panel', async () => {
    renderProjection('evidence');
    expect(await screen.findByText('Provenance')).toBeInTheDocument();
    expect(screen.getByText(/1 metric rows · 1 immutable artifacts/)).toBeInTheDocument();
    expect(screen.getByText('Report families')).toBeInTheDocument();
  });
});
