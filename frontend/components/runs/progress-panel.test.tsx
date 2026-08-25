import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { Audit, AuditStatus } from '@/lib/api/types';

import { ProgressPanel } from './progress-panel';

/**
 * `components/runs` shipped with no colocated tests. The run lifecycle surface
 * is the one place a user can stop work that costs money, so the assertions
 * that matter are about the Cancel affordance: it must be live while — and only
 * while — the backend would still accept a cooperative cancel. `reporting` is
 * deliberately NOT cancelable (execution and analysis are already done), which
 * is exactly the boundary a rendering test can pin.
 */
const BASE_AUDIT: Audit = {
  id: '11111111-1111-4111-8111-111111111111',
  workspace_id: '22222222-2222-4222-8222-222222222222',
  project_id: '33333333-3333-4333-8333-333333333333',
  status: 'running',
  benchmark_mode: 'consumer_like',
  audit_scope: 'brand',
  model_provenance: [],
  repetitions: 1,
  random_seed: 'seed',
  requested_count: 12,
  completed_count: 5,
  failed_count: 0,
  error_message: '',
  engine_snapshots: [],
  created_at: '2026-08-01T00:00:00Z',
  updated_at: '2026-08-01T00:01:00Z',
  started_at: '2026-08-01T00:00:10Z',
  completed_at: null,
};

function renderPanel(audit: Partial<Audit> = {}, props: Record<string, unknown> = {}) {
  const onCancel = vi.fn();
  render(
    <ProgressPanel
      audit={{ ...BASE_AUDIT, ...audit }}
      onCancel={onCancel}
      cancelPending={false}
      {...props}
    />,
  );
  return { onCancel };
}

const cancelButton = () => screen.getByRole('button', { name: /Cancel run|Cancelling/ });

describe('ProgressPanel', () => {
  it('shows the requested, completed, and failed counts', () => {
    renderPanel({ requested_count: 12, completed_count: 5, failed_count: 2 });

    expect(screen.getByText('12')).toBeVisible();
    expect(screen.getByText('5')).toBeVisible();
    expect(screen.getByText('2')).toBeVisible();
  });

  it.each<AuditStatus>(['draft', 'validating', 'queued', 'running', 'analyzing'])(
    'enables Cancel while the run is %s',
    (status) => {
      renderPanel({ status });

      expect(cancelButton()).toBeEnabled();
    },
  );

  it.each<AuditStatus>(['reporting', 'completed', 'partially_completed', 'failed', 'cancelled'])(
    'disables Cancel once the run is %s',
    (status) => {
      // Offering a cancel the backend would reject is worse than offering none.
      renderPanel({ status });

      expect(cancelButton()).toBeDisabled();
    },
  );

  it('fires the cancel callback exactly once per click', async () => {
    const user = userEvent.setup();
    const { onCancel } = renderPanel({ status: 'running' });

    await user.click(cancelButton());

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it('disables Cancel and says so while a cancel is in flight', () => {
    renderPanel({ status: 'running' }, { cancelPending: true });

    // Prevents a second cancel request against an already-cancelling run.
    expect(cancelButton()).toBeDisabled();
    expect(screen.getByText('Cancelling…')).toBeVisible();
  });

  it.each<AuditStatus>(['queued', 'running', 'analyzing', 'reporting'])(
    'shows the live updating indicator while %s',
    (status) => {
      renderPanel({ status });

      // `reporting` is not cancelable but IS still moving, so the panel must
      // still tell the user something is happening.
      expect(screen.getByText('Updating…')).toBeVisible();
    },
  );

  it.each<AuditStatus>(['completed', 'partially_completed', 'failed', 'cancelled'])(
    'hides the updating indicator once %s',
    (status) => {
      renderPanel({ status });

      expect(screen.queryByText('Updating…')).not.toBeInTheDocument();
    },
  );

  it('offers same-origin export links for both formats', () => {
    renderPanel();

    for (const name of ['Export CSV', 'Export MD']) {
      const link = screen.getByRole('link', { name });
      expect(link).toHaveAttribute('download');
      // Invariant 12: browser calls stay same-origin through the proxy.
      expect(link.getAttribute('href')).toMatch(/^\/api\/v1\//);
    }
  });

  it('offers a failure rerun only when there is a failure to rerun', async () => {
    const user = userEvent.setup();
    const onRerunFailures = vi.fn();
    renderPanel({ failed_count: 3 }, { onRerunFailures });

    await user.click(screen.getByRole('button', { name: 'Rerun failed' }));

    expect(onRerunFailures).toHaveBeenCalledTimes(1);
  });

  it('hides the failure rerun when nothing failed', () => {
    renderPanel({ failed_count: 0 }, { onRerunFailures: vi.fn() });

    expect(screen.queryByRole('button', { name: 'Rerun failed' })).not.toBeInTheDocument();
  });

  it('hides the failure rerun when no handler is supplied', () => {
    renderPanel({ failed_count: 3 });

    expect(screen.queryByRole('button', { name: 'Rerun failed' })).not.toBeInTheDocument();
  });

  it('disables the rerun while one is being created', () => {
    renderPanel({ failed_count: 3 }, { onRerunFailures: vi.fn(), rerunPending: true });

    expect(screen.getByRole('button', { name: 'Creating repair…' })).toBeDisabled();
  });

  it('surfaces a run error message', () => {
    renderPanel({ status: 'failed', error_message: 'Provider budget exhausted' });

    expect(screen.getByText('Provider budget exhausted')).toBeVisible();
  });

  it('renders no error paragraph when the run carries none', () => {
    renderPanel({ error_message: '' });

    expect(screen.queryByText(/Provider budget/)).not.toBeInTheDocument();
  });
});
