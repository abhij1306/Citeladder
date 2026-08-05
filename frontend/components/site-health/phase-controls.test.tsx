import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PhaseControls } from './phase-controls';

function mutation(error: Error | null = null) {
  return { error, isPending: false, mutate: vi.fn() };
}

describe('PhaseControls', () => {
  it('uses phase runs for running state and scopes errors to the invoked action', async () => {
    const startDiscoveryMutation = mutation(new Error('stale discovery error'));
    const stopDiscoveryMutation = mutation();
    const startAnalysisMutation = mutation();
    const stopAnalysisMutation = mutation();
    const crawl = {
      id: '22222222-2222-4222-8222-222222222222',
      discovery_status: 'stopped',
      analysis_status: 'stopped',
      counters: {
        discovered: 3,
        selected: 2,
        queued: 0,
        running: 0,
        analyzed: 2,
        errors: 0,
        blocked: 0,
      },
    };
    const phaseRun = {
      id: '33333333-3333-4333-8333-333333333333',
      phase: 'discovery',
      status: 'running',
      requested_count: 10,
      processed_count: 2,
      created_at: '2026-08-05T00:00:00Z',
      stopped_at: null,
      completed_at: null,
    };
    const siteHealthScreen = {
      crawl,
      entitlementQuery: { data: { advanced_controls_enabled: true } },
      monitoredQuery: { data: { selection_version: 4 } },
      dashboardQuery: {
        data: { phase_runs: { discovery: phaseRun, analysis: null } },
      },
      startDiscoveryMutation,
      stopDiscoveryMutation,
      startAnalysisMutation,
      stopAnalysisMutation,
    };

    render(<PhaseControls screen={siteHealthScreen as never} selectedUrlIds={new Set()} />);

    expect(screen.getByRole('heading', { name: 'URL discovery' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'URL analysis' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop discovery' })).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: 'Start analysis' }));
    expect(startAnalysisMutation.mutate).toHaveBeenCalledOnce();
    expect(screen.queryByText('stale discovery error')).not.toBeInTheDocument();
  });
});
