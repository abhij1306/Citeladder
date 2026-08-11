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
      active: true,
      startPending: false,
    };
    const onMutationStart = vi.fn();

    render(
      <PhaseControls
        screen={siteHealthScreen as never}
        lastMutation={null}
        onMutationStart={onMutationStart}
        onRecrawl={vi.fn()}
      />,
    );

    expect(screen.getByRole('heading', { name: 'Discover more URLs' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Analyze URLs' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Stop discovery' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Re-crawl site' })).toBeDisabled();

    await userEvent.click(screen.getByRole('button', { name: 'Start analysis' }));
    expect(onMutationStart).toHaveBeenCalledWith('startAnalysis');
    expect(startAnalysisMutation.mutate).toHaveBeenCalledOnce();
    expect(screen.queryByText('stale discovery error')).not.toBeInTheDocument();
  });

  it('keeps each action stable while its request is pending', () => {
    const siteHealthScreen = {
      crawl: {
        id: '22222222-2222-4222-8222-222222222222',
        discovery_status: 'stopped',
        analysis_status: 'running',
        counters: {
          discovered: 176,
          selected: 48,
          queued: 0,
          running: 2,
          analyzed: 34,
          errors: 1,
          blocked: 1,
        },
      },
      entitlementQuery: { data: { advanced_controls_enabled: true } },
      monitoredQuery: { data: { selection_version: 4 } },
      dashboardQuery: {
        data: { phase_runs: { discovery: null, analysis: null } },
      },
      startDiscoveryMutation: { ...mutation(), isPending: true },
      stopDiscoveryMutation: mutation(),
      startAnalysisMutation: mutation(),
      stopAnalysisMutation: { ...mutation(), isPending: true },
      active: false,
      startPending: false,
    };

    render(
      <PhaseControls
        screen={siteHealthScreen as never}
        lastMutation={null}
        onMutationStart={vi.fn()}
        onRecrawl={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Continue discovery' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Start analysis' })).not.toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
    expect(screen.getByText('problems')).toBeInTheDocument();
  });

  it('updates a phase button in place through start, running, stop, and stopped states', () => {
    const siteHealthScreen = {
      crawl: {
        id: '22222222-2222-4222-8222-222222222222',
        discovery_status: 'stopped',
        analysis_status: 'stopped',
        counters: {
          discovered: 12,
          selected: 4,
          queued: 0,
          running: 0,
          analyzed: 4,
          errors: 0,
          blocked: 0,
        },
      },
      entitlementQuery: { data: { advanced_controls_enabled: true } },
      monitoredQuery: { data: { selection_version: 4 } },
      dashboardQuery: { data: { phase_runs: { discovery: null, analysis: null } } },
      startDiscoveryMutation: mutation(),
      stopDiscoveryMutation: mutation(),
      startAnalysisMutation: mutation(),
      stopAnalysisMutation: mutation(),
      active: false,
      startPending: false,
    };
    const props = {
      lastMutation: null,
      onMutationStart: vi.fn(),
      onRecrawl: vi.fn(),
    };
    const { rerender } = render(<PhaseControls screen={siteHealthScreen as never} {...props} />);
    const controls = screen.getByTestId('site-health-phase-controls');

    expect(screen.getByRole('button', { name: 'Continue discovery' })).toBeInTheDocument();
    siteHealthScreen.startDiscoveryMutation.isPending = true;
    rerender(<PhaseControls screen={siteHealthScreen as never} {...props} />);
    expect(screen.getByRole('button', { name: 'Starting…' })).toBeDisabled();

    siteHealthScreen.startDiscoveryMutation.isPending = false;
    siteHealthScreen.crawl.discovery_status = 'running';
    rerender(<PhaseControls screen={siteHealthScreen as never} {...props} />);
    expect(screen.getByRole('button', { name: 'Stop discovery' })).toBeInTheDocument();

    siteHealthScreen.stopDiscoveryMutation.isPending = true;
    rerender(<PhaseControls screen={siteHealthScreen as never} {...props} />);
    expect(screen.getByRole('button', { name: 'Stopping…' })).toBeDisabled();

    siteHealthScreen.stopDiscoveryMutation.isPending = false;
    siteHealthScreen.crawl.discovery_status = 'stopped';
    rerender(<PhaseControls screen={siteHealthScreen as never} {...props} />);
    expect(screen.getByRole('button', { name: 'Continue discovery' })).toBeInTheDocument();
    expect(screen.getByTestId('site-health-phase-controls')).toBe(controls);
  });
});
